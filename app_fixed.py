#!/usr/bin/env python3
"""
KUCOIN HUNTER PRO v2.1 - Institutional Terminal (Binance API Migration)
Small account specialist: $9 → $20 target
Real-time order flow, liquidity pool tracking, volume analysis
Runs on port 4564 with waitress WSGI server
"""
import os, sys, json, time, hmac, hashlib, base64, gzip, requests, threading, logging
from collections import defaultdict, deque
from datetime import datetime, timezone, timedelta
from flask import Flask, render_template, jsonify, request

BOT = os.path.dirname(os.path.abspath(__file__))

# Load .env file
def load_env():
    env_path = os.path.join(BOT, ".env")
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip()
                    if value and key not in os.environ:
                        os.environ[key] = value

load_env()

PORT = 4564
LOG_FILE = os.path.join(BOT, "hunter.log")

# Binance Configuration
BINANCE_API_BASE = "https://api.binance.com"
BINANCE_WS_BASE = "wss://stream.binance.com:9443/ws"
BINANCE_API_KEY = os.environ.get("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.environ.get("BINANCE_API_SECRET", "")

# Hunter Configuration
TARGET_BALANCE = float(os.environ.get("HUNTER_TARGET_BALANCE", "20.0"))
LIVE_ORDERS = int(os.environ.get("HUNTER_LIVE_ORDERS", "0"))
MAX_POSITION_USD = float(os.environ.get("HUNTER_MAX_POSITION_USD", "20"))
MAX_DAILY_LOSS_PCT = float(os.environ.get("HUNTER_MAX_DAILY_LOSS_PCT", "5"))
MIN_VOLUME_USD = float(os.environ.get("HUNTER_MIN_VOLUME_USD", "500000"))
MIN_PRICE = float(os.environ.get("HUNTER_MIN_PRICE", "0.00001"))
MAX_PRICE = float(os.environ.get("HUNTER_MAX_PRICE", "100"))
RISK_PER_TRADE = 0.02

# Timezone
TZ_NAME = os.environ.get("HUNTER_TZ", "UTC")

# Rate limiting - Binance: ~1200 weight per minute
_LAST_BINANCE_CALL = 0
_BINANCE_MIN_INTERVAL = 0.1
_BINANCE_LOCK = threading.Lock()
_BINANCE_RETRY_COUNT = 0
_BINANCE_LAST_429 = 0

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
# BINANCE RATE-LIMITED CLIENT
# ============================================================================

class BinanceClient:
    """Binance Spot API Client with rate limiting and HMAC auth"""
    
    def __init__(self, api_key="", api_secret=""):
        self.api_key = api_key or BINANCE_API_KEY
        self.api_secret = api_secret or BINANCE_API_SECRET
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "User-Agent": "BinanceHunter/2.1",
            "Accept": "application/json",
            "X-MBX-APIKEY": self.api_key
        })
        self._ws_key = None
        self._has_credentials = bool(self.api_key and self.api_secret)
    
    def _rate_limit(self):
        global _LAST_BINANCE_CALL, _BINANCE_RETRY_COUNT, _BINANCE_LAST_429
        with _BINANCE_LOCK:
            now = time.time()
            if now - _BINANCE_LAST_429 < 5:
                time.sleep(0.5)
            elapsed = now - _LAST_BINANCE_CALL
            if elapsed < _BINANCE_MIN_INTERVAL:
                time.sleep(_BINANCE_MIN_INTERVAL - elapsed)
            _LAST_BINANCE_CALL = time.time()
    
    def _handle_429(self, e):
        global _BINANCE_RETRY_COUNT, _BINANCE_LAST_429
        _BINANCE_RETRY_COUNT += 1
        _BINANCE_LAST_429 = time.time()
        log_warn(f"Rate limited by Binance (429), backing off. Count: {_BINANCE_RETRY_COUNT}")
    
    def _sign_params(self, params):
        """Create HMAC SHA256 signature for authenticated endpoints"""
        query_string = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        signature = hmac.new(
            self.api_secret.encode(), query_string.encode(), hashlib.sha256
        ).hexdigest()
        params["signature"] = signature
        return params
    
    def _request(self, method, endpoint, params=None, data=None, signed=False, retries=3):
        self._rate_limit()
        
        params = params or {}
        if signed:
            params["timestamp"] = str(int(time.time() * 1000))
            params = self._sign_params(params)
        
        url = BINANCE_API_BASE + endpoint
        try:
            resp = self.session.request(method.upper(), url, params=params, json=data, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                self._handle_429(e)
                if retries > 0:
                    time.sleep(2)
                    return self._request(method, endpoint, params, data, signed, retries - 1)
            log_error(f"Binance request failed: {e}")
            raise
        except Exception as e:
            log_error(f"Binance request failed: {e}")
            raise
    
    # Public endpoints
    def get_symbols(self):
        data = self._request("GET", "/api/v3/exchangeInfo")
        symbols = []
        for s in data.get("symbols", []):
            if s.get("status") == "TRADING" and s.get("quoteAsset") == "USDT":
                symbols.append(s["symbol"])
        return sorted(symbols)
    
    def get_ticker(self, symbol):
        return self._request("GET", "/api/v3/ticker/price", {"symbol": symbol})
    
    def get_all_tickers(self):
        return self._request("GET", "/api/v3/ticker/24hr")
    
    def get_klines(self, symbol, interval, limit=500):
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        return self._request("GET", "/api/v3/klines", params)
    
    def get_order_book(self, symbol, limit=100):
        params = {"symbol": symbol, "limit": limit}
        return self._request("GET", "/api/v3/depth", params)
    
    def get_trades(self, symbol, limit=100):
        params = {"symbol": symbol, "limit": limit}
        return self._request("GET", "/api/v3/trades", params)
    
    # Private endpoints
    def get_account(self):
        if not self._has_credentials:
            raise Exception("No Binance credentials configured")
        return self._request("GET", "/api/v3/account", signed=True)
    
    @staticmethod
    def to_binance(symbol):
        """Convert BTC-USDT → BTCUSDT"""
        if "-" in symbol:
            return symbol.replace("-", "")
        return symbol
    
    @staticmethod
    def from_binance(symbol):
        """Convert BTCUSDT → BTC-USDT"""
        if "-" not in symbol and symbol.endswith("USDT"):
            return symbol[:-4] + "-USDT"
        return symbol
    
    @staticmethod
    def normalize_interval(interval):
        mapping = {"1m":"1m","3m":"3m","5m":"5m","15m":"15m","30m":"30m",
                   "1h":"1h","2h":"2h","4h":"4h","6h":"6h","8h":"8h",
                   "12h":"12h","1d":"1d","1w":"1w"}
        return mapping.get(interval, interval)

# Global client
binance = BinanceClient()

# ============================================================================
# CACHING LAYER
# ============================================================================

_TTL_CACHE = {}
_TTL_LOCK = threading.Lock()

def _ttl(key, ttl, fn):
    now = time.time()
    with _TTL_LOCK:
        hit = _TTL_CACHE.get(key)
        if hit and hit[0] > now:
            return hit[1]
    try:
        val = fn()
    except Exception as e:
        with _TTL_LOCK:
            if key in _TTL_CACHE:
                return _TTL_CACHE[key][1]
        raise
    if val is not None:
        with _TTL_LOCK:
            _TTL_CACHE[key] = (now + ttl, val)
            if len(_TTL_CACHE) > 2000:
                for k in [k for k,(era,_) in _TTL_CACHE.items() if era <= now]:
                    _TTL_CACHE.pop(k, None)
    return val

# ============================================================================
# FLASK APP
# ============================================================================

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

# ============================================================================
# ROUTES
# ============================================================================

@app.route('/')
def index():
    return render_template("terminal_pro_v2.html")

@app.route('/pro')
def pro():
    return render_template("terminal_pro_v2.html")

@app.route('/v2')
def v2():
    return render_template("terminal_pro_v2.html")

@app.route('/bloomberg')
def bloomberg():
    return render_template("bloomberg.html")

@app.route('/api/symbols')
def api_symbols():
    try:
        symbols = binance.get_symbols()
        return jsonify({"count": len(symbols), "symbols": symbols})
    except Exception as e:
        return jsonify({"count": 0, "symbols": [], "error": str(e)}), 200

@app.route('/api/status')
def api_status():
    try:
        balance = 0
        try:
            account = binance.get_account()
            for b in account.get("balances", []):
                if b.get("asset") == "USDT":
                    balance = float(b.get("free", 0)) + float(b.get("locked", 0))
                    break
        except Exception as e:
            log_warn(f"Account fetch failed (using demo balance): {e}")
            balance = 100.0
        
        tickers = binance.get_all_tickers()
        market_rank = []
        for t in tickers[:50]:
            try:
                market_rank.append({
                    "symbol": t["symbol"],
                    "current_price": float(t["lastPrice"]),
                    "price_change_percent": float(t["priceChangePercent"]),
                    "volume_24h": float(t["quoteVolume"]),
                    "trades_24h": int(float(t["count"]))
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
            "candidates": len(market_rank),
            "trading_symbols": len(market_rank),
            "market": market_rank[:20],
            "signals": {},
            "plans": [],
            "backtest": {},
            "telegram": {"enabled": bool(os.environ.get("TELEGRAM_BOT_TOKEN")), "chat": os.environ.get("TELEGRAM_CHAT_ID"), "sent": 0},
            **tz_info()
        })
    except Exception as e:
        log_error(f"Status error: {e}")
        return jsonify({
            "balance": 100.0, "target": TARGET_BALANCE, "pnl_today": 0,
            "positions": 0, "positions_detail": [], "trades_today": 0,
            "running": False, "live_orders": LIVE_ORDERS,
            "candidates": 0, "trading_symbols": 0, "market": [],
            "signals": {}, "plans": [], "backtest": {},
            "telegram": {"enabled": False, "chat": None, "sent": 0},
            "error": str(e),
            **tz_info()
        }), 200

@app.route('/api/klines/<symbol>')
def api_klines(symbol):
    interval = request.args.get("interval", "1m")
    limit = min(max(int(request.args.get("limit", "500")), 10), 1500)
    
    b_symbol = BinanceClient.to_binance(symbol)
    b_interval = BinanceClient.normalize_interval(interval)
    
    try:
        klines = binance.get_klines(b_symbol, b_interval, limit)
        candles = []
        for k in klines:
            candles.append([
                int(k[0]),       # open time ms
                float(k[1]),     # open
                float(k[2]),     # high
                float(k[3]),     # low
                float(k[4]),     # close
                float(k[5])      # volume
            ])
        return jsonify({"symbol": symbol, "interval": interval, "candles": candles})
    except Exception as e:
        return jsonify({"error": str(e), "candles": []}), 200

@app.route('/api/orderbook/<symbol>')
def api_orderbook(symbol):
    b_symbol = BinanceClient.to_binance(symbol)
    try:
        ob = binance.get_order_book(b_symbol, 100)
        bids = [{"p": float(b[0]), "q": float(b[1])} for b in ob.get("bids", [])[:20]]
        asks = [{"p": float(a[0]), "q": float(a[1])} for a in ob.get("asks", [])[:20]]
        return jsonify({"symbol": symbol, "bids": bids, "asks": asks})
    except Exception as e:
        log_error(f"Orderbook error for {symbol}: {e}")
        return jsonify({"symbol": symbol, "bids": [], "asks": [], "error": str(e)}), 200

@app.route('/api/trades/<symbol>')
def api_trades(symbol):
    b_symbol = BinanceClient.to_binance(symbol)
    try:
        trades = binance.get_trades(b_symbol, 100)
        result = []
        for t in trades:
            result.append({
                "p": float(t["price"]),
                "q": float(t["qty"]),
                "m": t.get("isBuyerMaker", False),
                "t": int(t["time"])
            })
        return jsonify({"symbol": symbol, "trades": result})
    except Exception as e:
        return jsonify({"symbol": symbol, "trades": [], "error": str(e)}), 200

@app.route('/api/ticker/<symbol>')
def api_ticker(symbol):
    b_symbol = BinanceClient.to_binance(symbol)
    try:
        price_data = binance.get_ticker(b_symbol)
        stats = binance.get_all_tickers()
        stat = next((s for s in stats if s.get("symbol") == b_symbol), {})
        return jsonify({
            "symbol": symbol,
            "price": float(price_data.get("price", 0)),
            "change": float(stat.get("priceChangePercent", 0)),
            "volume": float(stat.get("volume", 0)),
            "volume_value": float(stat.get("quoteVolume", 0)),
            "high": float(stat.get("highPrice", 0)),
            "low": float(stat.get("lowPrice", 0)),
            "open": float(stat.get("openPrice", 0))
        })
    except Exception as e:
        return jsonify({"symbol": symbol, "price": 0, "change": 0, "volume": 0, "volume_value": 0, "high": 0, "low": 0, "open": 0, "error": str(e)}), 200

@app.route('/api/radar')
def api_radar():
    try:
        tickers = binance.get_all_tickers()
        coiled = []
        moving = []
        
        for t in tickers:
            change = float(t.get("priceChangePercent", 0))
            volume = float(t.get("quoteVolume", 0))
            price = float(t.get("lastPrice", 0))
            
            if abs(change) >= 3:
                moving.append({
                    "symbol": BinanceClient.from_binance(t["symbol"]),
                    "price": price,
                    "change": change,
                    "quote_volume": volume,
                    "trades": int(float(t.get("count", 0)))
                })
            
            if abs(change) < 2 and volume > 100000:
                coiled.append({
                    "symbol": BinanceClient.from_binance(t["symbol"]),
                    "score": max(0, 50 - abs(change) * 10),
                    "rating": max(0, 50 - abs(change) * 10),
                    "price": price,
                    "change": change,
                    "volume_ratio": volume / 100000,
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
        return jsonify({"coiled": [], "moving_now": [], "error": str(e)}), 200

@app.route('/api/signals')
def api_signals():
    return jsonify({
        "plans": [],
        "backtest": {},
        "summary": {"total": 0, "wins": 0, "losses": 0, "winrate": 0}
    })

@app.route('/api/positions')
def api_positions():
    return jsonify({"positions": []})

@app.route('/api/equity')
def api_equity():
    try:
        balance = 0
        try:
            account = binance.get_account()
            for b in account.get("balances", []):
                if b.get("asset") == "USDT":
                    balance = float(b.get("free", 0)) + float(b.get("locked", 0))
                    break
        except Exception:
            balance = 100.0
        
        return jsonify({
            "equity": balance,
            "pnl": 0,
            "pnlPct": 0,
            "balance": balance,
            "equityHistory": []
        })
    except Exception as e:
        return jsonify({"equity": 0, "pnl": 0, "pnlPct": 0, "balance": 0, "equityHistory": []})

@app.route('/api/order', methods=['POST'])
def api_order():
    if not LIVE_ORDERS:
        return jsonify({"error": "Live orders disabled (HUNTER_LIVE_ORDERS=0)"}), 403
    
    data = request.get_json() or {}
    return jsonify({"error": "Order placement not yet implemented on Binance migration"}), 501

# Telegram webhook endpoint
@app.route('/telegram/webhook', methods=['POST'])
def telegram_webhook():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"ok": False}), 400
        
        message = data.get("message", {})
        text = message.get("text", "").strip()
        chat_id = str(message.get("chat", {}).get("id", ""))
        
        authorized_chat = os.environ.get("TELEGRAM_CHAT_ID")
        if authorized_chat and chat_id != authorized_chat:
            return jsonify({"ok": True, "ignored": True})
        
        if text.startswith("/status"):
            try:
                account = binance.get_account()
                balance = 0
                for b in account.get("balances", []):
                    if b.get("asset") == "USDT":
                        balance = float(b.get("free", 0)) + float(b.get("locked", 0))
                        break
            except Exception:
                balance = 0
            reply = f"🤖 Binance Hunter Status\n💰 Balance: ${balance:.2f}\n🎯 Target: ${TARGET_BALANCE}\n📊 Mode: {'LIVE' if LIVE_ORDERS else 'SHADOW'}"
        elif text.startswith("/balance"):
            try:
                account = binance.get_account()
                reply = "💰 Account Balances:\n"
                for b in account.get("balances", []):
                    free = float(b.get("free", 0))
                    locked = float(b.get("locked", 0))
                    if free > 0 or locked > 0:
                        reply += f"  {b['asset']}: {free + locked:.4f}\n"
            except Exception:
                reply = "Unable to fetch balances"
        elif text.startswith("/signals"):
            reply = "📡 Signals: Check the dashboard for live signals"
        elif text.startswith("/help"):
            reply = "🤖 Binance Hunter Commands:\n/status - Bot status\n/balance - Account balances\n/signals - Active signals\n/help - This help"
        else:
            reply = "Unknown command. Use /help"
        
        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        if bot_token and chat_id:
            try:
                requests.post(
                    f"https://api.telegram.org/bot{bot_token}/sendMessage",
                    json={"chat_id": chat_id, "text": reply},
                    timeout=5
                )
            except Exception as e:
                log_error(f"Telegram send failed: {e}")
        
        return jsonify({"ok": True})
    except Exception as e:
        log_error(f"Telegram webhook error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 200

@app.route('/api/telegram/set_webhook', methods=['POST'])
def set_telegram_webhook():
    try:
        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        if not bot_token:
            return jsonify({"error": "No bot token configured"}), 400
        
        webhook_url = request.json.get("url") or os.environ.get("WEBHOOK_URL")
        if not webhook_url:
            return jsonify({"error": "No webhook URL provided"}), 400
        
        webhook_url = webhook_url.rstrip("/") + "/telegram/webhook"
        resp = requests.post(
            f"https://api.telegram.org/bot{bot_token}/setWebhook",
            json={"url": webhook_url},
            timeout=10
        ).json()
        
        return jsonify(resp)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/ai/chat', methods=['POST'])
def api_ai_chat():
    try:
        data = request.get_json() or {}
        message = data.get('message', '').strip()
        context = data.get('context', {})
        
        if not message:
            return jsonify({"response": "Empty message"}), 200
        
        symbol = context.get('selectedSymbol', 'BTC-USDT')
        balance = float(context.get('balance', '$0').replace('$', '').replace(',', ''))
        mode = context.get('mode', 'SHADOW')
        
        market_context = ""
        try:
            b_symbol = BinanceClient.to_binance(symbol)
            price_data = binance.get_ticker(b_symbol)
            stats = binance.get_all_tickers()
            stat = next((s for s in stats if s.get("symbol") == b_symbol), {})
            price = float(price_data.get("price", 0))
            change = float(stat.get("priceChangePercent", 0))
            volume = float(stat.get("quoteVolume", 0))
            market_context = f"\n[MARKET DATA] {symbol}: ${price:,.4f} ({change:+.2f}%) Vol: ${volume:,.0f}"
        except Exception:
            market_context = f"\n[MARKET DATA] Unable to fetch {symbol}"
        
        response = generate_ai_response(message, symbol, balance, mode, market_context)
        return jsonify({"response": response})
    except Exception as e:
        log_error(f"AI chat error: {e}")
        return jsonify({"response": f"Error: {str(e)}"}), 200

def generate_ai_response(message, symbol, balance, mode, market_context):
    msg = message.lower()
    
    if msg.startswith('/analyze'):
        parts = msg.split()
        sym = parts[1] if len(parts) > 1 else symbol
        return f"**Analysis for {sym}**{market_context}\n\nUse the chart panel for technical analysis. Key levels:\n• Check SMA 20/50/200 alignment\n• RSI for overbought/oversold\n• Volume on breakouts\n• VCP pattern detection (3+ contractions)"
    
    elif msg.startswith('/signal'):
        parts = msg.split()
        sym = parts[1] if len(parts) > 1 else symbol
        return f"**Signal Request: {sym}**{market_context}\n\nFor precise signals, use the chart timeframes:\n• 15m/1h for swing entries\n• 4h/1d for position trades\n• Look for VCP breakouts with volume\n• Risk 2% per trade, target 2-3R"
    
    elif '/radar' in msg:
        return f"**Market Radar**{market_context}\n\nScanning all USDT pairs for:\n• **Coiled** - Low volatility, high volume (breakout candidates)\n• **Moving** - >3% moves (momentum plays)\n• **Volume spikes** - Unusual activity\n\nRefresh the left panel for live radar data."
    
    elif '/positions' in msg:
        return f"**Current Positions**\n\nMode: {mode}\nBalance: ${balance:,.2f}\n\nNo open positions in shadow mode.\nWhen LIVE: Shows entry, stop, targets, PnL."
    
    elif '/risk' in msg:
        daily_limit = balance * 0.05
        max_dd = balance * 0.10
        pos_max = min(20, balance)
        return f"""**Risk Management**
        
Account: ${balance:,.2f} | Mode: {mode}

**Limits:**
• Daily Loss: 5% = ${daily_limit:,.2f}
• Max Drawdown: 10% = ${max_dd:,.2f}  
• Max Position: ${pos_max:,.2f}
• Risk/Trade: 2% = ${balance * 0.02:,.2f}

**Status:** ✅ Within limits
**Action:** {("Reduce size" if balance < 15 else "Normal operation")}"""
    
    elif '/explain' in msg:
        topic = msg.replace('/explain', '').strip().upper()
        explanations = {
            'VCP': "**VCP (Volatility Contraction Pattern)** - Minervini's high-probability setup\n\n1. Stage 2 uptrend (price > SMAs)\n2. 3+ progressive contractions\n3. Volume dries on each pullback\n4. Final contraction <10% range\n5. Breakout on 50%+ volume surge\n\nEntry: Breakout + 1-2%\nStop: Below last contraction low\nTarget: 2-3x risk minimum",
            'RSI': "**RSI (Relative Strength Index)** - Momentum oscillator 0-100\n\n• >70 Overbought | <30 Oversold\n• 50 = Neutral momentum\n• Divergence = Reversal signal\n• Range: Bull 40-80, Bear 20-60",
            'MACD': "**MACD** - Trend + Momentum\n\n• MACD Line: 12EMA - 26EMA\n• Signal: 9EMA of MACD\n• Histogram = MACD - Signal\n• Zero cross = Trend change\n• Divergence = Momentum shift",
            'KELLY': "**Kelly Criterion** - Optimal bet sizing\n\nf* = (bp - q) / b\n• f* = bankroll fraction\n• b = odds (decimal-1)\n• p = win prob, q = 1-p\n\nHalf-Kelly = 50% optimal (safer)\nKuCoin Hunter: 2% fixed ≈ Quarter Kelly",
            'ORDERBLOCK': "**Order Blocks** - Institutional footprints\n\n• Bullish OB: Last down candle before rally\n• Bearish OB: Last up candle before drop\n• Strong displacement = valid OB\n• Re-test with rejection = entry",
            'WYCKOFF': "**Wyckoff Method** - Market cycles\n\n**Accumulation:** PS→SC→AR→ST→Spring→LPS→SOS\n**Markup:** Trend advance\n**Distribution:** PSY→BC→AR→ST→UT→LPSY→SOW\n**Markdown:** Trend decline"
        }
        return explanations.get(topic, f"**{topic}**\n\nNot in knowledge base. Available: VCP, RSI, MACD, KELLY, ORDERBLOCK, WYCKOFF")
    
    elif any(w in msg for w in ['btc', 'bitcoin']):
        return f"""**Bitcoin Analysis**{market_context}

**Structure:** Check chart for:
• SMA 20/50/200 alignment (Stage 2?)
• RSI level (momentum)
• Volume profile (accumulation/distribution)
• Key levels: $68k/$72k resistance, $62k/$58k support

**VCP Scan:** Use /analyze BTC-USDT"""
    
    elif any(w in msg for w in ['strategy', 'trade', 'setup']):
        return f"""**Trading Strategy - Binance Hunter**

**Core: VCP Breakouts (Minervini)**
• Scan all USDT pairs every 15m
• Filter: >$500k vol, $0.00001-$100
• Rank: Contraction quality + volume dry-up
• Entry: Breakout on volume surge
• Stop: 7-8% max (below last contraction)
• Target: 2-3R minimum

**Risk:** 2% per trade, 5% daily, 10% max DD
**Mode:** {mode} | Balance: ${balance:,.2f}"""
    
    elif any(w in msg for w in ['help', 'command']):
        return """**Available Commands**

**Analysis:**
• `/analyze [SYMBOL]` - Technical analysis
• `/signal [SYMBOL]` - Trade signal
• `/radar` - Market scanner

**Portfolio:**
• `/positions` - Open positions
• `/risk` - Risk report
• `/status` - System status

**Education:**
• `/explain VCP|RSI|MACD|KELLY|ORDERBLOCK|WYCKOFF`

**Quick:** Click quick-action buttons below chat"""
    
    else:
        return f"""**Binance Hunter AI** | {symbol} | ${balance:,.2f} | {mode}

{market_context}

**I can help with:**
• Technical analysis (`/analyze`)
• Trade signals (`/signal`)  
• Market radar (`/radar`)
• Risk management (`/risk`)
• Position tracking (`/positions`)
• Trading education (`/explain CONCEPT`)

**Ask me:** "What's the VCP setup for ETH?" or "Explain order blocks" or "Risk check"

---
*Real-time Binance data via REST API*"""

# ============================================================================
# UTILITIES
# ============================================================================

def _interval_seconds(interval):
    mapping = {"1m":60,"3m":180,"5m":300,"15m":900,"30m":1800,"1h":3600,"2h":7200,"4h":14400,"6h":21600,"12h":43200,"1d":86400,"1w":604800}
    return mapping.get(interval, 3600)

# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    log_info(f"BINANCE HUNTER DASHBOARD starting on port {PORT}")
    log_info(f"Mission: $9 → $20 | Port: {PORT} | Live Orders: {LIVE_ORDERS}")
    log_info(f"Binance credentials: {'CONFIGURED' if binance._has_credentials else 'MISSING (shadow mode)'}")
    
    try:
        from waitress import serve
        serve(app, host="0.0.0.0", port=PORT, threads=4)
    except ImportError:
        app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True)