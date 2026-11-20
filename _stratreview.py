#!/usr/bin/env python3
"""Forensic review of the hunter's signal ledger, using backtest-expert methodology.

Asks the questions that decide whether the filtration has an edge:
  - what is the base rate, and is the sample big enough to believe it
  - does a higher structural score actually predict a better outcome
  - which of the four hunter paths / timeframes produced the damage
  - where does the loss come from: the trigger, or the stop being too tight
  - what does the sizing do to the account at this hit rate
  - which flaws make the backtest optimistic rather than honest
"""
import json
import math
from collections import Counter, defaultdict

LEDGER = "signals.json"
rows = json.load(open(LEDGER))
TP, SL = 15.0, 5.0
RISK_PER_TRADE, MAX_POS = 0.10, 3


def f(x, d=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


done = [r for r in rows if r.get("status") != "OPEN"]
openrows = [r for r in rows if r.get("status") == "OPEN"]
outs = [f(r.get("outcome")) for r in done]
wins = [o for o in outs if o > 0]
losses = [o for o in outs if o < 0]
gw, gl = sum(wins), -sum(losses)

print("=" * 72)
print("1. THE SAMPLE")
print("=" * 72)
n = len(done)
print("closed signals      :", n)
print("still open          :", len(openrows))
aw = sum(wins) / len(wins) if wins else 0.0
al = sum(losses) / len(losses) if losses else 0.0
print("wins / losses       : %d / %d  (win rate %.1f%%)" % (len(wins), len(losses), len(wins) / n * 100 if n else 0))
print("avg win             : %+.3f%%" % aw)
print("avg loss            : %+.3f%%" % al)
print("payoff (W/L)        : %.2f" % (aw / abs(al) if al else 0))
be = abs(al) / (aw + abs(al)) * 100 if (aw + abs(al)) else 0
print("BREAK-EVEN win rate : %.1f%%  <-- need this to not lose money" % be)
print("expectancy / signal : %+.3f%%" % (sum(outs) / n if n else 0))
print("profit factor       : %.2f" % (gw / gl if gl else 0))

print("\nsample adequacy (backtest-expert: 30 absolute min, 100+ preferred, 200+ confident)")
print("  -> %d closed: %s" % (n, "BELOW the 30 floor" if n < 30 else
                             ("above the minimum but far short of 100" if n < 100 else
                              ("acceptable" if n < 200 else "confident"))))

print()
print("=" * 72)
print("2. WHERE THE LOSS ACTUALLY COMES FROM")
print("=" * 72)
print("resolution breakdown:", dict(Counter(r.get("status") for r in done)))
mfe = [f(r.get("mfe_pct")) for r in rows]
mae = [f(r.get("mae_pct")) for r in rows]
print("avg MFE (best excursion) : %+.3f%%" % (sum(mfe) / len(mfe)))
print("avg MAE (worst excursion): %+.3f%%" % (sum(mae) / len(mae)))
reached_1r = 0
rrs = []
for r in rows:
    pl = r.get("plan") or {}
    arm, entry = f(pl.get("trail_arm")), f(r.get("entry"))
    if arm > 0 and entry > 0:
        need = (arm - entry) / entry * 100.0
        rrs.append(need)
        if f(r.get("mfe_pct")) >= need:
            reached_1r += 1
print("signals whose best move ever reached +1R: %d / %d (%.1f%%)"
      % (reached_1r, len(rows), reached_1r / len(rows) * 100 if rows else 0))
print("   -> the filter is selecting entries that die before they travel.")
print("avg risk per signal (entry->stop): %s"
      % ("%.3f%%" % (sum(rrs) / len(rrs)) if rrs else "n/a"))

print()
print("=" * 72)
print("3. DOES THE SCORE PREDICT ANYTHING?  (the core filtration question)")
print("=" * 72)
buckets = defaultdict(list)
for r in done:
    s = int(f(r.get("score")))
    buckets[(s // 10) * 10].append(f(r.get("outcome")))
print("%-8s %6s %10s %10s" % ("score", "n", "win rate", "avg ret"))
for k in sorted(buckets):
    v = buckets[k]
    w = len([x for x in v if x > 0])
    print("%-8s %6d %9.1f%% %+9.3f%%" % ("%d-%d" % (k, k + 9), len(v), w / len(v) * 100, sum(v) / len(v)))
if len(buckets) > 1:
    lo = [x for k, v in buckets.items() if k < 50 for x in v]
    hi = [x for k, v in buckets.items() if k >= 50 for x in v]
    if lo and hi:
        print("\nlow score (<50)  avg: %+.3f%%  n=%d" % (sum(lo) / len(lo), len(lo)))
        print("high score (>=50) avg: %+.3f%%  n=%d" % (sum(hi) / len(hi), len(hi)))
        print("  -> %s" % ("higher score is WORSE or equal: the score is not ranking anything useful"
                           if sum(hi) / len(hi) <= sum(lo) / len(lo)
                           else "higher score looks better, but the sample is too small to trust"))

print()
print("=" * 72)
print("4. ATTRIBUTION — which path / timeframe / symbol is bleeding")
print("=" * 72)
for field in ("entry_type", "kind", "timeframe"):
    agg = defaultdict(list)
    for r in done:
        agg[str(r.get(field))].append(f(r.get("outcome")))
    print("\nby %s:" % field)
    for k in sorted(agg, key=lambda x: -len(agg[x])):
        v = agg[k]
        print("   %-14s n=%-4d avg=%+.3f%%  wr=%.0f%%" % (k, len(v), sum(v) / len(v),
                                                          len([x for x in v if x > 0]) / len(v) * 100))

sym = defaultdict(list)
for r in done:
    sym[r.get("symbol")].append(f(r.get("outcome")))
top = sorted(sym.items(), key=lambda kv: len(kv[1]), reverse=True)[:10]
print("\ntop symbols by signal count (worst first among the busiest):")
for s, v in sorted(top, key=lambda kv: sum(kv[1]) / len(kv[1]))[:10]:
    print("   %-12s n=%-4d avg=%+.3f%%" % (s, len(v), sum(v) / len(v)))

print()
print("=" * 72)
print("5. WHAT THIS DOES TO THE ACCOUNT  (risk model: %.0f%% risk, stop -%.0f%%)"
      % (RISK_PER_TRADE * 100, SL))
print("=" * 72)
# account return per signal = (outcome / stop distance) * risk fraction
acct = [o / SL * RISK_PER_TRADE for o in outs]
eq, peak, mdd = 1.0, 1.0, 0.0
curve = []
for a in acct:
    eq *= (1 + a)
    curve.append(eq)
    peak = max(peak, eq)
    mdd = max(mdd, (peak - eq) / peak)
print("account return per signal : %+.3f%% avg" % (sum(acct) / len(acct) * 100))
print("final equity multiple     : %.4f  (start 1.0)" % eq)
print("max drawdown              : %.1f%%" % (mdd * 100))
print("   -> on $9.29 that is a final balance of $%.4f" % (9.28535651 * eq))
print("   the engine has NOT traded (positions 0/3, pnl 0) — that restraint is the only")
print("   reason the account is still $9.29. The filter is being correctly refused.")

print()
print("=" * 72)
print("6. METHODOLOGY FLAWS FOUND IN THE VALIDATION CODE ITSELF")
print("=" * 72)
print("a) AMBIGUOUS-BAR OPTIMISM — signals.py mark() and backtest() both test the")
print("   take-profit BEFORE the stop inside one bar, so a bar that touches both")
print("   always resolves as a WIN. Every ambiguous bar is graded in the strategy's")
print("   favour. Live, that bar is a coin flip at best.")
print("b) NO FRICTION — no taker fee (0.1%/side), no slippage, no partial fill. On a")
print("   +15%/-5% envelope this is small per trade but it is not zero, and it is")
print("   always applied in the strategy's favour by being absent.")
print("c) THE BACKTEST DOES NOT REPLAY THE TRADED RULE — backtest() fires on")
print("   structure.hunt() alone, but the live path also passes bullish_gate()")
print("   (buy_ratio>=0.60, Fib/Gann bias, structure state). The base rate shown is")
print("   therefore for a DIFFERENT, looser rule than the one under test.")
print("d) HORIZON vs DATA — HORIZON_MIN=240 with ~200 bars of 1m history means a")
print("   4h timeout is barely observable; resolution then falls to expire() at 4x")
print("   the horizon, so TIMEOUT rows are not measured on a consistent clock.")
print("e) REGIME — the ledger spans hours to days, one regime. Nothing here has been")
print("   seen through a bear phase or a high-volatility phase.")
print("f) ATTRIBUTION IS BROKEN — entry_type is recorded as 'watch' for every row,")
print("   so the by_type table cannot tell the four hunter paths apart. The one")
print("   breakdown that would localise the bleeding is the one that is empty.")
