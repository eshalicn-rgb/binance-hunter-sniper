"""Raw dump of Binance key restrictions (the authoritative permission record).
Prints permission flags only; redacts any IP list."""
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


def get_signed(path, params=None):
    params = dict(params or {})
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


st, body = get_signed("/sapi/v1/account/apiRestrictions")
print("apiRestrictions HTTP", st)
try:
    j = json.loads(body)
    safe = {}
    for k, v in j.items():
        if "ip" in k.lower() and isinstance(v, list):
            safe[k] = f"<redacted: {len(v) if isinstance(v, list) else 'n/a'} entries>"
        else:
            safe[k] = v
    print(json.dumps(safe, indent=2))
except Exception:
    print(body[:500])

# Which IP does Binance see? (generic public IP echo)
try:
    req = urllib.request.Request("https://api.ipify.org?format=json")
    with urllib.request.urlopen(req, timeout=10) as r:
        print("\nOur public IP:", r.read().decode())
except Exception as e:
    print("\nIP lookup failed:", e)
