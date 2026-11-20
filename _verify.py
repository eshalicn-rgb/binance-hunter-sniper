import json, urllib.request

B = "http://127.0.0.1:3245"

def get(path):
    with urllib.request.urlopen(B + path, timeout=25) as r:
        return json.load(r)

fails = []

# 1) ledger carries no SELL anywhere
s = get("/api/signals")
sell = []
for key in ("open_rows", "plans", "recent"):
    for r in (s.get(key) or []):
        d = str(r.get("direction") or r.get("side") or "").upper()
        if d == "SELL":
            sell.append((key, r.get("symbol"), d))
print("ledger total/open/closed :", s.get("total"), s.get("open"), s.get("closed"))
print("SELL rows in ledger view :", sell)
if sell:
    fails.append("ledger still shows SELL")

# 2) pre-pump radar is bullish only
pp = get("/api/prepump")
rows = pp.get("coiled") or []
nonbull = [r["symbol"] for r in rows if not r.get("bullish") or r.get("direction") != "BUY"]
print("prepump rows             :", len(rows), "| non-bullish:", nonbull)
print("prepump count_coiled     :", pp.get("count_coiled"), "| threshold:", pp.get("threshold"))
if nonbull:
    fails.append("prepump leaked a bearish coil")

# 3) engine identity + timezone
st = get("/api/status")
print("running                  :", st.get("running"))
print("tz                       :", st.get("tz"), st.get("tz_label"), st.get("tz_offset_str"))
print("balance                  :", st.get("balance"))
print("watchlist                :", len(st.get("watchlist") or []))
print("telegram sent            :", (st.get("telegram") or {}).get("sent"))
if st.get("tz") != "America/New_York":
    fails.append("timezone is not America/New_York")
if not st.get("running"):
    fails.append("engine not running")

print()
print("VERIFY:", "FAIL " + "; ".join(fails) if fails else "ALL CHECKS PASSED")
