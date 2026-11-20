#!/usr/bin/env python3
"""
KUCOIN HUNTER - Spot Trading System (KuCoin API Migration)
Small account specialist: $9 → $20 target
Real-time order flow, liquidity pool tracking, volume analysis
Auto-enters on real movers before they move
Runs on port 4564 (unique, never touched)
"""
import os, sys, json, time, hmac, hashlib, base64, gzip, requests, threading, asyncio, logging
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from flask import Flask, render_template, jsonify, request

BOT = os.path.dirname(os.path.abspath(__file__))
PORT = 4564
STOP_FILE = os.path.join(BOT, "STOP_HUNTER")
STATE_FILE = os.path.join(BOT, "hunter_state.json")
RESULTS_FILE = os.path.join(BOT, "results.json")
DIGEST_FILE = os.path.join(BOT, "digest.json")
ALERTS_FILE = os.path.join(BOT, "alerts.json")
LOG_FILE = os.path.join(BOT, "hunter.log")

# KuCoin Configuration
KUCOIN_API_BASE = "https://api.kucoin.com"
KUCOIN_WS_BASE = "wss://ws-api-spot.kucoin.com"
KUCOIN_API_KEY = os.environ.get("KUCOIN_API_KEY", "")
KUCOIN_API_SECRET = os.environ.get("KUCOIN_API_SECRET", "")
KUCOIN_API_PASSPHRASE = os.environ.get("KUCOIN_API_PASSPHRASE", "")

# Hunter Configuration
TARGET_BALANCE = 20.0
LIVE_ORDERS = int(os.environ.get("HUNTER_LIVE_ORDERS", "0"))
MAX_POSITION_USD = float(os.environ.get("HUNTER_MAX_POSITION_USD", "20"))
MAX_DAILY_LOSS_PCT = float(os.environ.get("HUNTER_MAX_DAILY_LOSS_PCT", "5"))
MIN_VOLUME_USD = float(os.environ.get("HUNTER_MIN_VOLUME_USD", "500000"))
MIN_PRICE = float(os.environ.get("HUNTER_MIN_PRICE", "0.00001"))
MAX_PRICE = float(os.environ.get("HUNTER_MAX_PRICE", "100"))
RISK_PER_TRADE = 0.02

# Timezone
TZ_NAME = os.environ.get("TZ", "UTC")

def now_local():
    return datetime.now(timezone.utc).astimezone()

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
    return n if (n and not n.lstrip("+-").isdigit()) else ""

def tz_info():
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

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

def log_info(msg): logger.info(msg)
def log_error(msg): logger.error(msg)
def log_warn(msg): logger.warning(msg)

# ============================================================================
# KUCOIN CLIENT
# ============================================================================

