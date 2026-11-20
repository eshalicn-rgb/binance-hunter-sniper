#!/usr/bin/env python3
"""
TELEGRAM PUSH CARDS — Binance Hunter trade telemetry.
Cards for: SIGNAL, PRE-PUMP COIL, ENTRY, EXIT, DAILY/WEEKLY RESULT, CATCH, ALERT.
Style: dark pro cards matching the Binance Hunter card spec.
"""
import os
import threading
import time
from datetime import datetime, timedelta, timezone

import requests

try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None

API = "https://api.telegram.org/bot%s/%s"

# ---- formatting helpers -----------------------------------------------------

def _tx(sym):
    """TradingView chart link for a Binance USDT symbol."""
    return ("<a href=\"https://www.tradingview.com/chart/?symbol=BINANCE" + "%3A" + sym + "\" target=\"_blank\">" + sym + "</a>")


def _px(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "\u2014"
    if v >= 1000:
        return "%.2f" % v
    if v >= 1:
        return "%.5f" % v
    if v >= 0.01:
        return "%.6f" % v
    return "%.8f" % v


def _pct(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "\u2014"
    return "%+.2f%%" % v


def _stamp(ts=None):
    d = datetime.fromtimestamp(ts or time.time())
    off = time.timezone if d.dst() == timedelta(0) else time.altzone
    total = -off
    sign = "+" if total >= 0 else "-"
    hh, mm = divmod(abs(total) // 3600, 60)
    tail = ("%s%02d" % (sign, hh)) if mm == 0 else ("%s%02d:%02d" % (sign, hh, mm))
    return "%s %s" % (d.strftime("%Y-%m-%d %H:%M:%S"), tail)


def _utc(ts=None):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(ts or time.time())) + " UTC"


def _money(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "\u2014"
    sign = "-" if v < 0 else ""
    return "%s$%.4f" % (sign, abs(v))


def dir_icon(d):
    return "🟢" if str(d).upper() == "BUY" else "🔴"


def score_bar(score, width=10):
    """Filled-bar score visual: ■■■■■□□□□□  70/100"""
    n = max(0, min(width, int(round(float(score) / 100 * width))))
    return "\u2588" * n + "\u2591" * (width - n) + "  <b>{}/100</b>".format(score)


# ---- card builders ----------------------------------------------------------

def card_signal(symbol, direction, score, source="scanner", **kw):
    """SIGNAL card — real Binance price and the timeframe the signal was hunted on."""
    lines = []
    lines.append("<b>◆ SIGNAL · {} · {}</b>".format(_tx(symbol), dir_icon(direction) + " " + str(direction).upper()))
    lines.append("")
    lines.append("⚡ <b>Confidence</b>: {}".format(score_bar(score)))
    px = kw.get("price")
    vol = kw.get("vol")
    mom = kw.get("mom")
    imb = kw.get("imb")
    parts = []
    if px is not None:
        parts.append("Price <b>{}</b>".format(_px(px)))
    if vol:
        parts.append("Vol <b>{}x</b>".format("%.2f" % float(vol)))
    if mom is not None:
        parts.append("5m <b>{}</b>".format(_pct(mom)))
    if imb is not None:
        parts.append("Imbal <b>{}</b>".format("%.2f" % float(imb)))
    if parts:
        lines.append("   ".join(parts))
    tb = kw.get("ta_bias")
    if tb:
        lines.append("🕯 <b>Fib/Gann</b>: {} {}".format(tb, kw.get("ta_score", "")))
    flags = kw.get("flags")
    if flags:
        flist = flags if isinstance(flags, (list, tuple)) else [flags]
        lines.append("🏁 <b>Flags</b>: {}".format(", ".join(flist)[:40]))
    struct = kw.get("structure")
    if struct:
        lines.append("🏗 <b>Struct</b>: {}".format(str(struct)[:22]))
    tf = kw.get("tf")
    if tf:
        lines.append("⏱ <b>TF</b>: {}".format(tf))
    pl = kw.get("plan") or {}
    if pl.get("entry") is not None:
        lines.append("💰 <b>Entry</b>: {}".format(_px(pl.get("entry"))))
        lines.append("🛑 <b>Stop</b>: {} (-{}%)".format(_px(pl.get("stop")), pl.get("risk_pct") or 0))
        if pl.get("tp1") is not None:
            lines.append("🎯 <b>TP</b>: {} · {} · {}".format(_px(pl.get("tp1")), _px(pl.get("tp2")), _px(pl.get("tp3"))))
        lines.append("⚖ <b>R:R</b>: {:.2f}".format(float(pl.get("rr") or 0)))
    lines.append("📡 <b>Source</b>: {}".format(source))
    lines.append("BINANCE HUNTER · PAPER · {}".format(_stamp()))
    return "\n".join(lines)


def card_btc_signal(symbol, score, direction, price, vol_ratio, mom, imbalance, spread, tf, **kw):
    """Premium BTC signal card — fires only when all finest filters pass."""
    conf = min(100, score)
    gates = kw.get("gates", [])
    gate_str = " ".join(["✅ {}".format(g) if g else "❌ {}".format(g) for g in gates]) if gates else "—"

    lines = []
    lines.append("<b>🔥 BTC SIGNAL · {} · {}</b>".format(_tx(symbol), dir_icon(direction) + " " + str(direction).upper()))
    lines.append("")
    lines.append("⚡ <b>{}/100</b>   {}   {}".format(score, score_bar(score), score_bar(score)))
    lines.append("")
    lines.append("💳 <b>Token</b>: {} | {}".format(_tx(symbol), _px(price)))
    lines.append("📈 <b>5m Move</b>: {}   📊 <b>Volume</b>: {:.2f}x   🛒 <b>Buy</b>: {:.0f}%".format(
        _pct(mom), vol_ratio, float(kw.get("buy_ratio", 0.5)) * 100))
    lines.append("")
    lines.append("🚪 <b>Gates</b>: {}".format(gate_str))
    lines.append("")
    lines.append("📉 <b>Imbalance</b>: {:.2f}   ● <b>Spread</b>: {:.3f}%   ⏱ <b>TF</b>: {}".format(
        imbalance, spread, tf))
    pl = kw.get("plan") or {}
    if pl.get("entry") is not None:
        lines.append("💰 <b>Entry</b>: {}   🛑 <b>Stop</b>: {} (-{}%)".format(
            _px(pl.get("entry")), _px(pl.get("stop")), pl.get("risk_pct") or 0))
        lines.append("🎯 <b>TP</b>: {} · {} · {}".format(
            _px(pl.get("tp1")), _px(pl.get("tp2")), _px(pl.get("tp3"))))
        lines.append("⚖ <b>R:R</b>: {:.2f}".format(float(pl.get("rr") or 0)))
        lines.append("")
    lines.append("BINANCE HUNTER · PAPER · {}".format(_stamp()))
    return "\n".join(lines)


def card_prepump(symbol, score, reasons=None, **kw):
    """PRE-PUMP COIL card — clean readable style: score, price, entry/tp/sl, gates, coil state."""
    dir_icon_ch = "🟢" if kw.get("direction", "BUY") == "BUY" else "🔴"
    dir_text = kw.get("direction", "BUY")

    price = kw.get("price")
    vol_ratio = kw.get("volume_ratio") or kw.get("vol")
    spread = kw.get("spread")
    bid_liq = kw.get("bid_liq")
    ask_liq = kw.get("ask_liq")
    coiled = bool(kw.get("coiled", score >= 40))
    gates = kw.get("gates", [])
    pl = kw.get("plan") or {}

    lines = []
    lines.append("<b>◈ PRE-PUMP COIL · {} · {}</b>".format(_tx(symbol), dir_icon_ch + " " + dir_text.upper()))
    lines.append("")
    lines.append("⚡ <b>Score {}/100</b>   {}   {} <b>{}</b>".format(
        score, score_bar(score), dir_icon_ch, dir_text.upper()))
    lines.append("")
    px = _px(price) if price else "\u2014"
    lines.append("💳 <b>Token</b>: {} | {}".format(_tx(symbol), px))
    lines.append("")
    flow = 0
    if bid_liq is not None and ask_liq is not None:
        flow = float(bid_liq) + float(ask_liq)
    lines.append("💹 <b>Flow</b>: ${:,.0f}   📉 <b>Spread</b>: {:.3f}%   📊 <b>Volume</b>: {:.2f}x".format(
        flow, spread or 0, vol_ratio or 0))
    lines.append("⏱ <b>5m Move</b>: {}   ⏳ <b>TF</b>: 1m".format(kw.get("mom_pct", "\u2014")))
    lines.append("")
    if pl.get("entry") is not None:
        lines.append("💰 <b>Plan</b>: Entry {} | Stop {} (-{}%)".format(
            _px(pl.get("entry")), _px(pl.get("stop")), pl.get("risk_pct") or 0))
        lines.append("🎯 <b>TP</b>: {} / {} / {}   ⚖ <b>R:R</b>: {:.2f}".format(
            _px(pl.get("tp1")), _px(pl.get("tp2")), _px(pl.get("tp3")), float(pl.get("rr") or 0)))
        lines.append("")
    if gates:
        gate_str = " ".join(["✅ {}".format(g[1]) if g[0] == "PASS" else "❌ {}".format(g[1]) for g in gates])
        lines.append("🚪 <b>Gates</b>: {}".format(gate_str))
        lines.append("")
    lines.append("{} <b>Coil</b>: {}".format("🔒" if coiled else "🔓", "COILED" if coiled else "BUILDING"))
    lines.append("")
    if reasons:
        lines.append("📝 " + " · ".join(str(r) for r in reasons[:4]))
        lines.append("")
    lines.append("BINANCE HUNTER · PAPER · {}".format(_stamp()))
    return "\n".join(lines)


def card_entry(pos, analysis=None, entry_type="order-flow"):
    a = analysis or {}
    lines = []
    lines.append("<b>\u25b2 ENTRY FILLED · BINANCE HUNTER · {} · {}</b>".format(
        _tx(pos.get("symbol", "")), dir_icon(pos.get("side", "")) + " " + str(pos.get("side", "")).upper()))
    lines.append("")
    lines.append("💰 <b>Price</b>: {}   📦 <b>Qty</b>: {}".format(
        _px(pos.get("entry_price")), pos.get("quantity", "")))
    notional = (pos.get("quantity") or 0) * (pos.get("entry_price") or 0)
    lines.append("💵 <b>Notional</b>: {}".format(_money(notional)))
    score = pos.get("order_flow_score")
    if score is not None:
        lines.append("⚡ <b>Score</b>: {}/100".format(score))
    vol = pos.get("volume_ratio")
    if vol:
        lines.append("📊 <b>Volume</b>: {:.2f}x".format(float(vol)))
    tf = a.get("hunt_tf") or (a.get("struct") or {}).get("tf")
    if tf:
        lines.append("⏱ <b>Timeframe</b>: {}".format(tf))
    lines.append("📡 <b>Entry path</b>: {}".format(entry_type))
    t = a.get("ta") or {}
    if t:
        lines.append("🕯 <b>Fib/Gann</b>: {} {}/100".format(t.get("bias", ""), t.get("score", "")))
    s = a.get("struct") or {}
    if s.get("state"):
        lines.append("🏗 <b>Struct</b>: {} {}".format(s.get("state", ""), s.get("score", "")))
    if a.get("feed_flags"):
        lines.append("🏁 <b>Flags</b>: {}".format(", ".join(a["feed_flags"])[:40]))
    if a.get("catalyst"):
        lines.append("📰 <b>Catalyst</b>: %g" % float(a["catalyst"]))
    p = pos.get("plan") or a.get("plan") or {}
    if p.get("entry") is not None:
        lines.append("💰 <b>Entry</b>: {}".format(_px(p.get("entry"))))
        lines.append("🛑 <b>Stop</b>: {} (-{}%)".format(_px(p.get("stop")), p.get("risk_pct")))
        lines.append("🎯 <b>TP1</b>: {}   🎯 <b>TP2</b>: {}".format(_px(p.get("tp1")), _px(p.get("tp2"))))
        lines.append("⚖ <b>R:R</b>: {:.2f}".format(float(p.get("rr") or 0)))
    lines.append("🆔 <b>Order ID</b>: {}".format(pos.get("order_id", "\u2014")))
    lines.append("📌 <b>Status</b>: {}".format(pos.get("status", "")))
    lines.append("BINANCE HUNTER · PAPER · {}".format(_stamp()))
    return "\n".join(lines)


def card_exit(pos, pnl, pnl_pct, reason):
    lines = []
    lines.append("<b>\u25bc POSITION CLOSED · BINANCE HUNTER</b>")
    lines.append("")
    lines.append("💱 <b>Symbol</b>: {}".format(pos.get("symbol", "")))
    lines.append("📐 <b>Side</b>: {}".format(pos.get("side", "")))
    lines.append("💰 <b>Entry</b>: {}".format(_px(pos.get("entry_price"))))
    lines.append("📦 <b>Qty</b>: {}".format(pos.get("quantity", "")))
    lines.append("🏁 <b>Exit price</b>: {}".format(_px(pos.get("exit_price", pos.get("current_price")))))
    lines.append("💸 <b>P&L</b>: %+.2f%%".format(pnl_pct))
    lines.append("⚖ <b>R:R</b>: {:.2f}".format(float(pos.get("rr") or 0)))
    lines.append("⚠ <b>Reason</b>: {}".format(reason))
    lines.append("BINANCE HUNTER · PAPER · {}".format(_stamp()))
    return "\n".join(lines)


def card_result(period, s):
    lines = []
    lines.append("<b>📊 %s RESULT · BINANCE HUNTER</b>" % period.upper())
    lines.append("")
    lines.append("💰 <b>Balance</b>: $%.2f" % s.get("balance", 0))
    lines.append("📈 <b>P&L</b>: %+.2f%%" % s.get("pnl_pct", 0))
    lines.append("🔢 <b>Trades</b>: %d" % s.get("trades", 0))
    lines.append("✅ <b>Wins</b>: %d" % s.get("wins", 0))
    lines.append("🎯 <b>Win rate</b>: %.1f%%" % (s.get("win_rate") or 0))
    lines.append("⚖ <b>Avg R</b>: {:.2f}".format(float(s.get("avg_r", 0) or 0)))
    lines.append("🏆 <b>Best</b>: %+.2f%%" % s.get("best", 0))
    lines.append("💥 <b>Worst</b>: %+.2f%%" % s.get("worst", 0))
    lines.append("BINANCE HUNTER · PAPER · {}".format(_stamp()))
    return "\n".join(lines)


def card_catch(symbol, action, **kw):
    lines = []
    lines.append("<b>📋 CATCH · BINANCE HUNTER</b>")
    lines.append("")
    lines.append("💱 <b>Symbol</b>: {}".format(_tx(symbol)))
    lines.append("⚡ <b>Action</b>: {}".format(action))
    if kw.get("price") is not None:
        lines.append("💰 <b>Price</b>: {}".format(_px(kw["price"])))
    if kw.get("amount") is not None:
        lines.append("💵 <b>Amount</b>: {}".format(kw["amount"]))
    lines.append("BINANCE HUNTER · PAPER · {}".format(_stamp()))
    return "\n".join(lines)


def card_alert(symbol, direction, price, alert_type, pct=None, note=None):
    lines = []
    lines.append("<b>🚨 ALERT · BINANCE HUNTER</b>")
    lines.append("")
    lines.append("💱 <b>Symbol</b>: {}".format(_tx(symbol)))
    lines.append("⚠ <b>Alert</b>: {}".format(alert_type))
    if price is not None:
        lines.append("💰 <b>Price</b>: {}".format(_px(price)))
    if pct is not None:
        lines.append("📉 <b>Trigger</b>: %.2f%%" % pct)
    if note:
        lines.append("📝 <b>Note</b>: {}".format(note))
    lines.append("BINANCE HUNTER · PAPER · {}".format(_stamp()))
    return "\n".join(lines)


def card_alert_armed(a):
    return card_alert(a["symbol"], a["alert_type"], a.get("price"), a.get("alert_type"),
                      pct=a.get("pct"), note=a.get("note"))


def card_alert_fired(a, price=None):
    return card_alert(a["symbol"], a["alert_type"], a.get("price") or price,
                      pct=a.get("pct"), note=a.get("note"))


def card_boot(port, balance, target, sources):
    lines = []
    lines.append("<b>🚀 HUNTER ONLINE · BINANCE HUNTER</b>")
    lines.append("")
    lines.append("🔌 <b>Port</b>: {}".format(port))
    lines.append("💰 <b>Balance</b>: $%.2f" % balance)
    lines.append("🎯 <b>Target</b>: $%.2f" % target)
    lines.append("BINANCE HUNTER · PAPER · {}".format(_stamp()))
    return "\n".join(lines)


# =============================================================================
# NOTIFIER CLASS — Telegram push transport
# ------------------------------------------------------------------

class Notifier:
    """Throttled Telegram push. Fail-closed: never breaks a hunting cycle."""

    def __init__(self, env_path=None):
        if env_path:
            self._load_env(env_path)
        self.bot = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        self.chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
        self.lock = threading.Lock()
        self.sent = 0
        self.last_error = ""
        self.last_sent = 0.0
        self._botname = ""
        self._botname_ts = 0.0
        # Pre-pump-only audience (extra chat IDs that receive PRE-PUMP cards only)
        pp = os.environ.get("TELEGRAM_PREPUMP_CHAT_ID", "").strip()
        self.prepump_chats = [c.strip() for c in pp.split(",") if c.strip()] if pp else []

    @staticmethod
    def _load_env(path):
        try:
            if os.path.exists(path):
                with open(path, "r") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            os.environ.setdefault(k.strip(), v.strip())
        except Exception:
            pass

    @property
    def enabled(self):
        return bool(self.bot and self.chat)

    def _call(self, method, payload, timeout=10):
        if not self.bot:
            self.last_error = "no bot token"
            return None
        try:
            r = requests.post(API % (self.bot, method), json=payload, timeout=timeout)
            j = r.json() if r.content else {}
            if not j.get("ok"):
                self.last_error = str(j.get("description", "HTTP %s" % r.status_code))[:120]
            return j
        except Exception as e:
            self.last_error = type(e).__name__
            return None

    def _call_raw(self, method, payload, timeout=10):
        return self._call(method, payload, timeout)

    def send(self, text, silent=False, extra=None):
        """Push one card. Fail-closed: never raises, never blocks the engine."""
        if not self.enabled:
            return False
        with self.lock:
            ok = self._send_to(self.chat, text, silent)
            for cid in (extra or []):
                try:
                    self._send_to(cid, text, True)
                except Exception:
                    pass
            return ok

    def _send_to(self, chat_id, text, silent=False):
        res = self._call("sendMessage", {
            "chat_id": chat_id, "text": text, "parse_mode": "HTML",
            "disable_web_page_preview": True, "disable_notification": bool(silent)})
        ok = bool((res or {}).get("ok"))
        if ok:
            self.sent += 1
            self.last_sent = time.time()
        return ok

    def send_prepump(self, text):
        """PRE-PUMP only fan-out: primary chat plus the pre-pump-only audience."""
        return self.send(text, silent=False, extra=self.prepump_chats)

    def status(self):
        return {
            "bot": self.bot,
            "chat": self.chat,
            "enabled": self.enabled,
            "last_error": self.last_error or "",
            "last_sent": self.last_sent,
            "sent": self.sent,
            "prepump_chats": self.prepump_chats,
        }

    def discover_chat(self):
        """Resolve chat id from the newest inbound update (user must message the bot once)."""
        j = self._call("getUpdates", {"limit": 20, "timeout": 0})
        best = None
        for u in (j or {}).get("result", []) or []:
            for key in ("message", "edited_message", "channel_post", "my_chat_member"):
                c = u.get(key) or {}
                ch = (c.get("chat") or {}).get("id")
                if ch:
                    best = ch
        if best:
            self.chat = str(best)
            self.enabled = True
        return bool(self.enabled)
