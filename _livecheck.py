import json, urllib.request

def get(path):
    with urllib.request.urlopen("http://127.0.0.1:3245" + path, timeout=20) as r:
        return json.load(r)

pp = get("/api/prepump")
print("=== /api/prepump keys:", list(pp.keys()))
for k, v in pp.items():
    if isinstance(v, list):
        print("   ", k, "-> list of", len(v))
        for row in v[:6]:
            print("        ", {kk: row.get(kk) for kk in
                  ("symbol", "direction", "bullish", "buy_ratio", "score", "tf")})
    else:
        print("   ", k, "->", v)

print("\n=== /api/signals (ledger) ===")
sg = get("/api/signals")
rows = sg if isinstance(sg, list) else (sg.get("signals") or sg.get("rows") or [])
print("rows:", len(rows))
for r in rows[-6:]:
    print("   ", r.get("symbol"), "side=", r.get("side"), "signal=", r.get("kind") or r.get("signal"),
          "tf=", r.get("tf"), "ts=", r.get("ts"))

print("\n=== /api/watchlist sample ===")
wl = get("/api/watchlist")
wrows = wl if isinstance(wl, list) else (wl.get("watchlist") or wl.get("rows") or [])
print("rows:", len(wrows))
for r in (wrows[:6] if isinstance(wrows, list) else []):
    print("   ", {kk: r.get(kk) for kk in ("symbol", "direction", "buy_ratio", "score", "vol", "tf")})
