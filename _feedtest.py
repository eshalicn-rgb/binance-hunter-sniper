#!/usr/bin/env python3
"""Verify every feed source after the fix, using feeds.py itself."""
import sys, time
sys.path.insert(0, r"G:\GrokMT5Bot\binance_hunter")
import feeds

h = feeds.FeedsHub()
t0 = time.time()
h.refresh_news()
h.refresh_headlines()
h.rebuild_catalysts(["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "TRXUSDT", "ZECUSDT"])
snap = h.snapshot()
print("headlines total:", len(h.headlines))
print("catalysts:", len(h.catalysts), "| trending:", len(h.trending), "| fng:", h.fng.get("label"))
print("-" * 74)
ok = 0
for s in snap["sources"]:
    ok += s["status"] == "ok"
    print(f"  {s['status']:8} {s['name']:34} {s['note'][:26]}")
print("-" * 74)
print(f"{ok}/{len(snap['sources'])} sources ok   ({time.time()-t0:.1f}s)")
# per-source headline counts
from collections import Counter
c = Counter(x.get("source") for x in h.headlines)
print("headline sources:", dict(c))
print("\nsample headlines:")
for x in h.headlines[:5]:
    print("  [%s/%s] %s" % (x.get("kind"), x.get("source"), x["title"][:76]))
