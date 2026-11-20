"""First-Move Radar — catch a coin BEFORE it shows up on the top-gainers list.

Why this exists
---------------
A "top gainer" list is the *output* of a pump: by the time a token ranks there,
the move has already happened and we are the exit liquidity. The inputs run
earlier — smart money buys quietly while price is still flat, and social buzz
builds before the candle does. So this radar reads the *inputs*:

  * smart-money net inflow   (money arriving before price)
  * social hype volume       (attention arriving before price)

and then scores a token by how strong those inputs are **while its price has
barely moved**. A token that has already run is penalised, because the edge we
want is the first move, not the third.

What it is not
--------------
Not a signal generator. It cannot create an entry on its own: everything it
returns still has to clear the hunter's own structural bullish gate, liquidity
and spread filters. When the radar has no data (offline, throttled, endpoint
down) the hunter simply runs without it — never on stale or invented numbers.

The rank endpoints are public Binance Web3 bapi endpoints, reached through the
project-local ``tools/market_rank.mjs`` wrapper (the upstream skill CLI has a
Windows dispatch bug that prints nothing).
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))

# The radar reads DEX ranks (BSC / Solana / Base) and maps tickers onto Binance
# pairs. Those ranks happily contain tokenised equities (MSTRB, GOOGLB...) and
# pegged assets, which are not crypto small caps and must never reach the
# hunter's shortlist — same rule the market sweep uses.
from symbol_filter import is_pegged, is_tokenised  # noqa: E402

# --- config -----------------------------------------------------------------
DEFAULT_TOOL = os.path.join(HERE, "tools", "market_rank.mjs")
# BSC, Solana, Base — the three chains the inflow/social ranks cover.
DEFAULT_CHAINS = ("56", "CT_501", "8453")
REFRESH_SEC = 240          # refresh the ranks on a throttle (they are rate-limited and slow)
CALL_TIMEOUT = 25          # seconds per endpoint call
TOKEN_TTL = 900            # a radar row older than this is not trusted

# social-hype is a heavier payload; keep its own throttle
SOCIAL_SEC = 420


def _find_node() -> str:
    """Locate a node binary the same way the rest of the project does."""
    for c in (os.environ.get("NODE_BIN"), shutil.which("node"),
              r"G:\Program Files\nodejs\node.exe",
              r"C:\Program Files\nodejs\node.exe"):
        if c and os.path.exists(c):
            return c
    return "node"


def _f(x, d=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


def _ticker(name) -> str:
    """Normalise a token name/symbol to a Binance base ticker (A-Z0-9 only).

    DEX ranks carry display names ('Binance Coin', '旺柴'); Binance pairs carry
    tickers ('BNB'). We take the alphanumeric core and upper-case it, then the
    caller intersects the result with the real Binance symbol set — so a miss is
    always a miss, never a guess.
    """
    s = "".join(ch for ch in str(name or "") if ch.isalnum()).upper()
    return s


class FirstMoveRadar:
    """Leading-indicator radar over the Binance Web3 rank endpoints."""

    def __init__(self, tool=DEFAULT_TOOL, chains=DEFAULT_CHAINS,
                 refresh_sec=REFRESH_SEC, enabled=True):
        self.tool = tool
        self.chains = tuple(chains)
        self.refresh_sec = refresh_sec
        self.enabled = enabled and os.path.exists(tool)
        self.node = _find_node()
        self.lock = threading.Lock()
        self.rows = {}          # ticker -> {inflow, chg, hype, sentiment, chain, name, ca}
        self.updated = 0.0
        self.last_error = ""
        self.calls = 0
        self._last_social = 0.0
        self._inflight = False

    # ---------------------------------------------------------------- transport
    def _call(self, cmd, params):
        """Run the vendored rank tool and return its parsed JSON, or None."""
        if not self.enabled:
            return None
        fd, path = tempfile.mkstemp(suffix=".json", prefix="mr_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(params, f)
            # CREATE_NO_WINDOW: parent is pythonw.exe, so without this every
            # node.exe spawn allocates a fresh console -> black window popping
            # up every ~2s.  Never remove this flag.
            proc = subprocess.run(
                [self.node, self.tool, cmd, "--params-file", path, "--compact"],
                capture_output=True, text=True, timeout=CALL_TIMEOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
            )
            self.calls += 1
            if proc.returncode != 0 or not proc.stdout.strip():
                self.last_error = (proc.stderr or proc.stdout or "no output").strip()[:160]
                return None
            return json.loads(proc.stdout)
        except Exception as e:
            self.last_error = str(e)[:160]
            return None
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

    # ------------------------------------------------------------------ parsing
    def _merge_inflow(self, chain, payload):
        data = (payload or {}).get("data")
        if isinstance(data, dict):
            data = data.get("list") or data.get("rows") or data.get("data") or []
        if not isinstance(data, list):
            return
        for t in data:
            if not isinstance(t, dict):
                continue
            tick = _ticker(t.get("tokenName") or t.get("symbol") or t.get("name"))
            if not tick:
                continue
            with self.lock:
                row = self.rows.setdefault(tick, {})
                row["ticker"] = tick
                row["name"] = str(t.get("tokenName") or tick)
                row["chain"] = chain
                row["ca"] = t.get("ca") or t.get("contractAddress")
                row["inflow"] = max(_f(row.get("inflow")), _f(t.get("inflow")))
                chg = _f(t.get("priceChangeRate"), None) if t.get("priceChangeRate") is not None else None
                if chg is not None:
                    row["chg"] = chg
                row["volume"] = max(_f(row.get("volume")), _f(t.get("volume")))
                row["mcap"] = max(_f(row.get("mcap")), _f(t.get("marketCap")))
                row["liq"] = max(_f(row.get("liq")), _f(t.get("liquidity")))

    def _merge_social(self, chain, payload):
        data = (payload or {}).get("data")
        board = (data or {}).get("leaderBoardList") if isinstance(data, dict) else data
        if not isinstance(board, list):
            return
        for t in board:
            if not isinstance(t, dict):
                continue
            meta = t.get("metaInfo") or {}
            tick = _ticker(meta.get("symbol") or t.get("symbol"))
            if not tick:
                continue
            mi = t.get("marketInfo") or {}
            si = t.get("socialHypeInfo") or {}
            with self.lock:
                row = self.rows.setdefault(tick, {})
                row["ticker"] = tick
                row.setdefault("name", tick)
                row.setdefault("chain", chain)
                row["hype"] = max(_f(row.get("hype")), _f(si.get("socialHype")))
                row["sentiment"] = si.get("sentiment") or row.get("sentiment")
                if "chg" not in row:
                    row["chg"] = _f(mi.get("priceChange"))
                row["brief"] = (si.get("socialSummaryBrief") or row.get("brief") or "")[:140]

    # ------------------------------------------------------------------- refresh
    def refresh(self, force=False):
        """Pull both ranks for every chain. Safe to call often — it self-throttles."""
        if not self.enabled:
            return 0
        now = time.time()
        with self.lock:
            if self._inflight:
                return 0
            if not force and now - self.updated < self.refresh_sec:
                return 0
            self._inflight = True
        try:
            for chain in self.chains:
                p = self._call("smart-money-inflow", {"chainId": chain})
                if p:
                    self._merge_inflow(chain, p)
            # social-hype is heavier, so give it a longer throttle of its own
            if force or now - self._last_social >= SOCIAL_SEC:
                self._last_social = now
                for chain in self.chains:
                    p = self._call("social-hype",
                                   {"chainId": chain, "targetLanguage": "en", "timeRange": 1})
                    if p:
                        self._merge_social(chain, p)
            with self.lock:
                self.updated = time.time()
                return len(self.rows)
        finally:
            with self.lock:
                self._inflight = False

    def maybe_refresh_async(self):
        """Kick a refresh in a daemon thread if the cache is stale. Never blocks."""
        if not self.enabled:
            return
        if time.time() - self.updated < self.refresh_sec:
            return
        with self.lock:
            if self._inflight:
                return
        threading.Thread(target=self.refresh, kwargs={"force": True}, daemon=True).start()

    # -------------------------------------------------------------------- score
    @staticmethod
    def score_row(row):
        """0-100 'pregain' score: reward arriving money/attention, punish a move
        that already happened. A dip with heavy inflow can score high; a token
        already up 60% cannot."""
        inflow = max(0.0, _f(row.get("inflow")))
        hype = max(0.0, _f(row.get("hype")))
        chg = _f(row.get("chg"), 0.0)

        s = 40.0
        # smart-money build-up: $1k -> ~18, $100k -> ~30
        s += min(30.0, 6.0 * math.log10(1.0 + inflow))
        # social buzz: log-scaled, capped
        s += min(20.0, 4.0 * math.log10(1.0 + hype))
        # already moved? the first move is gone — penalise gains past +3%
        late = max(0.0, chg - 3.0)
        s -= min(45.0, 0.8 * late)
        # a coin already down hard is falling, not coiling
        s -= min(15.0, 0.5 * max(0.0, -chg - 12.0))
        return max(0.0, min(100.0, round(s, 1)))

    def candidates(self, binance_symbols=None, min_score=55, limit=30):
        """Return pre-gainer rows, best first, optionally restricted to symbols the
        hunter can actually trade on Binance spot."""
        with self.lock:
            rows = [dict(r) for r in self.rows.values()]
        allowed = None
        if binance_symbols:
            allowed = {s.upper() for s in binance_symbols}
        out = []
        for r in rows:
            tick = r.get("ticker")
            if not tick:
                continue
            pair = tick + "USDT"
            r["pair"] = pair
            # A tokenised equity receipt is a stock gapping, not crypto order
            # flow; a pegged asset has no move to catch. Neither belongs on a
            # pre-pump list, and neither may take a slot from a real micro-cap.
            if is_tokenised(pair) or is_pegged(pair):
                continue
            r["tradeable"] = True if allowed is None else (pair in allowed)
            r["pregain"] = self.score_row(r)
            out.append(r)
        out.sort(key=lambda r: (r["tradeable"], r["pregain"]), reverse=True)
        return [r for r in out if r["pregain"] >= min_score][:limit]

    def tradeable(self, binance_symbols, min_score=55, limit=30):
        """Only the rows that map onto a real Binance USDT pair."""
        return [r for r in self.candidates(binance_symbols, min_score, limit)
                if r.get("tradeable")]

    def snapshot(self):
        with self.lock:
            age = time.time() - self.updated if self.updated else None
            return {
                "enabled": self.enabled,
                "rows": len(self.rows),
                "calls": self.calls,
                "age_sec": round(age, 1) if age is not None else None,
                "stale": (age is None or age > TOKEN_TTL),
                "error": self.last_error,
                "chains": list(self.chains),
            }


if __name__ == "__main__":   # manual smoke: python pregainers.py
    r = FirstMoveRadar(enabled=True)
    n = r.refresh(force=True)
    print("rows:", n, "| snapshot:", r.snapshot())
    for c in r.candidates(limit=15):
        print("%-8s %-10s score=%5.1f chg=%7.2f inflow=%12.0f hype=%10.0f tradeable=%s"
              % (c.get("ticker"), c.get("chain"), c.get("pregain"),
                 _f(c.get("chg")), _f(c.get("inflow")), _f(c.get("hype")), c.get("tradeable")))
