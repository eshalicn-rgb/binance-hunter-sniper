import os
import signals as G

A = {"current_price": 100.0, "hunt_tf": "5m",
     "struct": {"price": 100.0, "atr": 1.2, "trigger": 100.8, "invalidation": 98.5,
                "target": 106.0, "tf": "5m"}}

p = G.plan(A, balance=9.28535651, risk_pct=0.10)
print("plan:", p)
assert p and p["valid"], p
assert p["entry"] == 100.8 and p["stop"] == 98.5, p
assert p["tp2"] == 106.0, p
print("rr", p["rr"], "risk%", p["risk_pct"], "qty", p["qty"], "notional", p["notional"])

# fallback: no structure at all
q = G.plan({"current_price": 2.0})
print("naked plan:", q)
assert q and q["entry"] == 2.0 and q["stop"] < 2.0, q

# cap: a wild invalidation far below must be clamped to the -5% envelope
w = G.plan({"current_price": 100.0, "struct": {"atr": 1.0, "invalidation": 50.0}})
print("capped stop:", w["stop"], w["stop_src"])
assert w["stop"] >= 95.0, w

led_path = os.path.join(os.path.dirname(__file__), "_sig_test.json")
if os.path.exists(led_path):
    os.remove(led_path)
led = G.SignalLedger(led_path)

# --- TP row: bars run straight into the plan's tp2 (106.0)
row = led.record("TESTUSDT", "BUY", 100.0, entry_type="order-flow", timeframe="1m",
                 score=80, kind="signal", plan=G.plan(A))
t0 = int(row["ts"]) * 1000
kl = [[t0 + i * 60000, px, px + 0.5, px - 0.5, px, 100]
      for i, px in enumerate([100.5, 101.5, 103.0, 106.5, 105.0])]
led.mark("TESTUSDT", kl)
print("TP row ->", row["status"], row["outcome"], "mfe", row["mfe_pct"])

# --- TRAIL row: arms at +1R (103.1) then gives back 1xATR (1.2)
row2 = led.record("TEST2USDT", "BUY", 100.0, entry_type="order-flow", timeframe="1m",
                  score=80, kind="signal", plan=G.plan(A))
t0 = (int(row2["ts"]) // 60 + 1) * 60000
kl2 = [[t0 + i * 60000, px, px + 0.4, px - 0.4, px, 100]
       for i, px in enumerate([103.3, 101.0, 100.9])]
led.mark("TEST2USDT", kl2)
print("TRAIL row ->", row2["status"], row2["outcome"])

s = led.summary()
print("summary:", {k: s[k] for k in ("total", "open", "closed", "tp", "sl", "trail", "timeout", "win_rate")})
print("open_plans:", [r["symbol"] for r in led.open_plans()])

# --- backtest_all over a trending series plus one we cannot fetch
def kl_for(sym):
    if sym == "MISSINGUSDT":
        return None
    out = []
    for i in range(220):
        px = 100.0 * (1 + 0.0035 * i) + 1.5 * ((i % 7) - 3)
        out.append([t0 + i * 60000, px, px * 1.004, px * 0.996, px, 100])
    return out

sweep = led.backtest_all(["AUSDT", "BUSDT", "MISSINGUSDT"], kl_for, stride=4, limit=5)
print("sweep:", {k: sweep.get(k) for k in ("symbols", "trades", "win_rate", "avg_ret", "profit_factor")},
      "skipped", sweep.get("skipped"))
print("ran:", [(r["symbol"], r["trades"], r["win_rate"], r["avg_ret"]) for r in sweep.get("ran", [])])

os.remove(led_path)
print("OK")