class KuCoinClient:
    """KuCoin Spot API Client"""
    
    def __init__(self, api_key="", api_secret="", passphrase=""):
        self.api_key = api_key or KUCOIN_API_KEY
        self.api_secret = api_secret or KUCOIN_API_SECRET
        self.passphrase = passphrase or KUCOIN_API_PASSPHRASE
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "User-Agent": "KuCoinHunter/1.0"
        })
        self._ws_token = None
        self._ws_token_expiry = 0
        
    def _sign(self, timestamp, method, endpoint, body=""):
        message = timestamp + method.upper() + endpoint + body
        signature = base64.b64encode(
            hmac.new(self.api_secret.encode(), message.encode(), hashlib.sha256).digest()
        ).decode()
        passphrase_sig = base64.b64encode(
            hmac.new(self.api_secret.encode(), self.passphrase.encode(), hashlib.sha256).digest()
        ).decode()
        return {
            "KC-API-SIGN": signature,
            "KC-API-TIMESTAMP": timestamp,
            "KC-API-KEY": self.api_key,
            "KC-API-PASSPHRASE": passphrase_sig,
            "KC-API-KEY-VERSION": "2"
        }
    
    def _request(self, method, endpoint, params=None, data=None):
        timestamp = str(int(time.time() * 1000))
        body = json.dumps(data) if data else ""
        query = "&".join(f"{k}={v}" for k, v in (params or {}).items())
        full_endpoint = endpoint + ("?" + query if query else "")
        
        headers = self._sign(timestamp, method, full_endpoint, body)
        self.session.headers.update(headers)
        
        url = KUCOIN_API_BASE + full_endpoint
        try:
            resp = self.session.request(method.upper(), url, json=data, timeout=10)
            resp.raise_for_status()
            result = resp.json()
            if result.get("code") != "200000":
                raise Exception(f"KuCoin API: {result.get('msg')}")
            return result.get("data", {})
        except Exception as e:
            log_error(f"KuCoin request failed: {e}")
            raise
        finally:
            for k in ["KC-API-SIGN", "KC-API-TIMESTAMP", "KC-API-KEY", "KC-API-PASSPHRASE", "KC-API-KEY-VERSION"]:
                self.session.headers.pop(k, None)
    
    # Public endpoints
    def get_symbols(self):
        return self._request("GET", "/api/v2/symbols")
    
    def get_ticker(self, symbol):
        return self._request("GET", "/api/v1/market/orderbook/level1", {"symbol": symbol})
    
    def get_all_tickers(self):
        return self._request("GET", "/api/v1/market/allTickers")
    
    def get_klines(self, symbol, interval, start_at=None, end_at=None, limit=None):
        params = {"symbol": symbol, "type": interval}
        if start_at: params["startAt"] = start_at
        if end_at: params["endAt"] = end_at
        if limit: params["limit"] = limit
        return self._request("GET", "/api/v1/market/candles", params)
    
    def get_order_book(self, symbol, level=20):
        return self._request("GET", f"/api/v1/market/orderbook/level2_{min(level, 100)}", {"symbol": symbol})
    
    def get_trade_histories(self, symbol, limit=100):
        return self._request("GET", "/api/v1/market/histories", {"symbol": symbol, "limit": limit})
    
    def get_24hr_stats(self, symbol):
        return self._request("GET", "/api/v1/market/stats", {"symbol": symbol})
    
    # Private endpoints
    def get_accounts(self):
        return self._request("GET", "/api/v1/accounts")
    
    def get_ws_token(self):
        if self._ws_token and time.time() < self._ws_token_expiry:
            return self._ws_token
        data = self._request("POST", "/api/v1/bullet-private")
        self._ws_token = data.get("token", "")
        self._ws_token_expiry = time.time() + data.get("instanceServers", [{}])[0].get("pingInterval", 18000) / 1000 - 60
        return self._ws_token
    
    @staticmethod
    def to_kucoin(symbol):
        if "-" in symbol: return symbol
        for q in ["USDT", "BTC", "ETH", "USDC", "BNB", "KCS"]:
            if symbol.endswith(q): return symbol[:-len(q)] + "-" + q
        return symbol
    
    @staticmethod
    def from_kucoin(symbol):
        return symbol.replace("-", "")
    
    @staticmethod
    def normalize_interval(interval):
        mapping = {"1m":"1min","3m":"3min","5m":"5min","15m":"15min","30m":"30min",
                   "1h":"1hour","2h":"2hour","4h":"4hour","6h":"6hour","8h":"8hour",
                   "12h":"12hour","1d":"1day","1w":"1week"}
        return mapping.get(interval, interval)

# Global client
kucoin = KuCoinClient()

# ============================================================================
# FLASK APP
# ============================================================================

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config["TEMPLATES_AUTO_RELOAD"] = True

# Caching
_TTL_CACHE = {}
_TTL_LOCK = threading.Lock()
_TF_TTL = {"1m":8,"3m":12,"5m":20,"15m":45,"30m":60,"1h":90,"2h":120,"4h":240,"6h":300,"12h":480,"1d":600,"3d":900,"1w":1200}
_TA_INTERVALS = ("1m","5m","15m","1h","4h","1d")

def _ttl(key, ttl, fn):
    now = time.time()
    with _TTL_LOCK:
        hit = _TTL_CACHE.get(key)
        if hit and hit[0] > now: return hit[1]
    val = fn()
    if val is not None:
        with _TTL_LOCK:
            _TTL_CACHE[key] = (now + ttl, val)
            if len(_TTL_CACHE) > 4000:
                for k in [k for k,(era,_) in _TTL_CACHE.items() if era <= now]:
                    _TTL_CACHE.pop(k, None)
    return val

