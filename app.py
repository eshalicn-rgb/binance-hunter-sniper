#!/usr/bin/env python3
"""
BINANCE HUNTER - Spot Trading System
Small account specialist: $9 → $20 target
Real-time order flow, liquidity pool tracking, volume analysis
Auto-enters on real movers before they move
Runs on port 4564 (unique, never touched)
"""
import os, sys, json, time, hmac, hashlib, gzip, requests, threading, asyncio, logging
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from flask import Flask, render_template_string, render_template, jsonify, request

BOT = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("HUNTER_PORT", "4564"))
STOP_FILE = os.path.join(BOT, "STOP_HUNTER")
STATE_FILE = os.path.join(BOT, "hunter_state.json")
RESULTS_FILE = os.path.join(BOT, "results.json")     # closed-trade ledger for daily/weekly cards
DIGEST_FILE = os.path.join(BOT, "digest.json")       # last daily/weekly push stamps
ALERTS_FILE = os.path.join(BOT, "alerts.json")       # armed price/time alerts (fire themselves)
LOG_FILE = os.path.join(BOT, "hunter.log")

# Swarm integration (root of GrokMT5Bot holds the swarm package)
ROOT = os.path.dirname(BOT)
for _p in (ROOT, BOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from swarm.coordinator import get_swarm
from feeds import FeedsHub, NOTABLE_USD, SURGE_NOTABLE, CATALYST_MIN
from notify import (Notifier, card_signal, card_entry, card_exit, card_result,
                    card_catch, card_boot, card_alert, card_prepump,
                    card_alert_armed, card_alert_fired)
import ta
import structure
import signals
import altfins
import alertbook
import pregainers
import regime
import notion_journal as nj
try:
    import tgtools as tgtools_mod
except Exception as _tgt_exc:          # inbound tools must never block boot
    tgtools_mod = None
    _TGT_IMPORT_ERROR = f"{type(_tgt_exc).__name__}: {_tgt_exc}"
else:
    from enhance import (  # noqa: E402
        momentum_stack, squeeze, rel_strength, breakout, tier,
        read, prepump_boost, hunt_boost,
    )
    _TGT_IMPORT_ERROR = ""

from chat import ChatBrain

# Load .env file manually (no external dependency)
def _load_env():
    env_path = os.path.join(BOT, ".env")
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())

_load_env()

# ---------------------------------------------------------------------------
# Timezone: ONE source of truth for the bot and the dashboard.
# Set HUNTER_TZ in .env (IANA name). Daily/weekly windows and every stamp use it.
# ---------------------------------------------------------------------------
try:
    from zoneinfo import ZoneInfo
except Exception:                                    # pragma: no cover
    ZoneInfo = None

TZ_NAME = (os.environ.get("HUNTER_TZ") or "Asia/Riyadh").strip()

def _resolve_tz(name):
    """Resolve an IANA name; fall back to a fixed offset, then UTC."""
    if ZoneInfo is not None:
        try:
            return name, ZoneInfo(name)
        except Exception:
            pass
    for fmt in ("%z",):
        try:
            return "UTC%s" % name, timezone(timedelta(hours=float(name)))
        except Exception:
            pass
    return "UTC", timezone.utc

TZ_NAME, HUNTER_TZINFO = _resolve_tz(TZ_NAME)

def now_local():
    """Timezone-correct now for logs, ledgers, windows and cards."""
    return datetime.now(HUNTER_TZINFO)

def tz_offset_hours():
    try:
        return (now_local().utcoffset() or timedelta(0)).total_seconds() / 3600.0
    except Exception:
        return 0.0

def _tz_label():
    try:
        n = now_local().tzname() or ""
    except Exception:
        n = ""
    # zoneinfo returns things like "AST"/"+03"; prefer a readable GMT form when numeric
    return n if (n and not n.lstrip("+-").isdigit()) else ""

def tz_info():
    """Everything the dashboard needs to render times in the hunter's timezone."""
    off = tz_offset_hours()
    sign = "+" if off >= 0 else "-"
    hh = int(abs(off))
    mm = int(round((abs(off) - hh) * 60))
    label = _tz_label() or TZ_NAME.split("/")[-1].replace("_", " ")
    return {
        "tz": TZ_NAME,
        "tz_offset": round(off, 4),
        "tz_offset_str": "%s%02d:%02d" % (sign, hh, mm),
        "tz_label": label,
        "tz_clock": now_local().strftime("%Y-%m-%d %H:%M:%S"),
    }

# Binance API credentials (loaded from .env)
BINANCE_API_KEY = os.environ.get("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.environ.get("BINANCE_API_SECRET", "")
BINANCE_BASE = os.environ.get("BINANCE_BASE", "https://api.binance.com")

# Trading parameters for small account
START_BALANCE = float(os.environ.get("HUNTER_START_BALANCE", "100.0"))
TARGET_BALANCE = float(os.environ.get("HUNTER_TARGET_BALANCE", "20.0"))
RISK_PER_TRADE = float(os.environ.get("RISK_PER_TRADE", "0.02"))  # risk per trade (matches .env default 0.02)
MAX_POSITIONS = 3        # Max concurrent positions
MIN_VOLUME_USDT = 5000   # Min 24h volume USDT for coin selection
MIN_LIQUIDITY_USDT = 10000  # Min liquidity for entry
VOLUME_SPIKE_MULT = 2.0  # Volume spike multiplier for entry trigger
PRICE_CHANGE_MULT = 1.5  # Price change multiplier

# Full-market sweep + deep-scan shortlist
SHORTLIST = int(os.environ.get("SHORTLIST", "20"))   # symbols deep-scanned each cycle (order book + trades + klines)
WATCH_MIN = 60            # score floor for recording a cycle's shortlist into the follow-up ledger
SWEEP_MIN_QUOTE = 100000  # min 24h quote volume (USDT) to be considered tradable
MARKET_SHOW = 400         # ranked market rows exposed to the dashboard
DEEP_KLINES = 120         # 1m bars pulled per deep-scan symbol (drives Fib/Gann structure)
DEAD_MIN_TRADES = 150     # fewer than this in 24h = dead market, never hunted
CATALYST_RISK = 0.06      # catalyst entries risk less than flow entries (6% vs 10%)
PREPUMP_ENTRY = 40        # pre-pump score required by the early (before-the-move) path
PREPUMP_RISK = 0.05       # earliest, least-certain path, so it risks the least

# ---- live orders: armed, but behind hard risk limits ----
# The hunter trades live (real Binance orders) — the operator's instruction — with
# the risk-management envelope below as the protection instead of a blanket lock.
# Set HUNTER_LIVE_ORDERS=0 to disarm into shadow mode without touching code.
LIVE_ORDERS = os.environ.get("HUNTER_LIVE_ORDERS", "0") == "1"

# ---- key permission cache -----------------------------------------------------
# A Binance key only places orders when `enableSpotAndMarginTrading` is true. When
# it is not, EVERY order attempt returns 401/-2015, which would repeat on every
# signal and drown the log. So the engine probes the signed apiRestrictions
# endpoint through this cache instead of firing doomed orders, and a watcher
# thread announces the moment the permission appears — no restart required.
_PERM_CACHE = {"allowed": None, "ip_restrict": None, "checked": 0.0, "raw": None}

# ---- risk management (hard limits that bound the damage while the hunter works) ----
MIN_NOTIONAL_USD = 5.2    # Binance spot min is 5.0; 4% headroom for slippage, but low
                          # enough that 65% of a small account still clears it
                          # ($8.62 x 0.65 = $5.60 — a $6 floor silently froze the desk)
MAX_POS_FRAC = 0.65       # never commit more than this share of equity to one entry
ENTRY_GUARD_SEC = float(os.environ.get("HUNTER_ENTRY_GUARD_SEC", "300"))  # one entry per symbol per window
MAX_DAY_LOSS_FRAC = 0.15  # stand down for the rest of the day past -15% equity
MAX_CONSEC_LOSSES = 3     # pause new entries after this many losses in a row
LOSS_PAUSE_SEC = 1800     # ...for this long
DAILY_PROFIT_LOCK = 0.30  # once +30% on the day, stop opening new risk (lock the win)
BNB_RESERVE_USD = 1.00    # balance kept reserved (never sized into entries) to cover BNB trading fees
BNB_FEE_DISCOUNT = 0.25   # 25% effective fee discount when fees are paid with BNB

# ---- hunt profile: what a "prey" must clear to be worth sniping ---------------
# Calibrated to the scorers' real range (the old 80/3.0 bars were above anything
# the market printed, which is why the hunter took zero trades in 47h). Still a
# real momentum burst — volume + acceleration + one-sided flow + bullish structure.
def _envf(name, default):
    try:
        return float(os.environ.get(name, "") or default)
    except Exception:
        return float(default)


# Gates are tunable from .env so the signal feed can be widened without a code
# edit. Defaults are the checked-out 2026-11 values: strict enough to keep the
# hunter long-only and liquid, loose enough that a quiet tape still prints.
HUNT_MIN_SCORE = _envf("HUNT_MIN_SCORE", 35)     # order-flow score floor (lowered for more signals)
HUNT_MIN_VOL = _envf("HUNT_MIN_VOL", 1.0)        # volume vs baseline (lowered)
HUNT_MIN_MOM = _envf("HUNT_MIN_MOM", 0.3)        # % move over 5m (lowered)
HUNT_MAX_SPREAD = _envf("HUNT_MAX_SPREAD", 0.8)  # % bid/ask spread (widened from 0.5)
HUNT_MIN_DEPTH = _envf("HUNT_MIN_DEPTH", 5000)   # $ per side in the book (widened from 10000)
HUNT_MIN_IMBAL = _envf("HUNT_MIN_IMBAL", 0.40)   # buy-side share of the book (widened from 0.50)
HUNT_GATE_NEED = _envf("HUNT_GATE_NEED", 0.40)   # bullish-structure confidence (widened from 0.50)
CATALYST_MIN_DEPTH = 10000
CATALYST_MIN_VOL = 1.0
PREPUMP_MIN_DEPTH = 10000
PREPUMP_ENTRY = _envf("PREPUMP_ENTRY", 30)   # pre-pump score required (lowered for more signals)
FIRSTMOVE_MIN = _envf("FIRSTMOVE_MIN", 40)   # First-Move Radar pregain score required to fire
FIRSTMOVE_MIN_VOL = 0.8   # a pre-gainer still needs volume arriving
FIRSTMOVE_INJECT = 10     # radar names force-added to the deep scan each cycle
HOLD_MAX_MIN = 120        # "eat and leave": a scalp that has not worked in 2h is dead capital
SCALP_TP_FLOOR = 1.0      # take-profit never tighter than +1% (clears the ~0.2% round trip)

# What may be hunted lives in one shared module so the market sweep, the
# First-Move Radar and the pre-pump watch cannot disagree about it.
from symbol_filter import (  # noqa: E402
    STABLE_BASES, TOKENISED_BASES, base_of, huntable, is_pegged, is_tokenised,
)

# Swarm integration
swarm = get_swarm()
swarm.heartbeat("executor")
swarm.heartbeat("scanner")
swarm.heartbeat("analyst")
swarm.heartbeat("whale")
swarm.heartbeat("risk_guard")
swarm.heartbeat("coordinator")
swarm.heartbeat("portfolio")
swarm.heartbeat("dashboard")
swarm.heartbeat("newsdesk")
swarm.heartbeat("quant")

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)
log = logging.getLogger("hunter")

def log_info(msg): log.info(msg); print(msg)
def log_error(msg): log.error(msg); print(msg)
def log_warn(msg): log.warning(msg); print(msg)

# --- Binance rate-limit guard -------------------------------------------------
# Weight limits (per IP per minute, Binance public API): ticker/24hr weight=40
# (all symbols) or 1 (single symbol); depth weight varies 1-5; klines weight 1-100;
# aggTrades weight 1; exchangeInfo weight 10. We conservatively pace requests so
# we never accumulate weight fast enough to trigger an IP ban (HTTP 418).
_BINANCE_MIN_INTERVAL = 0.5        # seconds between any two REST calls
_BINANCE_MAX_WEIGHT_PER_MIN = 600  # stay well under 1200/min
_binance_last_call = 0.0
_binance_weight_window = []        # list of (ts, weight) for rolling 60s window
_binance_backoff_until = 0.0       # epoch, set on 418/ban response
_binance_lock = threading.Lock()   # serialise pace() so deep-scan workers don't flood the pool


def _binance_pace(weight: int = 1):
    """Throttle Binance REST calls and apply rolling weight limit."""
    global _binance_last_call, _binance_weight_window, _binance_backoff_until
    with _binance_lock:
        now = time.time()
        # drop window entries older than 60s
        _binance_weight_window = [(t, w) for t, w in _binance_weight_window if now - t < 60.0]
        used = sum(w for _, w in _binance_weight_window)
        if used + weight > _BINANCE_MAX_WEIGHT_PER_MIN:
            wait = 60.0 - (now - _binance_weight_window[0][0]) if _binance_weight_window else 0.0
            time.sleep(max(0.0, wait))
            now = time.time()
            _binance_weight_window = [(t, w) for t, w in _binance_weight_window if now - t < 60.0]
        # enforce minimum interval between calls
        elapsed = now - _binance_last_call
        if elapsed < _BINANCE_MIN_INTERVAL:
            time.sleep(_BINANCE_MIN_INTERVAL - elapsed)
        _binance_last_call = time.time()
        _binance_weight_window.append((_binance_last_call, weight))


