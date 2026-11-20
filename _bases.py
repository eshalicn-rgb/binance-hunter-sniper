import json, urllib.request
with urllib.request.urlopen("https://api.binance.com/api/v3/exchangeInfo", timeout=25) as r:
    info = json.loads(r.read().decode())
rows = []
for s in info["symbols"]:
    if s.get("status") != "TRADING": continue
    if s.get("quoteAsset") != "USDT": continue
    b = s.get("baseAsset") or ""
    if len(b) >= 2 and b.endswith("B") and 1 <= len(b) - 1 <= 5:
        rows.append(b)
print(len(rows))
print(", ".join(sorted(rows)))
