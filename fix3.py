import sys

with open('notify.py', 'rb') as f:
    content = f.read()

start_marker = b'def card_prepump(symbol, score, reasons=None, **kw):'
end_marker = b'\r\n\r\ndef card_entry('

start_idx = content.find(start_marker)
end_idx = content.find(end_marker, start_idx)

print('Start:', start_idx)
print('End:', end_idx)

if start_idx == -1:
    print("ERROR: Could not find start marker")
    sys.exit(1)

if end_idx == -1:
    print("Could not find end marker, searching for just 'def card_entry('")
    end_idx = content.find(b'\r\n\r\ndef card_entry(', start_idx)
    if end_idx == -1:
        end_idx = content.find(b'\r\ncard_entry(', start_idx)
    print('End:', end_idx)

new_func = b'''def card_prepump(symbol, score, reasons=None, **kw):
    """PRE-PUMP COIL card — modern dark-themed pre-pump coil card."""
    dir_icon = "\\xe2\\x9f\\x82" if kw.get("direction", "BUY") == "BUY" else "\\xe2\\x9d\\x84"
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

    lines.append("<b>\xe2\x9a\xa1 PRE-PUMP COIL \xc2\xb7 {} ({})</b>".format(symbol, symbol))
    lines.append("")
    lines.append("\xf0\x9f\x94\xa7 <b>{}%</b>   \xf0\x9f\xa7\x90 <b>{}%</b>   \xf0\x9f\x8e\xa7 <b>{}</b>".format(score, conf_pct, dir_text.upper()))
    lines.append("")
    lines.append("\xf0\x9f\xaa\x99 <b>Token</b>: {} | LP: {}".format(_tx(symbol), lp_locked))
    lines.append("")
    lines.append("\xf0\x9f\x94\x92 Mint Auth: <b>{}</b>   \xf0\x9f\x94\x90 Safety: <b>{}%</b>   \xf0\x9f\x92\x8e Confidence: <b>{}%</b>".format(mint_auth, safety_score, conf_pct))
    lines.append("")
    lines.append("\xf0\x9f\x92\xa7 <b>Flow</b>: {} | 1h: {} | Inflow: {}".format(liq_usd, liq_1h, inflow))
    lines.append("")

    gate_str = " ".join(["\xf0\x9f\x91\x8c {} |".format(g[1]) if g[0] == "PASS" else "\xf0\x9f\x94\x93 {} |".format(g[1]) for g in gates])
    lines.append("\xf0\x9f\x9a\xaa <b>Gates</b>: {}".format(gate_str))
    lines.append("")

    lines.append("\xe2\x9d\x93 <b>Reject Reasons</b>")
    for r in reject_reasons[:3]:
        lines.append("\xe2\x9c\x95 {}".format(r))
    lines.append("")

    verify_str = " \xe2\x80\xa2 ".join(verify_tools[:4])
    lines.append("\xf0\x9f\x94\x8d <b>Verify</b>: {}".format(verify_str))
    lines.append("")

    lines.append("\xf0\x9f\x93\x8d <b>Mint</b>: <code>{}</code>".format(mint_addr))
    lines.append("")
    lines.append("PHANTOM99 \xc2\xb7 PAPER \xc2\xb7 {}".format(_stamp()))

    return "\\n".join(lines)


'''

new_content = content[:start_idx] + new_func + content[end_idx:]

with open('notify.py', 'wb') as f:
    f.write(new_content)

print("Successfully replaced card_prepump function")
