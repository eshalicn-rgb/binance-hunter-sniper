import os
os.chdir('G:/GrokMT5Bot/binance_hunter')

with open('notify.py', 'r', encoding='utf-8') as f:
    content = f.read()

start_marker = 'def card_prepump(symbol, score, reasons=None, **kw):'
end_marker = '\r\n\r\ndef card_entry('

start_idx = content.find(start_marker)
end_idx = content.find(end_marker)

print('Start:', start_idx)
print('End:', end_idx)

if start_idx != -1 and end_idx != -1:
    new_func = '''def card_prepump(symbol, score, reasons=None, **kw):
    """PRE-PUMP COIL card — modern dark-themed pre-pump coil card."""
    dir_icon = "\u25c8" if kw.get("direction", "BUY") == "BUY" else "\u25c9"
    dir_text = kw.get("direction", "BUY")

    score_bar = "\\u2588" * max(0, score // 10) + "\\u2591" * max(0, 10 - score // 10)
    conf_pct = int(score * 0.85)
    conf_bar = "\\u2588" * max(0, conf_pct // 10) + "\\u2591" * max(0, 10 - conf_pct // 10)

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

    lines.append("<b>\u25c8 PRE-PUMP COIL \xc2\xb7 {} ({})</b>".format(symbol, symbol))
    lines.append("")
    lines.append("\u25a1 <b>{}%</b>   \U0001F4CA <b>{}%</b>   \U0001F50D <b>{}</b>".format(score, conf_pct, dir_text.upper()))
    lines.append("")
    lines.append("\U0001F4B3 <b>Token</b>: {} | LP: {}".format(_tx(symbol), lp_locked))
    lines.append("")
    lines.append("\u25cf Mint Auth: <b>{}</b>   \U0001F512 Safety: <b>{}%</b>   \U0001F48F Confidence: <b>{}%</b>".format(mint_auth, safety_score, conf_pct))
    lines.append("")
    lines.append("\U0001F4A7 <b>Flow</b>: {} | 1h: {} | Inflow: {}".format(liq_usd, liq_1h, inflow))
    lines.append("")

    gate_str = " ".join(["\u2705 {} |".format(g[1]) if g[0] == "PASS" else "\u274C {} |".format(g[1]) for g in gates])
    lines.append("\U0001F4A9 <b>Gates</b>: {}".format(gate_str))
    lines.append("")

    lines.append("\u2753 <b>Reject Reasons</b>")
    for r in reject_reasons[:3]:
        lines.append("\u2717 {}".format(r))
    lines.append("")

    verify_str = " \u2022 ".join(verify_tools[:4])
    lines.append("\U0001F52D <b>Verify</b>: {}".format(verify_str))
    lines.append("")

    lines.append("\U0001F4CD <b>Mint</b>: <code>{}</code>".format(mint_addr))
    lines.append("")
    lines.append("PHANTOM99 \xc2\xb7 PAPER \xc2\xb7 {}".format(_stamp()))

    return "\\n".join(lines)


'''

    new_content = content[:start_idx] + new_func + content[end_idx:]

    with open('notify.py', 'w', encoding='utf-8') as f:
        f.write(new_content)

    print("Successfully replaced card_prepump function")
else:
    print("Could not find markers")
    print("Start:", start_idx)
    print("End:", end_idx)
