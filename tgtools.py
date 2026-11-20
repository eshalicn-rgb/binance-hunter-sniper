"""
TELEGRAM TOOLS — inbound command layer for the Binance Hunter bot.

notify.py only pushes. This module adds the other half: a daemon long-poll on
getUpdates, a read-only command dispatcher, and a reply path, so the bot can be
driven from the phone.

Hard rules
----------
* READ ONLY. Nothing in here can open, close, size or cancel anything. The only
  writer is Telegram itself (sending a reply) and the offset file.
* The bot token never appears in a log line, a reply, or a status payload.
* Every renderer is defensive: a missing attribute renders as "—", never raises.
* Fails closed. If Telegram is unreachable the loop backs off and keeps the
  Flask app untouched.

The same callables are exposed as a TOOLS registry so the AI CEO on 3245 can
answer with live numbers instead of guessing them.
"""

import json
import os
import time
import threading
import traceback

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
OFFSET_FILE = os.path.join(HERE, "tg_offset.json")
API = "https://api.telegram.org/bot%s/%s"

MAX_MSG = 3600          # Telegram hard limit is 4096; leave room for HTML tags
MIN_GAP = 0.6           # seconds between replies to the same chat
POLL_TIMEOUT = 25       # getUpdates long-poll seconds
BACKOFF = [2, 5, 10, 20, 30]

# plain words people actually type, mapped onto the real tools
ALIASES = {
    "s": "status", "st": "status", "stat": "status", "bal": "status",
    "balance": "status", "account": "status", "acct": "status",
    "pos": "positions", "position": "positions", "open": "positions",
    "p": "pnl", "profit": "pnl", "perf": "pnl", "results": "pnl",
    "sig": "signals", "signal": "signals", "plans": "signals", "plan": "signals",
    "coil": "prepump", "pre-pump": "prepump", "prepump": "prepump",
    "shortlist": "watch", "list": "watch", "coins": "watch", "symbols": "watch",
    "pairs": "watch", "wl": "watch",
    "leaderboard": "top", "rank": "top", "movers": "top",
    "px": "price", "q": "price", "quote": "price", "chart": "ta",
    "analysis": "ta", "tech": "ta",
    "l": "ledger", "stats": "ledger", "history": "ledger",
    "r": "risk", "guard": "risk", "breakers": "risk",
    "reg": "regime", "market": "regime",
    "funnel": "sweep", "scan": "sweep",
    "me": "id", "whoami": "id", "chat": "id",
    "cmds": "help", "commands": "help", "menu": "help", "?": "help",
}



# ─────────────────────────────────────────────────────────── formatting helpers
def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _m(v, dp=2):
    try:
        return f"{float(v):,.{dp}f}"
    except (TypeError, ValueError):
        return "—"


def _p(v, dp=2):
    try:
        return f"{float(v):+.{dp}f}%"
    except (TypeError, ValueError):
        return "—"


def _html(s):
    return s


def _rows(pairs, w=10):
    out = []
    for k, v in pairs:
        out.append(f"{str(k)[:w]:<{w}} {v}")
    return "\n".join(out)


def _pre(text):
    return "<pre>" + _esc(text) + "</pre>"


def _tbl(pairs, w=11, indent=" "):
    """Aligned two-column table, safe inside <pre> on a phone."""
    return "\n".join(f"{indent}{str(k):<{w}} {v}" for k, v in pairs)


def _get(obj, *path, default=None):
    """Safe attribute / key walk."""
    cur = obj
    for step in path:
        if cur is None:
            return default
        try:
            if isinstance(cur, dict):
                cur = cur.get(step, default)
            else:
                cur = getattr(cur, step, default)
        except Exception:
            return default
    return cur if cur is not None else default


def _strip_token(s):
    """Never let a token survive into a log / reply."""
    s = str(s)
    if "bot" in s and "/" in s:
        try:
            head, tail = s.split("bot", 1)
            if ":" in tail:
                rest = tail.split("/", 1)[1] if "/" in tail else ""
                return head + "bot<token>" + ("/" + rest if rest else "")
        except Exception:
            pass
    return s


