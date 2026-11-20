import json, urllib.request

def post(path, body):
    req = urllib.request.Request(
        "http://127.0.0.1:3245" + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)

def get(path):
    with urllib.request.urlopen("http://127.0.0.1:3245" + path, timeout=20) as r:
        return json.load(r)

cases = [
    ("CROSS UP + note, live price fallback",
     {"symbol": "ETHUSDT", "alert_type": "CROSS UP",
      "note": "reclaim of 2400 on the 15m, watching 2450 then 2520"}),
    ("CROSS DOWN + note + explicit price",
     {"symbol": "BTCUSDT", "alert_type": "CROSS DOWN", "price": 80850.5,
      "note": "lost the 4h trendline"}),
    ("late-October tag note",
     {"symbol": "SOLUSDT", "alert_type": "CROSS UP", "price": 141.02,
      "note": "break <resistance> & retest holding"}),
]

for name, body in cases:
    r = post("/api/alert", body)
    print("===", name)
    print("sent:", r.get("sent"), "| error:", r.get("error"))
    print(r.get("card") or "")
    print()

st = get("/api/status")
print("telegram sent:", (st.get("telegram") or {}).get("sent"))
