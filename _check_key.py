"""Diagnose the Binance API key's capability. Prints ONLY permission flags, never secrets or balances."""
import hashlib, hmac, json, os, time, urllib.parse, urllib.request

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

print("key_present   :", bool(key), "len=", len(key))
print("secret_present:", bool(secret), "len=", len(secret))
print("key_env_var   :", cfg.get("BINANCE_KEY_TYPE", "(none)"))

BASE = "https://api.binance.com"


def signed_get(path, params):
    params = dict(params)
    params["timestamp"] = int(time.time() * 1000)
    params.setdefault("recvWindow", 5000)
    qs = urllib.parse.urlencode(params)
    sig = hmac.new(secret.encode(), qs.encode(), hashlib.sha256).hexdigest()
    url = BASE + path + "?" + qs + "&signature=" + sig
    req = urllib.request.Request(url, headers={"X-MBX-APIKEY": key})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.status, json.loads(r.read().decode())


def try_call(label, path, params=None):
    try:
        st, body = signed_get(path, params or {})
        if isinstance(body, dict):
            keep = {k: body[k] for k in ("canTrade", "canWithdraw", "canDeposit",
                                         "accountType", "permissions", "uid",
                                         "makerCommission", "takerCommission",
                                         "updateTime") if k in body}
            print(f"{label:14}: HTTP {st} -> {json.dumps(keep)}")
        else:
            print(f"{label:14}: HTTP {st} -> {body}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="ignore")
        print(f"{label:14}: HTTP {e.code} -> {raw}")
    except Exception as e:
        print(f"{label:14}: ERR {e}")


# Read-only endpoints
try_call("ping", "/api/v3/ping")
try_call("account", "/api/v3/account")
try_call("apiRestrictions", "/sapi/v1/account/apiRestrictions")

# Harmless write probe: query an order that cannot exist (no funds committed).
try_call("read-order-probe", "/api/v3/order", {"symbol": "BTCUSDT", "orderId": 1})