class BinanceClient:
    """Binance REST API client with full market data and trading"""
    def __init__(self):
        self.api_key = BINANCE_API_KEY
        self.api_secret = BINANCE_API_SECRET
        self.session = requests.Session()
        if self.api_key:
            self.session.headers.update({"X-MBX-APIKEY": self.api_key})
        # Enlarge the connection pool so deep-scan workers + Flask API requests
        # never exhaust the default pool of 10 (which caused the crash loop).
        from requests.adapters import HTTPAdapter
        self.session.mount("https://", HTTPAdapter(pool_connections=50, pool_maxsize=50))
        self.session.mount("http://", HTTPAdapter(pool_connections=50, pool_maxsize=50))
    
    def _signature(self, params):
        # Sign the params in INSERTION order, not sorted order.
        #
        # Binance verifies the HMAC over the exact query string it receives, and
        # requests encodes a dict in insertion order. The old sorted() here built
        # a different string from the one actually sent whenever a request had
        # more than one parameter, so every real order came back
        #   -1022 "Signature for this request is not valid."
        # Single-param calls (the apiRestrictions probe) passed by luck because
        # sorted order and insertion order are identical for one key.
        query_string = "&".join([f"{k}={v}" for k, v in params.items()])
        return hmac.new(self.api_secret.encode(), query_string.encode(), hashlib.sha256).hexdigest()
    
    def spot_trading_allowed(self, force=False, ttl=300):
        """Signed probe: can this key actually place a SPOT order right now?

        Cached (300 s default) so the hunter never hammers the endpoint, and the
        same cache feeds the permission watcher thread and the dashboard banner.
        `allowed` is True / False / None — None means "could not tell" (missing
        credentials or a network error) and must never be read as permission.
        """
        global _PERM_CACHE
        now = time.time()
        if not force and _PERM_CACHE.get("checked") and now - _PERM_CACHE["checked"] < ttl:
            return dict(_PERM_CACHE)
        out = {"allowed": None, "ip_restrict": None, "checked": now, "raw": None}
        if not self.api_key or not self.api_secret:
            out["raw"] = "no API credentials in .env"
            _PERM_CACHE = out
            return dict(out)
        try:
            url = f"{BINANCE_BASE}/sapi/v1/account/apiRestrictions"
            params = {"timestamp": int(time.time() * 1000)}
            params["signature"] = self._signature(params)
            resp = self.session.get(url, params=params, timeout=10)
            if resp.status_code == 200:
                d = resp.json() or {}
                out["allowed"] = bool(d.get("enableSpotAndMarginTrading"))
                out["ip_restrict"] = bool(d.get("ipRestrict"))
                out["raw"] = "ok"
            else:
                out["raw"] = f"HTTP {resp.status_code}"
        except Exception as e:
            out["raw"] = str(e)
        _PERM_CACHE = out
        return dict(out)

    def _binance_get(self, url, params=None, weight=1, timeout=10):
        """Paced Binance GET with exponential backoff on IP ban (418)."""
        global _binance_backoff_until
        if time.time() < _binance_backoff_until:
            return None  # still in backoff — skip this call
        _binance_pace(weight)
        try:
            resp = self.session.get(url, params=params, timeout=timeout)
            if resp.status_code == 418:
                # IP banned — back off exponentially, starting at 60s
                backoff = max(60.0, (_binance_backoff_until - time.time()) * 2 or 60.0)
                _binance_backoff_until = time.time() + backoff
                log_error(f"Binance IP banned (418) — backing off {backoff:.0f}s")
                return None
            return resp
        except Exception as e:
            log_error(f"Binance request error: {e}")
            return None

    def get_ticker_24hr(self, symbol=None):
        """Get 24hr ticker statistics"""
        try:
            url = f"{BINANCE_BASE}/api/v3/ticker/24hr"
            params = {} if symbol is None else {"symbol": symbol}
            weight = 40 if symbol is None else 1
            resp = self._binance_get(url, params=params, weight=weight)
            if resp is None:
                return []
            if resp.status_code == 200:
                return resp.json()
            return []
        except Exception as e:
            log_error(f"Ticker error: {e}")
            return []
    
    def get_prices(self, symbols):
        """Last price for many symbols in ONE call — used by the armed alerts.

        `/api/v3/ticker/price` takes a batch of symbols, so N armed alerts cost one
        request instead of N. A symbol the exchange does not answer for is simply
        absent from the map, and a missing price never fires an alert.
        """
        out = {}
        syms = [s for s in dict.fromkeys(symbols) if s]
        if not syms:
            return out
        try:
            resp = self._binance_get(f"{BINANCE_BASE}/api/v3/ticker/price",
                                     params={"symbols": json.dumps(syms[:100])}, weight=1)
            if resp is None:
                return out
            if resp.status_code == 200:
                for r in resp.json() or []:
                    try:
                        out[r["symbol"]] = float(r["price"])
                    except (KeyError, TypeError, ValueError):
                        continue
                return out
        except Exception as e:
            log_error(f"Batch price error: {e}")
        # batch rejected (too many symbols / bad request) — fall back per symbol
        for s in syms[:100]:
            t = self.get_ticker_24hr(s)
            if isinstance(t, dict):
                try:
                    v = float(t.get("lastPrice", 0) or 0)
                except (TypeError, ValueError):
                    v = 0.0
                if v > 0:
                    out[s] = v
        return out

    def get_order_book(self, symbol, limit=100):
        """Get order book for liquidity analysis"""
        try:
            resp = self._binance_get(f"{BINANCE_BASE}/api/v3/depth",
                                     params={"symbol": symbol, "limit": limit}, weight=5)
            if resp is None:
                return None
            if resp.status_code == 200:
                return resp.json()
            return None
        except Exception as e:
            log_error(f"Order book error {symbol}: {e}")
            return None
    
    def get_recent_trades(self, symbol, limit=500):
        """Get recent trades for order flow analysis"""
        try:
            resp = self._binance_get(f"{BINANCE_BASE}/api/v3/aggTrades",
                                     params={"symbol": symbol, "limit": limit}, weight=1)
            if resp is None:
                return []
            if resp.status_code == 200:
                return resp.json()
            return []
        except Exception as e:
            log_error(f"Trades error {symbol}: {e}")
            return []
    
    def get_klines(self, symbol, interval="1m", limit=100):
        """Get candlestick data"""
        try:
            resp = self._binance_get(f"{BINANCE_BASE}/api/v3/klines",
                                     params={"symbol": symbol, "interval": interval, "limit": limit}, weight=2)
            if resp is None:
                return []
            if resp.status_code == 200:
                return resp.json()
            return []
        except Exception as e:
            log_error(f"Klines error {symbol}: {e}")
            return []
    
    def get_exchange_info(self):
        """Listing status for every symbol — the authoritative dead/delisted filter."""
        try:
            resp = self._binance_get(f"{BINANCE_BASE}/api/v3/exchangeInfo",
                                     params={"permissions": "SPOT"}, weight=10)
            if resp is None:
                return None
            if resp.status_code == 200:
                return resp.json()
            log_error(f"Exchange info error: HTTP {resp.status_code}")
            return None
        except Exception as e:
            log_error(f"Exchange info error: {e}")
            return None

    def get_account(self):
        """Get account info"""
        if not self.api_key or not self.api_secret:
            return {"error": "No API credentials"}
        try:
            params = {"timestamp": int(time.time() * 1000)}
            params["signature"] = self._signature(params)
            resp = self._binance_get(f"{BINANCE_BASE}/api/v3/account",
                                     params=params, weight=10)
            if resp is None:
                return {"error": "rate limited / backoff"}
            if resp.status_code == 200:
                return resp.json()
            return {"error": resp.text}
        except Exception as e:
            log_error(f"Account error: {e}")
            return {"error": str(e)}
    
    # ---- exchange filters -------------------------------------------------
    # An order that breaks stepSize / minQty / minNotional is rejected by Binance
    # (-1111 "Precision is over the maximum", -1013 "Filter failure") BEFORE it
    # reaches the book. Rounding to a blind 6 decimals guarantees rejection on
    # symbols like XRP (step 0.1) or DOT (step 0.01), so every size is now shaped
    # to the symbol's own LOT_SIZE / NOTIONAL filters.
    def _symbol_filters(self, symbol, ttl=3600):
        now = time.time()
        cache = getattr(self, "_filters", None)
        if cache is None:
            cache = self._filters = {}
        hit = cache.get(symbol)
        if hit and now - hit[0] < ttl:
            return hit[1]
        info = None
        try:
            resp = self.session.get(f"{BINANCE_BASE}/api/v3/exchangeInfo",
                                    params={"symbol": symbol}, timeout=10)
            if resp.status_code == 200:
                info = resp.json()
        except Exception as e:
            log_error(f"Filter fetch error {symbol}: {e}")
        rows = (info or {}).get("symbols") or []
        if not rows:
            return None
        s = rows[0]
        f = {"status": s.get("status"), "step": None, "min_qty": 0.0,
             "max_qty": None, "tick": None, "min_notional": 0.0,
             "base": s.get("baseAsset"), "quote": s.get("quoteAsset")}
        for flt in s.get("filters", []):
            t = flt.get("filterType")
            if t == "LOT_SIZE":
                f["step"] = flt.get("stepSize")
                f["min_qty"] = float(flt.get("minQty") or 0)
                f["max_qty"] = float(flt.get("maxQty") or 0) or None
            elif t == "MARKET_LOT_SIZE" and f["step"] is None:
                f["step"] = flt.get("stepSize")
                f["min_qty"] = float(flt.get("minQty") or 0)
            elif t in ("NOTIONAL", "MIN_NOTIONAL"):
                f["min_notional"] = max(f["min_notional"],
                                        float(flt.get("minNotional") or 0))
            elif t == "PRICE_FILTER":
                f["tick"] = flt.get("tickSize")
        cache[symbol] = (now, f)
        return f

    def normalize_qty(self, symbol, quantity, price, side="BUY"):
        """Shape a quantity to the symbol's filters.
        Returns (qty_string, note) or (None, reason). Never rounds UP risk:
        the base size is floored to stepSize, and is only lifted when the
        exchange's own minQty/minNotional would otherwise reject it.

        A SELL is never lifted. It can only spend what the account holds, and
        lifting it to minNotional is exactly what turns a small holding into a
        -1013 NOTIONAL rejection with the coins stranded in the account (a $5.74
        BTC clip whose net fee left 0.00006993 BTC cannot be step-floored to a
        $5.00 order — the caller must dust it instead)."""
        from decimal import Decimal, ROUND_DOWN, ROUND_UP
        f = self._symbol_filters(symbol)
        if not f:
            return None, f"exchangeInfo unavailable for {symbol}"
        if f.get("status") and f["status"] != "TRADING":
            return None, f"{symbol} is {f['status']} on Binance (not TRADING)"
        if not price or price <= 0:
            return None, f"no valid price for {symbol}"
        step = Decimal(str(f.get("step") or "0.00000001"))
        q = Decimal(str(quantity))
        if step > 0:
            q = (q / step).to_integral_value(rounding=ROUND_DOWN) * step
        if q <= 0:
            return None, f"quantity rounds to zero for {symbol}"
        px = Decimal(str(price))
        min_notional = Decimal(str(f.get("min_notional") or 0))
        selling = str(side).upper() == "SELL"
        if selling:
            # never lift: the exchange will take what exists or nothing at all
            if min_notional and q * px < min_notional:
                return None, (f"DUST sellable {q} x {price} = {q * px:.4f} "
                              f"< minNotional {min_notional} for {symbol}")
        else:
            min_qty = Decimal(str(f.get("min_qty") or 0))
            if min_qty and q < min_qty:
                q = (min_qty / step).to_integral_value(rounding=ROUND_UP) * step
            if min_notional and q * px < min_notional:
                need = min_notional / px
                if step > 0:
                    need = (need / step).to_integral_value(rounding=ROUND_UP) * step
                q = need
        max_qty = Decimal(str(f.get("max_qty") or 0))
        if max_qty and q > max_qty:
            return None, f"size {q} above maxQty {max_qty} for {symbol}"
        if q <= 0:
            return None, f"quantity rounds to zero for {symbol}"
        qty_s = format(q.normalize(), "f")
        if "." in qty_s:
            qty_s = qty_s.rstrip("0").rstrip(".")
        note = ""
        if Decimal(qty_s) != Decimal(str(quantity)):
            note = f"{quantity} -> {qty_s} (step {step}, minNotional {min_notional})"
        return qty_s, note

    def place_order(self, symbol, side, quantity, order_type="MARKET", price=None):
        """Place a market order (quantity is shaped to the symbol filters first)"""
        if not self.api_key or not self.api_secret:
            log_error("No API credentials - cannot place order")
            return None
        if price:
            qty_s, note = self.normalize_qty(symbol, quantity, price, side=side)
            if not qty_s:
                log_error(f"ORDER REJECTED LOCALLY {symbol}: {note}")
                return None
            if note:
                log_info(f"ORDER SIZE {symbol}: {note}")
            quantity = qty_s
        try:
            url = f"{BINANCE_BASE}/api/v3/order"
            params = {
                "symbol": symbol,
                "side": side,
                "type": order_type,
                "quantity": quantity,
                "newOrderRespType": "FULL",
                "timestamp": int(time.time() * 1000),
            }
            params["signature"] = self._signature(params)
            resp = self.session.post(url, params=params, timeout=10)
            if resp.status_code == 200:
                result = resp.json()
                fills = result.get("fills") or [{}]
                avg = result.get("cummulativeQuoteQty")
                try:
                    qty = float(result.get("executedQty") or 0)
                    avg = (float(avg) / qty) if qty else fills[0].get("price", "N/A")
                except Exception:
                    avg = fills[0].get("price", "N/A")
                log_info(f"ORDER PLACED: {side} {result.get('executedQty', quantity)} "
                         f"{symbol} @ {avg}")
                return result
            else:
                code = ""
                try:
                    code = (resp.json() or {}).get("code", "")
                except Exception:
                    pass
                log_error(f"Order failed {resp.status_code} [{code}]: {resp.text}")
                return None
        except Exception as e:
            log_error(f"Order exception {symbol}: {e}")
            return None

    # ---- exit-side plumbing: a live exit must actually sell the coins --------
    def base_asset(self, symbol):
        f = self._symbol_filters(symbol) or {}
        if f.get("base"):
            return f["base"]
        for q in ("USDT", "FDUSD", "USDC", "TUSD", "BUSD", "BTC", "ETH", "BNB"):
            if symbol.endswith(q) and len(symbol) > len(q):
                return symbol[:-len(q)]
        return symbol

    def free_balance(self, asset):
        try:
            params = {"timestamp": int(time.time() * 1000)}
            params["signature"] = self._signature(params)
            r = self.session.get(f"{BINANCE_BASE}/api/v3/account", params=params, timeout=10)
            if r.status_code != 200:
                log_error(f"Balance fetch {asset}: HTTP {r.status_code}")
                return None
            for b in r.json().get("balances", []):
                if b.get("asset") == asset:
                    return float(b.get("free") or 0)
        except Exception as e:
            log_error(f"Balance fetch error {asset}: {e}")
        return None

    def dust_asset(self, asset):
        """Convert an unsellable remainder into BNB. Binance charges 2% for this,
        and it is the honest price of exiting a position that the LOT_SIZE and
        NOTIONAL filters have boxed in (step-floored size < minNotional)."""
        try:
            params = {"asset": asset, "timestamp": int(time.time() * 1000)}
            params["signature"] = self._signature(params)
            r = self.session.post(f"{BINANCE_BASE}/sapi/v1/asset/dust",
                                 params=params, timeout=10)
            if r.status_code == 200:
                d = r.json() or {}
                log_warn(f"DUST {asset}: +{d.get('totalTransfered')} BNB "
                         f"(fee {d.get('totalServiceCharge')} BNB)")
                return d
            log_error(f"DUST failed {r.status_code}: {r.text}")
        except Exception as e:
            log_error(f"DUST exception {asset}: {e}")
        return None

    def sell_position(self, symbol, quantity=None, price=None):
        """Market-exit the real holding, sized from the FREE balance and floored
        to stepSize (never lifted). Returns
        {"ok": True, "qty", "avg", "dust"} or {"ok": False, "reason"}."""
        f = self._symbol_filters(symbol)
        if not f:
            return {"ok": False, "reason": f"exchangeInfo unavailable for {symbol}"}
        asset = self.base_asset(symbol)
        free = self.free_balance(asset)
        if free is None:
            return {"ok": False, "reason": f"could not read free {asset}"}
        if quantity:
            free = min(free, float(quantity))
        if free <= 0:
            return {"ok": False, "reason": f"no free {asset}"}
        px = float(price or 0)
        if px <= 0:
            t = self.get_ticker_24hr(symbol) or {}
            px = float(t.get("lastPrice") or 0)
        qty_s, note = self.normalize_qty(symbol, free, px, side="SELL")
        if not qty_s:
            if "DUST" in str(note):
                d = self.dust_asset(asset)
                if d:
                    return {"ok": True, "qty": 0.0, "avg": px, "dust": True,
                            "note": note, "dust_result": d}
                return {"ok": False, "reason": f"{note}; dust failed"}
            return {"ok": False, "reason": note}
        if note:
            log_info(f"EXIT SIZE {symbol}: {note}")
        res = self.place_order(symbol, "SELL", qty_s, price=px)
        if not res:
            return {"ok": False, "reason": "sell rejected by exchange"}
        q = float(res.get("executedQty") or qty_s)
        quote = float(res.get("cummulativeQuoteQty") or 0)
        return {"ok": True, "qty": q, "avg": (quote / q) if q else px,
                "dust": False, "order": res}

class OrderFlowAnalyzer:
    """Analyze order flow and liquidity pools"""
    def __init__(self):
        self.volume_history = defaultdict(lambda: deque(maxlen=100))
        self.price_history = defaultdict(lambda: deque(maxlen=100))
        self.liquidity_pools = defaultdict(dict)
        self.order_flow_score = defaultdict(float)
    
    def analyze_volume_spike(self, symbol, ticker_24h, recent_trades, klines=None):
        """Real relative volume + short momentum from 1m klines (recomputed every cycle)."""
        vol_24h = float(ticker_24h.get("quoteVolume", ticker_24h.get("volume", 0)) or 0)
        price_change = float(ticker_24h.get("priceChangePercent", 0) or 0)

        # --- relative volume: last completed 1m bar vs its own rolling baseline ---
        vol_ratio = 1.0
        mom = 0.0
        try:
            if klines and len(klines) >= 8:
                qv = [float(k[7]) for k in klines]       # quote volume per 1m bar
                closes = [float(k[4]) for k in klines]
                completed = qv[:-1]                      # drop the still-forming bar
                if len(completed) >= 6:
                    base = sum(completed[-20:]) / len(completed[-20:])
                    if base > 0:
                        vol_ratio = completed[-1] / base
                if len(closes) >= 6 and closes[-6] > 0:
                    mom = (closes[-1] - closes[-6]) / closes[-6] * 100.0
        except Exception:
            pass

        self.volume_history[symbol].append(vol_ratio)

        # --- real order flow from recent trades (quote notional) ---
        buy_vol = 0.0
        sell_vol = 0.0
        for trade in recent_trades or []:
            try:
                t_vol = float(trade.get("q", 0)) * float(trade.get("p", 0))
            except (TypeError, ValueError):
                continue
            if trade.get("m", False):   # m=true -> buyer is maker -> aggressive SELL
                sell_vol += t_vol
            else:
                buy_vol += t_vol
        total_vol = buy_vol + sell_vol
        buy_ratio = buy_vol / total_vol if total_vol > 0 else 0.5

        return {
            "symbol": symbol,
            "volume_24h": vol_24h,
            "volume_ratio": round(vol_ratio, 2),
            "momentum_5m": round(mom, 2),
            "price_change_percent": round(price_change, 2),
            "buy_ratio": round(buy_ratio, 4),
            "sell_ratio": round(1 - buy_ratio, 4),
            "buy_notional": round(buy_vol, 2),
            "sell_notional": round(sell_vol, 2),
            "order_flow_score": 0,
            "is_mover": False,
        }

    def score(self, rec):
        """Dynamic 0-100 sniper score. Only aligns to 80+ on real, live conditions."""
        vr = float(rec.get("volume_ratio", 1.0) or 1.0)
        mom = abs(float(rec.get("momentum_5m", 0) or 0))
        imb = abs(float(rec.get("imbalance", 0) or 0))
        spread = float(rec.get("spread_pct", 99) or 99)
        br = float(rec.get("buy_ratio", 0.5) or 0.5)

        s = 0.0
        s += 35.0 * min(vr / 3.0, 1.0)                    # volume expansion (3x = full)
        s += 25.0 * min(mom / 3.0, 1.0)                   # 5-min momentum (3% = full)
        s += 20.0 * min(imb / 0.60, 1.0)                  # book imbalance (0.6 = full)
        s += 10.0 if (0 < spread <= 0.30) else 0          # tight, tradable spread
        s += 10.0 if (br >= 0.65 or br <= 0.35) else 0    # one-sided aggression
        rec["order_flow_score"] = int(round(s))
        rec["is_mover"] = rec["order_flow_score"] >= 60 and vr >= 2.0
        self.order_flow_score[rec["symbol"]] = rec["order_flow_score"]
        return rec
    
    def analyze_liquidity(self, symbol, order_book):
        """Analyze liquidity pools from order book"""
        if not order_book:
            return {"bid_liquidity": 0, "ask_liquidity": 0, "imbalance": 0, "spread_pct": 0}
        
        bids = order_book.get("bids", [])
        asks = order_book.get("asks", [])
        
        bid_liq = sum(float(b[1]) * float(b[0]) for b in bids[:20])
        ask_liq = sum(float(a[1]) * float(a[0]) for a in asks[:20])
        
        if bids and asks:
            best_bid = float(bids[0][0])
            best_ask = float(asks[0][0])
            spread_pct = ((best_ask - best_bid) / best_bid) * 100
        else:
            spread_pct = 0
        
        imbalance = (bid_liq - ask_liq) / (bid_liq + ask_liq) if (bid_liq + ask_liq) > 0 else 0
        
        self.liquidity_pools[symbol] = {
            "bid_liquidity": round(bid_liq, 2),
            "ask_liquidity": round(ask_liq, 2),
            "imbalance": round(imbalance, 4),
            "spread_pct": round(spread_pct, 4),
            "updated": time.time()
        }
        
        return self.liquidity_pools[symbol]

