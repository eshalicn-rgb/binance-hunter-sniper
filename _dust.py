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

st, d = signed("POST", "/sapi/v1/asset/dust", {"asset": "BTC"})
print("DUST", st, json.dumps(d)[:400])
st2, acc = signed("GET", "/api/v3/account", {})
for a in ("USDT", "BTC", "BNB"):
    print(a, "free", next(b["free"] for b in acc["balances"] if b["asset"] == a))
