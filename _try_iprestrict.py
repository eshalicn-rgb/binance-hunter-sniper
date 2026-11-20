"""Attempt to flip IP restriction ON via the Binance SAPI endpoints.

Goal: get ipRestrict:true WITHOUT the interactive Google/Email 2FA challenge,
which would remove the key from Default Security Controls (DSC) scope and let
Spot & Margin trading be enabled.

Prints status codes + redacted bodies only. Never echoes key/secret.
"""
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


def call(method, path, params=None, signed=True):
    params = dict(params or {})
    if signed:
        params["timestamp"] = int(time.time() * 1000)
        params["recvWindow"] = 60000
        qs = urllib.parse.urlencode(params)
        sig = hmac.new(secret.encode(), qs.encode(), hashlib.sha256).hexdigest()
        qs = qs + "&signature=" + sig
    else:
        qs = urllib.parse.urlencode(params)
    url = BASE + path + ("?" + qs if qs else "")
    data = None
    if method == "POST":
        data = url.split("?", 1)[1].encode() if "?" in url else b""
        url = url.split("?", 1)[0]
    headers = {"X-MBX-APIKEY": key}
    if method == "POST":
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read().decode(errors="ignore")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="ignore")
    except Exception as e:
        return -1, repr(e)


def redact(body):
    try:
        j = json.loads(body)
    except Exception:
        return body[:300]
    out = {}
    for k, v in j.items():
        if "ip" in k.lower():
            out[k] = f"<{len(v)} entries>" if isinstance(v, list) else v
        else:
            out[k] = v
    return json.dumps(out)


STEPS = [
    # 1. legacy read of the IP-restriction sub-resource
    ("GET", "/sapi/v1/account/apiRestrictions/ipRestriction", None),
    # 2. same, but declaring our own key as accountApiKey (the -1102 fix)
    ("GET", "/sapi/v1/account/apiRestrictions/ipRestriction",
     {"accountApiKey": key}),
    # 3. legacy enable IP restriction, giving our single trusted IP
    ("POST", "/sapi/v1/account/apiRestrictions/ipRestriction",
     {"ipAddress": "128.234.16.108", "accountApiKey": key}),
    # 4. add the IP to the allow-list (some builds want this separately)
    ("POST", "/sapi/v1/account/apiRestrictions/ipRestriction/ipList",
     {"ipAddress": "128.234.16.108", "accountApiKey": key}),
]

for i, (method, path, params) in enumerate(STEPS, 1):
    st, body = call(method, path, params)
    print(f"[{i}] {method} {path} -> HTTP {st}")
    print("    ", redact(body)[:400])
    time.sleep(0.4)

print("\n--- authoritative re-read ---")
st, body = call("GET", "/sapi/v1/account/apiRestrictions")
print("apiRestrictions HTTP", st)
print(redact(body)[:600])
