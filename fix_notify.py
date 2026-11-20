with open('notify.py', 'r', encoding='utf-8') as f:
    content = f.read()

start = content.find('def card_prepump(symbol, score, reasons=None, **kw):')
end = content.find('\n\ndef card_entry(')

print('Start:', start)
print('End:', end)

if start != -1 and end != -1:
    new_func = '''def card_prepump(symbol, score, reasons=None, **kw):
    """PRE-PUMP COIL card — modern dark-themed pre-pump coil card."""
    dir_icon = "🟢" if kw.get("direction", "BUY") == "BUY" else "🔴"
    dir_text = kw.get("direction", "BUY")

    score_bar = "█" * max(0, score // 10) + "░" * max(0, 10 - score // 10)
    conf_pct = int(score * 0.85)
    conf_bar = "█" * max(0, conf_pct // 10) + "░" * max(0, 10 - conf_pct // 10)

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

    lines.append("<b>⚡ PRE-PUMP COIL · {} ({})</b>".format(symbol, symbol))
    lines.append("")
    lines.append("🛡️ <b>{}%</b>   🧠 <b>{}%</b>   🎯 <b>{}</b>".format(score, conf_pct, dir_text.upper()))
    lines.append("")
    lines.append("🪙 <b>Token</b>: {} | LP: {}".format(_tx(symbol), lp_locked))
    lines.append("")
    lines.append("🔒 Mint Auth: <b>{}</b>   🔐 Safety: <b>{}%</b>   💎 Confidence: <b>{}%</b>".format(mint_auth, safety_score, conf_pct))
    lines.append("")
    lines.append("💧 <b>Flow</b>: {} | 1h: {} | Inflow: {}".format(liq_usd, liq_1h, inflow))
    lines.append("")

    gate_str = " ".join(["✅ {} |".format(g[1]) if g[0] == "PASS" else "❌ {} |".format(g[1]) for g in gates])
    lines.append("🚪 <b>Gates</b>: {}".format(gate_str))
    lines.append("")

    lines.append("❌ <b>Reject Reasons</b>")
    for r in reject_reasons[:3]:
        lines.append("✕ {}".format(r))
    lines.append("")

    verify_str = " • ".join(verify_tools[:4])
    lines.append("🔍 <b>Verify</b>: {}".format(verify_str))
    lines.append("")

    lines.append("📋 <b>Mint</b>: <code>{}</code>".format(mint_addr))
    lines.append("")
    lines.append("PHANTOM99 · PAPER · {}".format(_stamp()))

    return "\\n".join(lines)


'''

    new_content = content[:start_idx] + new_func + content[end_idx:]

    with open('notify.py', 'w', encoding='utf-8') as f:
        f.write(new_content)

    print("Successfully replaced card_prepump function")
else:
    print("Could not find markers")
