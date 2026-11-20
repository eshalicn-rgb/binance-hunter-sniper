"""Let Binance's own parameter validation tell us the endpoint's real shape.

Each attempt prints HTTP code + Binance error code/msg only. No secrets echoed.
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
IP = "128.234.16.108"


def post(path, params):
    params = dict(params)
    params["timestamp"] = int(time.time() * 1000)
    params["recvWindow"] = 60000
    qs = urllib.parse.urlencode(params)
    sig = hmac.new(secret.encode(), qs.encode(), hashlib.sha256).hexdigest()
    body = (qs + "&signature=" + sig).encode()
    req = urllib.request.Request(
        BASE + path, data=body, method="POST",
        headers={"X-MBX-APIKEY": key,
                 "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read().decode(errors="ignore")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="ignore")
    except Exception as e:
        return -1, repr(e)


def show(tag, st, body):
    try:
        j = json.loads(body)
        msg = j.get("msg", "")
        code = j.get("code", "")
        extra = ""
        if not msg:
            extra = " OK " + json.dumps(
                {k: v for k, v in j.items() if "ip" not in k.lower()})[:160]
        print(f"{tag:<58} HTTP {st}  code={code} msg={msg}{extra}")
    except Exception:
        print(f"{tag:<58} HTTP {st}  {body[:160]}")


P = "/sapi/v1/account/apiRestrictions/ipRestriction"
IPLIST = P + "/ipList"

ATTEMPTS = [
    ("ipRestrict=true, acctKey", P, {"accountApiKey": key, "ipRestrict": "true"}),
    ("ipRestrict=1, acctKey", P, {"accountApiKey": key, "ipRestrict": "1"}),
    ("ipRestrict=true, acctKey, ipAddress", P,
     {"accountApiKey": key, "ipRestrict": "true", "ipAddress": IP}),
    ("status=1, acctKey", P, {"accountApiKey": key, "status": "1"}),
    ("subAccountApiKey=key, status=1", P,
     {"subAccountApiKey": key, "status": "1", "ipAddress": IP}),
    ("acctKey + subAccountApiKey + status", P,
     {"accountApiKey": key, "subAccountApiKey": key, "status": "1"}),
    ("ipList: ipAddress + acctKey", IPLIST,
     {"accountApiKey": key, "ipAddress": IP}),
    ("ipList: status + ipAddress", IPLIST,
     {"status": "1", "ipAddress": IP, "accountApiKey": key}),
]

for tag, path, params in ATTEMPTS:
    st, body = post(path, params)
    show(tag, st, body)
    time.sleep(0.4)
