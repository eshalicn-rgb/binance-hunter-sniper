import hashlib, hmac, json, time, urllib.parse, urllib.request, urllib.error
from decimal import Decimal

BASE = "https://api.binance.com"
cfg = {}
for line in open(".env", encoding="utf-8", errors="ignore"):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1); cfg[k.strip()] = v.strip().strip('"').strip("'")
K, S = cfg["BINANCE_API_KEY"], cfg["BINANCE_API_SECRET"]

def signed(method, path, params):
    p = dict(params); p["timestamp"] = int(time.time()*1000); p["recvWindow"] = 5000
    qs = urllib.parse.urlencode(p)
    sig = hmac.new(S.encode(), qs.encode(), hashlib.sha256).hexdigest()
    if method == "POST":
        req = urllib.request.Request(BASE + path, data=(qs + "&signature=" + sig).encode(), headers={"X-MBX-APIKEY": K})
    else:
        req = urllib.request.Request(BASE + path + "?" + qs + "&signature=" + sig, headers={"X-MBX-APIKEY": K})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode(errors="ignore") or "{}")

st, acc = signed("GET", "/api/v3/account", {})
free = Decimal(next(b["free"] for b in acc["balances"] if b["asset"] == "BNB"))
px = Decimal(json.load(urllib.request.urlopen(BASE + "/api/v3/ticker/price?symbol=BNBUSDT", timeout=10))["price"])
print("BNB free", free, "@", px, "=", (free*px).quantize(Decimal("0.01")))
# step 0.001 -> sell 0.007 (largest step-valid, notional must clear 5.0)
q = Decimal("0.007")
print("sell notional", (q*px).quantize(Decimal("0.01")))
st2, sell = signed("POST", "/api/v3/order", {"symbol": "BNBUSDT", "side": "SELL", "type": "MARKET",
                                             "quantity": format(q, "f"), "newOrderRespType": "FULL"})
print("SELL", st2, {k: sell.get(k) for k in ("orderId", "status", "executedQty", "cummulativeQuoteQty")})
if st2 != 200: print("RAW", sell)
st3, acc = signed("GET", "/api/v3/account", {})
u = Decimal(next(b["free"] for b in acc["balances"] if b["asset"] == "USDT"))
b = Decimal(next(b["free"] for b in acc["balances"] if b["asset"] == "BNB"))
print("after: USDT", u, "| BNB", b, "| net worth $", (u + b*px).quantize(Decimal("0.01")))
