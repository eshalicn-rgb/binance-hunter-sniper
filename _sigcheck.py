import json, urllib.request

def get(path):
    with urllib.request.urlopen("http://127.0.0.1:3245" + path, timeout=20) as r:
        return json.load(r)

s = get("/api/signals")
print("=== /api/signals keys ===")
for k, v in s.items():
    if isinstance(v, list):
        print("   ", k, "-> list", len(v))
        for row in v[:6]:
            print("       ", {kk: row.get(kk) for kk in
                  ("symbol", "side", "direction", "signal", "kind", "tf", "entry")})
    else:
        print("   ", k, "->", v)
