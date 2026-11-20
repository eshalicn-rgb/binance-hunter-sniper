#!/usr/bin/env python3
"""
TRIGGER LAB v2 — does the structural filter have an edge, and on WHICH timeframe?

v1 answered the 1m question: no. 105 combinations of entry rule x stop x target were
all negative, and entering on a timer with NO filter at all scored about the same as
the best filtered variant. That points at something more basic than the trigger:

    a 0.4% stop with a 0.2% round-trip fee means the FEE IS 50% OF THE RISK.

On a timeframe where the risk is bigger than the fee, that arithmetic stops dominating.
So this version sweeps the timeframe as well as the rule, and it splits every sample in
half — the first half is what you would have tuned on, the second half is the only one
that means anything. A variant that pays in the first half and not the second is a
curve-fit, not an edge.

Methodology is unchanged from v1 and deliberately harsh:
  CONTROL       every rule is measured against entering on a timer with no filter.
  NO LOOK-AHEAD read from bars up to i, entered at i's close, carried forward past i.
  PESSIMISTIC   a bar spanning both levels resolves as the STOP.
  FRICTION      taker fee paid twice, on every trade including the losers.
  EQUAL R:R     each stop is paired with 1R/2R/3R so a wide stop is not flattered.
  IS / OOS      every number is reported on both halves of the sample.
"""
import argparse
import json
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, ".")
import structure as S                       # noqa: E402

BARS = 1000
READ = 200
WARM = 140
HORIZON = 60
FEE = 0.20
STRIDE = 2

SYMS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "ADAUSDT", "SUIUSDT",
    "AVAXUSDT", "DOGEUSDT", "TIAUSDT", "ENAUSDT", "ZECUSDT", "GTCUSDT",
]
STOPS = [
    ("pct0.4", ("pct", 0.4)), ("pct1.0", ("pct", 1.0)), ("pct2.0", ("pct", 2.0)),
    ("pct4.0", ("pct", 4.0)),
    ("atr1.0", ("atr", 1.0)), ("atr1.5", ("atr", 1.5)),
    ("atr2.0", ("atr", 2.0)), ("atr3.0", ("atr", 3.0)),
]
TARGETS = [1.0, 2.0, 3.0]
ENTRIES = ["raw", "confirm", "hold2", "pullback", "control"]


