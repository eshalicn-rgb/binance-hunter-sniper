#!/usr/bin/env python3
"""
ALTFINS FEED  —  real, external chart-pattern and signal data.

AltFins publishes AI-detected chart patterns with the whole trade plan already
attached: pattern, stage, timeframe, direction, probability, entry, stop, target
and a rendered pattern image. That is exactly the bullish-only pattern filter the
hunter was missing, and none of it has to be computed locally.

Key      ALTFINS_API_KEY   (env or binance_hunter/.env)
Base     ALTFINS_BASE      (default https://altfins.com)

Fail-closed: no key, a rejected key or a network error all return empty data, and
the dashboard shows the feed as unavailable rather than inventing a pattern.

Endpoints (verified live against the account's plan):

    POST /api/v1/nonauth/patterns/searches        chart + fibonacci patterns, paginated
    GET  /api/v1/public/signals-feed              live signal feed
    GET  /api/v2/public/signals-feed/signal-keys  signal-key dictionary
    POST /api/v2/public/screener-data/search-requests

The account's plan does NOT include /api/v2/public/patterns-data or
/api/v2/public/technical-analysis — both answer 403 — so they are not called.
"""
import json
import os
import threading
import time

import requests

BASE_DEFAULT = "https://altfins.com"
TTL = 300                     # seconds between fetches of the pattern set
TIMEOUT = 12

# AltFins pattern stage -> weight. A breakout has already confirmed the level,
# an emerging pattern is still forming, a completed one is history.
STAGE_W = {"BREAKOUT": 1.0, "APPROACH": 0.75, "EMERGING": 0.45, "COMPLETED": 0.2}

# How much each bullish pattern shape is worth on its own.
QUALITY = {
    "INVERSE_HEAD_AND_SHOULDERS": 1.00,
    "DOUBLE_BOTTOM": 0.95,
    "TRIPLE_BOTTOM": 0.95,
    "FALLING_WEDGE": 0.90,
    "ASCENDING_TRIANGLE": 0.85,
    "CHANNEL_DOWN": 0.80,          # bullish break out of a descending channel
    "FLAG": 0.75,
    "PENNANT": 0.75,
    "RECTANGLE": 0.70,
    "TRIANGLE": 0.70,
    "GARTLEY": 0.70,
    "ABCD": 0.70,
    "BUTTERFLY": 0.65,
    "POINT_RETRACEMENT": 0.60,     # fibonacci
    "POINT_EXTENSION": 0.60,
    "CHANNEL_UP": 0.55,
    "HORIZONTAL_SUPPORT": 0.50,
    "RISING_WEDGE": 0.40,
    "HORIZONTAL_RESISTANCE": 0.40,
}

TF_MAP = {"MINUTES15": "15m", "HOURLY": "1h", "HOURS4": "4h", "DAILY": "1d"}

# Stages worth acting on vs merely watching
ACTION_STAGES = ("BREAKOUT", "APPROACH")


