import json, os

p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "signals.json")
d = json.load(open(p, encoding="utf-8"))
rows = d if isinstance(d, list) else d.get("rows", [])

print("rows:", len(rows))
for r in rows:
    print("-" * 70)
    print("%-10s kind=%-6s status=%-8s outcome=%s" % (
        r.get("symbol"), r.get("kind"), r.get("status"), r.get("outcome")))
    print("   entry=%s tf=%s bars=%s mfe=%s mae=%s last_pct=%s" % (
        r.get("entry"), r.get("timeframe"), r.get("bars"),
        r.get("mfe_pct"), r.get("mae_pct"), r.get("last_pct")))
    pl = r.get("plan") or {}
    print("   plan stop=%s tp1=%s tp2=%s tp3=%s arm=%s dist=%s rr=%s" % (
        pl.get("stop"), pl.get("tp1"), pl.get("tp2"), pl.get("tp3"),
        pl.get("trail_arm"), pl.get("trail_dist"), pl.get("rr")))
    print("   reasons=%s state=%s trigger=%s invalidation=%s" % (
        r.get("reasons"), r.get("state"), r.get("trigger"), r.get("invalidation")))
    if pl.get("stop") and r.get("entry"):
        e = float(r["entry"]); s = float(pl["stop"])
        print("   -> stop is %s entry  ((stop-entry)/entry*100 = %+.3f%%)" % (
            "BELOW" if s < e else "ABOVE", (s - e) / e * 100.0))