# ─────────────────────────────────────────────────────────────────── the class
class TelegramTools(object):
    """Long-poll command surface for the hunter Telegram bot."""

    def __init__(self, hunter_src, notify):
        self.hunter = hunter_src
        self.notify = notify
        self.bot = getattr(notify, "bot", "") or ""
        self.owner = str(getattr(notify, "chat", "") or "")
        self.lock = threading.Lock()
        self.stop_flag = threading.Event()
        self.thread = None
        self.offset = self._load_offset()
        self.seen = 0
        self.handled = 0
        self.errors = 0
        self.last_cmd = ""
        self.last_cmd_ts = 0.0
        self.last_error = ""
        self.last_chat = {}
        self.started_ts = 0.0
        self.tools = self._build_tools()

    # ── plumbing ────────────────────────────────────────────────────────────
    def _load_offset(self):
        try:
            with open(OFFSET_FILE, "r", encoding="utf-8") as f:
                return int(json.load(f).get("offset", 0))
        except Exception:
            return 0

    def _save_offset(self):
        try:
            tmp = OFFSET_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"offset": self.offset, "ts": int(time.time())}, f)
            os.replace(tmp, OFFSET_FILE)
        except Exception:
            pass

    def _call(self, method, payload, timeout=12):
        """POST to Telegram. Returns parsed dict or None. Token never logged."""
        if not self.bot:
            self.last_error = "no token"
            return None
        try:
            r = requests.post(API % (self.bot, method), json=payload,
                              timeout=timeout)
            data = r.json()
            if not data.get("ok"):
                self.last_error = str(data.get("description", "telegram error"))[:160]
                return None
            return data
        except Exception as exc:
            self.last_error = type(exc).__name__
            return None

    def send(self, chat_id, text):
        """Send HTML text, chunked. Returns True if at least one chunk landed."""
        if not text:
            return False
        chat_id = str(chat_id or self.owner)
        if not chat_id:
            return False
        ok = False
        while text:
            chunk = text[:MAX_MSG]
            if len(text) > MAX_MSG:
                cut = chunk.rfind("\n", 0, MAX_MSG - 200)
                if cut > 400:
                    chunk = text[:cut]
            text = text[len(chunk):]
            res = self._call("sendMessage", {
                "chat_id": chat_id,
                "text": chunk,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            })
            ok = ok or bool(res)
            if text:
                time.sleep(0.15)
        return ok

    # ── rate limit ──────────────────────────────────────────────────────────
    def _gate(self, chat_id):
        now = time.time()
        last = self.last_chat.get(chat_id, 0.0)
        if now - last < MIN_GAP:
            time.sleep(MIN_GAP - (now - last))
        self.last_chat[chat_id] = time.time()

    # ── loop ────────────────────────────────────────────────────────────────
    def start(self):
        if self.thread and self.thread.is_alive():
            return False
        if not self.bot:
            return False
        self.stop_flag.clear()
        self.thread = threading.Thread(target=self._loop, name="tg-tools",
                                       daemon=True)
        self.thread.start()
        self.started_ts = time.time()
        return True

    def stop(self):
        self.stop_flag.set()

    def _loop(self):
        bad = 0
        while not self.stop_flag.is_set():
            try:
                res = self._call("getUpdates", {
                    "offset": self.offset,
                    "timeout": POLL_TIMEOUT,
                    "allowed_updates": ["message", "channel_post"],
                }, timeout=POLL_TIMEOUT + 15)
                if not res:
                    bad = min(bad + 1, len(BACKOFF) - 1)
                    self.errors += 1
                    self.stop_flag.wait(BACKOFF[bad])
                    continue
                bad = 0
                for upd in res.get("result", []):
                    self.offset = max(self.offset, int(upd.get("update_id", 0)) + 1)
                    self._save_offset()
                    self.seen += 1
                    msg = upd.get("message") or upd.get("channel_post") or {}
                    try:
                        self._handle(msg)
                    except Exception:
                        self.errors += 1
                        self.last_error = traceback.format_exc(limit=1).strip()[-160:]
            except Exception as exc:
                self.errors += 1
                self.last_error = type(exc).__name__
                self.stop_flag.wait(5)
        return

    def _handle(self, msg):
        text = (msg.get("text") or msg.get("caption") or "").strip()
        chat = msg.get("chat") or {}
        chat_id = str(chat.get("id", "") or "")
        if not text or not chat_id:
            return
        self._gate(chat_id)
        self.handled += 1
        reply = self.dispatch(text, chat_id=chat_id, who=msg.get("from") or {})
        if reply:
            self.send(chat_id, reply)

    # ── dispatch ────────────────────────────────────────────────────────────
    def dispatch(self, text, chat_id=None, who=None):
        """Route one line of text. Always returns a string (never raises)."""
        raw = text.strip()
        if not raw:
            return ""
        parts = raw.split()
        head = parts[0].lstrip("/")
        head = head.split("@")[0].lower()
        args = parts[1:]
        head = ALIASES.get(head, head)
        self.last_cmd = head
        self.last_cmd_ts = time.time()

        if head in ("start", "hello", "hi"):
            head = "help"
        tool = self.tools.get(head)
        if not tool:
            hints = self._fuzzy(head)
            tail = ("\n\nTry: " + ", ".join("/" + h for h in hints)) if hints else ""
            return ("Unknown tool <b>/" + _esc(head) + "</b>." + tail +
                    "\nSend /help for the full list.")
        try:
            return tool["fn"](args)
        except Exception:
            self.errors += 1
            self.last_error = traceback.format_exc(limit=1).strip()[-160:]
            return ("<b>/" + _esc(head) + "</b> failed on a data read.\n" +
                    _pre(self.last_error))

    def _fuzzy(self, name):
        """Up to three plausible tools for a typo."""
        hits = []
        for k in self.tools:
            if not name:
                break
            shared = len(set(k) & set(name))
            if k.startswith(name[:2]) or shared >= max(2, len(name) - 1):
                hits.append((shared, k))
        hits.sort(reverse=True)
        return [k for _, k in hits[:3]]

    # ── tool registry ───────────────────────────────────────────────────────
    def _build_tools(self):
        reg = {}
        for name, desc, args, fn in [
            ("help",     "list every tool",                       "",       self.t_help),
            ("status",   "balance, pnl, positions, regime, risk", "",       self.t_status),
            ("pnl",      "today + all-time ledger performance",    "",       self.t_pnl),
            ("positions", "open paper positions in detail",        "",       self.t_positions),
            ("signals",  "recent signals and live plans",          "",       self.t_signals),
            ("prepump",  "pre-pump coil candidates",               "",       self.t_prepump),
            ("top",      "top ranked symbols right now",           "[n]",    self.t_top),
            ("watch",    "watchlist / hunt candidates",            "",       self.t_watch),
            ("price",    "24h stats for a symbol",                 "SYMBOL", self.t_price),
            ("ta",       "1h RSI/EMA/ATR read on a symbol",        "SYMBOL", self.t_ta),
            ("alerts",   "armed and fired price alerts",           "",       self.t_alerts),
            ("ledger",   "exit mix and bucket win rates",          "",       self.t_ledger),
            ("risk",     "risk envelope and breakers",             "",       self.t_risk),
            ("regime",   "market regime gate",                     "",       self.t_regime),
            ("sweep",    "symbol sweep funnel counts",             "",       self.t_sweep),
            ("id",       "chat id + bot identity",                 "",       self.t_id),
            ("tools",    "machine-readable tool registry",         "",       self.t_tools),
        ]:
            reg[name] = {"name": name, "desc": desc, "args": args,
                         "fn": fn, "readonly": True}
        return reg

    # ── renderers ───────────────────────────────────────────────────────────
    def t_help(self, args):
        short = {
            "help": "this card", "status": "account + hunting",
            "pnl": "today / all-time", "positions": "open trades",
            "signals": "plans + recent", "prepump": "coil setups",
            "ledger": "exit mix, buckets", "risk": "breakers, limits",
            "regime": "market gate", "alerts": "armed levels",
            "watch": "shortlist coins", "top": "movers rank",
            "price": "24h quote", "ta": "rsi / ema / atr",
            "sweep": "funnel counts", "id": "chat + bot",
            "tools": "raw registry",
        }
        groups = (
            ("LIVE", ("status", "pnl", "positions", "signals", "prepump",
                      "ledger", "risk", "regime", "alerts")),
            ("MARKET", ("watch", "top", "price", "ta", "sweep")),
            ("NAV", ("id", "tools", "help")),
        )
        rule = "-" * 29
        out = ["HUNTER / COMMANDS", rule]
        for label, names in groups:
            pairs = []
            for n in names:
                t = self.tools.get(n)
                if not t:
                    continue
                use = n + (" " + t["args"] if t["args"] else "")
                pairs.append((use, short.get(n, t["desc"])[:18].ljust(18)))
            if not pairs:
                continue
            out.append(label)
            out.append(_tbl(pairs, w=12))
            out.append("")
        out.append(rule)
        out.append("nav  status / pnl / watch / signals")
        out.append("     top / price SYM / ta SYM / help")
        out.append("")
        out.append("shadow / read-only / no orders")
        return _pre("\n".join(out).rstrip())

    def t_status(self, args):
        h = self.hunter
        bal = _get(h, "balance", default=0.0)
        pnl = _get(h, "pnl_today", default=0.0)
        pos = _get(h, "positions", default={}) or {}
        running = bool(_get(h, "running", default=False))
        live = os.environ.get("HUNTER_LIVE_ORDERS", "0")
        risk = _get(h, "risk_snapshot", default=lambda: {})() or {}
        reg = _get(h, "regime")
        reg_snap = {}
        try:
            reg_snap = reg.snapshot() or {}
        except Exception:
            pass
        body = _rows([
            ("balance", "$" + _m(bal)),
            ("pnl today", "$" + _m(pnl) + "  (" + _p(_get(h, "pnl_today_pct", default=0)) + ")"),
            ("positions", str(len(pos))),
            ("trades", str(_get(h, "trades_today", default=0))),
            ("hunting", "YES" if running else "PAUSED"),
            ("orders", "SHADOW" if str(live) in ("0", "", "False") else "LIVE"),
            ("swept", str(_get(h, "swept_count", default=0))),
            ("candidates", str(_get(h, "candidates_count", default=0))),
            ("pre-pump", str(_get(h, "prepump_entries", default=0))),
            ("catalyst", str(_get(h, "catalyst_entries", default=0))),
        ])
        extra = ""
        if reg_snap:
            extra = "\n" + _pre(_rows([
                ("regime", str(reg_snap.get("zone", "—"))[:10]),
                ("score", _m(reg_snap.get("score"), 2)),
                ("stale", "YES" if reg_snap.get("stale") else "no"),
                ("guide", str(reg_snap.get("guidance", "—"))[:10]),
            ]))
        brk = ""
        if risk:
            okr = risk.get("ok", True)
            brk = "\n" + _pre(_rows([
                ("day pnl", _p(risk.get("day_pnl_pct", 0))),
                ("streak", f"{risk.get('loss_streak', 0)}/{risk.get('max_consec_losses', '—')}"),
                ("state", "OPEN" if okr else "BLOCKED"),
                ("reason", str(risk.get("halt_reason") or risk.get("reason") or "—")[:10]),
            ]))
        return _pre("HUNTER · STATUS\n" + body) + extra + brk

    def t_pnl(self, args):
        h = self.hunter
        led = _get(h, "ledger")
        s = {}
        try:
            s = led.summary() or {}
        except Exception:
            pass
        n = int(s.get("closed", 0) or 0)
        win = float(s.get("win_rate", 0) or 0)
        exp = float(s.get("expectancy", 0) or 0)
        pf = float(s.get("profit_factor", 0) or 0)
        body = _rows([
            ("today", "$" + _m(_get(h, "pnl_today", default=0))),
            ("balance", "$" + _m(_get(h, "balance", default=0))),
            ("closed", str(n)),
            ("win rate", f"{win:.1f}%"),
            ("expectancy", f"{exp:+.3f}R"),
            ("profit", f"{pf:.2f}"),
        ])
        return _pre("HUNTER · P&L\n" + body)

    def t_positions(self, args):
        pos = _get(self.hunter, "positions", default={}) or {}
        if not pos:
            return _pre("HUNTER · POSITIONS\n\nflat — no open paper position.")
        blocks = []
        for sym, p in list(pos.items())[:8]:
            p = p or {}
            blocks.append(_rows([
                (sym, ""),
                ("entry", _m(p.get("entry", p.get("entry_price")))),
                ("qty", _m(p.get("qty", p.get("qty_base")), 6)),
                ("sl", _m(p.get("sl", p.get("stop")))),
                ("tp", _m(p.get("tp", p.get("target")))),
                ("why", str(p.get("bucket", p.get("reason", "—")))[:10]),
            ]))
        return _pre("HUNTER · POSITIONS\n\n" + "\n\n".join(blocks))

    def t_signals(self, args):
        h = self.hunter
        led = _get(h, "ledger")
        plans, rows = [], []
        try:
            plans = led.open_plans() or []
        except Exception:
            pass
        try:
            rows = (led.recent(8) if hasattr(led, "recent") else []) or []
        except Exception:
            pass
        out = ["HUNTER · SIGNALS"]
        if plans:
            out.append("\nLIVE PLANS")
            for p in plans[:8]:
                out.append(_rows([
                    (str(p.get("symbol", "?"))[:10], str(p.get("bucket", ""))[:12]),
                    ("entry", _m(p.get("entry"))),
                    ("trail", _m(p.get("trail"))),
                    ("tp", _m(p.get("tp"))),
                    ("sl", _m(p.get("sl"))),
                    ("tf", str(p.get("tf", p.get("timeframe", "—")))),
                ]))
                out.append("")
        if rows:
            out.append("RECENT")
            for r in rows[:8]:
                out.append(_rows([
                    (str(r.get("symbol", "?"))[:10], str(r.get("outcome", ""))[:12]),
                    ("r", f"{float(r.get('r', 0) or 0):+.2f}R"),
                ]))
        if not plans and not rows:
            out.append("\nno signal rows yet.")
        return _pre("\n".join(out))

    def t_prepump(self, args):
        h = self.hunter
        cands = []
        for attr in ("prepump_rows", "prepump", "prepump_candidates"):
            v = getattr(h, attr, None)
            if isinstance(v, list) and v:
                cands = v
                break
        n = _get(h, "prepump_entries", default=0)
        out = ["PRE-PUMP COIL · HUNTER", ""]
        if cands:
            for c in cands[:10]:
                if isinstance(c, dict):
                    out.append(_rows([
                        (str(c.get("symbol", "?"))[:10], str(c.get("bucket", "coil"))[:12]),
                        ("score", _m(c.get("score"), 1)),
                        ("depth", "$" + _m(c.get("depth", 0), 0)),
                        ("imbal", _m(c.get("imbalance", c.get("imbal", 0)), 2)),
                    ]))
                    out.append("")
        else:
            out.append(f"no candidate row exposed in memory.")
        out.append(f"pre-pump entries today: {n}")
        return _pre("\n".join(out))

    def t_top(self, args):
        n = 10
        if args:
            try:
                n = max(3, min(20, int(args[0])))
            except ValueError:
                pass
        rank = _get(self.hunter, "market_rank", default=[]) or []
        if not rank:
            return _pre("HUNTER · TOP\n\nmarket rank is empty right now.")
        out = ["HUNTER · TOP " + str(n)]
        for i, r in enumerate(rank[:n], 1):
            if not isinstance(r, dict):
                continue
            out.append(_rows([
                (f"{i}.", str(r.get("symbol", "?"))[:10]),
                ("chg", _p(r.get("change", r.get("chg_pct", 0)))),
                ("vol", "$" + _m(r.get("quote_vol", r.get("volume", 0)), 0)),
            ]))
        return _pre("\n".join(out))

    def t_watch(self, args):
        wl = _get(self.hunter, "watchlist", default=[]) or []
        if not wl:
            return _pre("HUNTER · WATCH\n\nnothing on the watchlist.")
        out = ["HUNTER · WATCH"]
        for w in wl[:20]:
            if isinstance(w, dict):
                out.append(_rows([
                    (str(w.get("symbol", "?"))[:10], str(w.get("bucket", w.get("state", "")))[:12]),
                    ("score", _m(w.get("score"), 1)),
                ]))
            else:
                out.append("  " + str(w)[:24])
        return _pre("\n".join(out))

    # ── network reads (public Binance, no keys) ─────────────────────────────
    def _ticker(self, sym):
        r = requests.get("https://api.binance.com/api/v3/ticker/24hr",
                         params={"symbol": sym}, timeout=8)
        d = r.json()
        if "code" in d:
            return None
        return d

    def _klines(self, sym, interval="1h", limit=120):
        r = requests.get("https://api.binance.com/api/v3/klines",
                         params={"symbol": sym, "interval": interval,
                                 "limit": limit}, timeout=10)
        return r.json()

    def t_price(self, args):
        sym = (args[0] if args else "").upper()
        if not sym:
            return "Usage: <code>/price BTCUSDT</code>"
        try:
            d = self._ticker(sym)
        except Exception as exc:
            return _pre("price error: " + _strip_token(exc))
        if not d:
            return _pre(f"no market for {sym} — check the pair name.")
        return _pre("HUNTER · " + sym + "\n" + _rows([
            ("last", _m(d.get("lastPrice"))),
            ("24h", _p(d.get("priceChangePercent"))),
            ("high", _m(d.get("highPrice"))),
            ("low", _m(d.get("lowPrice"))),
            ("vol", "$" + _m(d.get("quoteVolume"), 0)),
            ("trades", _m(d.get("count"), 0)),
        ]))

    def t_ta(self, args):
        sym = (args[0] if args else "").upper()
        if not sym:
            return "Usage: <code>/ta BTCUSDT</code>"
        try:
            k = self._klines(sym)
            d = self._ticker(sym)
        except Exception as exc:
            return _pre("ta error: " + _strip_token(exc))
        if not isinstance(k, list) or len(k) < 60 or not d:
            return _pre(f"not enough history for {sym}.")
        close = [float(x[4]) for x in k]
        high = [float(x[2]) for x in k]
        low = [float(x[3]) for x in k]

        def ema(vals, n):
            kf = 2.0 / (n + 1)
            e = vals[0]
            for v in vals[1:]:
                e = v * kf + e * (1 - kf)
            return e

        def rsi(vals, n=14):
            gains, losses = [], []
            for i in range(1, len(vals)):
                ch = vals[i] - vals[i - 1]
                gains.append(max(ch, 0.0))
                losses.append(max(-ch, 0.0))
            ag = sum(gains[-n:]) / n
            al = sum(losses[-n:]) / n
            if al == 0:
                return 100.0
            return 100 - (100 / (1 + ag / al))

        atr = sum(max(high[i] - low[i], abs(high[i] - close[i - 1]),
                      abs(low[i] - close[i - 1]))
                  for i in range(len(k) - 14, len(k))) / 14
        px = close[-1]
        e20, e50 = ema(close, 20), ema(close, 50)
        body = _rows([
            ("last", _m(px)),
            ("rsi14", f"{rsi(close):.1f}"),
            ("ema20", _m(e20) + (" above" if px > e20 else " below")),
            ("ema50", _m(e50) + (" above" if px > e50 else " below")),
            ("atr14", _m(atr) + f"  ({100*atr/px:.2f}%)"),
            ("trend", "UP" if e20 > e50 and px > e20 else
                      "DOWN" if e20 < e50 and px < e20 else "CHOP"),
            ("24h", _p(d.get("priceChangePercent"))),
            ("vol", "$" + _m(d.get("quoteVolume"), 0)),
        ])
        return _pre("HUNTER · " + sym + " · 1H\n" + body)

    def t_alerts(self, args):
        path = os.path.join(HERE, "alerts.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = None
        if not data:
            return _pre("HUNTER · ALERTS\n\nnone armed.")
        rows = data if isinstance(data, list) else data.get("alerts", [])
        if not rows:
            return _pre("HUNTER · ALERTS\n\nnone armed.")
        out = ["HUNTER · ALERTS"]
        for a in rows[:12]:
            out.append(_rows([
                (str(a.get("symbol", "?"))[:10], str(a.get("kind", a.get("type", "")))[:10]),
                ("at", _m(a.get("price", a.get("level")))),
                ("state", str(a.get("state", "armed"))[:8]),
            ]))
        return _pre("\n".join(out))

    def t_ledger(self, args):
        led = _get(self.hunter, "ledger")
        s = {}
        try:
            s = led.summary() or {}
        except Exception:
            pass
        mix = [(k_, s.get(k_)) for k_ in ("tp", "trail", "sl", "timeout")
               if s.get(k_) is not None]
        buckets = s.get("by_type") or {}
        out = ["HUNTER · LEDGER", _rows([
            ("closed", str(s.get("closed", "—"))),
            ("win", f"{float(s.get('win_rate', 0) or 0):.1f}%"),
            ("exp", f"{float(s.get('expectancy', 0) or 0):+.3f}R"),
            ("pf", f"{float(s.get('profit_factor', 0) or 0):.2f}"),
            ("best/worst", f"{float(s.get('best', 0) or 0):+.1f} / {float(s.get('worst', 0) or 0):+.1f}R"),
        ])]
        if mix:
            out.append("\nEXIT MIX")
            for k_, v in mix:
                out.append(f"{str(k_)[:10]:<10} {v}")
        if buckets:
            out.append("\nBY TYPE")
            for k_, v in list(buckets.items())[:7]:
                if isinstance(v, dict):
                    out.append(f"{str(k_)[:10]:<10} {v.get('n', v.get('total', '?'))}x  "
                               f"{float(v.get('win_rate', 0) or 0):.1f}%")
                else:
                    out.append(f"{str(k_)[:10]:<10} {v}")
        return _pre("\n".join(out))

    def t_risk(self, args):
        fn = _get(self.hunter, "risk_snapshot")
        snap = {}
        try:
            snap = (fn() if callable(fn) else fn) or {}
        except Exception:
            pass
        if not snap:
            return _pre("HUNTER · RISK\n\nrisk snapshot unavailable.")
        out = ["HUNTER · RISK"]
        for k_, v in list(snap.items())[:14]:
            out.append(f"{str(k_)[:12]:<12} {v}")
        return _pre("\n".join(out))

    def t_regime(self, args):
        reg = _get(self.hunter, "regime")
        snap = {}
        try:
            snap = reg.snapshot() or {}
        except Exception:
            pass
        if not snap:
            return _pre("HUNTER · REGIME\n\ngate has not published yet.")
        out = ["HUNTER · REGIME"]
        for k_, v in list(snap.items())[:12]:
            out.append(f"{str(k_)[:12]:<12} {v}")
        return _pre("\n".join(out))

    def t_sweep(self, args):
        h = self.hunter
        return _pre("HUNTER · SWEEP FUNNEL\n" + _rows([
            ("swept", str(_get(h, "swept_count", default=0))),
            ("candidates", str(_get(h, "candidates_count", default=0))),
            ("trading", str(len(_get(h, "trading_set", default=[]) or []))),
            ("pegged", str(_get(h, "pegged_excluded", default=0))),
            ("dead", str(_get(h, "dead_excluded", default=0))),
            ("tokenised", str(_get(h, "tokenised_excluded", default=0))),
            ("sweep", str(getattr(h, "sweep", "—"))[:20]),
        ]))

    def t_id(self, args):
        who = ""
        try:
            who = self.notify.whoami() or ""
        except Exception:
            pass
        return _pre("HUNTER · IDENTITY\n" + _rows([
            ("bot", "@" + who if who else "—"),
            ("chat", self.owner or "—"),
            ("uptime", f"{(time.time()-self.started_ts)/60:.0f}m" if self.started_ts else "—"),
            ("seen", str(self.seen)),
            ("handled", str(self.handled)),
            ("errors", str(self.errors)),
        ]))

    def t_tools(self, args):
        out = ["HUNTER / TOOL REGISTRY", "-" * 29]
        for name in sorted(self.tools):
            t = self.tools[name]
            out.append(f"{name:<10} {t['args'] or '-':<7} {t['desc'][:16]}")
        out += ["", "keys: name / args / what", "nav  help for the table"]
        return _pre("\n".join(out))

    # ── status for /api/telegram/* ──────────────────────────────────────────
    def snapshot(self):
        return {
            "enabled": bool(self.bot),
            "owner": self.owner,
            "polling": bool(self.thread and self.thread.is_alive()),
            "seen": self.seen,
            "handled": self.handled,
            "errors": self.errors,
            "offset": self.offset,
            "last_cmd": self.last_cmd,
            "last_cmd_age": round(time.time() - self.last_cmd_ts, 1) if self.last_cmd_ts else None,
            "last_error": self.last_error,
            "uptime": round(time.time() - self.started_ts, 0) if self.started_ts else 0,
            "tools": sorted(self.tools),
        }

    def call(self, name, args=None):
        """Programmatic entry point — used by the AI CEO."""
        t = self.tools.get(str(name).lstrip("/").lower())
        if not t:
            return "unknown tool: " + str(name)
        try:
            return t["fn"](list(args or []))
        except Exception as exc:
            return "tool error: " + type(exc).__name__


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def start(hunter_src, notify):
    """Build + start the poller. Returns the instance (callable .stop())."""
    tools = TelegramTools(hunter_src, notify)
    tools.start()
    return tools