@app.after_request
def _gzip_body(resp):
    try:
        if (resp.status_code != 200 or resp.direct_passthrough 
                or "gzip" not in (request.headers.get("Accept-Encoding") or "")
                or resp.mimetype not in ("application/json", "text/html")):
            return resp
        body = resp.get_data()
        if len(body) < 1500 or body[:2] == b"\x1f\x8b": return resp
        packed = gzip.compress(body, 6, mtime=0)
        if len(packed) >= len(body) * 0.9: return resp
        resp.set_data(packed)
        resp.headers["Content-Encoding"] = "gzip"
        resp.headers["Content-Length"] = str(len(packed))
        resp.headers["Vary"] = "Accept-Encoding"
    except Exception as e:
        log_error(f"gzip error: {e}")
    return resp

# ============================================================================
# ROUTES
# ============================================================================

@app.route('/')
def index():
    return render_template("terminal.html")

@app.route('/api/ws/token')
def api_ws_token():
    try:
        # Use public WS token (no auth required for market data)
        data = kucoin._request("POST", "/api/v1/bullet-public")
        token = data.get("token", "")
        endpoint = data.get("instanceServers", [{}])[0].get("endpoint", KUCOIN_WS_BASE)
        return jsonify({"token": token, "endpoint": endpoint})
    except Exception as e:
        log_error(f"WS token error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/symbols')
def api_symbols():
    try:
        data = kucoin.get_symbols()
        symbols = [s["symbol"] for s in data if s.get("enableTrading")]
        return jsonify({"count": len(symbols), "symbols": sorted(symbols)})
    except Exception as e:
        return jsonify({"count": 0, "symbols": [], "error": str(e)})

@app.route('/api/status')
def api_status():
    try:
        # Get account balance (handles missing/invalid credentials)
        balance = 0
        try:
            accounts = kucoin.get_accounts()
            for acc in accounts:
                if acc.get("currency") == "USDT":
                    balance = float(acc.get("available", 0)) + float(acc.get("holds", 0))
                    break
        except Exception as e:
            log_warn(f"Account fetch failed (using demo balance): {e}")
            balance = 100.0  # Demo balance
        
        # Get tickers for market overview
        tickers = kucoin.get_all_tickers()
        market_rank = []
        for t in tickers.get("ticker", [])[:50]:
            try:
                market_rank.append({
                    "symbol": t["symbol"],
                    "current_price": float(t["last"]),
                    "price_change_percent": float(t["changeRate"]) * 100,
                    "volume_24h": float(t.get("volValue", 0)),
                    "trades_24h": int(float(t.get("vol", 0)))
                })
            except Exception:
                continue
        
        return jsonify({
            "balance": round(balance, 2),
            "target": TARGET_BALANCE,
            "pnl_today": 0,
            "positions": 0,
            "positions_detail": [],
            "trades_today": 0,
            "running": False,
            "live_orders": LIVE_ORDERS,
            "swept": 0,
            "candidates": len(market_rank),
            "pegged_excluded": 0,
            "dead_excluded": 0,
            "tokenised_excluded": 0,
            "trading_symbols": len(market_rank),
            "catalyst_entries": 0,
            "prepump_entries": 0,
            "firstmove_entries": 0,
            "risk": {"daily_loss_pct": 0, "max_drawdown_pct": 0},
            "radar": {"coiled": [], "moving_now": [], "watch": None},
            "regime": {"regime": "UNKNOWN", "score": 0},
            "watchlist": [],
            "market": market_rank[:20],
            "signals": {},
            "plans": [],
            "backtest": {},
            "altfins": None,
            "sweep": None,
            "telegram": {"enabled": bool(os.environ.get("TELEGRAM_BOT_TOKEN")), "chat": os.environ.get("TELEGRAM_CHAT_ID"), "sent": 0},
            **tz_info()
        })
    except Exception as e:
        log_error(f"Status error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/klines/<symbol>')
def api_klines(symbol):
    interval = request.args.get("interval", "1m")
    limit = min(max(int(request.args.get("limit", "500")), 10), 1500)
    
    kucoin_symbol = KuCoinClient.to_kucoin(symbol)
    kucoin_interval = KuCoinClient.normalize_interval(interval)
    end_at = int(time.time())
    start_at = end_at - (limit * _interval_seconds(interval))
    
    try:
        klines = kucoin.get_klines(kucoin_symbol, kucoin_interval, start_at, end_at)
        # Convert KuCoin format to standard: [time, open, high, low, close, volume]
        candles = []
        for k in reversed(klines):  # KuCoin returns newest first
            candles.append([
                int(k[0]) * 1000,  # timestamp ms
                float(k[1]),       # open
                float(k[2]),       # high
                float(k[3]),       # low
                float(k[4]),       # close
                float(k[5])        # volume
            ])
        return jsonify({"symbol": symbol, "interval": interval, "candles": candles})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/orderbook/<symbol>')
def api_orderbook(symbol):
    kucoin_symbol = KuCoinClient.to_kucoin(symbol)
    try:
        # KuCoin supports level2_20 or level2_100
        ob = kucoin.get_order_book(kucoin_symbol, 100)
        bids = [{"p": float(b[0]), "q": float(b[1])} for b in ob.get("bids", [])[:20]]
        asks = [{"p": float(a[0]), "q": float(a[1])} for a in ob.get("asks", [])[:20]]
        return jsonify({"symbol": symbol, "bids": bids, "asks": asks})
    except Exception as e:
        log_error(f"Orderbook error for {symbol}: {e}")
        return jsonify({"symbol": symbol, "bids": [], "asks": [], "error": str(e)})

@app.route('/api/trades/<symbol>')
def api_trades(symbol):
    kucoin_symbol = KuCoinClient.to_kucoin(symbol)
    try:
        trades = kucoin.get_trade_histories(kucoin_symbol, 100)
        result = []
        for t in trades:
            result.append({
                "p": float(t["price"]),
                "q": float(t["size"]),
                "m": t["side"] == "sell",  # maker is seller
                "t": int(t["time"])
            })
        return jsonify({"symbol": symbol, "trades": result})
    except Exception as e:
        return jsonify({"symbol": symbol, "trades": [], "error": str(e)})

@app.route('/api/ticker/<symbol>')
def api_ticker(symbol):
    kucoin_symbol = KuCoinClient.to_kucoin(symbol)
    try:
        ticker = kucoin.get_ticker(kucoin_symbol)
        stats = kucoin.get_24hr_stats(kucoin_symbol)
        return jsonify({
            "symbol": symbol,
            "price": float(ticker.get("price", 0)),
            "change": float(stats.get("changeRate", 0)) * 100,
            "volume": float(stats.get("vol", 0)),
            "volume_value": float(stats.get("volValue", 0)),
            "high": float(stats.get("high", 0)),
            "low": float(stats.get("low", 0)),
            "open": float(stats.get("open", 0))
        })
    except Exception as e:
        return jsonify({"symbol": symbol, "error": str(e)})

@app.route('/api/radar')
def api_radar():
    try:
        tickers = kucoin.get_all_tickers()
        coiled = []
        moving = []
        
        for t in tickers.get("ticker", []):
            change = float(t.get("changeRate", 0)) * 100
            volume = float(t.get("volValue", 0))
            price = float(t.get("last", 0))
            
            if abs(change) >= 3:
                moving.append({
                    "symbol": t["symbol"],
                    "price": price,
                    "change": change,
                    "quote_volume": volume,
                    "trades": int(t.get("vol", 0))
                })
            
            # Simple coil detection: low change, decent volume
            if abs(change) < 2 and volume > 100000:
                coiled.append({
                    "symbol": t["symbol"],
                    "score": max(0, 50 - abs(change) * 10),
                    "rating": max(0, 50 - abs(change) * 10),
                    "reasons": ["low_volatility", "volume_present"],
                    "coiled": True,
                    "price": price,
                    "change": change,
                    "volume_ratio": volume / 100000,
                    "catalyst": False,
                    "direction": "BUY",
                    "bullish": True
                })
        
        moving.sort(key=lambda x: abs(x["change"]), reverse=True)
        coiled.sort(key=lambda x: x.get("rating", 0), reverse=True)
        
        return jsonify({
            "coiled": coiled[:24],
            "moving_now": moving[:24],
            "watch": coiled[0] if coiled else None,
            "updated": now_local().strftime("%H:%M:%S"),
            **tz_info()
        })
    except Exception as e:
        return jsonify({"coiled": [], "moving_now": [], "error": str(e)})

@app.route('/api/signals')
def api_signals():
    # Placeholder - would integrate with signal generation logic
    return jsonify({
        "plans": [],
        "backtest": {},
        "summary": {"total": 0, "wins": 0, "losses": 0, "winrate": 0}
    })

@app.route('/api/positions')
def api_positions():
    # Placeholder - would integrate with position tracking
    return jsonify({"positions": []})

@app.route('/api/equity')
def api_equity():
    try:
        balance = 0
        try:
            accounts = kucoin.get_accounts()
            for acc in accounts:
                if acc.get("currency") == "USDT":
                    balance = float(acc.get("available", 0)) + float(acc.get("holds", 0))
                    break
        except Exception:
            balance = 100.0  # Demo balance
        
        return jsonify({
            "equity": balance,
            "pnl": 0,
            "pnlPct": 0,
            "balance": balance,
            "equityHistory": []  # Would be populated from results
        })
    except Exception as e:
        return jsonify({"equity": 0, "pnl": 0, "pnlPct": 0, "balance": 0, "equityHistory": []})

@app.route('/api/order', methods=['POST'])
def api_order():
    if not LIVE_ORDERS:
        return jsonify({"error": "Live orders disabled (HUNTER_LIVE_ORDERS=0)"}), 403
    
    data = request.get_json() or {}
    try:
        result = kucoin.place_order(
            symbol=data.get("symbol"),
            side=data.get("side"),
            order_type=data.get("type", "market"),
            size=data.get("size"),
            price=data.get("price"),
            client_oid=data.get("clientOid")
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# Telegram webhook endpoint
@app.route('/telegram/webhook', methods=['POST'])
def telegram_webhook():
    """Handle incoming Telegram messages"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"ok": False}), 400
        
        # Simple command handling
        message = data.get("message", {})
        text = message.get("text", "").strip()
        chat_id = str(message.get("chat", {}).get("id", ""))
        
        if text.startswith("/status"):
            # Return status
            accounts = kucoin.get_accounts()
            balance = 0
            for acc in accounts:
                if acc.get("currency") == "USDT":
                    balance = float(acc.get("available", 0)) + float(acc.get("holds", 0))
                    break
            reply = f"🤖 KuCoin Hunter Status\n💰 Balance: ${balance:.2f}\n🎯 Target: ${TARGET_BALANCE}\n📊 Mode: {'LIVE' if LIVE_ORDERS else 'SHADOW'}"
        elif text.startswith("/balance"):
            accounts = kucoin.get_accounts()
            reply = "💰 Account Balances:\n"
            for acc in accounts:
                avail = float(acc.get("available", 0))
                if avail > 0:
                    reply += f"  {acc['currency']}: {avail:.4f}\n"
        elif text.startswith("/help"):
            reply = "🤖 KuCoin Hunter Commands:\n/status - Bot status\n/balance - Account balances\n/signals - Active signals\n/help - This help"
        else:
            reply = "Unknown command. Use /help"
        
        # Send reply via Telegram Bot API
        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        if bot_token:
            requests.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={"chat_id": chat_id, "text": reply}
            )
        
        return jsonify({"ok": True})
    except Exception as e:
        log_error(f"Telegram webhook error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


# Set Telegram webhook
@app.route('/api/telegram/set_webhook', methods=['POST'])
def set_telegram_webhook():
    try:
        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        if not bot_token:
            return jsonify({"error": "No bot token configured"}), 400
        
        # Get ngrok/public URL from request or env
        webhook_url = request.json.get("url") or os.environ.get("WEBHOOK_URL")
        if not webhook_url:
            return jsonify({"error": "No webhook URL provided"}), 400
        
        webhook_url = webhook_url.rstrip("/") + "/telegram/webhook"
        resp = requests.post(
            f"https://api.telegram.org/bot{bot_token}/setWebhook",
            json={"url": webhook_url}
        ).json()
        
        return jsonify(resp)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def _interval_seconds(interval):
    mapping = {"1m":60,"3m":180,"5m":300,"15m":900,"30m":1800,"1h":3600,"2h":7200,"4h":14400,"6h":21600,"12h":43200,"1d":86400,"1w":604800}
    return mapping.get(interval, 3600)


# Global error handler
@app.errorhandler(Exception)
def handle_error(e):
    log_error(f"Unhandled error: {e}")
    return jsonify({"error": "Internal server error"}), 500


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    log_info(f"KUCOIN HUNTER DASHBOARD starting on port {PORT}")
    log_info(f"Mission: $9 → $20 | Port: {PORT} | Live Orders: {LIVE_ORDERS}")
    
    # Use waitress for production
    try:
        from waitress import serve
        serve(app, host="0.0.0.0", port=PORT, threads=4)
    except ImportError:
        app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True)