class Hunter:
    """Main Hunter trading engine"""
    def __init__(self):
        self.client = BinanceClient()
        self.analyzer = OrderFlowAnalyzer()
        self.state = self._load_state()
        self.positions = {}
        self.watchlist = []
        self.running = False
        self.balance = START_BALANCE
        self.target = TARGET_BALANCE
        self.trades_today = 0
        self.pnl_today = 0.0
        self.cooldown = {}  # symbol -> timestamp of last exit
        self.entry_guard = {}  # symbol -> timestamp of last entry attempt (dedupes per cycle)
        self.last_scan = 0
        self.last_heartbeat = 0
        self.market_rank = []      # full-market ranked rows (basic metrics)
        self.swept_count = 0       # symbols swept from the 24h endpoint
        self.candidates_count = 0  # tradable USDT pairs after filter
        self._last_reject_log = 0  # throttle for the live rejection feed
        self.feeds = FeedsHub()    # external crypto sources (news/trending/FNG/futures/whales)
        self._catch_ts = {}        # per-kind throttle for agent "catches"
        self._signal_sym_type = {} # symbol -> "signal" or "prepump" (mutually exclusive)
        self.pegged_excluded = 0   # stablecoin/fiat/commodity pegs filtered out
        self.dead_excluded = 0     # halted / delisted / inactive markets filtered out
        self.tokenised_excluded = 0  # tokenised equity/ETF receipts filtered out
        self.trading_set = set()   # symbols Binance reports as TRADING
        self._trading_ts = 0.0     # last exchangeInfo refresh
        self.catalyst_entries = 0  # entries fired by the news/social keyword engine
        self.prepump_entries = 0   # entries fired early by the pre-pump radar
        self.notify = Notifier(os.path.join(BOT, ".env"))  # Telegram push cards
        self._card_ts = {}         # per-kind throttle for push cards
        self._boot_carded = False
        # --- armed alerts: armed once, the engine fires them when the level/time hits
        self.alerts = alertbook.AlertBook(ALERTS_FILE, tzinfo=HUNTER_TZINFO)
        self.alerts_fired = 0      # how many alerts this engine has fired
        # --- signal follow-up: every fired signal gets a real plan and is tracked
        self.ledger = signals.SignalLedger(os.path.join(BOT, "signals.json"))
        self._mark_ts = 0.0        # last ledger marking pass
        # --- AltFins bullish chart patterns (fail-closed external source)
        self.altfins = altfins.AltFins()
        self._alt_ts = 0.0
        # --- backtest-all sweep over the universe
        self.sweep = None
        self._sweep_ts = 0.0
        # --- First-Move Radar: catch the first move before the move (leading ranks)
        self.radar = pregainers.FirstMoveRadar()
        self._radar_ts = 0.0
        self.firstmove_entries = 0
        # --- market regime gate: RISK_OFF stands the hunter down (risk control only)
        self.regime = regime.RegimeGate()
        self._regime_ts = 0.0
        # --- risk management state: the envelope that bounds the damage while live
        self.day_key = self._day_key()
        self.day_start_balance = self.balance
        self.loss_streak = 0
        self.pause_until = 0.0
        self.day_locked = False
        self.risk_halt_reason = ""
        self.trade_perm_reason = ""  # why live orders are refused (missing key permission)

    # ------------------------------------------------------------------ risk
    @staticmethod
    def _day_key(when=None):
        """Calendar day in the hunter's timezone (New York) — the risk day."""
        try:
            return datetime.now(HUNTER_TZINFO).strftime("%Y-%m-%d")
        except Exception:
            return time.strftime("%Y-%m-%d")

    def _roll_day(self):
        """Reset the daily risk counters when the New York date turns over."""
        key = self._day_key()
        if key != self.day_key:
            self.day_key = key
            self.day_start_balance = self.balance
            self.day_locked = False
            self.loss_streak = 0
            self.pause_until = 0.0
            log_info(f"RISK: new trading day {key} — envelope reset, "
                     f"start balance ${self.balance:.2f}")

    def _risk_ok(self):
        """The gate every NEW entry must clear. Returns (ok, reason).

        Hard circuit breakers, in priority order: an open loss-streak pause wins,
        then the daily loss cap, then the daily profit lock. Breakers only ever
        BLOCK; they never open a position. Existing positions are always allowed
        to manage and exit — a breaker must not trap capital.
        """
        self._roll_day()
        now = time.time()
        if now < self.pause_until:
            mins = int((self.pause_until - now) / 60) + 1
            return False, f"loss-streak pause ({self.loss_streak} in a row) — {mins}m left"
        if self.day_locked:
            return False, self.risk_halt_reason or "daily loss cap hit — locked"
        if self.day_start_balance > 0:
            day_pnl = (self.balance - self.day_start_balance) / self.day_start_balance
            if day_pnl <= -MAX_DAY_LOSS_FRAC:
                self.day_locked = True
                self.risk_halt_reason = (f"daily loss cap {day_pnl*100:.1f}% "
                                         f"(<= -{MAX_DAY_LOSS_FRAC*100:.0f}%) — locked until tomorrow")
                log_warn("RISK: " + self.risk_halt_reason)
                return False, self.risk_halt_reason
            if day_pnl >= DAILY_PROFIT_LOCK:
                self.day_locked = True
                self.risk_halt_reason = (f"daily profit lock +{day_pnl*100:.1f}% "
                                         f"(>= +{DAILY_PROFIT_LOCK*100:.0f}%) — protecting the win")
                log_info("RISK: " + self.risk_halt_reason)
                return False, self.risk_halt_reason
        ok, why = self.regime.allow_entries()
        if not ok:
            return False, why
        return True, "within limits"

    def risk_snapshot(self):
        """Read-only view of the entry gate for the dashboard banner.

        Reuses _risk_ok() so the banner can never disagree with the engine about
        whether new entries are allowed. Breakers are already latched by the time
        they show here, so this poll cannot silently widen the envelope.
        """
        self._roll_day()
        now = time.time()
        ok, why = self._risk_ok()
        pnl = 0.0
        if self.day_start_balance > 0:
            pnl = (self.balance - self.day_start_balance) / self.day_start_balance

        # the banner must never disagree with the engine: the same cached probe
        # that execute_trade gates on, and always a plain-English reason
        _perm = self.client.spot_trading_allowed()
        _perm_why = self.trade_perm_reason
        if _perm.get("allowed") is True:
            _perm_why = ""
        elif _perm.get("allowed") is False:
            _perm_why = _perm_why or "Binance key has no Spot & Margin trading permission"
        else:
            _perm_why = _perm_why or f"trading permission unknown ({_perm.get('raw')})"

        return {
            "ok": bool(ok),
            "reason": why,
            "day_key": self.day_key,
            "start_balance": round(self.day_start_balance, 4),
            "day_pnl_pct": round(pnl * 100.0, 2),
            "day_locked": bool(self.day_locked),
            "halt_reason": self.risk_halt_reason,
            "loss_streak": self.loss_streak,
            "pause_sec": max(0, int(self.pause_until - now)),
            "max_day_loss_pct": round(MAX_DAY_LOSS_FRAC * 100.0, 1),
            "max_consec_losses": MAX_CONSEC_LOSSES,
            "daily_profit_lock_pct": round(DAILY_PROFIT_LOCK * 100.0, 1),
            "max_pos_frac": MAX_POS_FRAC,
            "min_notional": MIN_NOTIONAL_USD,
            "live_orders": LIVE_ORDERS,
            "trade_perm": _perm.get("allowed"),
            "trade_perm_reason": _perm_why,
        }

    def refresh_trading_symbols(self, ttl=900):
        """Cache Binance's TRADING symbol list — the authoritative not-dead filter."""
        now = time.time()
        if self.trading_set and now - self._trading_ts < ttl:
            return self.trading_set
        info = self.client.get_exchange_info()
        syms = set()
        try:
            for s in (info or {}).get("symbols", []) or []:
                if s.get("status") == "TRADING" and s.get("quoteAsset") == "USDT":
                    syms.add(s.get("symbol"))
        except Exception:
            syms = set()
        if syms:
            self.trading_set = syms
            self._trading_ts = now
        return self.trading_set
    
    def _load_state(self):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {"started": now_local().isoformat(), "trades": [], "pnl": 0.0}
    
    def _save_state(self):
        try:
            with open(STATE_FILE, "w") as f:
                json.dump(self.state, f, indent=2)
        except Exception as e:
            log_error(f"Save state error: {e}")
    
    def get_balance(self):
        """Get USDT balance"""
        acc = self.client.get_account()
        if "error" in acc:
            return START_BALANCE
        for b in acc.get("balances", []):
            if b["asset"] == "USDT":
                return float(b["free"]) + float(b["locked"])
        return START_BALANCE
    
    def scan_market(self):
        """Sweep the ENTIRE Binance USDT spot market, then deep-scan a ranked shortlist."""
        tickers = self.client.get_ticker_24hr()
        if not tickers:
            return []
        if isinstance(tickers, dict):
            tickers = [tickers]
        tmap = {t.get("symbol"): t for t in tickers if t.get("symbol")}

        # ---- dead-market filter: Binance listing status is authoritative ----
        trading = self.refresh_trading_symbols()

        # ---- Stage 1: FULL market sweep (one call covers every listed symbol) ----
        market = []
        pegged = 0
        dead = 0
        tokenised = 0
        for t in tickers:
            sym = t.get("symbol", "")
            if not sym.endswith("USDT"):
                continue
            if is_tokenised(sym):
                tokenised += 1
                continue
            if is_pegged(sym):
                pegged += 1
                continue
            if trading and sym not in trading:      # halted / delisted / not TRADING
                dead += 1
                continue
            try:
                qv = float(t.get("quoteVolume", 0) or 0)
                chg = float(t.get("priceChangePercent", 0) or 0)
                px = float(t.get("lastPrice", 0) or 0)
                cnt = int(t.get("count", 0) or 0)
            except (TypeError, ValueError):
                continue
            if px <= 0 or qv < SWEEP_MIN_QUOTE:
                continue
            if cnt < DEAD_MIN_TRADES:              # illiquid, no real two-way flow
                dead += 1
                continue
            market.append({
                "symbol": sym,
                "current_price": px,
                "price_change_percent": round(chg, 2),
                "volume_24h": qv,
                "trades_24h": cnt,
            })
        self.swept_count = len(tickers)
        self.candidates_count = len(market)
        self.pegged_excluded = pegged
        self.dead_excluded = dead
        self.tokenised_excluded = tokenised
        try:
            swarm.heartbeat("scanner", bump=True)
        except Exception:
            pass

        # rank the whole market by activity x volatility
        market.sort(key=lambda x: x["volume_24h"] * (1 + abs(x["price_change_percent"]) / 10.0), reverse=True)
        self.market_rank = market[:MARKET_SHOW]

        # ---- Stage 2: deep scan the shortlist (trades + order book + 1m klines) ----
        # The First-Move Radar is a LEADING list (money and attention arriving
        # before the candle), so its tradable names are force-included in the deep
        # scan even when they sit below the volume cut. That is how a small cap is
        # hunted *before* it turns into a gainer, without widening the scan.
        scan_rows = list(market[:SHORTLIST])
        try:
            self.refresh_trading_symbols()
            have = {r["symbol"] for r in scan_rows}
            extra = 0
            for c in self.radar.tradeable(self.trading_set or None, FIRSTMOVE_MIN, 40):
                sym = c.get("pair")
                if sym and sym not in have and sym in (self.trading_set or set()):
                    t = tmap.get(sym)
                    if t:
                        scan_rows.append({
                            "symbol": sym,
                            "current_price": float(t.get("lastPrice", 0) or 0),
                            "price_change_percent": float(t.get("priceChangePercent", 0) or 0),
                            "volume_24h": float(t.get("quoteVolume", 0) or 0),
                            "trades_24h": int(t.get("count", 0) or 0),
                        })
                        have.add(sym)
                        extra += 1
                        if extra >= FIRSTMOVE_INJECT:
                            break
        except Exception as e:
            log_error(f"radar inject error: {e}")

        results = []
        MAX_WORKERS = 1  # serial deep-scan — one Binance call at a time, no pool exhaustion

        def _deep_scan(row):
            """Fetch klines + trades + order book for one symbol, return its analysis dict or None."""
            symbol = row["symbol"]
            ticker = tmap.get(symbol)
            if ticker is None:
                return None
            klines = self.client.get_klines(symbol, interval="1m", limit=DEEP_KLINES)
            trades = self.client.get_recent_trades(symbol, limit=50)
            ob = self.client.get_order_book(symbol, limit=20)
            # a market with no recent candles or no two-sided book is dead — never hunt it
            if len(klines or []) < 20 or not trades:
                return None
            if not (ob or {}).get("bids") or not (ob or {}).get("asks"):
                return None
            of = self.analyzer.analyze_volume_spike(symbol, ticker, trades or [], klines or [])
            of.update(self.analyzer.analyze_liquidity(symbol, ob))
            of["current_price"] = row["current_price"]
            of["price_change_percent"] = row["price_change_percent"]
            of["volume_24h"] = row["volume_24h"]
            of["bid_price"] = float(ticker.get("bidPrice", 0) or 0)
            of["ask_price"] = float(ticker.get("askPrice", 0) or 0)
            of["high_24h"] = float(ticker.get("highPrice", 0) or 0)
            of["low_24h"] = float(ticker.get("lowPrice", 0) or 0)
            of["trades_24h"] = row["trades_24h"]
            of["klines"] = klines  # keep for enhance.py read outside the fetch loop
            self.analyzer.score(of)
            try:
                full_ta = ta.analyze(symbol, klines, "1m")
            except Exception:
                full_ta = None
            if full_ta:
                near = full_ta["nearest"]
                of["ta"] = {
                    "score": full_ta["score"], "bias": full_ta["bias"], "trend": full_ta["trend"],
                    "position": full_ta["fib"]["position"],
                    "swing_lo": full_ta["swing"]["lo"], "swing_hi": full_ta["swing"]["hi"],
                    "support": near["support"]["price"] if near["support"] else None,
                    "resistance": near["resistance"]["price"] if near["resistance"] else None,
                    "golden": ta.GOLDEN_LO <= full_ta["fib"]["position"] <= ta.GOLDEN_HI,
                    "gann1x1": full_ta["gann"]["fan"].get("1x1"),
                }
            try:
                self.feeds.scan_whales(symbol, trades, of["current_price"])
                self.feeds.scan_walls(symbol, ob)
            except Exception:
                pass
            try:
                of["prepump"] = ta.prepump(
                    symbol, klines, order_book=ob, ticker=ticker,
                    volume_ratio=of.get("volume_ratio", 0),
                    buy_ratio=of.get("buy_ratio", 0.5),
                    catalyst=self.feeds.news_score(symbol),
                    ta_read=full_ta)
            except Exception as e:
                of["prepump"] = None
                log_error(f"prepump error {symbol}: {e}")
            try:
                rr = self._radar_row(symbol)
                if rr:
                    of["radar"] = rr
            except Exception:
                pass
            try:
                st = structure.hunt_multi(symbol, klines)
            except Exception as e:
                st = None
                log_error(f"structure error {symbol}: {e}")
            if st:
                of["struct"] = {
                    "tf": st.get("tf"), "state": st.get("state"), "score": st.get("score"),
                    "labels": st.get("labels"), "bullish": st.get("bullish"),
                    "bos": st.get("bos"), "choch": st.get("choch"),
                    "swing_hi": st.get("swing_hi"), "swing_lo": st.get("swing_lo"),
                    "align": st.get("align"), "trigger": st.get("trigger"),
                    "target": st.get("target"), "invalidation": st.get("invalidation"),
                    "atr": st.get("atr"), "price": st.get("price"),
                    "patterns": st.get("patterns"), "ladder": st.get("ladder"),
                    "tf_count": st.get("tf_count"), "multi_tf": st.get("multi_tf"),
                    "vp": st.get("vp"), "time": st.get("time"),
                    "reasons": st.get("reasons"),
                }
                of["hunt_tf"] = st.get("tf") or "1m"
                sc = int(st.get("score") or 0)
                aligned = bool((st.get("align") or {}).get("aligned"))
                if st.get("bullish") and aligned:
                    of["struct_adj"] = 5 if sc >= 75 else 3
                elif (not st.get("bullish")) and sc >= 62:
                    of["struct_adj"] = -5
                else:
                    of["struct_adj"] = 0
            else:
                of["hunt_tf"] = "1m"
                of["struct_adj"] = 0
            return of

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {pool.submit(_deep_scan, row): row["symbol"] for row in scan_rows}
            for fut in as_completed(futures):
                r = fut.result()
                if r:
                    results.append(r)

        # ---- leading evidence from enhance.py (pure, zero-extra-REST reads) ----
        # runs inside the per-symbol loop so every symbol gets its own read;
        # klines and of are already fetched for this symbol — no extra REST.
        for r in results:
            try:
                rread = read(r.get("klines") or [], high24=r.get("high_24h") or 0, btc_m5=0.0)
                if rread:
                    r["enhance"] = rread
                    pboost, pwhy = prepump_boost(rread)
                    r["prepump_boost"] = pboost
                    adju, awhy = hunt_boost(rread)
                    r["hunt_boost"] = adju
                    r["boost_whys"] = pwhy + awhy
                else:
                    r["enhance"] = None
                    r["prepump_boost"] = 0
                    r["hunt_boost"] = 0
                    r["boost_whys"] = []
            except Exception as e:
                log_error(f"enhance read error {r.get('symbol')}: {e}")
                r["enhance"] = None
                r["prepump_boost"] = 0
                r["hunt_boost"] = 0
                r["boost_whys"] = []

        # ---- external source feeds (throttled internally) ----
        try:
            self.feeds.refresh_news()
            self.feeds.refresh_trending()
            self.feeds.refresh_fng()
            self.feeds.refresh_futures([r["symbol"] for r in results[:6]])
            self.feeds.refresh_headlines()
            self.feeds.rebuild_catalysts([r["symbol"] for r in results])
        except Exception:
            pass

        # ---- fold feed + Fib/Gann confluence into the live score ----
        for r in results:
            base = r["symbol"][:-4] if r["symbol"].endswith("USDT") else r["symbol"]
            try:
                adj, flags = self.feeds.bias(r["symbol"], base)
            except Exception:
                adj, flags = 0, []
            # long-only hunter: Fib/Gann is only ever scored against the long side,
            # so a bearish read subtracts confluence instead of earning it for a short
            direction = "BUY"
            try:
                tadj, treason = ta.adjust(r.get("ta"), direction)
            except Exception:
                tadj, treason = 0, ""
            if treason:
                flags = list(flags) + [treason]
            # structural read folded in as a bounded confluence (max ±5)
            sadj = int(r.get("struct_adj") or 0)
            if sadj:
                stx = r.get("struct") or {}
                flags = list(flags) + ["struct %s %s" % (stx.get("state", "?"), stx.get("tf", ""))]
            r["feed_adj"] = adj
            r["ta_adj"] = tadj
            r["struct_adj"] = sadj
            r["feed_flags"] = flags
            r["catalyst"] = self.feeds.news_score(r["symbol"])
            cat = self.feeds.catalyst(r["symbol"])
            r["catalyst_title"] = (cat or {}).get("title", "")
            r["catalyst_source"] = (cat or {}).get("source", "")
            r["catalyst_url"] = (cat or {}).get("url", "")
            r["catalyst_url"] = (cat or {}).get("url", "")
            total = adj + tadj + sadj
            if total:
                r["order_flow_score"] = max(0, min(100, int(r.get("order_flow_score", 0)) + total))

            # leading evidence from enhance.py (pure, zero-extra-REST reads)
            try:
                rread = read(r.get("klines") or [], high24=r.get("high_24h") or 0, btc_m5=0.0)
                if rread:
                    r["enhance"] = rread
                    pboost, pwhy = prepump_boost(rread)
                    r["prepump_boost"] = pboost
                    adju, awhy = hunt_boost(rread)
                    r["hunt_boost"] = adju
                    r["boost_whys"] = pwhy + awhy
                else:
                    r["enhance"] = None
                    r["prepump_boost"] = 0
                    r["hunt_boost"] = 0
                    r["boost_whys"] = []
            except Exception as e:
                log_error(f"enhance read error {r.get('symbol')}: {e}")
                r["enhance"] = None
                r["prepump_boost"] = 0
                r["hunt_boost"] = 0
                r["boost_whys"] = []

            # pre-pump: the news layer has scored the catalyst by now, so fold it in
            pp = r.get("prepump")
            if pp and int(r.get("catalyst") or 0) >= 6:
                pp["score"] = min(100, int(pp.get("score", 0)) + 5)
                pp["coiled"] = pp["score"] >= ta.PREPUMP_MIN
                pp["reasons"] = (["news catalyst %.0f" % int(r["catalyst"])] + (pp.get("reasons") or []))[:6]

        results.sort(key=lambda x: x.get("order_flow_score", 0), reverse=True)
        try:
            self.feeds.set_volume_surge(results)
        except Exception:
            pass

        # ---- AltFins bullish chart patterns refreshed into a cached edge
        try:
            if time.time() - self._alt_ts > 300:
                self.altfins.refresh(tradable=self.trading_set)
                self._alt_ts = time.time()
        except Exception as e:
            log_error(f"AltFins refresh error: {e}")

        # ---- every candidate leaves the scan with an AltFins edge and a real plan
        for r in results:
            try:
                r["altfins"] = self.altfins.bias(r.get("symbol"))
            except Exception:
                r["altfins"] = 0.0
            try:
                a = r.get("altfins") or 0.0
                if a:
                    r["order_flow_score"] = min(100, int(r.get("order_flow_score", 0)) + int(round(a)))
                    r.setdefault("feed_flags", []).append("altfins +%s" % a)
            except Exception:
                pass
            try:
                r["plan"] = signals.plan(r, self.balance, risk_pct=RISK_PER_TRADE)
            except Exception:
                r["plan"] = None

        # ---- follow-up ledger: record the filter's own shortlist so the hunt is
        #      measurable (fronttest) even on cycles that never fire an entry.
        #      Bullish structures only -- the hunter is long-only, so a bearish or
        #      sideways read is not a hunt and must not pollute the fronttest.
        try:
            rejected = []
            for r in results[:6]:
                ok_q, why_q = self.hunt_quality(r)
                if ok_q:
                    self._track(r, "BUY", r.get("order_flow_score", 0), "watch", kind="watch")
                else:
                    rejected.append(f"{r.get('symbol')}:{why_q}")
            if rejected and time.time() - getattr(self, "_last_reject_log", 0) > 120:
                log_error("watch filtered -> " + " | ".join(rejected[:6]))
                self._last_reject_log = time.time()
        except Exception as e:
            log_error(f"watch track error: {e}")

        self.watchlist = results[:SHORTLIST]
        return self.watchlist
    
    def _track(self, analysis, direction, score, entry_type, kind="signal", tf=None, px=None):
        """Open a follow-up row for a fired signal, with its real plan attached.

        `px` is the true fill for an executed entry. A watched signal is instead
        anchored to the plan's own entry, so the row's stop and targets are measured
        from the same price the plan was built around. Using the live tick there can
        sit on the far side of the trigger and manufacture a phantom stop.
        """
        try:
            # Never open a follow-up row for a pegged asset or a tokenised equity:
            # this is the single funnel every signal/entry passes through, so the
            # refusal here covers the order-flow, newsdesk, pre-pump, watch and
            # entry emitters in one place.
            if not huntable(analysis.get("symbol")):
                log_error(f"track refused (not huntable): {analysis.get('symbol')}")
                return None
            st = analysis.get("struct") or {}
            pl = analysis.get("plan") or signals.plan(analysis, self.balance, risk_pct=RISK_PER_TRADE)
            if px is None and kind != "entry":
                px = (pl or {}).get("entry")
            if not px:
                px = analysis.get("current_price") or st.get("price")
            return self.ledger.record(
                analysis.get("symbol"), direction, px,
                entry_type=entry_type,
                timeframe=tf or analysis.get("hunt_tf") or st.get("tf") or "1m",
                score=score, kind=kind,
                reasons=st.get("reasons"), state=st.get("state"),
                trigger=st.get("trigger"), target=st.get("target"),
                invalidation=st.get("invalidation"), plan=pl)
            # Notion journal: every fired signal is tracked outside the local ledger
            try:
                nj.log_signal(
                    symbol=analysis.get("symbol"), score=score,
                    entry_type=entry_type, timeframe=tf or analysis.get("hunt_tf") or st.get("tf") or "1m",
                    reasons=st.get("reasons"), state=st.get("state"),
                    trigger=st.get("trigger"), target=st.get("target"),
                    invalidation=st.get("invalidation"), plan=pl, ts=time.time())
            except Exception as e:
                log_error(f"notion_journal signal error: {e}")
        except Exception as e:
            log_error(f"_track error: {e}")
            return None

    def has_open_signal(self, symbol):
        """True if this symbol already has an OPEN follow-up/signal row.

        We want exactly one thing per token: either a NEW signal or a
        follow-up — never both. So once a symbol has a live row in the
        ledger, no new signal card fires for it until it resolves."""
        try:
            for r in (self.ledger.rows or []):
                if r.get("status") == "OPEN" and r.get("symbol") == symbol:
                    return True
        except Exception:
            pass
        return False

    def _max_positions(self):
        """How many concurrent positions this balance can actually size.

        With a $6 exchange floor a $9 account fits exactly one entry, no matter
        what MAX_POSITIONS says — so the cap follows the money, and opens up to 3
        as the account grows.
        """
        try:
            fits = int(self.balance // MIN_NOTIONAL_USD) or 1
        except Exception:
            fits = 1
        return max(1, min(MAX_POSITIONS, fits))

    def _radar_row(self, symbol):
        """The First-Move Radar row for a Binance pair, tagged with its live score."""
        base = (symbol[:-4] if symbol.endswith("USDT") else symbol).upper()
        with self.radar.lock:
            r = self.radar.rows.get(base)
            if not r:
                return None
            row = dict(r)
        row["pregain"] = self.radar.score_row(row)
        return row

    def _refresh_leads(self, now):
        """Refresh the leading indicators the hunter reads. Both are throttled and
        run off-thread, so a slow source never stalls a hunting cycle."""
        try:
            self.radar.maybe_refresh_async()
        except Exception:
            pass
        try:
            self.regime.maybe_refresh_async()
        except Exception:
            pass

    def should_enter_firstmove(self, analysis):
        """BULLISH ONLY — the First-Move Radar path.

        Fires when money or attention is arriving while price is still flat (the
        very thing that *makes* a top gainer), and the long-side structure agrees.
        Deliberately strict on structure and liquidity but tolerant of a flat 5m
        move — the entire point is to be early, so demanding that price has already
        moved would defeat the path.
        """
        row = analysis.get("radar") or {}
        score = float(row.get("pregain") or 0)
        if score < FIRSTMOVE_MIN:
            return False, f"Radar too weak: {score:.0f} (need {FIRSTMOVE_MIN})"
        vr = float(analysis.get("volume_ratio", 0) or 0)
        if vr < FIRSTMOVE_MIN_VOL:
            return False, f"Radar blocked — volume not arriving ({vr:.1f}x)"
        spread = analysis.get("spread_pct", 100)
        max_spread = self._eff_gate("HUNT_MAX_SPREAD", HUNT_MAX_SPREAD)
        if spread > max_spread:
            return False, f"Radar blocked — spread {spread:.2f}%"
        bid_liq = analysis.get("bid_liquidity", 0)
        ask_liq = analysis.get("ask_liquidity", 0)
        min_depth = self._eff_gate("HUNT_MIN_DEPTH", HUNT_MIN_DEPTH)
        if bid_liq < min_depth or ask_liq < min_depth:
            return False, f"Radar blocked — depth ${bid_liq:.0f}/${ask_liq:.0f}"
        if len(self.positions) >= self._max_positions():
            return False, "Max positions reached"
        sym = analysis["symbol"]
        if sym in self.positions:
            return False, f"Already in position: {sym}"
        now = time.time()
        if sym in self.cooldown and now - self.cooldown[sym] < 600:
            return False, "Cooldown active"
        # Mutual exclusion: one signal per token — signal OR prepump, never both
        if self.has_open_signal(sym):
            return False, f"Already tracking: {sym}"
        if self._signal_sym_type.get(sym) == "signal":
            return False, f"Signal already claimed: {sym}"
        min_need = self._eff_gate("HUNT_GATE_NEED", HUNT_GATE_NEED)
        ok, why, direction = structure.bullish_gate(analysis, need=min_need)
        if not ok:
            return False, "Radar " + why
        t = analysis.get("ta") or {}
        tb = t.get("bias")
        swarm.register_signal("quant", symbol=sym, direction=direction, score=int(score),
                              reason=f"first-move {score:.0f} — radar inflow")
        try:
            self._card("firstmove:" + sym, card_signal(
                sym, direction, int(score), "first-move", vol=vr,
                price=analysis.get("current_price"),
                tf=analysis.get("hunt_tf") or "1m",
                mom=analysis.get("momentum_5m"), imb=analysis.get("imbalance"),
                ta_bias=tb, ta_score=t.get("score"), flags=analysis.get("feed_flags"),
                plan=analysis.get("plan")), ttl=180)
        except Exception:
            pass
        self._track(analysis, direction, int(score), "first-move", kind="signal")
        return True, (f"radar {score:.0f} | inflow ${float(row.get('inflow') or 0):,.0f} | "
                      f"hype {float(row.get('hype') or 0):,.0f} | chg {float(row.get('chg') or 0):+.1f}%")

    def hunt_quality(self, analysis):
        """The hunt bar WITHOUT position/cooldown state.

        Mirrors should_enter() checks 1-7 so the follow-up ledger only records
        rows that were genuinely snipeable. Recording score>=WATCH_MIN alone is
        what produced 329 'watch' rows measuring pure noise.
        """
        score = analysis.get("order_flow_score", 0) or 0
        vol_ratio = analysis.get("volume_ratio", 0) or 0
        momentum = abs(analysis.get("momentum_5m", 0) or 0)
        imbalance = abs(analysis.get("imbalance", 0) or 0)
        spread = analysis.get("spread_pct", 100)
        if spread is None:
            spread = 100
        bid_liq = analysis.get("bid_liquidity", 0) or 0
        ask_liq = analysis.get("ask_liquidity", 0) or 0

        min_score = self._eff_gate("HUNT_MIN_SCORE", HUNT_MIN_SCORE)
        if score < min_score:
            return False, f"score {score}<{min_score:.0f}"
        min_vol = self._eff_gate("HUNT_MIN_VOL", HUNT_MIN_VOL)
        if vol_ratio < min_vol:
            return False, f"vol {vol_ratio:.1f}x<{min_vol:.1f}x"
        min_mom = self._eff_gate("HUNT_MIN_MOM", HUNT_MIN_MOM)
        if momentum < min_mom:
            return False, f"mom {momentum:.1f}%<{min_mom:.1f}%"
        max_spread = self._eff_gate("HUNT_MAX_SPREAD", HUNT_MAX_SPREAD)
        if spread > max_spread:
            return False, f"spread {spread:.2f}%>{max_spread:.1f}%"
        min_depth = self._eff_gate("HUNT_MIN_DEPTH", HUNT_MIN_DEPTH)
        if bid_liq < min_depth or ask_liq < min_depth:
            return False, f"depth bid/ask ${bid_liq:.0f}/${ask_liq:.0f}<${min_depth:.0f}"
        min_imbal = self._eff_gate("HUNT_MIN_IMBAL", HUNT_MIN_IMBAL)
        if imbalance < min_imbal:
            return False, f"imbal {imbalance:.2f}<{min_imbal:.2f}"
        min_need = self._eff_gate("HUNT_GATE_NEED", HUNT_GATE_NEED)
        ok, why, _direction = structure.bullish_gate(analysis, need=min_need)
        if not ok:
            return False, why
        return True, "ok"

    def _eff_gate(self, name, default):
        """Regime-aware effective gate threshold.

        NEUTRAL / choppy market → wider gates (catch early moves before they print).
        RISK_ON → slightly tighter gates (quality over quantity).
        RISK_OFF should never reach here (allow_entries blocks it first).
        """
        base = float(default)
        zone = self.regime.zone
        score = self.regime.score or 50.0
        if zone == "RISK_ON":
            mult = 0.85   # tighter when trend is strong
        elif zone == "NEUTRAL":
            mult = 1.5    # wider when tape is quiet — catch the first move early
        else:
            mult = 1.25   # defensive fallback
        if name == "HUNT_MIN_SCORE":
            return max(10, base * mult)
        if name == "HUNT_MIN_VOL":
            return base / mult        # lower vol bar when widening
        if name == "HUNT_MIN_MOM":
            return base / mult        # lower momentum bar when widening
        if name == "HUNT_MAX_SPREAD":
            return base * mult        # tolerate wider spread
        if name == "HUNT_MIN_DEPTH":
            return base / mult        # accept thinner books
        if name == "HUNT_MIN_IMBAL":
            return max(0.10, base / mult)
        if name == "HUNT_GATE_NEED":
            return max(0.10, base / mult)
        return base

    def should_enter(self, analysis):
        """Strict sniper filtration - no random entries, protect capital"""
        symbol = analysis["symbol"]
        score = analysis.get("order_flow_score", 0)
        vol_ratio = analysis.get("volume_ratio", 0)
        price_change = abs(analysis.get("momentum_5m", 0) or 0)
        imbalance = abs(analysis.get("imbalance", 0))
        spread = analysis.get("spread_pct", 100)
        current_price = analysis.get("current_price", 0)
        bid_liq = analysis.get("bid_liquidity", 0)
        ask_liq = analysis.get("ask_liquidity", 0)

        # Depth data availability flag: spread/imbalance/score default to
        # sentinel values (100 / 0 / 0) when the depth websocket hasn't run
        # for this symbol yet. Without depth we can only apply momentum-based
        # gates for watchlist population; depth gates fire once data arrives.
        has_depth = spread < 99.0 and imbalance > 0.0 and score > 0

        # STRICT ENTRY CRITERIA - protect the $9 account

        # 1. Minimum order flow score (regime-adjusted) — skipped when depth
        #    data hasn't arrived yet
        min_score = self._eff_gate("HUNT_MIN_SCORE", HUNT_MIN_SCORE)
        if has_depth and score < min_score:
            return False, f"Score too low: {score}/100 (need {min_score:.0f})"

        # 2. Volume spike must be real (regime-adjusted) — skipped when depth
        #    data hasn't arrived yet
        min_vol = self._eff_gate("HUNT_MIN_VOL", HUNT_MIN_VOL)
        if has_depth and vol_ratio < min_vol:
            return False, f"Volume not spiking: {vol_ratio:.1f}x (need {min_vol:.1f}x)"

        # 3. The prey must be moving, not drifting (regime-adjusted)
        min_mom = self._eff_gate("HUNT_MIN_MOM", HUNT_MIN_MOM)
        if price_change < min_mom:
            return False, f"5m momentum too small: {price_change:.1f}% (need {min_mom:.1f}%)"

        # 4-6. Depth gates — only enforced once depth websocket data exists.
        #      Before that, skip them so symbols can enter the watchlist.
        if has_depth:
            max_spread = self._eff_gate("HUNT_MAX_SPREAD", HUNT_MAX_SPREAD)
            if spread > max_spread:
                return False, f"Spread too wide: {spread:.2f}% (need <={max_spread:.1f}%)"

            min_depth = self._eff_gate("HUNT_MIN_DEPTH", HUNT_MIN_DEPTH)
            if bid_liq < min_depth or ask_liq < min_depth:
                return False, f"Liquidity too thin: bid=${bid_liq:.0f} ask=${ask_liq:.0f} (need ${min_depth:.0f}/side)"

            min_imbal = self._eff_gate("HUNT_MIN_IMBAL", HUNT_MIN_IMBAL)
            if imbalance < min_imbal:
                return False, f"Order book imbalanced: {imbalance:.2f} (need {min_imbal:.2f}+)"

        # 7. BULLISH ONLY — one shared long-only gate: real buy-side flow, no
        #    opposing Fib/Gann read, no downtrend. The hunter never shorts, so a
        #    "SELL" signal is structurally impossible from here on. (regime-adjusted)
        min_need = self._eff_gate("HUNT_GATE_NEED", HUNT_GATE_NEED)
        ok, why, direction = structure.bullish_gate(analysis, need=min_need)
        if not ok:
            return False, why

        # 10. Max positions check (derived from what the balance can actually size)
        if len(self.positions) >= self._max_positions():
            return False, "Max positions reached"

        # 11. Cooldown - don't re-enter the same symbol within 10 minutes
        now = time.time()
        if symbol in self.positions:
            return False, f"Already in position: {symbol}"
        if symbol in self.cooldown and now - self.cooldown[symbol] < 600:
            remaining = int(600 - (now - self.cooldown[symbol]))
            return False, f"Cooldown active: {remaining}s remaining"

        # 12. Mutual exclusion: one signal per token — signal OR prepump, never both
        if self.has_open_signal(symbol):
            return False, f"Already tracking: {symbol}"
        if self._signal_sym_type.get(symbol) == "prepump":
            return False, f"Pre-pump already claimed: {symbol}"

        # the Fib/Gann read is reported on the card, never used to pick a side
        t = analysis.get("ta") or {}
        tb = t.get("bias")

        # Register the signal through the swarm and push a SIGNAL card
        swarm.register_signal("scanner", symbol=symbol, direction=direction, score=score,
                              reason=f"vol={vol_ratio:.1f}x chg={price_change:.1f}% imb={imbalance:.2f}")
        try:
            self._card("signal:" + symbol, card_signal(
                symbol, direction, score, "order-flow", vol=vol_ratio,
                price=analysis.get("current_price"),
                tf=analysis.get("hunt_tf") or "1m",
                mom=analysis.get("momentum_5m"), imb=imbalance,
                ta_bias=tb, ta_score=t.get("score"), flags=analysis.get("feed_flags"),
                plan=analysis.get("plan")), ttl=180)
        except Exception:
            pass
        self._track(analysis, direction, score, "order-flow", kind="signal")

        ta_note = f" fib/gann={tb} {t.get('score', '')}" if t else ""
        return True, (f"ENTER {direction} score={score} vol={vol_ratio:.1f}x "
                      f"chg={price_change:.1f}% imb={imbalance:.2f}{ta_note}")

    def should_enter_catalyst(self, analysis):
        """Second entry path: hard news/social catalyst + a demonstrably safe book.

        Not a random entry. The coin must be named by a keyword-matched official
        announcement, news headline or social post AND still clear every liquidity,
        spread, depth and structure gate — it just does not need a 3x volume spike,
        because the catalyst is the reason the move has not started yet.
        """
        symbol = analysis["symbol"]
        cat = float(analysis.get("catalyst", 0) or 0)
        if cat < CATALYST_MIN:
            return False, f"No catalyst: {cat:g}"

        spread = analysis.get("spread_pct", 100)
        bid_liq = analysis.get("bid_liquidity", 0)
        ask_liq = analysis.get("ask_liquidity", 0)
        vr = float(analysis.get("volume_ratio", 0) or 0)
        max_spread = self._eff_gate("HUNT_MAX_SPREAD", HUNT_MAX_SPREAD)
        if spread > max_spread:
            return False, f"Catalyst blocked — spread {spread:.2f}%"
        min_depth = self._eff_gate("HUNT_MIN_DEPTH", CATALYST_MIN_DEPTH)
        if bid_liq < min_depth or ask_liq < min_depth:
            return False, f"Catalyst blocked — depth ${bid_liq:.0f}/${ask_liq:.0f}"
        if vr < CATALYST_MIN_VOL:
            return False, f"Catalyst blocked — volume {vr:.1f}x (need {CATALYST_MIN_VOL}x)"
        if len(self.positions) >= self._max_positions():
            return False, "Max positions reached"
        if symbol in self.positions:
            return False, f"Already in position: {symbol}"
        now = time.time()
        if symbol in self.cooldown and now - self.cooldown[symbol] < 600:
            return False, "Cooldown active"

        # Mutual exclusion: one signal per token — signal OR prepump, never both
        if self.has_open_signal(symbol):
            return False, f"Already tracking: {symbol}"
        if self._signal_sym_type.get(symbol) == "prepump":
            return False, f"Pre-pump already claimed: {symbol}"

        # long-only: a catalyst still has to be a pump we can buy — same gate
        min_need = self._eff_gate("HUNT_GATE_NEED", HUNT_GATE_NEED)
        ok, why, direction = structure.bullish_gate(analysis, need=min_need)
        if not ok:
            return False, "Catalyst blocked — " + why
        t = analysis.get("ta") or {}
        tb = t.get("bias")

        swarm.register_signal("newsdesk", symbol=symbol, direction=direction, score=int(cat * 10),
                              reason=f"catalyst {cat:g} — {analysis.get('catalyst_title', 'news')[:80]}")
        try:
            self._card("cat:" + symbol, card_signal(
                symbol, direction, int(cat * 10), "newsdesk", vol=vr,
                price=analysis.get("current_price"),
                tf=analysis.get("hunt_tf") or "1m",
                mom=analysis.get("momentum_5m"), imb=analysis.get("imbalance"),
                ta_bias=tb, ta_score=t.get("score"), flags=analysis.get("feed_flags"),
                plan=analysis.get("plan")), ttl=180)
        except Exception:
            pass
        self._track(analysis, direction, int(cat * 10), "newsdesk", kind="signal")
        return True, f"CATALYST {cat:g} {direction} — {analysis.get('catalyst_title', '')[:70]}"
    
    def should_enter_prepump(self, analysis):
        """Third entry path: buy the coil BEFORE the move, not the move itself.

        This is the only path that fires without a volume spike or a 5m momentum
        print, because by definition it runs ahead of them. It compensates by
        demanding the strongest structural evidence (a high pre-pump score with
        named reasons) plus real two-sided depth, so we are early but not blind.
        """
        pp = analysis.get("prepump") or {}
        score = int(pp.get("score", 0) or 0)
        if score < PREPUMP_ENTRY:
            return False, f"Pre-pump too low: {score}/{PREPUMP_ENTRY}"

        symbol = analysis["symbol"]
        spread = analysis.get("spread_pct", 100)
        bid_liq = analysis.get("bid_liquidity", 0)
        ask_liq = analysis.get("ask_liquidity", 0)
        vr = float(analysis.get("volume_ratio", 0) or 0)
        max_spread = self._eff_gate("HUNT_MAX_SPREAD", HUNT_MAX_SPREAD)

        if spread > max_spread:
            return False, f"Pre-pump blocked — spread {spread:.2f}%"
        min_depth = self._eff_gate("HUNT_MIN_DEPTH", PREPUMP_MIN_DEPTH)
        if bid_liq < min_depth or ask_liq < min_depth:
            return False, f"Pre-pump blocked — depth ${bid_liq:.0f}/${ask_liq:.0f} (need ${min_depth:.0f}/side)"
        if vr < CATALYST_MIN_VOL:
            return False, f"Pre-pump blocked — no volume ramp ({vr:.1f}x)"

        # long-only: a coil nobody is buying is not a bullish coil, and the
        # structure itself must read bullish — the strictest form of the gate
        ok, why, direction = structure.bullish_gate(
            analysis, need=0.50, require_bullish_struct=True)
        if not ok:
            return False, "Pre-pump blocked — " + why
        t = analysis.get("ta") or {}
        tb = t.get("bias")

        if len(self.positions) >= self._max_positions():
            return False, "Max positions reached"
        if symbol in self.positions:
            return False, f"Already in position: {symbol}"
        now = time.time()
        if symbol in self.cooldown and now - self.cooldown[symbol] < 600:
            return False, "Cooldown active"

        # Mutual exclusion: one signal per token — signal OR prepump, never both
        if self.has_open_signal(symbol):
            return False, f"Already tracking: {symbol}"
        if self._signal_sym_type.get(symbol) == "signal":
            return False, f"Signal already claimed: {symbol}"

        why = ", ".join((pp.get("reasons") or [])[:3]) or "coiled"
        swarm.register_signal("quant", symbol=symbol, direction=direction, score=score,
                              reason=f"pre-pump {score} — {why}")
        try:
            self._card("prepump:" + symbol, card_prepump(
                symbol, score, pp.get("reasons"), vol=vr,
                direction=direction,
                price=analysis.get("current_price"),
                tf=analysis.get("hunt_tf") or "1m",
                mom=analysis.get("momentum_5m"), imb=analysis.get("imbalance"),
                spread=spread, bid_liq=bid_liq, ask_liq=ask_liq,
                structure="%s %s" % ((analysis.get("struct") or {}).get("state", ""),
                                     (analysis.get("struct") or {}).get("score", "")),
                need_vol=HUNT_MIN_VOL, need_mom=HUNT_MIN_MOM,
                plan=analysis.get("plan")), ttl=180, prepump=True)
        except Exception:
            pass
        self._track(analysis, direction, score, "pre-pump", kind="signal")
        return True, f"PRE-PUMP {score} {direction} — {why[:90]}"
    
    def execute_trade(self, analysis, entry_type="order-flow", risk=None, entry_reason=None):
        """Execute a trade. risk defaults to RISK_PER_TRADE; catalyst entries risk less.
        entry_reason is an optional free-text reason stored on the position (paper/log)."""
        # ---- one entry per symbol per window ----
        # Several detectors (pre-pump, first-move, order-flow) can fire on the SAME
        # symbol inside ONE hunting heartbeat. Two calls 44 ms apart placed two real
        # BUYs in live mode and bypassed MAX_POS_FRAC, because neither call could see
        # the other's position yet. Guard on the symbol, not on self.positions.
        _g_sym = analysis.get("symbol") or ""
        _g_last = self.entry_guard.get(_g_sym)
        _g_now = time.time()
        if _g_last and _g_now - _g_last < ENTRY_GUARD_SEC:
            log_info(f"ENTRY GUARD {_g_sym}: entered {_g_now - _g_last:.1f}s ago "
                     f"via another detector — skipping duplicate [{entry_type}]")
            return None

        symbol = analysis["symbol"]
        current_price = analysis["current_price"]
        buy_ratio = analysis.get("buy_ratio", 0.5)

        # long-only: the hunter buys pumps, it never shorts
        side = "BUY"
        if buy_ratio < 0.5:
            log_warn(f"Refusing non-bullish fill: buy_ratio {buy_ratio:.2f} {symbol}")
            return None

        # the plan travels with the position so the live exits can honour it
        pl = analysis.get("plan") or signals.plan(analysis, self.balance, risk_pct=RISK_PER_TRADE)
        # REJECT plans that don't clear the minimum reward:risk (PLAN_MIN_RR)
        if not pl or not pl.get("valid"):
            log_info(f"PLAN REJECTED {symbol}: rr={ (pl or {}).get('rr', 0):.2f} < PLAN_MIN_RR {signals.PLAN_MIN_RR} — skipping [{entry_type}]")
            return None
        if current_price <= 0:
            return None

        # risk-first sizing: risk budget / stop distance, lifted to the exchange
        # floor (a 10% slice of a $9 account is $0.93 — under Binance's $5 min, so
        # without the lift the order could never be placed) and capped so one entry
        # never commits more than MAX_POS_FRAC of equity. Actual risk stays tiny
        # because the stop distance is small: $6 clip x 1% stop = $0.06 (0.6% of equity).
        stop_px = float((pl or {}).get("stop") or 0) or current_price * 0.99
        stop_dist = max(current_price - stop_px, current_price * 0.004)
        # keep BNB reserve out of sizing so fee money is never committed to an entry
        tradeable_balance = max(self.balance - BNB_RESERVE_USD, 0.0)
        risk_budget = tradeable_balance * (risk if risk is not None else RISK_PER_TRADE)
        # BNB fee discount reduces effective cost: less size needed for same risk
        usdt_amount = min(max(risk_budget * current_price / stop_dist / (1 - BNB_FEE_DISCOUNT),
                              MIN_NOTIONAL_USD),
                          tradeable_balance * MAX_POS_FRAC, self.balance)
        if usdt_amount < MIN_NOTIONAL_USD:
            need = MIN_NOTIONAL_USD / MAX_POS_FRAC
            log_warn(f"Balance too small to clear the ${MIN_NOTIONAL_USD:.2f} floor "
                     f"(have ${self.balance:.2f}; need ${need:.2f} equity at "
                     f"{MAX_POS_FRAC:.0%} max position) — no fill")
            return None
        # shape the size to THIS symbol's LOT_SIZE / NOTIONAL filters. A blind
        # 6-decimal round is rejected by Binance on XRP (step 0.1), DOT (0.01),
        # QNT (0.001) with -1111 before the order ever reaches the book.
        qty_s, qnote = self.client.normalize_qty(symbol, usdt_amount / current_price,
                                                 current_price)
        if not qty_s:
            log_warn(f"ORDER SHAPE REJECTED {symbol}: {qnote}")
            try:
                swarm.record_event("executor", "size-rejected", symbol, str(qnote))
            except Exception:
                pass
            return None
        if qnote:
            log_info(f"ORDER SIZE {symbol}: {qnote}")
        quantity = float(qty_s)
        usdt_amount = quantity * current_price
        if usdt_amount > self.balance:
            log_warn(f"ORDER SKIPPED {symbol}: shaped size ${usdt_amount:.2f} "
                     f"exceeds balance ${self.balance:.2f}")
            return None

        # ---- commit the guard here ----
        # Everything above is validation. From this line the entry is decided:
        # it will fill live, be described in shadow, or be blocked on permissions.
        # Stamping before the shadow branch is what stops the second shadow entry
        # that used to print 44 ms after the first in the same cycle.
        self.entry_guard[_g_sym or symbol] = time.time()

        # ---- shadow/paper mode: record the trade as a real-looking entry
        # ---- (HUNTER_LIVE_ORDERS=0) — forward testing, no real Binance order ----
        if not LIVE_ORDERS:
            log_info(f"PAPER ENTRY (live orders disarmed): would BUY {symbol} "
                     f"~${usdt_amount:.2f} @ {current_price} [{entry_type}]")
            try:
                swarm.record_event("executor", "paper-entry", symbol,
                                   f"paper — would BUY ${usdt_amount:.2f} [{entry_type}]")
            except Exception:
                pass
            # Record the paper entry as a real-looking trade for forward testing.
            # Mirrors the live branch: positions, state, ledger entry, Telegram card.
            pos = {
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "entry_price": current_price,
                "timestamp": time.time(),
                "order_flow_score": analysis.get("order_flow_score", 0),
                "volume_ratio": analysis.get("volume_ratio", 0),
                "order_id": None,
                "entry_type": entry_type,
                "entry_reason": entry_reason,
                "catalyst": analysis.get("catalyst", 0),
                "ta_bias": (analysis.get("ta") or {}).get("bias", ""),
                "feed_flags": analysis.get("feed_flags", []),
                "hunt_tf": analysis.get("hunt_tf") or "1m",
                "plan": pl,
                "hi": current_price,
                "status": "OPEN",
                "paper": True,
            }
            self.positions[symbol] = pos
            self.state["trades"].append(pos)
            self._save_state()
            # Notion journal: log the paper entry so it is tracked outside local JSON
            try:
                page_id = nj.log_entry(
                    symbol=symbol, side=side, entry_price=current_price, qty=quantity,
                    notional_usd=usdt_amount, entry_type=entry_type,
                    entry_reason=entry_reason, score=analysis.get("order_flow_score", 0),
                    timeframe=analysis.get("hunt_tf") or "1m", plan=pl,
                    paper=True, order_id=pos.get("order_id"), ts=time.time())
                pos["notion_page_id"] = page_id
            except Exception as e:
                log_error(f"notion_journal entry error: {e}")
            # Record entry in the follow-up ledger (same record kind as live mode)
            try:
                self._track(analysis, side, analysis.get("order_flow_score", 0),
                            entry_type, kind="entry", px=current_price)
            except Exception:
                pass
            # Send entry card (same as live mode)
            try:
                self._card("paper:" + symbol, card_signal(
                    symbol, side, analysis.get("order_flow_score", 0), entry_type,
                    vol=analysis.get("volume_ratio", 0),
                    price=current_price,
                    tf=analysis.get("hunt_tf") or "1m",
                    mom=analysis.get("momentum_5m"),
                    imb=analysis.get("imbalance"),
                    ta_bias=(analysis.get("ta") or {}).get("bias", ""),
                    ta_score=(analysis.get("ta") or {}).get("score"),
                    flags=analysis.get("feed_flags"),
                    plan=pl), ttl=180)
            except Exception:
                pass
            return None

        # ---- live permission gate: the key must actually carry Spot trading ----
        # Without it Binance answers 401/-2015 on every signal. Probe once (cached),
        # refuse cleanly, and say exactly what is missing — once an hour, not once a cycle.
        perm = self.client.spot_trading_allowed()
        if perm.get("allowed") is not True:
            why = ("Binance key has no Spot & Margin trading permission"
                   if perm.get("allowed") is False
                   else f"trading permission unknown ({perm.get('raw')})")
            self.trade_perm_reason = why
            log_warn(f"LIVE ORDER BLOCKED {symbol}: {why} — "
                     f"would BUY ${usdt_amount:.2f} @ {current_price} [{entry_type}]")
            try:
                swarm.record_event("executor", "blocked-no-permission", symbol,
                                   f"{why}; would BUY ${usdt_amount:.2f} [{entry_type}]")
            except Exception:
                pass
            try:
                self._card("noperm",
                           (f"🔒 *LIVE ORDER BLOCKED*\n{why}\n"
                            f"Wanted to buy *{symbol}* ~${usdt_amount:.2f} "
                            f"({entry_type}).\nBinance needs the key switched to "
                            f"*Enable Spot & Margin Trading* (email code + Google "
                            f"Authenticator). The hunter stays armed and will fill "
                            f"automatically the moment it is on."), ttl=3600)
            except Exception:
                pass
            return None

        result = self.client.place_order(symbol, side, quantity, price=current_price)
        if result:
            pos = {
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "entry_price": current_price,
                "timestamp": time.time(),
                "order_flow_score": analysis.get("order_flow_score", 0),
                "volume_ratio": analysis.get("volume_ratio", 0),
                "order_id": result.get("orderId"),
                "entry_type": entry_type,
                "entry_reason": entry_reason,
                "catalyst": analysis.get("catalyst", 0),
                "ta_bias": (analysis.get("ta") or {}).get("bias", ""),
                "feed_flags": analysis.get("feed_flags", []),
                "hunt_tf": analysis.get("hunt_tf") or "1m",
                "plan": pl,
                "hi": current_price,
                "status": "OPEN"
            }
            self.positions[symbol] = pos
            self.state["trades"].append(pos)
            self._save_state()
            # Notion journal: log the live entry so it is tracked outside local JSON
            try:
                page_id = nj.log_entry(
                    symbol=symbol, side=side, entry_price=current_price, qty=quantity,
                    notional_usd=usdt_amount, entry_type=entry_type,
                    entry_reason=entry_reason, score=analysis.get("order_flow_score", 0),
                    timeframe=analysis.get("hunt_tf") or "1m", plan=pl,
                    paper=False, order_id=result.get("orderId"), ts=time.time())
                pos["notion_page_id"] = page_id
            except Exception as e:
                log_error(f"notion_journal entry error: {e}")
            log_info(f"HUNTER ENTERED [{entry_type}]: {side} {symbol} @ {current_price} "
                     f"qty={quantity} score={analysis.get('order_flow_score', 0)}")
            # Record entry through swarm
            swarm.record_entry(symbol, side, current_price, quantity, "executor", usdt_amount)
            # ...and open a follow-up row for the real trade, not just the signal
            self._track(analysis, side, analysis.get("order_flow_score", 0), entry_type, kind="entry",
                        px=current_price)
            try:
                self._card("entry:" + symbol,
                           card_entry(pos, analysis, entry_type=entry_type))
            except Exception:
                pass
            return pos
        return None

    # ---------------- closed-trade ledger (daily / weekly cards) ----------------
    def _load_results(self):
        try:
            with open(RESULTS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return []

    def record_result(self, pos):
        """Append one closed trade to the ledger that feeds the daily/weekly cards."""
        try:
            rows = self._load_results()
            rows.append({
                "ts": int(pos.get("exit_ts", time.time())),
                "symbol": pos.get("symbol"),
                "side": pos.get("side"),
                "entry": pos.get("entry_price"),
                "exit": pos.get("exit_price"),
                "qty": pos.get("quantity"),
                "pnl": pos.get("pnl", 0),
                "pnl_pct": pos.get("pnl_pct", 0),
                "reason": pos.get("exit_reason", ""),
                "entry_type": pos.get("entry_type", "order-flow"),
                "entry_reason": pos.get("entry_reason", ""),
                "score": pos.get("order_flow_score"),
            })
            with open(RESULTS_FILE, "w") as f:
                json.dump(rows[-2000:], f, indent=1)
            # Notion journal: close the page for this trade
            page_id = pos.get("notion_page_id")
            if page_id:
                try:
                    nj.log_exit(
                        page_id=page_id, symbol=pos.get("symbol"),
                        exit_price=pos.get("exit_price"), pnl_pct=pos.get("pnl_pct", 0),
                        pnl_usd=pos.get("pnl", 0), reason=pos.get("exit_reason", ""),
                        entry_price=pos.get("entry_price"), ts=pos.get("exit_ts"))
                except Exception as e:
                    log_error(f"notion_journal exit error: {e}")
        except Exception as e:
            log_error(f"record_result error: {e}")

    @staticmethod
    def _window_rows(rows, since):
        return [r for r in rows if float(r.get("ts", 0)) >= since]

    def results_summary(self, period="daily"):
        """Aggregate the ledger over a day or a week. Never fabricates a number."""
        rows = self._load_results()
        now = time.time()
        if period == "weekly":
            since = now - 7 * 86400
        else:
            # midnight in the hunter's timezone, not the OS clock's
            since = now_local().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        w = self._window_rows(rows, since)
        pnls = [float(r.get("pnl", 0) or 0) for r in w]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        net = sum(pnls)
        start = self.balance - net if period == "weekly" else self.balance
        prog = None
        try:
            prog = "%.1f%% to target" % max(0.0, min(100.0, self.balance / TARGET_BALANCE * 100))
        except Exception:
            prog = "—"
        return {
            "period": period,
            "window": ("since %s" % now_local().strftime("%Y-%m-%d 00:00 %Z")) if period == "daily"
                      else "last 7 days",
            "trades": len(w),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": (len(wins) / len(w) * 100) if w else 0.0,
            "pnl": net,
            "best": max(pnls) if pnls else 0,
            "worst": min(pnls) if pnls else 0,
            "balance": self.balance,
            "progress": prog,
            "positions": "%d / %d" % (len(self.positions), MAX_POSITIONS),
            "mode": "LIVE" if self.running else "IDLE",
        }

    def _digest_due(self):
        """Push the daily card once per day and the weekly card once per week."""
        try:
            with open(DIGEST_FILE, "r") as f:
                d = json.load(f)
        except Exception:
            d = {}
        n = now_local()
        day = n.strftime("%Y-%m-%d")
        week = "%s-W%s" % (n.strftime("%Y"), n.strftime("%W"))
        due = []
        if d.get("day") != day:
            d["day"] = day
            due.append("daily")
        # weekly fires on Monday, the first cycle of the new ISO week
        if d.get("week") != week and n.weekday() == 0:
            d["week"] = week
            due.append("weekly")
        elif d.get("week") != week and n.weekday() > 0 and self.trades_today > 0:
            d.setdefault("week", week)
        try:
            with open(DIGEST_FILE, "w") as f:
                json.dump(d, f, indent=1)
        except Exception:
            pass
        return due

    def _card(self, kind, text, ttl=0, silent=False, prepump=False):
        """Throttled Telegram push. Fail-closed: never breaks a hunting cycle.

        prepump=True fans the card out to the pre-pump-only audience as well.
        Signals and prepumps are mutually exclusive per symbol: once a symbol
        gets a signal card, it can never get a prepump card (and vice versa).
        This keeps the two strategies separate — prepump has its own gates and
        settings and never bleeds into the signal path.
        """
        try:
            if not self.notify.enabled:
                log_warn(f"CARD {kind} skipped: telegram not enabled")
                return False
            now = time.time()
            # extract symbol from kind like "signal:BTCUSDT" / "cat:BTCUSDT" / "prepump:BTCUSDT"
            sym = kind.split(":", 1)[1] if ":" in kind else kind
            is_signal = kind.startswith(("signal:", "cat:"))
            is_prepump = kind.startswith("prepump:")

            # --- cross-type mutual exclusion: signal vs prepump ---
            if is_signal or is_prepump:
                existing = self._signal_sym_type.get(sym)
                if existing is not None and existing != ("prepump" if is_prepump else "signal"):
                    # this symbol already took the other path — block mixing
                    return False
                self._signal_sym_type[sym] = "prepump" if is_prepump else "signal"

            if ttl and now - self._card_ts.get(kind, 0) < ttl:
                return False
            self._card_ts[kind] = now
            if prepump:
                ok = self.notify.send_prepump(text)
            else:
                ok = self.notify.send(text, silent=silent)
            if not ok:
                log_warn(f"CARD {kind} not delivered: {self.notify.last_error or 'unknown'}")
            return ok
        except Exception as e:
            log_error(f"CARD {kind} raised {type(e).__name__}: {e}")
            return False

    def _autodiscover_chat(self, ttl=180):
        """If no chat id is configured, ask Telegram for one (user must message the bot once)."""
        if self.notify.enabled:
            return
        now = time.time()
        if now - self._card_ts.get("_discover", 0) < ttl:
            return
        self._card_ts["_discover"] = now
        try:
            if self.notify.discover_chat():
                log_info(f"TELEGRAM chat discovered: {self.notify.chat}")
                self._card("boot", card_boot(PORT, self.balance, TARGET_BALANCE, "telegram linked"))
        except Exception:
            pass
    
    def check_alerts(self):
        """Fire every armed alert whose price crossed or whose clock arrived.

        One batched price call covers every armed price alert, so N alerts cost one
        request. A TIME-only alert needs no market data. Nothing is ever sent unless
        the alert actually triggered — and a missing price leaves it armed.
        """
        armed = self.alerts.armed()
        if not armed:
            return 0
        syms = [a["symbol"] for a in armed if a.get("price")]
        prices = self.client.get_prices(syms) if syms else {}
        fired = self.alerts.check(lambda s: prices.get(s))
        for a in fired:
            self.alerts_fired += 1
            try:
                self.notify.send(card_alert_fired(a, a.get("fired_price")))
            except Exception as e:
                log_error(f"alert card error: {e}")
            try:
                swarm.record_event("coordinator", "alert-fired", a.get("symbol", ""),
                                   f'{a.get("type")} {a.get("price") or ""} · {a.get("fired_reason")}')
            except Exception:
                pass
            log_info(f"ALERT FIRED: {a.get('symbol')} {a.get('type')} "
                     f"target={a.get('price')} px={a.get('fired_price')} why={a.get('fired_reason')}")
        return len(fired)

    def check_exits(self):
        """Check exit conditions for open positions"""
        to_close = []
        for symbol, pos in list(self.positions.items()):
            ticker = self.client.get_ticker_24hr(symbol)
            if not ticker:
                continue
            current_price = float(ticker.get("lastPrice", 0))
            entry = pos["entry_price"]
            
            if pos["side"] == "BUY":
                pnl_pct = (current_price - entry) / entry * 100
            else:
                pnl_pct = (entry - current_price) / entry * 100
            
            # exits follow the plan the signal was hunted with, inside the engine's
            # ±15% / -5% envelope; a position that ran lets the trailing stop work
            pl = pos.get("plan") or {}
            tp_pct, sl_pct = 15.0, 5.0
            try:
                # "eat and leave": the FIRST target is the take — a small account
                # wants turnover, not a moonshot. Floored at +1% so a win always
                # clears the ~0.2% round-trip fee.
                if pl.get("tp1"):
                    tp_pct = min(max((float(pl["tp1"]) - entry) / entry * 100.0, SCALP_TP_FLOOR), 15.0)
                if pl.get("stop"):
                    sl_pct = min(max((entry - float(pl["stop"])) / entry * 100.0, 0.4), 5.0)
            except Exception:
                tp_pct, sl_pct = 15.0, 5.0

            hi = max(float(pos.get("hi") or entry), current_price)
            pos["hi"] = hi
            arm = float(pl.get("trail_arm") or 0)
            dist = float(pl.get("trail_dist") or 0)
            held_min = (time.time() - pos.get("timestamp", time.time())) / 60.0

            if arm > 0 and dist > 0 and hi >= arm and current_price <= hi - dist:
                to_close.append((symbol, "TRAIL %.2f" % (hi - dist)))
            elif pnl_pct >= tp_pct:
                to_close.append((symbol, "TP +%.2f%%" % tp_pct))
            elif pnl_pct <= -sl_pct:
                to_close.append((symbol, "SL -%.2f%%" % sl_pct))
            elif held_min >= HOLD_MAX_MIN:
                # time stop: dead capital is an opportunity cost — leave the table
                to_close.append((symbol, "TIME %dm" % int(held_min)))
        
        for symbol, reason in to_close:
            pos = self.positions.get(symbol)
            if not pos:
                continue
            ticker = self.client.get_ticker_24hr(symbol)
            mark = float(ticker.get("lastPrice", 0)) if ticker else pos["entry_price"]

            # ---- a live exit must actually SELL. Marking a position CLOSED while
            # the coins are still sitting in the account is how a ledger starts
            # lying about money (and how a "closed" bag is never really closed).
            if LIVE_ORDERS:
                sold = self.client.sell_position(symbol, pos.get("quantity"), mark)
                if not sold.get("ok"):
                    log_error(f"EXIT NOT FILLED {symbol}: {sold.get('reason')} "
                              f"— position stays open, retrying next cycle")
                    try:
                        swarm.record_event("executor", "exit-rejected", symbol,
                                           str(sold.get("reason"))[:120])
                    except Exception:
                        pass
                    continue
                exit_qty = sold.get("qty") or pos.get("quantity", 0)
                exit_price = float(sold.get("avg") or mark)
                pos["exit_dust"] = bool(sold.get("dust"))
                pos["exit_qty"] = exit_qty
            else:
                exit_qty = pos.get("quantity", 0)
                exit_price = mark
            self.positions.pop(symbol, None)

            if pos["side"] == "BUY":
                pnl = (exit_price - pos["entry_price"]) * exit_qty
            else:
                pnl = (pos["entry_price"] - exit_price) * exit_qty

            pos["exit_price"] = exit_price
            pos["pnl"] = round(pnl, 4)
            pos["pnl_pct"] = round(((exit_price - pos["entry_price"]) / pos["entry_price"] * 100)
                                   if pos["side"] == "BUY" else
                                   ((pos["entry_price"] - exit_price) / pos["entry_price"] * 100), 3)
            pos["exit_reason"] = reason
            pos["exit_ts"] = time.time()
            pos["held"] = "%dm" % max(1, int((time.time() - pos.get("timestamp", time.time())) / 60))
            pos["status"] = "CLOSED"
            self.pnl_today += pnl
            self.trades_today += 1
            self.balance += pnl
            # the ledger is bookkeeping; the exchange balance is the truth
            if LIVE_ORDERS:
                real = self.client.free_balance("USDT")
                if real is not None:
                    self.balance = real
            # circuit breaker bookkeeping: a loss in a row arms the pause
            if pnl < 0:
                self.loss_streak += 1
                if self.loss_streak >= MAX_CONSEC_LOSSES:
                    self.pause_until = time.time() + LOSS_PAUSE_SEC
                    log_warn(f"RISK: {self.loss_streak} losses in a row — "
                             f"pausing new entries {LOSS_PAUSE_SEC // 60}m")
            elif pnl > 0:
                self.loss_streak = 0
            self.state["pnl"] = self.state.get("pnl", 0) + pnl
            self._save_state()
            # Record exit through swarm + set per-symbol cooldown
            try:
                swarm.record_exit(symbol, exit_price, reason)
            except Exception:
                pass
            self.record_result(pos)
            try:
                self._card("exit:" + symbol,
                           card_exit(pos, pnl, pos["pnl_pct"], reason))
            except Exception:
                pass
            self.cooldown[symbol] = time.time()
            log_info(f"HUNTER EXITED: {symbol} {reason} P&L=${pnl:.4f} Balance=${self.balance:.2f}")
    
    def run_cycle(self, skip_scan=False):
        """One hunting cycle"""
        # The coordinator owns this loop and nothing else, so it is the only agent
        # that beats here. Every other agent's liveness is earned by filing work in
        # the record_* paths below (SwarmCoordinator._bump), never blanket-stamped.
        try:
            swarm.heartbeat("coordinator", bump=True)
        except Exception:
            pass
        # Expire stale cooldowns (older than 600s)
        now = time.time()
        self.cooldown = {s: t for s, t in self.cooldown.items() if now - t < 600}
        self.entry_guard = {s: t for s, t in self.entry_guard.items()
                            if now - t < max(ENTRY_GUARD_SEC, 600)}
        # _signal_sym_type is permanent (signal vs prepump mutual exclusion)

        self._autodiscover_chat()

        if self.balance >= TARGET_BALANCE:
            log_info(f"TARGET REACHED: ${self.balance:.2f} >= ${TARGET_BALANCE}")
            self._card("target", card_result("MISSION", self.results_summary("daily")), silent=False)
            self.running = False
            return

        # The paper ledger is the truth in shadow mode. Only a LIVE engine may read
        # the exchange here: overwriting the sim balance with a real $0 would
        # instantly trip the daily loss cap and lock the hunter out of its own sim.
        if LIVE_ORDERS:
            self.balance = self.get_balance()
        if not self._boot_carded:
            self._boot_carded = True
            try:
                self._card("boot", card_boot(PORT, self.balance, TARGET_BALANCE,
                                             "feeds + fib/gann armed"))
            except Exception:
                pass

        # ---- refresh the leading data (throttled, off-thread, never blocks) ----
        if not skip_scan:
            self._refresh_leads(now)

        results = self.scan_market()
        try:
            self._agent_duty(results, now)
        except Exception:
            pass

        # ---- risk management: every NEW entry must clear the envelope ----
        entered = False
        risk_ok, risk_why = self._risk_ok()
        if not risk_ok:
            try:
                self._catch("risk_halt", "risk_guard", "stand-down", "-", risk_why, 30)
            except Exception:
                pass

        # ---- Agent pipeline: scanner → analyst → newsdesk → quant → whale → risk_guard → executor ----
        # Each agent processes the scan results and registers findings through the swarm blackboard,
        # so agents genuinely interact instead of just heartbeating independently.
        entered = False

        # ── 1. SCANNER: deep-scan results are the input every other agent reads ──
        scanner_ranked = sorted(results, key=lambda r: r.get("order_flow_score", 0) or 0, reverse=True)
        for analysis in scanner_ranked[:10]:
            sym = analysis.get("symbol", "?")
            score = int(analysis.get("order_flow_score", 0) or 0)
            try:
                swarm.register_signal("scanner", symbol=sym, direction="BUY", score=score,
                                      reason=f"scan score={score} vol={analysis.get('volume_ratio',0):.1f}x mom={analysis.get('momentum_5m',0):.1f}%")
            except Exception:
                pass

        # ── 2. ANALYST: Fib/Gann structure on each candidate ──
        for analysis in scanner_ranked[:10]:
            sym = analysis.get("symbol", "?")
            st = analysis.get("struct") or {}
            ta = analysis.get("ta") or {}
            bias = ta.get("bias", "NEUTRAL")
            tscore = int(ta.get("score", 0) or 0)
            sstate = st.get("state", "?")
            sscore = int(st.get("score", 0) or 0)
            try:
                swarm.register_signal("analyst", symbol=sym, direction="BUY", score=tscore,
                                      reason=f"fib/gann={bias} {tscore} struct={sstate} {sscore}")
            except Exception:
                pass

        # ── 3. NEWSDESK: catalyst / news check ──
        for analysis in scanner_ranked[:10]:
            sym = analysis.get("symbol", "?")
            cat = float(analysis.get("catalyst", 0) or 0)
            if cat < CATALYST_MIN:
                continue
            try:
                swarm.register_signal("newsdesk", symbol=sym, direction="BUY", score=int(cat * 10),
                                      reason=f"catalyst {cat:.0f} — {analysis.get('catalyst_title', 'news')[:60]}")
            except Exception:
                pass

        # ── 4. QUANT: pre-pump coil detection ──
        for analysis in scanner_ranked[:10]:
            sym = analysis.get("symbol", "?")
            pp = analysis.get("prepump") or {}
            pscore = int(pp.get("score", 0) or 0)
            if pscore < PREPUMP_ENTRY:
                continue
            try:
                swarm.register_signal("quant", symbol=sym, direction="BUY", score=pscore,
                                      reason=f"pre-pump {pscore} — {', '.join((pp.get('reasons') or [])[:3])}")
            except Exception:
                pass

        # ── 5. WHALE: order-flow / imbalance / liquidity check ──
        for analysis in scanner_ranked[:10]:
            sym = analysis.get("symbol", "?")
            imb = float(analysis.get("imbalance", 0) or 0)
            spread = float(analysis.get("spread_pct", 0) or 0)
            bid_liq = float(analysis.get("bid_liquidity", 0) or 0)
            ask_liq = float(analysis.get("ask_liquidity", 0) or 0)
            try:
                swarm.register_signal("whale", symbol=sym, direction="BUY", score=int(abs(imb) * 100),
                                      reason=f"imbalance={imb:.2f} spread={spread:.3f}% depth=${min(bid_liq,ask_liq):.0f}")
            except Exception:
                pass

        # ── 6. RISK_GUARD: approve or reject each candidate across ALL entry paths ──
        approved = []
        for analysis in scanner_ranked[:10]:
            sym = analysis.get("symbol", "?")
            should, reason, entry_type = False, "", "order-flow"
            # Path 1: order-flow (volume spike + momentum)
            should, reason = self.should_enter(analysis)
            entry_type = "order-flow"
            if not should:
                # Path 2: pre-pump (buy the coil before the move — no volume spike needed)
                should, reason = self.should_enter_prepump(analysis)
                entry_type = "pre-pump"
            if not should:
                # Path 3: catalyst (news/social catalyst + safe book)
                should, reason = self.should_enter_catalyst(analysis)
                entry_type = "catalyst"
            if not should:
                # Path 4: first-move radar (money arriving before price moves)
                should, reason = self.should_enter_firstmove(analysis)
                entry_type = "first-move"
            if should:
                analysis["_entry_type"] = entry_type
                approved.append(analysis)
                try:
                    swarm.record_event("risk_guard", "approve", sym,
                                       f"PASS [{entry_type}] — {reason}")
                except Exception:
                    pass
            else:
                try:
                    swarm.record_rejection("risk_guard", sym, reason)
                except Exception:
                    pass

        # ── 7. EXECUTOR: execute all approved candidates this cycle ──
        # Up to one entry per symbol per cycle; respects MAX_POSITIONS and the
        # entry guard so a symbol can't be double-filled by two paths.
        if risk_ok and approved:
            open_count = len(self.positions)
            for best in approved:
                if open_count >= self._max_positions():
                    break
                entry_type = best.get("_entry_type", "order-flow")
                pos = self.execute_trade(best, entry_type=entry_type)
                if pos:
                    entered = True
                    open_count += 1
                    self._track(best, "BUY", best.get("order_flow_score", 0), entry_type, kind="signal")
                    try:
                        swarm.record_entry(sym=best.get("symbol", "?"), side="BUY",
                                           price=float(best.get("current_price", 0) or 0),
                                           quantity=float((best.get("plan") or {}).get("qty") or 0),
                                           agent_name="executor", risk_usd=float((best.get("plan") or {}).get("notional") or 0))
                    except Exception:
                        pass
                    try:
                        swarm.record_event("executor", "entry-executed", best.get("symbol", "?"),
                                           f"ENTRY {best.get('symbol', '?')} score={best.get('order_flow_score',0)} [{entry_type}]")
                    except Exception:
                        pass

        try:
            swarm.heartbeat("analyst", bump=True)
        except Exception:
            pass
        try:
            self._record_catches()
            swarm.heartbeat("whale", bump=True)
        except Exception:
            pass
        # daily / weekly result cards
        try:
            for period in self._digest_due():
                s = self.results_summary(period)
                s["balance"] = self.balance
                self._card("digest:" + period, card_result(period, s), silent=(period == "daily"))
        except Exception:
            pass
        self.check_exits()
        self.mark_signals()

        # ---- heartbeat every agent every cycle so none go offline ----
        # Agents that only heartbeat when they have work (executor, newsdesk,
        # scanner) go offline during quiet periods. Heartbeat them all here so
        # the swarm dashboard stays green.
        for _agent in ("coordinator", "scanner", "analyst", "newsdesk", "quant",
                       "whale", "risk_guard", "executor", "portfolio", "dashboard"):
            try:
                swarm.heartbeat(_agent, bump=False)
            except Exception:
                pass

    def mark_signals(self, force=False):
        """Mark every OPEN signal against real klines so the follow-up is measured.

        Throttled: one pass per ~30s, at most 12 symbols, one REST call each.
        """
        now = time.time()
        if not force and now - self._mark_ts < 30:
            return 0
        self._mark_ts = now
        try:
            syms = {r.get("symbol") for r in self.ledger.rows if r.get("status") == "OPEN"}
        except Exception:
            return 0
        n = 0
        for s in [x for x in syms if x][:12]:
            try:
                kl = self.client.get_klines(s, interval="1m", limit=200)
            except Exception:
                kl = None
            if kl:
                n += self.ledger.mark(s, kl, tf_min=1)
        if n:
            self.ledger.expire()
        return n

    def _catch(self, kind, agent, action, symbol, reason, ttl):
        """Emit a throttled agent 'catch' to the swarm blackboard."""
        now = time.time()
        if now - self._catch_ts.get(kind, 0) < ttl:
            return
        self._catch_ts[kind] = now
        try:
            swarm.record_event(agent, action, symbol, reason)
        except Exception:
            pass
        try:
            self.feeds.record_catch(agent, kind, reason, symbol)
        except Exception:
            pass

    def _agent_duty(self, results, now):
        """Per-cycle duties for the agents whose work is not inside the feed/scan loops.

        Each _catch() files a swarm record_event, and record_event now counts that as
        a task and refreshes liveness — so these agents earn their 'online' badge by
        doing this work, instead of being blanket-stamped every cycle.
        """
        open_n = len(self.positions)
        # Portfolio Manager: equity + exposure snapshot
        self._catch("duty_portfolio", "portfolio", "exposure", "",
                    f"{open_n}/{MAX_POSITIONS} open | equity ${self.balance:.2f} | "
                    f"risk {RISK_PER_TRADE * 100:.0f}%/trade", 60)
        # Risk Manager: state the live risk envelope and flag any limit breach
        breach = "MAX POSITIONS REACHED" if open_n >= MAX_POSITIONS else "within limits"
        self._catch("duty_risk", "risk_guard", "risk-envelope", "",
                    f"exposure {open_n}/{MAX_POSITIONS} {breach} | stop clamp -0.4..-5%", 60)
        # Dashboard Monitor: confirm the snapshot the UI renders is complete
        self._catch("duty_dash", "dashboard", "render", "",
                    f"snapshot {len(results)} scanned | {self.swept_count} swept | "
                    f"{self.dead_excluded} dead | {self.pegged_excluded} pegged | "
                    f"{self.tokenised_excluded} tokenised", 60)
        # Quant: state the strongest Fib/Gann structure read on the book this cycle
        best_ta, best_sym = 0, ""
        for r in (self.watchlist or [])[:12]:
            try:
                sc = int(((r.get("ta") or {}).get("score", 0)) or 0)
            except Exception:
                sc = 0
            if sc > best_ta:
                best_ta, best_sym = sc, r.get("symbol", "")
        self._catch("duty_quant", "quant", "structure", best_sym,
                    f"top Fib/Gann {best_ta}/100" + (f" on {best_sym}" if best_sym else " (no structure yet)"), 60)

    def _record_catches(self):
        """Let the agents surface whatever the external sources just caught."""
        f = self.feeds
        whales = getattr(f, "whales", []) or []
        if whales:
            w = whales[0]
            if w["notional"] >= NOTABLE_USD:
                self._catch("whale", "whale", "whale", w["symbol"],
                            f'{w["side"]} block ${w["notional"]:,.0f} @ {w["price"]}', 40)
        walls = getattr(f, "walls", []) or []
        if walls:
            wl = walls[0]
            if wl["notional"] >= NOTABLE_USD:
                self._catch("wall", "whale", "wall", wl["symbol"],
                            f'{wl["side"]} wall ${wl["notional"]:,.0f} @ {wl["price"]}', 60)
        surge = getattr(f, "volume_surge", []) or []
        if surge and float(surge[0].get("volume_ratio", 0) or 0) >= SURGE_NOTABLE:
            s = surge[0]
            self._catch("surge", "scanner", "surge", s["symbol"],
                        f'volume {s["volume_ratio"]:.1f}x baseline', 45)
        news = getattr(f, "news", []) or []
        if news:
            self._catch("news", "analyst", "news", "", news[0]["title"][:140], 240)
        v = (getattr(f, "fng", {}) or {}).get("value")
        if v and (v >= 80 or v <= 20):
            self._catch("fng", "risk_guard", "sentiment", "",
                        f'Fear & Greed {v} — {(f.fng or {}).get("label", "")}', 900)
        fut = getattr(f, "futures", {}) or {}
        for sym, rec in list(fut.items())[:3]:
            if abs(rec.get("oi_chg_pct", 0) or 0) >= 2.0:
                self._catch("oi_" + sym, "analyst", "derivatives", sym,
                            f'open interest {rec["oi_chg_pct"]:+.2f}% (5m)', 300)
        # news / social keyword engine
        cats = getattr(f, "catalysts", []) or []
        if cats:
            c = cats[0]
            if abs(c.get("strength", 0)) >= 4:
                self._catch("cat_" + c["symbol"], "newsdesk", "catalyst", c["symbol"],
                            f'{c["dir"]} {c["strength"]:g} · {c["source"]} · {c["title"][:90]}', 240)
                try:
                    swarm.heartbeat("newsdesk", bump=True)
                except Exception:
                    pass
        # Fib / Gann structure confluence
        for r in (self.watchlist or [])[:6]:
            t = r.get("ta") or {}
            if t and int(t.get("score", 50)) >= 78:
                self._catch("ta_" + r["symbol"], "quant", "structure", r["symbol"],
                            f'Fib/Gann {t.get("bias")} {t.get("score")}/100 · fib pos {t.get("position")}', 300)
                try:
                    swarm.heartbeat("quant", bump=True)
                except Exception:
                    pass
                break

    def start(self):
        """Start the hunter"""
        self.running = True
        log_info("BINANCE HUNTER STARTED - $9 → $20 mission")
        while self.running and not os.path.exists(STOP_FILE):
            try:
                self.run_cycle()
            except Exception as e:
                log_error(f"Cycle error: {e}")
            time.sleep(10)  # 10s cycle
        log_info("BINANCE HUNTER STOPPED")
        try:
            if os.path.exists(os.path.join(BOT, "hunter.pid")):
                os.remove(os.path.join(BOT, "hunter.pid"))
        except Exception:
            pass

# Flask Dashboard
app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config["TEMPLATES_AUTO_RELOAD"] = True
hunter = Hunter()

# ---- dashboard hot path: TTL read-through cache + gzip ------------------------
# The page polls ~11 endpoints every ~4 s and three of them are pure Binance
# round-trips (klines / depth / aggTrades) refetched on every single poll — that
# is where the 300-765 ms went, not the Flask body building. Those feeds are
# already seconds-granular on the exchange side, so a short TTL costs no accuracy
# and removes the wait. Nothing here touches the hunter loop or entry decisions:
# only the HTTP layer reads through this cache.
_TTL_CACHE = {}
_TTL_LOCK = threading.Lock()

# TA / structure cost grows with the candle window, so the TTL does too.
_TF_TTL = {"1m": 8, "3m": 12, "5m": 20, "15m": 45, "30m": 60,
           "1h": 90, "2h": 120, "4h": 240, "6h": 300, "12h": 480,
           "1d": 600, "3d": 900, "1w": 1200}
_TA_INTERVALS = ("1m", "5m", "15m", "1h", "4h", "1d")


def _ttl(key, ttl, fn):
    """Return a cached value for `key`, else compute it and cache it for `ttl` s."""
    now = time.time()
    with _TTL_LOCK:
        hit = _TTL_CACHE.get(key)
        if hit and hit[0] > now:
            return hit[1]
    val = fn()
    if val is not None:
        with _TTL_LOCK:
            _TTL_CACHE[key] = (now + ttl, val)
            if len(_TTL_CACHE) > 4000:      # hard bound, drop the expired first
                for k in [k for k, (era, _) in _TTL_CACHE.items() if era <= now]:
                    _TTL_CACHE.pop(k, None)
    return val


@app.after_request
def _gzip_body(resp):
    """gzip JSON/HTML: /api/status is ~150 KB and / is ~121 KB of raw text."""
    try:
        if (resp.status_code != 200
                or resp.direct_passthrough
                or "gzip" not in (request.headers.get("Accept-Encoding") or "")
                or resp.mimetype not in ("application/json", "text/html")):
            return resp
        body = resp.get_data()
        if len(body) < 1500 or body[:2] == b"\x1f\x8b":
            return resp
        packed = gzip.compress(body, 6, mtime=0)
        if len(packed) >= len(body) * 0.9:
            return resp
        resp.set_data(packed)
        resp.headers["Content-Encoding"] = "gzip"
        resp.headers["Content-Length"] = str(len(packed))
        resp.headers["Vary"] = "Accept-Encoding"
    except Exception as e:
        log_error(f"gzip error: {e}")
    return resp

@app.route('/')
def index():
    global hunter
    return render_template("dashboard.html")

@app.route('/api/swarm')
def api_swarm():
    """Live swarm agent status from the coordinator blackboard."""
    try:
        return jsonify(swarm.get_status())
    except Exception as e:
        return jsonify({"agents": {}, "metrics": {}, "error": str(e)})

@app.route('/api/decisions')
def api_decisions():
    """Recent swarm decision blackboard entries."""
    import os as _os
    path = _os.path.join(os.path.dirname(BOT), "swarm", "decisions.jsonl")
    out = []
    if _os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            for line in f.readlines()[-40:]:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except Exception:
                        pass
    return jsonify({"decisions": out[-40:]})

@app.route('/api/feeds')
def api_feeds():
    """External crypto source feeds: news, trending, sentiment, derivatives, whales, walls, volume."""
    try:
        return jsonify(hunter.feeds.snapshot())
    except Exception as e:
        return jsonify({"news": [], "trending": [], "fng": {}, "futures": {},
                        "whales": [], "walls": [], "volume_surge": [], "catches": [],
                        "sources": [], "error": str(e)})

@app.route('/toggle', methods=['POST'])
def toggle():
    hunter.running = not hunter.running
    return jsonify({"running": hunter.running})

@app.route('/enter', methods=['POST'])
def enter():
    data = request.get_json() or {}
    symbol = data.get("symbol")
    reason = data.get("reason") or ""
    for w in hunter.watchlist:
        if w["symbol"] == symbol:
            should, why = hunter.should_enter(w)
            if should:
                pos = hunter.execute_trade(w, entry_type="manual", entry_reason=reason)
                if not pos:
                    return jsonify({"error": "order rejected by Binance"})
                return jsonify({"message": f"Entered {symbol} {pos['side']} @ {pos['entry_price']}",
                                "reason": reason})
            else:
                return jsonify({"error": why})
    return jsonify({"error": "Symbol not found in watchlist"})

@app.route('/api/status')
def api_status():
    light = request.args.get("light") == "1"
    payload = _ttl(("status", light), 1.5, lambda: _status_payload(light))
    return jsonify(payload)


def _status_payload(light):
    return {
        "balance": round(hunter.balance, 2),
        "target": TARGET_BALANCE,
        "pnl_today": round(hunter.pnl_today, 4),
        "positions": len(hunter.positions),
        "positions_detail": list(hunter.positions.values()),
        "trades_today": hunter.trades_today,
        "running": hunter.running,
        "live_orders": LIVE_ORDERS,
        "swept": hunter.swept_count,
        "candidates": hunter.candidates_count,
        "pegged_excluded": hunter.pegged_excluded,
        "dead_excluded": hunter.dead_excluded,
        "tokenised_excluded": getattr(hunter, "tokenised_excluded", 0),
        "trading_symbols": len(hunter.trading_set),
        "catalyst_entries": hunter.catalyst_entries,
        "prepump_entries": hunter.prepump_entries,
        "firstmove_entries": hunter.firstmove_entries,
        "risk": hunter.risk_snapshot(),
        "radar": hunter.radar.snapshot(),
        "regime": hunter.regime.snapshot(),
        "watchlist": hunter.watchlist[:SHORTLIST],
        "market": hunter.market_rank[:MARKET_SHOW],
        "signals": {k: v for k, v in hunter.ledger.summary().items()
                    if k not in ("open_rows", "recent")},
        "plans": hunter.ledger.open_plans()[:12],
        "backtest": hunter.ledger.backtest_summary(),
        "altfins": (hunter.altfins.snapshot() if not light else None),
        "sweep": hunter.sweep,
        "telegram": {"enabled": hunter.notify.enabled, "chat": hunter.notify.chat, "sent": hunter.notify.sent},
        **tz_info(),
    }

@app.route('/api/ta/<symbol>')
def api_ta(symbol):
    """Fibonacci + Gann structure read of one symbol, with every derived level."""
    interval = request.args.get("interval", "1m")
    if interval not in _TA_INTERVALS:
        interval = "1m"
    try:
        limit = max(60, min(int(request.args.get("limit", "300")), 1000))
    except (TypeError, ValueError):
        limit = 300
    payload = _ttl(("ta", symbol, interval, limit), _TF_TTL.get(interval, 60),
                   lambda: _ta_payload(symbol, interval, limit))
    return jsonify(payload)


def _ta_payload(symbol, interval, limit):
    klines = hunter.client.get_klines(symbol, interval=interval, limit=limit)
    try:
        res = ta.analyze(symbol, klines, interval)
    except Exception as e:
        res = None
        log_error(f"TA error {symbol}: {e}")
    if not res:
        return {"symbol": symbol, "interval": interval, "levels": [], "score": None,
                "bias": None, "reasons": ["no structure"]}
    return res

# ---- pre-pump radar: sticky "keep following it" pick -------------------------
# Hysteresis: once a token is the watched pre-pump lead we KEEP it until either
# it drops out of the radar or a challenger beats it by FOLLOW_MARGIN points.
# Without the margin the bar flip-flops every cycle and nothing is "followed".
PP_WATCH = {"symbol": None, "since": None, "peak": 0.0}
FOLLOW_MARGIN = 5.0


def _pp_rating(pp, r):
    """Composite 0-100 pre-pump rating: coil score + volume loading + buy pressure
    + order flow + catalyst, penalised for the move already made."""
    try:
        sc = float(pp.get("score") or 0)
    except (TypeError, ValueError):
        sc = 0.0
    try:
        vr = float(r.get("volume_ratio") or 0)
    except (TypeError, ValueError):
        vr = 0.0
    try:
        fl = float(r.get("order_flow_score") or 0)
    except (TypeError, ValueError):
        fl = 0.0
    try:
        br = float(pp.get("buy_ratio", 0.5) or 0.5)
    except (TypeError, ValueError):
        br = 0.5
    try:
        ch = float(r.get("price_change_percent") or 0)
    except (TypeError, ValueError):
        ch = 0.0
    fln = fl / 100.0 if fl > 1.0 else fl
    late = max(0.0, ch - 3.0)                     # a move already made is less huntable
    rating = (sc
              + min(12.0, max(0.0, vr - 1.0) * 8.0)     # volume loading
              + min(10.0, max(0.0, br - 0.5) * 40.0)    # bid pressure
              + min(8.0, max(0.0, fln) * 8.0)           # order flow
              + (6.0 if r.get("catalyst") else 0.0)     # news catalyst
              - min(40.0, late * 4.0))
    return max(0.0, min(100.0, rating))


@app.route('/api/prepump')
def api_prepump():
    """Pre-pump radar: what is coiling (about to move) vs what is already moving now."""
    wl = hunter.watchlist or []
    coiled = []
    for r in wl:
        pp = r.get("prepump")
        if not pp:
            continue
        br = float(pp.get("buy_ratio", 0.5) or 0.5)
        try:
            vr = float(r.get("volume_ratio") or 0)
        except (TypeError, ValueError):
            vr = 0.0
        try:
            ch = float(r.get("price_change_percent") or 0)
        except (TypeError, ValueError):
            ch = 0.0
        rating = _pp_rating(pp, r)
        coiled.append({
            "symbol": r.get("symbol"),
            "score": pp.get("score", 0),
            "rating": round(rating, 1),
            "reasons": pp.get("reasons", []),
            # honest "coiled": strong rating, volume actually loading, not already pumped
            "coiled": bool(rating >= ta.PREPUMP_MIN and vr >= 1.2 and ch <= 3.0),
            "ramp": pp.get("ramp"),
            "price": r.get("current_price"),
            "change": r.get("price_change_percent"),
            "flow": r.get("order_flow_score"),
            "volume_ratio": r.get("volume_ratio"),
            "catalyst": r.get("catalyst"),
            "buy_ratio": round(br, 3),
            "direction": "BUY" if br >= 0.5 else None,
            "bullish": br >= 0.5,
        })
    # long-only hunter: a bearish coil is not a hunt, so the radar shows bulls only
    coiled = [c for c in coiled if c.get("bullish")]
    # highest rating first — the table is a hunt list, not a checklist
    coiled.sort(key=lambda c: c.get("rating") or 0, reverse=True)

    # ---- sticky follow: keep the current lead unless a challenger clears the margin
    watch = None
    if coiled:
        cur = next((c for c in coiled if c.get("symbol") == PP_WATCH.get("symbol")), None)
        best = coiled[0]
        if cur is None or (best.get("symbol") != cur.get("symbol")
                           and (best.get("rating") or 0) >= (cur.get("rating") or 0) + FOLLOW_MARGIN):
            PP_WATCH["symbol"] = best.get("symbol")
            PP_WATCH["since"] = time.time()
            PP_WATCH["peak"] = best.get("rating") or 0
        else:
            PP_WATCH["peak"] = max(PP_WATCH.get("peak") or 0, cur.get("rating") or 0)
        cur = next((c for c in coiled if c.get("symbol") == PP_WATCH.get("symbol")), None) or best
        watch = dict(cur)
        watch["since"] = (datetime.fromtimestamp(PP_WATCH["since"]).strftime("%H:%M:%S")
                          if PP_WATCH.get("since") else None)
        watch["following_sec"] = int(time.time() - PP_WATCH["since"]) if PP_WATCH.get("since") else 0
        watch["peak"] = round(PP_WATCH.get("peak") or 0, 1)

    moving = []
    for m in (hunter.market_rank or [])[:60]:
        try:
            ch = float(m.get("price_change_percent") or 0)
        except (TypeError, ValueError):
            continue
        if abs(ch) >= 3:
            moving.append({"symbol": m.get("symbol"), "price": m.get("current_price"),
                           "change": ch, "quote_volume": m.get("volume_24h"),
                           "trades": m.get("trades_24h")})
    moving.sort(key=lambda x: abs(x["change"]), reverse=True)
    return jsonify({"coiled": coiled[:24], "moving_now": moving[:24],
                    "watch": watch,
                    "threshold": ta.PREPUMP_MIN,
                    "rating_min": ta.PREPUMP_MIN,
                    "count_coiled": sum(1 for c in coiled if c.get("coiled")),
                    "updated": now_local().strftime("%H:%M:%S"),
                    **tz_info()})

@app.route('/api/results')
def api_results():
    """Daily + weekly result summaries (the same numbers the Telegram cards carry)."""
    return jsonify({"daily": hunter.results_summary("daily"),
                    "weekly": hunter.results_summary("weekly"),
                    "ledger": hunter._load_results()[-50:]})

@app.route('/api/notify')
def api_notify():
    """Telegram card status. ?discover=1 to resolve a chat id, ?test=1 to push a test card."""
    if request.args.get("discover"):
        hunter.notify.discover_chat()
    if request.args.get("test"):
        s = hunter.results_summary("daily")
        s["balance"] = hunter.balance
        ok = hunter.notify.send(card_result("daily", s))
        return jsonify({"sent": ok, **hunter.notify.status()})
    return jsonify(hunter.notify.status())

@app.route('/api/alert', methods=['POST'])
def api_alert():
    """Arm a price/time alert — the ENGINE fires it, not you.

    Body: {symbol, alert_type, price?, at?, note?, pct?}
      alert_type  CROSS UP | CROSS DOWN | ABOVE | BELOW | TIME
      price       the trigger level (required for every type except TIME)
      at          the clock — "14:30" (hunter time), "YYYY-MM-DD HH:MM", or ISO
      note        your own text, carried into both the armed and the fired card

    The alert is stored and checked every few seconds; the Telegram card is pushed
    only when the price actually crosses or the clock arrives. With both a level and
    a clock, whichever is hit first fires it.

    `immediate: true` sends the card now instead — the one manual path, used by the
    Test push button.
    """
    def _num(v):
        try:
            float(v)
            return float(v)
        except (TypeError, ValueError):
            return None

    data = request.get_json(force=True) or {}
    symbol = (data.get("symbol") or "").strip().upper()
    alert_type = (data.get("alert_type") or "").strip().upper() or "CROSS UP"
    note = (data.get("note") or "").strip()[:280]
    price = _num(data.get("price"))
    at = (data.get("at") or "").strip()
    pct = _num(data.get("pct"))
    if not symbol:
        return jsonify({"error": "missing field: symbol"}), 400
    if not huntable(symbol):
        return jsonify({"error": "pegged or tokenised asset is not huntable",
                        "symbol": symbol}), 400

    # ---- one-shot immediate card (Test push / manual): the only manual path ----
    if data.get("immediate"):
        direction = (data.get("direction") or "").strip().upper()
        if direction not in ("BUY", "SELL"):
            direction = "SELL" if "DOWN" in alert_type else "BUY"
        if not price or price <= 0:
            try:
                tk = hunter.client.get_ticker_24hr(symbol) or {}
                price = _num((tk or {}).get("lastPrice"))
            except Exception:
                price = None
        if not price or price <= 0:
            return jsonify({"error": "no price: pass price, or a symbol with a live ticker"}), 400
        card_text = card_alert(symbol, direction, price, alert_type, pct, note or None)
        ok = hunter.notify.send(card_text)
        return jsonify({"sent": ok, "mode": "immediate", "card": card_text,
                        "status": hunter.notify.status()})

    # ---- arm it: it fires itself ----
    try:
        armed_price = hunter.client.get_prices([symbol]).get(symbol)
    except Exception:
        armed_price = None
    try:
        a = hunter.alerts.arm(symbol, alert_type, price=price, at=at or None,
                              note=note or None, armed_price=armed_price)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    confirmed = None
    if data.get("confirm", True):
        try:
            confirmed = bool(hunter.notify.send(
                card_alert_armed(alertbook.AlertBook.row_view(a)), silent=True))
        except Exception:
            confirmed = False
    log_info(f"ALERT ARMED: {a['symbol']} {a['type']} target={a.get('price')} "
             f"when={a.get('when_disp')}")
    return jsonify({"armed": True, "mode": "armed",
                    "alert": alertbook.AlertBook.row_view(a),
                    "confirmed": confirmed, "alerts": hunter.alerts.view(),
                    "status": hunter.notify.status()})


@app.route('/api/alerts')
def api_alerts():
    """Every armed alert with its live distance, plus the recently fired ones."""
    v = hunter.alerts.view()
    # A stablecoin / tokenised-equity alert is not a hunt: hide any legacy row
    # that was armed before the pegged filter existed.
    for k in ("armed", "fired"):
        v[k] = [r for r in (v.get(k) or []) if huntable(r.get("symbol"))]
    v["counts"]["armed"] = len(v["armed"])
    v["counts"]["fired"] = len(v["fired"])
    v["fired_total"] = hunter.alerts_fired
    return jsonify(v)


@app.route('/api/alert/cancel', methods=['POST'])
def api_alert_cancel():
    """Disarm one armed alert by id. A fired alert is already spent."""
    aid = (request.get_json(force=True) or {}).get("id") or ""
    ok = hunter.alerts.cancel(aid)
    return jsonify({"cancelled": ok, "alerts": hunter.alerts.view()})


@app.route('/api/alert/clear', methods=['POST'])
def api_alert_clear():
    """Drop fired (default) or cancelled rows. Armed alerts are never touched."""
    state = ((request.get_json(force=True) or {}).get("state") or "fired").lower()
    state = {"fired": alertbook.FIRED, "cancelled": alertbook.CANCELLED}.get(state, alertbook.FIRED)
    return jsonify({"cleared": hunter.alerts.clear(state), "alerts": hunter.alerts.view()})

@app.route('/api/chart/<symbol>')
def api_chart(symbol):
    """Return recent klines for charting. Interval is whitelisted, limit clamped."""
    CHART_INTERVALS = {
        "1m": 240, "3m": 240, "5m": 240, "15m": 240, "30m": 240,
        "1h": 300, "2h": 300, "4h": 300, "6h": 300, "12h": 300,
        "1d": 300, "3d": 300, "1w": 300,
    }
    interval = request.args.get("interval", "1m")
    if interval not in CHART_INTERVALS:
        interval = "1m"
    try:
        limit = int(request.args.get("limit", str(CHART_INTERVALS[interval])))
    except (TypeError, ValueError):
        limit = CHART_INTERVALS[interval]
    limit = max(10, min(limit, 1000))
    payload = _ttl(("chart", symbol, interval, limit),
                   3 if interval in ("1m", "3m", "5m") else 15,
                   lambda: _chart_payload(symbol, interval, limit))
    return jsonify(payload)


def _chart_payload(symbol, interval, limit):
    klines = hunter.client.get_klines(symbol, interval=interval, limit=limit)
    candles = []
    for k in klines:
        candles.append({
            "t": int(k[0]),
            "o": float(k[1]),
            "h": float(k[2]),
            "l": float(k[3]),
            "c": float(k[4]),
            "v": float(k[5]),
        })
    return {"symbol": symbol, "interval": interval, "candles": candles}

@app.route('/api/orderbook/<symbol>')
def api_orderbook(symbol):
    """Get live order book for a symbol."""
    payload = _ttl(("ob", symbol), 2, lambda: _orderbook_payload(symbol))
    return jsonify(payload)


def _orderbook_payload(symbol):
    ob = hunter.client.get_order_book(symbol, limit=20)
    if not ob:
        return {"symbol": symbol, "bids": [], "asks": []}
    bids = [{"p": float(b[0]), "q": float(b[1])} for b in ob.get("bids", [])[:10]]
    asks = [{"p": float(a[0]), "q": float(a[1])} for a in ob.get("asks", [])[:10]]
    return {"symbol": symbol, "bids": bids, "asks": asks}


@app.route('/api/recent/<symbol>')
def api_recent(symbol):
    """Get recent trades for a symbol."""
    payload = _ttl(("recent", symbol), 3, lambda: _recent_payload(symbol))
    return jsonify(payload)


def _recent_payload(symbol):
    trades = hunter.client.get_recent_trades(symbol, limit=50)
    result = []
    for t in trades:
        result.append({
            "p": float(t.get("p", 0)),
            "q": float(t.get("q", 0)),
            "m": bool(t.get("m", False)),
            "t": int(t.get("T", 0)),
        })
    return {"symbol": symbol, "trades": result}

@app.route('/api/signals')
def api_signals():
    """Signal follow-up: fronttest summary + the live plans behind open signals."""
    s = hunter.ledger.summary()
    # Only huntable symbols reach the table: a legacy stablecoin plan must not
    # keep showing a "signal" long after the filter that should have refused it.
    s["plans"] = [p for p in hunter.ledger.open_plans()
                  if huntable(p.get("symbol"))][:20]
    s["backtest"] = hunter.ledger.backtest_summary()
    return jsonify(s)

@app.route('/api/plan/<symbol>')
def api_plan(symbol):
    """The real hunting plan (entry / stop / tp1-3 / trail / size) for one symbol."""
    payload = _ttl(("plan", symbol), 10, lambda: _plan_payload(symbol))
    if payload is None:
        return jsonify({"symbol": symbol, "plan": None, "error": "no data"}), 404
    return jsonify(payload)


def _plan_payload(symbol):
    # No plan exists for a pegged asset or a tokenised equity — there is nothing
    # to scalp. Refusing here keeps a stablecoin from ever showing a plan card.
    if not huntable(symbol):
        return None
    row = None
    for r in (hunter.watchlist or []) + (hunter.market_rank or []):
        if r.get("symbol") == symbol:
            row = r
            break
    if row is None:
        try:
            kl = hunter.client.get_klines(symbol, interval="1m", limit=200)
            row = {"symbol": symbol,
                   "current_price": float(kl[-1][4]) if kl else 0,
                   "struct": structure.hunt_multi(symbol, kl) if kl else None}
        except Exception as e:
            log_error(f"plan error {symbol}: {e}")
            row = None
    if not row:
        return None
    pl = row.get("plan") or signals.plan(row, hunter.balance, risk_pct=RISK_PER_TRADE)
    return {"symbol": symbol, "price": row.get("current_price"),
            "tf": (row.get("struct") or {}).get("tf"),
            "plan": pl, "struct": row.get("struct"),
            "altfins": row.get("altfins")}

@app.route('/api/structure/<symbol>')
def api_structure(symbol):
    """Market structure read of one symbol across the hunted timeframe ladder."""
    interval = request.args.get("interval", "1m")
    if interval not in _TA_INTERVALS:
        interval = "1m"
    try:
        limit = max(80, min(int(request.args.get("limit", "300")), 1000))
    except (TypeError, ValueError):
        limit = 300
    payload = _ttl(("structure", symbol, interval, limit), _TF_TTL.get(interval, 60),
                   lambda: _structure_payload(symbol, interval, limit))
    if payload is None:
        return jsonify({"symbol": symbol, "error": "no structure"}), 404
    return jsonify(payload)


def _structure_payload(symbol, interval, limit):
    kl = hunter.client.get_klines(symbol, interval=interval, limit=limit)
    try:
        res = structure.hunt_multi(symbol, kl) if kl else None
    except Exception as e:
        log_error(f"structure error {symbol}: {e}")
        res = None
    if not res:
        return None
    res = dict(res)          # never mutate the object parked in the cache
    res["plan"] = signals.plan({"current_price": res.get("price"), "struct": res,
                                "hunt_tf": res.get("tf")}, hunter.balance, risk_pct=RISK_PER_TRADE)
    return res

@app.route('/api/altfins')
def api_altfins():
    """AltFins bullish chart-pattern feed: what it is watching and how strong."""
    return jsonify(hunter.altfins.snapshot())

@app.route('/api/backtest/<symbol>')
def api_backtest(symbol):
    """Replay the structural rule over one symbol's own history (cached 15 min)."""
    cached = hunter.ledger.cached_backtest(symbol)
    if cached and request.args.get("fresh") != "1":
        return jsonify(cached)
    try:
        limit = max(120, min(int(request.args.get("limit", "400")), 1000))
    except (TypeError, ValueError):
        limit = 400
    kl = hunter.client.get_klines(symbol, interval="1m", limit=limit)
    res = hunter.ledger.backtest(symbol, kl, tf="1m", tf_min=1, stride=3)
    if not res:
        return jsonify({"symbol": symbol, "error": "not enough history"}), 404
    return jsonify(res)

@app.route('/api/backtest_all')
def api_backtest_all():
    """Replay the structural rule across the hunter's universe and aggregate."""
    if request.args.get("fresh") != "1" and hunter.sweep and time.time() - hunter._sweep_ts < 900:
        return jsonify(hunter.sweep)
    try:
        limit = max(2, min(int(request.args.get("limit", "6")), 15))
    except (TypeError, ValueError):
        limit = 6
    syms = []
    for r in (hunter.watchlist or []) + (hunter.market_rank or []):
        s = r.get("symbol")
        if s and s not in syms:
            syms.append(s)

    def kl_for(s):
        try:
            return hunter.client.get_klines(s, interval="1m", limit=400)
        except Exception:
            return None

    hunter.sweep = hunter.ledger.backtest_all(syms, kl_for, tf="1m", tf_min=1,
                                              stride=3, limit=limit)
    hunter._sweep_ts = time.time()
    return jsonify(hunter.sweep)

@app.route('/api/symbols')
def api_symbols():
    """Every tradable Binance USDT pair — the coin searcher's index."""
    try:
        syms = sorted(hunter.refresh_trading_symbols() or [])
    except Exception:
        syms = []
    if not syms:
        syms = sorted({r.get("symbol") for r in (hunter.market_rank or []) if r.get("symbol")})
    return jsonify({"count": len(syms), "symbols": syms})

def run_hunter_loop():
    while hunter.running and not os.path.exists(STOP_FILE):
        try:
            hunter.run_cycle()
        except Exception as e:
            log_error(f"Hunter cycle error: {e}")
        time.sleep(10)

def run_alert_loop():
    """Armed alerts get their own clock.

    A full market sweep can run for a minute, so an alert armed on a fast cross must
    not wait behind it. This loop polls every few seconds and fires the alert the
    moment the level or the clock is hit.
    """
    time.sleep(12)                      # let the engine and its client come up
    while True:
        try:
            if not os.path.exists(STOP_FILE):
                hunter.check_alerts()
        except Exception as e:
            log_error(f"Alert loop error: {e}")
        time.sleep(3)

def run_perm_watch():
    """Watch the API key until it can actually trade, then say so.

    Binance requires an AND(email code, Google Authenticator) challenge to switch
    Spot trading on, which cannot be automated. So this thread waits for the human
    to finish it and announces the exact moment live entries become possible —
    no restart needed, because the entry gate reads the same cache.
    """
    time.sleep(20)
    was = None
    while True:
        try:
            perm = hunter.client.spot_trading_allowed(force=True)
            allowed = perm.get("allowed")
            if was is None and allowed is not None:
                was = allowed
                if allowed:
                    log_info("LIVE PERMISSION: key carries Spot trading — orders armed")
                else:
                    log_warn("LIVE PERMISSION: key cannot trade yet — entries will be "
                             "blocked, not spammed; waiting for the Binance 2FA switch")
            elif allowed is not None and allowed != was:
                was = allowed
                if allowed:
                    log_info("LIVE PERMISSION GRANTED — live entries are now possible")
                    hunter.trade_perm_reason = ""
                    hunter._card("perm-on",
                                 "✅ *BINANCE PERMISSION ENABLED*\n"
                                 "The key can now place Spot orders.\n"
                                 "Live entries are armed — the hunter will fill on the "
                                 "next qualified pre-pump.", ttl=0)
                    try:
                        swarm.record_event("executor", "permission-on", "", "spot trading enabled")
                    except Exception:
                        pass
        except Exception as e:
            log_error(f"Permission watch error: {e}")
        time.sleep(300)

# ─────────────────────────────────────────────────────────── TELEGRAM TOOLS ──
# Inbound command surface. Read-only by construction: tgtools has no order path.
tg_tools = None
if tgtools_mod is not None:
    try:
        tg_tools = tgtools_mod.TelegramTools(hunter, hunter.notify)
    except Exception as _e:
        log_error(f"telegram tools init failed: {type(_e).__name__}")

# AI CEO chatbot — consumes tg_tools.tools registry
chat_brain = ChatBrain(tg_tools) if tg_tools is not None else None


@app.route("/api/chat", methods=["POST"])
def api_chat():
    if chat_brain is None:
        return jsonify({"ok": False, "error": "chatbot not initialised"}), 503
    data = request.get_json(silent=True) or {}
    message = data.get("message", "").strip()
    if not message:
        return jsonify({"ok": False, "error": "message required"}), 400
    res = chat_brain.process(message)
    return jsonify({"ok": True, **res})


@app.route("/api/chat/history", methods=["GET"])
def api_chat_history():
    if chat_brain is None:
        return jsonify({"ok": False, "error": "chatbot not initialised"}), 503
    return jsonify({"ok": True, "history": chat_brain.get_history()})


@app.route("/api/chat/clear", methods=["POST"])
def api_chat_clear():
    if chat_brain is None:
        return jsonify({"ok": False, "error": "chatbot not initialised"}), 503
    chat_brain.clear_history()
    return jsonify({"ok": True, "cleared": True})


@app.route("/api/telegram/status")
def api_tg_status():
    if tg_tools is None:
        return jsonify({"ok": False, "error": _TGT_IMPORT_ERROR or "not initialised"})
    return jsonify({"ok": True, **tg_tools.snapshot(),
                    "notify": hunter.notify.status()})


@app.route("/api/telegram/tools")
def api_tg_tools():
    if tg_tools is None:
        return jsonify({"ok": False, "error": _TGT_IMPORT_ERROR or "not initialised"})
    return jsonify({"ok": True, "tools": [
        {"name": t["name"], "args": t["args"], "desc": t["desc"],
         "readonly": t["readonly"]}
        for t in sorted(tg_tools.tools.values(), key=lambda x: x["name"])]})


@app.route("/api/telegram/preview")
def api_tg_preview():
    """Render a command locally without sending it anywhere."""
    if tg_tools is None:
        return jsonify({"ok": False, "error": _TGT_IMPORT_ERROR or "not initialised"})
    cmd = (request.args.get("cmd") or "/status").strip()
    return jsonify({"ok": True, "cmd": cmd, "reply": tg_tools.dispatch(cmd)})


@app.route("/api/telegram/test", methods=["POST"])
def api_tg_test():
    """Push one real card to the owner chat. Nothing is traded."""
    if tg_tools is None:
        return jsonify({"ok": False, "error": _TGT_IMPORT_ERROR or "not initialised"})
    try:
        text = tg_tools.dispatch("/status")
        sent = tg_tools.send(tg_tools.owner, text)
        return jsonify({"ok": bool(sent), "chat": tg_tools.owner})
    except Exception as e:
        return jsonify({"ok": False, "error": type(e).__name__})


if __name__ == "__main__":
    # Start hunter thread
    hunter.running = True
    t = threading.Thread(target=run_hunter_loop, daemon=True)
    t.start()

    # Armed alerts run on their own fast clock, independent of the market sweep
    ta_thread = threading.Thread(target=run_alert_loop, daemon=True)
    ta_thread.start()

    # Permission watch: announce the instant the key can actually trade
    perm_thread = threading.Thread(target=run_perm_watch, daemon=True)
    perm_thread.start()

    # Telegram tools: inbound commands, read-only, no console, no order path
    if tg_tools is not None:
        try:
            started = tg_tools.start()
            log_info(f"Telegram tools {'polling' if started else 'idle'} "
                     f"(chat {tg_tools.owner or '-'})")
        except Exception as e:
            log_error(f"telegram tools start failed: {type(e).__name__}")
    
    # Start the hunter scanning loop in a background thread so live data flows
    # before the web server binds. Without this the dashboard shows only stubs.
    def _run_hunter():
        try:
            hunter.start()
        except Exception as e:
            log_error(f"Hunter loop exited: {e}")
    import threading as _threading
    _t = _threading.Thread(target=_run_hunter, daemon=True, name="hunter-loop")
    _t.start()
    
    # Write PID file for start_all.bat detection
    try:
        with open(os.path.join(BOT, "hunter.pid"), "w") as f:
            f.write(str(os.getpid()))
    except Exception:
        pass
    
    log_info(f"BINANCE HUNTER DASHBOARD starting on port {PORT}")
    log_info(f"Mission: $9 → $20 | Port: {PORT}")
    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True)
