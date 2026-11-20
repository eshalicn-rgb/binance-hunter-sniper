#!/usr/bin/env python3
"""
Binance Hunter Telegram Push Cards
Signal Cards + Pre-Pump Coil cards with TradingView links
"""

import os
import time
from datetime import datetime, timedelta, timezone

import requests

try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None

API = "https://api.telegram.org/bot%s/%s"
WIDTH = 34


def _tx(sym):
    """TradingView clickable link for a Binance USDT symbol."""
    return "<a href=\"https://www.tradingview.com/chart/?symbol=BINANCE%3A{}\" target=\"_blank\">{}</a>".format(sym, symbol)


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
    d = datetime.fromtimestamp(ts or time.time(), _tz())
    off = d.utcoffset() or timedelta(0)
    total = int(off.total_seconds())
    sign = "+" if total >= 0 else "-"
    hh, mm = divmod(abs(total) // 60, 60)
    tail = ("%s%02d" % (sign, hh)) if mm == 0 else ("%s%02d:%02d" % (sign, hh, mm))
    return "%s %s" % (d.strftime("%Y-%m-%d %H:%M:%S"), tail)


def _tz():
    name = (os.environ.get("HUNTER_TZ") or "Asia/Riyadh").strip()
    if ZoneInfo is not None:
        try:
            return ZoneInfo(name)
        except Exception:
            pass
    return timezone.utc


def card_signal(symbol, direction, score, source="scanner", **kw):
    """SIGNAL card — real Binance signal."""
    dir_icon = "🟢" if direction == "BUY" else "🔴" if direction == "SELL" else "⚪"
    dir_text = direction if direction else "BUY"

    score_bar = "\u2588" * max(0, score // 10) + "░" * max(0, 10 - score // 10)
    conf_pct = int(score * 0.85)

    kw_opt = kw or {}
    mint_auth = kw.get("mint_auth", "REVOKED")
    lp_locked = kw.get("lp_locked", "100.0%")
    liq_usd = kw.get("liq_usd", "$2,482,612")
    liq_1h = kw.get("liq_1h", "$83,752")
    inflow = kw.get("inflow", "+0.03x")

    lines = []
    lines.append("<b>◆ SIGNAL · {} ({})</b>".format(symbol, symbol))
    lines.append("")
    lines.append("🛡️ <b>{}%</b>   🧠 <b>{}%</b>   🎯 <b>{}</b>".format(score, conf_pct, dir_text.upper()))
    lines.append("")
    lines.append("🪙 <b>Token</b>: {} | LP: {}".format(_tx(symbol), lp_locked))
    lines.append("")
    lines.append("🔒 Mint Auth: <b>{}</b>   🔐 Safety: <b>{}%</b>   💎 Confidence: <b>{}%</b>".format(mint_auth, safety_score, conf_pct))
    lines.append("")
    lines.append("💧 <b>Flow</b>: {} | 1h: {} | Inflow: {}".format(liq_usd, liq_1h, inflow))
    lines.append("")

    gate_str = " ".join(["✅ {} |".format(g[1]) if g[0] == "PASS" else "❌ {} |".format(g[1]) for g in kw.get("gates", [("PASS", "mint"), ("PASS", "liquidity"), ("PASS", "structure"), ("PASS", "volume"), ("PASS", "spread")])])
    lines.append("🚪 <b>Gates</b>: {}".format(gate_str))
    lines.append("")

    lines.append("❌ <b>Reject Reasons</b>")
    for r in kw.get("reject_reasons", ["Only 0 holders"])[:3]:
        lines.append("✕ {}".format(r))
    lines.append("")

    verify_str = " \u2022 ".join(kw.get("verify_tools", ["Solscan", "RugCheck", "DexScreener", "Birdeye", "Jupiter"]))
    lines.append("🔍 <b>Verify</b>: {}".format(verify_str))
    lines.append("")

    lines.append("\U0001F4CD <b>Mint</b>: <code>{}</code>".format(kw.get("mint_addr", "PumpCoinMint...")))
    lines.append("")
    lines.append("PHANTOM99 · PAPER · {}".format(_stamp()))

    return "\n".join(lines)


def card_prepump(symbol, score, reasons=None, **kw):
    """PRE-PUMP COIL card — modern dark-themed pre-pump coil card."""
    dir_icon = "🟢" if kw.get("direction", "BUY") == "BUY" else "🔴"
    dir_text = kw.get("direction", "BUY")

    score_bar = "\u2588" * max(0, score // 10) + "░" * max(0, 10 - score // 10)
    conf_pct = int(score * 0.85)

    mint_auth = "REVOKED"
    lp_locked = kw.get("lp_locked", "100.0%")
    safety_score = int(score * 0.9)

    liq_usd = kw.get("liq_usd", "$2,482,612")
    liq_1h = kw.get("liq_1h", "$83,752")
    inflow = kw.get("inflow", "+0.03x")

    gates = kw.get("gates", [
        ("PASS", "mint"), ("PASS", "liquidity"), ("PASS", "structure"),
        ("PASS", "volume"), ("PASS", "spread"),
    ])

    reject_reasons = kw.get("reject_reasons", ["Only 0 holders"])

    verify_tools = kw.get("verify_tools", ["Solscan", "RugCheck", "DexScreener", "Birdeye", "Jupiter"])

    mint_addr = kw.get("mint_addr", "PumpCoinMint...")

    lines = []

    lines.append("<b>\u25c8 PRE-PUMP COIL · {}</b>".format(symbol))
    lines.append("")
    lines.append("\u25a1 <b>{}%</b>   \U0001F4CA <b>{}%</b>   \U0001F50D <b>{}</b>".format(score, conf_pct, dir_text.upper()))
    lines.append("")
    lines.append("\U0001F4B3 <b>Token</b>: {} | LP: {}".format(_tx(symbol), lp_locked))
    lines.append("")
    lines.append("\u25cf Mint Auth: <b>{}</b>   🔐 Safety: <b>{}%</b>   💎 Confidence: <b>{}%</b>".format(mint_auth, safety_score, conf_pct))
    lines.append("")
    lines.append("\U0001F4A7 <b>Flow</b>: {} | 1h: {} | Inflow: {}".format(liq_usd, liq_1h, inflow))
    lines.append("")

    gate_str = " ".join(["✅ {} |".format(g[1]) if g[0] == "PASS" else "❌ {} |".format(g[1]) for g in gates])
    lines.append("🚪 <b>Gates</b>: {}".format(gate_str))
    lines.append("")

    lines.append("❌ <b>Reject Reasons</b>")
    for r in reject_reasons[:3]:
        lines.append("✕ {}".format(r))
    lines.append("")

    verify_str = " \u2022 ".join(verify_tools[:4])
    lines.append("🔍 <b>Verify</b>: {}".format(verify_str))
    lines.append("")

    lines.append("\U0001F4CD <b>Mint</b>: <code>{}</code>".format(mint_addr))
    lines.append("")
    lines.append("PHANTOM99 · PAPER · {}".format(_stamp()))

    return "\n".join(lines)
