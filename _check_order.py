"""Probe whether the Binance key can actually place orders WITHOUT placing one.
Uses POST /api/v3/order/test which validates+signs but never executes."""
import hashlib, hmac, json, os, time, urllib.parse, urllib.request, urllib.error

ENV = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
cfg = {}
with open(ENV, "r", encoding="utf-8", errors="ignore") as f:
    for line in f:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        cfg[k.strip()] = v.strip().strip('"').strip("'")

key = cfg.get("BINANCE_API_KEY", "")
secret = cfg.get("BINANCE_API_SECRET", "")
BASE = "https://api.binance.com"


def post_signed(path, params):
    params = dict(params)
    params["timestamp"] = int(time.time() * 1000)
    params.setdefault("recvWindow", 5000)
    qs = urllib.parse.urlencode(params)
    sig = hmac.new(secret.encode(), qs.encode(), hashlib.sha256).hexdigest()
    body = (qs + "&signature=" + sig).encode()
    req = urllib.request.Request(BASE + path, data=body, method="POST",
                                 headers={"X-MBX-APIKEY": key,
                                          "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="ignore")
    except Exception as e:
        return -1, str(e)


def public(path, params):
    from urllib.request import urlopen
    qs = urllib.parse.urlencode(params)
    with urlopen(BASE + path + "?" + qs, timeout=15) as r:
        return json.loads(r.read().decode())


def shape(symbol, usd=6.0):
    """Same filter shaping the engine uses (LOT_SIZE step, minQty, minNotional).
    Returns (qty_string, price). Proves the order carries a size Binance accepts."""
    from decimal import Decimal, ROUND_UP
    info = public("/api/v3/exchangeInfo", {"symbol": symbol})["symbols"][0]
    step, minq, minnot = Decimal("0.00000001"), Decimal(0), Decimal(0)
    for f in info["filters"]:
        t = f["filterType"]
        if t == "LOT_SIZE":
            step = Decimal(f["stepSize"])
            minq = Decimal(f["minQty"])
        elif t in ("NOTIONAL", "MIN_NOTIONAL"):
            minnot = max(minnot, Decimal(f.get("minNotional") or "0"))
    px = Decimal(str(public("/api/v3/ticker/price", {"symbol": symbol})["price"]))
    q = (Decimal(str(usd)) / px / step).to_integral_value(rounding=ROUND_UP) * step
    if minq and q < minq:
        q = (minq / step).to_integral_value(rounding=ROUND_UP) * step
    if minnot and q * px < minnot:
        q = (minnot / px / step).to_integral_value(rounding=ROUND_UP) * step
    s = format(q.normalize(), "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s, px


# 1) TEST order (never executes) — quote-sized, the floor the hunter uses
st, body = post_signed("/api/v3/order/test", {
    "symbol": "BTCUSDT", "side": "BUY", "type": "MARKET", "quoteOrderQty": 6,
})
print(f"order/test MARKET   : HTTP {st} -> {body}")

# 2) TEST limit order — filter-shaped so a -1013 here would be a real finding
qty, px = shape("XRPUSDT", 6.0)
st2, body2 = post_signed("/api/v3/order/test", {
    "symbol": "XRPUSDT", "side": "BUY", "type": "LIMIT",
    "timeInForce": "GTC", "quantity": qty, "price": f"{px:.4f}",
})
print(f"order/test LIMIT    : XRPUSDT qty={qty} @ {px} -> HTTP {st2} -> {body2}")

# 3) Real open-orders list (read, signed)
def get_signed(path, params):
    params = dict(params)
    params["timestamp"] = int(time.time() * 1000)
    qs = urllib.parse.urlencode(params)
    sig = hmac.new(secret.encode(), qs.encode(), hashlib.sha256).hexdigest()
    req = urllib.request.Request(BASE + path + "?" + qs + "&signature=" + sig,
                                 headers={"X-MBX-APIKEY": key})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="ignore")


st3, body3 = get_signed("/api/v3/openOrders", {})
print(f"openOrders          : HTTP {st3} -> {body3[:300]}")

# 4) Server public IP as Binance sees it
st4, body4 = get_signed("/sapi/v1/system/status", {})
print(f"system/status       : HTTP {st4} -> {body4[:200]}")
