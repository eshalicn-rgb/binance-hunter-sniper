import html
import re
import signals as G
import notify as N

A = {"current_price": 100.0, "hunt_tf": "5m",
     "struct": {"price": 100.0, "atr": 1.2, "trigger": 100.8, "invalidation": 98.5,
                "target": 106.0, "tf": "5m", "state": "UPTREND", "score": 88},
     "ta": {"bias": "LONG", "score": 71}}
pl = G.plan(A, balance=9.28535651, risk_pct=0.10)

card = N.card_signal("ZECUSDT", "BUY", 84, "order-flow", vol=4.2, price=100.0,
                     tf="5m", mom=3.4, imb=0.71, ta_bias="LONG", ta_score=71,
                     flags=["trending", "altfins +3"], plan=pl)

pos = {"symbol": "ZECUSDT", "side": "BUY", "quantity": 0.0307, "entry_price": 100.0,
       "order_flow_score": 84, "volume_ratio": 4.2, "order_id": 123456, "plan": pl}
entry = N.card_entry(pos, A, entry_type="order-flow")

for name, raw in (("SIGNAL", card), ("ENTRY", entry)):
    txt = html.unescape(re.sub(r"<[^>]+>", "", raw))
    print("=" * 40, name)
    print(txt)

for label in ("ENTRY", "STOP", "TP1", "TP2", "TRAIL", "R:R"):
    assert label in html.unescape(re.sub(r"<[^>]+>", "", card)), label
print("CARD PLAN ROWS OK  rr=%s risk%%=%s" % (pl["rr"], pl["risk_pct"]))