def _f(x, d=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


def _env_file():
    """Read binance_hunter/.env when the key was not exported into the process."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    out = {}
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    except Exception:
        pass
    return out


class AltFins:
    def __init__(self, key=None, base=None, enabled=None):
        envf = _env_file()
        self.key = (key or os.environ.get("ALTFINS_API_KEY", "")
                    or envf.get("ALTFINS_API_KEY", ""))
        self.base = (base or os.environ.get("ALTFINS_BASE", "")
                     or envf.get("ALTFINS_BASE", BASE_DEFAULT)).rstrip("/")
        if enabled is None:
            raw = os.environ.get("ALTFINS_ENABLED", envf.get("ALTFINS_ENABLED", "1"))
            enabled = str(raw).lower() not in ("0", "false", "no", "")
        self.enabled = bool(enabled and self.key)
        self.session = requests.Session()
        self._lock = threading.Lock()
        self._cache = {}            # "patterns:BULLISH" -> {"ts":.., "rows":[..]}
        self.last_error = None
        self.last_ok = 0
        self.calls = 0

    # ----------------------------------------------------------------- transport
    def _headers(self):
        return {"X-API-KEY": self.key, "Accept": "application/json",
                "Content-Type": "application/json"}

    def _get(self, path, params=None):
        if not self.enabled:
            return None
        try:
            self.calls += 1
            r = self.session.get(self.base + path, headers=self._headers(),
                                 params=params, timeout=TIMEOUT)
            if r.status_code != 200:
                self.last_error = "%s GET %s -> %s" % (self.base, path, r.status_code)
                return None
            self.last_ok = time.time()
            self.last_error = None
            return r.json()
        except Exception as e:
            self.last_error = "GET %s: %s" % (path, e)
            return None

    def _post(self, path, body=None, params=None):
        if not self.enabled:
            return None
        try:
            self.calls += 1
            r = self.session.post(self.base + path, headers=self._headers(),
                                  params=params, data=json.dumps(body or {}),
                                  timeout=TIMEOUT)
            if r.status_code != 200:
                self.last_error = "%s POST %s -> %s" % (self.base, path, r.status_code)
                return None
            self.last_ok = time.time()
            self.last_error = None
            return r.json()
        except Exception as e:
            self.last_error = "POST %s: %s" % (path, e)
            return None

    # ----------------------------------------------------------------- endpoints
    def patterns(self, direction="BULLISH", pattern_type=None, sub_type=None,
                 interval=None, stage=None, relevant=True, size=100, page=0):
        """Paginated chart patterns. Defaults to bullish and relevant only."""
        body = {}
        if direction:
            body["direction"] = direction
        if pattern_type:
            body["patternType"] = pattern_type
        if sub_type:
            body["patternSubType"] = sub_type
        if interval:
            body["timeInterval"] = interval
        if stage:
            body["patternResultType"] = stage
        if relevant is not None:
            body["relevant"] = bool(relevant)
        return self._post("/api/v1/nonauth/patterns/searches", body,
                          params={"page": page, "size": size})

    def signals(self, size=200):
        return self._get("/api/v1/public/signals-feed", params={"size": size})

    def signal_keys(self):
        return self._get("/api/v2/public/signals-feed/signal-keys")

    def screener(self, body=None, size=50):
        return self._post("/api/v2/public/screener-data/search-requests",
                          body or {}, params={"page": 0, "size": size})

    # ----------------------------------------------------------------- shaping
    @staticmethod
    def _shape(row):
        """One raw AltFins row -> the flat record the hunter and dashboard use."""
        sec = row.get("securityIdentifier") or {}
        ticker = (sec.get("ticker") or "").upper()
        sub = row.get("patternSubType") or "?"
        stage = row.get("patternResultType") or "?"
        tf_raw = row.get("timeInterval") or ""
        q = QUALITY.get(sub, 0.5)
        w = STAGE_W.get(stage, 0.3)
        strength = int(round(min(100.0, q * w * 100.0)))
        pot = _f((row.get("initialProfitPotential") or {}).get("value"))
        if pot > 0:
            strength = int(round(min(100.0, strength + min(8.0, pot * 100.0 * 0.15))))

        # AltFins exposes targetLevel on the free plan but locks signalEntryLevel
        # and stopLoss for chart patterns. Use the API level when it is there and
        # fall back to the live price for entry — never invent a stop.
        entry = _f((row.get("signalEntryLevel") or {}).get("value"), None)
        entry_source = "api"
        if entry is None:
            entry = _f((row.get("lastPrice") or {}).get("value"), None)
            entry_source = "last"
        stop = _f((row.get("stopLoss") or {}).get("value"), None)

        return {
            "ticker": ticker,
            "symbol": ticker + "USDT" if ticker and not ticker.endswith("USDT") else ticker,
            "name": sec.get("friendlyName") or sec.get("name") or ticker,
            "pattern": sub,
            "pattern_label": sub.replace("_", " ").title(),
            "type": row.get("patternType"),
            "stage": stage,
            "timeframe": TF_MAP.get(tf_raw, tf_raw.lower()),
            "timeframe_raw": tf_raw,
            "direction": row.get("direction"),
            "probability": _f((row.get("probability") or {}).get("value"), None),
            "strength": strength,
            "profit_potential": round(pot * 100.0, 2) if pot else None,
            "entry": entry,
            "entry_source": entry_source,
            "stop": stop,
            "target": _f((row.get("targetLevel") or {}).get("value"), None),
            "last_price": _f((row.get("lastPrice") or {}).get("value"), None),
            "age": row.get("age"),
            "length": row.get("length"),
            "relevant": row.get("relevant"),
            "complete": row.get("complete"),
            "expires_at": row.get("expiresAt"),
            "identified": row.get("identifiedTimestamp"),
            "analysis": (row.get("analysisText") or "")[:280],
            "image": row.get("imageUrlDark") or row.get("imageUrlLight"),
            "actionable": stage in ACTION_STAGES,
        }

    # ----------------------------------------------------------------- refresh
    def refresh(self, tradable=None, force=False):
        """Pull bullish chart patterns + fibonacci patterns and keep only the
        symbols the hunter can actually trade. `tradable` is a set of Binance
        symbols (e.g. XMRUSDT); None keeps everything.

        Returns a dict: {rows, by_symbol, actionable, count, ts, error}.
        """
        if not self.enabled:
            return {"rows": [], "by_symbol": {}, "count": 0, "actionable": 0,
                    "ts": time.time(), "error": self.last_error or "no ALTFINS_API_KEY"}

        with self._lock:
            c = self._cache.get("bullish")
            if c and not force and (time.time() - c["ts"]) < TTL:
                return c["data"]

        rows = []
        err = None
        got_any = False
        # the two categories that matter for a long-only sniper
        for ptype in ("CHART_PATTERNS", "FIBONACCI_PATTERNS"):
            j = self.patterns(direction="BULLISH", pattern_type=ptype,
                              relevant=True, size=100)
            if j is None:
                err = self.last_error
                continue
            got_any = True
            for raw in (j.get("content") or []):
                try:
                    rows.append(self._shape(raw))
                except Exception:
                    continue

        if not got_any and err:
            data = {"rows": [], "by_symbol": {}, "count": 0, "actionable": 0,
                    "ts": time.time(), "error": err}
            self._cache["bullish"] = {"ts": time.time(), "data": data}
            return data

        if tradable:
            rows = [r for r in rows if r["symbol"] in tradable]

        # highest strength first, and de-duplicate symbol+pattern+tf
        seen = set()
        uniq = []
        for r in sorted(rows, key=lambda x: -x["strength"]):
            k = (r["symbol"], r["pattern"], r["timeframe"])
            if k in seen:
                continue
            seen.add(k)
            uniq.append(r)

        by_symbol = {}
        for r in uniq:
            by_symbol.setdefault(r["symbol"], []).append(r)

        data = {
            "rows": uniq[:120],
            "by_symbol": by_symbol,
            "count": len(uniq),
            "actionable": sum(1 for r in uniq if r["actionable"]),
            "ts": time.time(),
            "error": None,
        }
        with self._lock:
            self._cache["bullish"] = {"ts": time.time(), "data": data}
        return data

    def cached(self):
        c = self._cache.get("bullish")
        return c["data"] if c else None

    # ----------------------------------------------------------------- consumers
    def for_symbol(self, symbol):
        """Best bullish pattern for one Binance symbol, or None."""
        d = self.cached()
        if not d:
            return None
        rows = d["by_symbol"].get(symbol)
        return rows[0] if rows else None

    def plan(self, symbol):
        """The trade plan AltFins already computed: entry / stop / target."""
        r = self.for_symbol(symbol)
        if not r:
            return None
        return {"entry": r["entry"], "stop": r["stop"], "target": r["target"],
                "pattern": r["pattern_label"], "stage": r["stage"],
                "timeframe": r["timeframe"], "strength": r["strength"],
                "profit_potential": r["profit_potential"], "analysis": r["analysis"]}

    def bias(self, symbol):
        """Small directional edge to fold into the hunter's score.
        A confirmed bullish breakout is worth more than a pattern still forming."""
        r = self.for_symbol(symbol)
        if not r:
            return 0.0
        stage = r["stage"]
        base = {"BREAKOUT": 3.0, "APPROACH": 2.0, "EMERGING": 1.0}.get(stage, 0.0)
        if base and r.get("profit_potential"):
            base += min(1.0, r["profit_potential"] / 20.0)
        return round(base, 2)

    def snapshot(self):
        d = self.cached()
        if not d:
            return {"available": bool(self.enabled), "count": 0, "actionable": 0,
                    "rows": [], "error": self.last_error or ("no ALTFINS_API_KEY" if not self.enabled else "not fetched yet")}
        return {
            "available": True,
            "count": d["count"],
            "actionable": d["actionable"],
            "updated": d["ts"],
            "age": round(time.time() - d["ts"], 1),
            "rows": d["rows"][:60],
            "by_stage": _count_by(d["rows"], "stage"),
            "by_pattern": _count_by(d["rows"], "pattern_label", 10),
            "by_tf": _count_by(d["rows"], "timeframe"),
            "error": d["error"],
        }


def _count_by(rows, key, top=None):
    agg = {}
    for r in rows:
        agg[r.get(key)] = agg.get(r.get(key), 0) + 1
    items = sorted(agg.items(), key=lambda x: -x[1])
    if top:
        items = items[:top]
    return dict(items)


if __name__ == "__main__":                      # quick live smoke test
    import sys
    af = AltFins()
    d = af.refresh()
    print("enabled:", af.enabled, "count:", d["count"], "actionable:", d["actionable"],
          "error:", d["error"])
    for r in d["rows"][:12]:
        print("%-8s %-22s %-9s %-4s str=%3d pot=%s entry=%s stop=%s tgt=%s" % (
            r["symbol"], r["pattern_label"], r["stage"], r["timeframe"],
            r["strength"], r["profit_potential"], r["entry"], r["stop"], r["target"]))
    sys.exit(0)
