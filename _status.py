import json, urllib.request, sys

def get(path):
    with urllib.request.urlopen("http://127.0.0.1:3245" + path, timeout=15) as r:
        return json.load(r)

try:
    s = get("/api/status")
except Exception as e:
    print("STATUS UNREACHABLE:", e)
    sys.exit(1)

print("running      :", s.get("running"))
print("tz           :", s.get("tz"), s.get("tz_label"), s.get("tz_offset_str"))
print("balance      :", s.get("balance"))
print("positions    :", len(s.get("positions") or []))
print("watchlist    :", len(s.get("watchlist") or []))
print("cycle        :", s.get("cycle"))
print("sources      :", s.get("sources_ok"), "/", s.get("sources_total"))
print("telegram     :", s.get("telegram"))

pp = get("/api/prepump")
coils = pp.get("coils") or pp.get("items") or []
print("\nprepump coils:", len(coils))
bad = [c for c in coils if c.get("bullish") is not True or c.get("direction") != "BUY"]
for c in coils[:8]:
    print("  ", c.get("symbol"), "dir=", c.get("direction"),
          "bullish=", c.get("bullish"), "buy_ratio=", c.get("buy_ratio"),
          "score=", c.get("score"))
print("NON-BULLISH COILS:" , len(bad))