def _f(x, d=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


def fetch(symbol, interval, limit=BARS):
    q = urllib.parse.urlencode({"symbol": symbol, "interval": interval, "limit": limit})
    url = "https://api.binance.com/api/v3/klines?" + q
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            if attempt == 2:
                print("  ! %s %s: %s" % (symbol, interval, e))
                return []
            time.sleep(1.5)
    return []


def build_events(kl, mid):
    """Candidates per bar. `mid` is the i of the first out-of-sample bar."""
    ev = []
    n = len(kl)
    i = WARM
    while i < n - HORIZON - 1:
        win = kl[max(0, i - READ + 1):i + 1]
        try:
            r = S.hunt("_", win, "1m")
        except Exception:
            r = None
        atr = _f((r or {}).get("atr"))
        price = _f(kl[i][4])
        if r and r.get("bullish") and atr > 0 and price > 0:
            trig, inv = _f(r.get("trigger")), _f(r.get("invalidation"))
            base = {"i": i, "entry": price, "atr": atr, "trig": trig, "inv": inv,
                    "score": r.get("score"), "oos": i >= mid}
            ev.append(dict(base, rule="raw"))
            if trig > 0 and price > trig:
                ev.append(dict(base, rule="confirm"))
                if i > 0 and _f(kl[i - 1][4]) > trig:
                    ev.append(dict(base, rule="hold2"))
            if trig > 0 and inv > 0 and inv < trig < price:
                for j in range(i + 1, min(n - 1, i + 1 + 20)):
                    if _f(kl[j][3]) <= trig:
                        ev.append(dict(base, rule="pullback", entry=trig, i=j,
                                       oos=j >= mid))
                        break
                    if _f(kl[j][2]) >= trig + atr:
                        break
        if (i - WARM) % STRIDE == 0 and atr > 0 and price > 0:
            ev.append({"i": i, "entry": price, "atr": atr, "trig": 0.0, "inv": 0.0,
                       "score": None, "oos": i >= mid, "rule": "control"})
        i += STRIDE
    return ev


def resolve(kl, e, kind, k, R):
    entry = e["entry"]
    stop_px = entry * (1 - k / 100.0) if kind == "pct" else entry - k * e["atr"]
    if stop_px <= 0 or stop_px >= entry:
        return None
    risk = (entry - stop_px) / entry
    tp_px = entry * (1 + risk * R)
    fwd = kl[e["i"] + 1:e["i"] + 1 + HORIZON]
    if not fwd:
        return None
    for b in fwd:
        if _f(b[3]) <= stop_px:
            return -(risk * 100.0) - FEE          # fee charged on losers too
        if _f(b[2]) >= tp_px:
            return (risk * R * 100.0) - FEE
    return (_f(fwd[-1][4]) - entry) / entry * 100.0 - FEE


def stats(outs):
    n = len(outs)
    if not n:
        return None
    w = [o for o in outs if o > 0]
    l = [o for o in outs if o < 0]
    gw, gl = sum(w), -sum(l)
    aw = gw / len(w) if w else 0.0
    al = gl / len(l) if l else 0.0
    return {"n": n, "wr": len(w) / n * 100.0,
            "need": (al / (aw + al) * 100.0) if (aw + al) > 0 else 100.0,
            "exp": sum(outs) / n, "pf": (gw / gl if gl else 0.0)}


def run_interval(interval, grab):
    data, events = {}, []
    for s in SYMS:
        kl = grab(s, interval)
        if not kl or len(kl) < WARM + HORIZON + 10:
            continue
        data[s] = kl
        ev = build_events(kl, mid=len(kl) // 2)
        for e in ev:
            e["symbol"] = s
        events += ev

    res = {}
    for rule in ENTRIES:
        for lab, (kind, k) in STOPS:
            for R in TARGETS:
                full, is_, oos = [], [], []
                for e in events:
                    if e["rule"] != rule:
                        continue
                    o = resolve(data[e["symbol"]], e, kind, k, R)
                    if o is None:
                        continue
                    full.append(o)
                    (oos if e["oos"] else is_).append(o)
                res[(rule, lab, R)] = (stats(full), stats(is_), stats(oos))
    return res, events, len(data)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--intervals", default="1m,5m,15m,1h")
    args = ap.parse_args()
    intervals = [x.strip() for x in args.intervals.split(",") if x.strip()]

    cache = {}

    def grab(sym, iv):
        key = (sym, iv)
        if key not in cache:
            cache[key] = (fetch(sym, iv), time.time())
        return cache[key][0]

    out = {}
    for iv in intervals:
        t0 = time.time()
        res, events, nsym = run_interval(iv, grab)
        if not res:
            print("== %s : no data ==" % iv)
            continue
        out[iv] = res
        print("=" * 104)
        print("TIMEFRAME %s   —   %d symbols, %d candidates, %d bars each"
              % (iv, nsym, len(events), BARS))
        print("=" * 104)
        print("%-9s %-16s %5s %8s %9s %9s %9s %10s" %
              ("rule", "best geometry", "n", "exp%", "in-sample", "out-samp", "wr/need", "pf"))
        for rule in ENTRIES:
            cand = [(res[(rule, lab, R)], lab, R) for lab, _ in STOPS for R in TARGETS
                    if (rule, lab, R) in res and res[(rule, lab, R)][0]
                    and res[(rule, lab, R)][0]["n"] >= 30]
            if not cand:
                continue
            (full, is_, oos), lab, R = max(cand, key=lambda x: x[0][0]["exp"])
            tag = " <-- NO FILTER" if rule == "control" else ""
            print("%-9s %-16s %5d %+8.3f %+9.3f %+9.3f %9s %10.2f%s" %
                  (rule, "%s/%gR" % (lab, R), full["n"], full["exp"],
                   is_["exp"] if is_ else 0.0, oos["exp"] if oos else 0.0,
                   "%.0f/%.0f" % (full["wr"], full["need"]), full["pf"], tag))
        # fair head-to-head at ONE geometry: whichever the control liked best
        ctrl = [(res[("control", lab, R)], lab, R) for lab, _ in STOPS for R in TARGETS
                if res.get(("control", lab, R)) and res[("control", lab, R)][0]
                and res[("control", lab, R)][0]["n"] >= 30]
        if ctrl:
            _, lab, R = max(ctrl, key=lambda x: x[0][0]["exp"])
            print("\n   head-to-head at the control's own best geometry (%s / %gR):" % (lab, R))
            base = res[("control", lab, R)][0]["exp"]
            for rule in ENTRIES:
                st = res.get((rule, lab, R))
                if st and st[0]:
                    d = st[0]["exp"] - base
                    print("      %-9s exp=%+.3f%%  vs control %s   oos=%+.3f%%"
                          % (rule, st[0]["exp"], ("%+.3f" % d) if rule != "control" else "   —  ",
                             st[2]["exp"] if st[2] else 0.0))
        print("   (%.0fs)\n" % (time.time() - t0))

    with open("_triggerlab2.json", "w") as fh:
        json.dump({iv: {("%s|%s|%g" % k): [a, b, c] for k, (a, b, c) in r.items()}
                   for iv, r in out.items()}, fh, indent=1)
    print("written _triggerlab2.json")


if __name__ == "__main__":
    main()
