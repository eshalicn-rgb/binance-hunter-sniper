#!/usr/bin/env python3
"""
TRIGGER LAB — find out whether any entry rule and stop actually has an edge.

The review found the live rule loses (WR 8.3%, expectancy -0.72%) and that a 0.4%
stop sits inside 1m noise. This lab answers the next question honestly: does ANY
combination of entry rule and stop survive real history, and does it beat the
no-filter control?

Design rules that make the answer trustworthy:

  CONTROL      every entry variant is compared against entering on a timer with no
               filter at all. If the control makes money, the "filter" added nothing
               and any apparent edge is just the market drifting up in the window.

  NO LOOK-AHEAD a candidate at bar i is read from klines[i-READ+1..i] only and entered
               at that bar's close. Forward bars are strictly after i.

  PESSIMISTIC  when one forward bar spans both the stop and the target, the STOP wins.
               Without tick data that is the honest half of the ambiguity.

  FRICTION     every trade pays the taker fee twice.

  SAME TARGET  variants are compared at equal reward:risk, so a wider stop is not
               flattered by geometry. Each stop is paired with 1R / 2R / 3R targets.

  REQUIRED WR  the win rate the variant must beat to break even at its own payoff.
               A win rate below that line is a loss no matter how good it looks.
"""
import json
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, ".")
import structure as S                       # noqa: E402

BARS = 1000          # 1m bars per symbol (one Binance call)
READ = 200           # bars the read sees, the way the engine reads it
WARM = 140           # bars before the first candidate
HORIZON = 60         # bars a trade is given to resolve before the clock closes it
FEE = 0.20           # taker fee paid twice, in %
STRIDE = 2           # evaluate every Nth bar

SYMS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "ADAUSDT", "SUIUSDT",
    "AVAXUSDT", "DOGEUSDT", "TIAUSDT", "ENAUSDT", "ZECUSDT", "GTCUSDT",
]

# stop models: ("label", ("pct"|"atr", k))
STOPS = [
    ("pct0.4 (live)", ("pct", 0.4)),
    ("pct1.0", ("pct", 1.0)),
    ("pct2.0", ("pct", 2.0)),
    ("atr1.0", ("atr", 1.0)),
    ("atr1.5", ("atr", 1.5)),
    ("atr2.0", ("atr", 2.0)),
    ("atr3.0", ("atr", 3.0)),
]
TARGETS = [1.0, 2.0, 3.0]
ENTRIES = ["raw", "confirm", "hold2", "pullback", "control"]


def _f(x, d=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


def klines(symbol, limit=BARS):
    q = urllib.parse.urlencode({"symbol": symbol, "interval": "1m", "limit": limit})
    url = "https://api.binance.com/api/v3/klines?" + q
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            if attempt == 2:
                print("  ! %s: %s" % (symbol, e))
                return []
            time.sleep(1.5)
    return []


def build_events(kl):
    """Walk the history and collect every candidate the entry rules would fire on.

    One pass, three rule variants recorded side by side, so the expensive structural
    read is done once per bar rather than once per variant.
    """
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
            trig = _f(r.get("trigger"))
            inv = _f(r.get("invalidation"))
            base = {"i": i, "entry": price, "atr": atr, "trig": trig, "inv": inv,
                    "score": r.get("score"), "state": r.get("state")}
            ev.append(dict(base, rule="raw"))
            # confirmed: this bar CLOSED above the level it broke
            if trig > 0 and price > trig:
                ev.append(dict(base, rule="confirm"))
                # held: the previous bar closed above it too
                if i > 0 and _f(kl[i - 1][4]) > trig:
                    ev.append(dict(base, rule="hold2"))
            # pullback: armed here, filled only if price comes back to the level
            if trig > 0 and inv > 0 and inv < trig < price:
                for j in range(i + 1, min(n - 1, i + 1 + 20)):
                    if _f(kl[j][3]) <= trig:                  # retest -> fill at the level
                        ev.append(dict(base, rule="pullback", entry=trig, i=j))
                        break
                    if _f(kl[j][2]) >= trig + atr:            # ran away -> missed
                        break
        # control: no filter at all, same bars, same geometry
        if (i - WARM) % STRIDE == 0 and atr > 0 and price > 0:
            ev.append({"i": i, "entry": price, "atr": atr, "trig": 0.0, "inv": 0.0,
                       "score": None, "state": None, "rule": "control"})
        i += STRIDE
    return ev


def resolve(kl, e, stop_kind, stop_k, R):
    """Carry one entry forward under one stop/target pair. Stop is tested first."""
    entry = e["entry"]
    if stop_kind == "pct":
        stop_px = entry * (1 - stop_k / 100.0)
    else:
        stop_px = entry - stop_k * e["atr"]
    if stop_px <= 0 or stop_px >= entry:
        return None
    risk = (entry - stop_px) / entry
    if risk <= 0:
        return None
    tp_px = entry * (1 + risk * R)
    fwd = kl[e["i"] + 1:e["i"] + 1 + HORIZON]
    if not fwd:
        return None
    for b in fwd:
        hi, lo = _f(b[2]), _f(b[3])
        if lo <= stop_px:
            return round(-stop_k if stop_kind == "pct" else -risk * 100.0 - FEE, 3)
        if hi >= tp_px:
            return round((risk * R * 100.0) - FEE, 3)
    last = _f(fwd[-1][4])
    return round((last - entry) / entry * 100.0 - FEE, 3)


def stats(outs):
    n = len(outs)
    if not n:
        return None
    w = [o for o in outs if o > 0]
    l = [o for o in outs if o < 0]
    gw, gl = sum(w), -sum(l)
    aw = gw / len(w) if w else 0.0
    al = gl / len(l) if l else 0.0
    wr = len(w) / n * 100.0
    need = (al / (aw + al) * 100.0) if (aw + al) > 0 else 100.0
    return {"n": n, "wr": wr, "need": need, "exp": sum(outs) / n, "pf": (gw / gl if gl else 0.0)}


def main():
    t0 = time.time()
    data, events = {}, []
    for s in SYMS:
        kl = klines(s)
        if not kl or len(kl) < WARM + HORIZON + 10:
            continue
        data[s] = kl
        ev = build_events(kl)
        for e in ev:
            e["symbol"] = s
        events += ev
        print("  %-11s bars=%d  candidates=%d  (raw=%d confirm=%d hold2=%d pullback=%d)"
              % (s, len(kl), len(ev),
                 sum(1 for x in ev if x["rule"] == "raw"),
                 sum(1 for x in ev if x["rule"] == "confirm"),
                 sum(1 for x in ev if x["rule"] == "hold2"),
                 sum(1 for x in ev if x["rule"] == "pullback")))

    print("\nread %d symbols, %d candidates in %.0fs\n" % (len(data), len(events), time.time() - t0))
    if not events:
        print("no candidates — nothing to test")
        return

    # ---- the headline: does any variant beat its own break-even line? -------------
    results = {}
    for rule in ENTRIES:
        for lab, (kind, k) in STOPS:
            for R in TARGETS:
                outs = []
                for e in events:
                    if e["rule"] != rule:
                        continue
                    o = resolve(data[e["symbol"]], e, kind, k, R)
                    if o is not None:
                        outs.append(o)
                st = stats(outs)
                if st:
                    results[(rule, lab, R)] = st

    for rule in ENTRIES:
        print("=" * 96)
        print("ENTRY: %s%s" % (rule, "   <-- NO FILTER, THE BASELINE" if rule == "control" else ""))
        print("=" * 96)
        head = "%-15s" % "stop"
        for R in TARGETS:
            head += "%22s" % ("%gR target" % R)
        print(head)
        print("%-15s" % "" + "".join("%22s" % "exp% / wr% / need%" for _ in TARGETS))
        for lab, _ in STOPS:
            row = "%-15s" % lab
            for R in TARGETS:
                st = results.get((rule, lab, R))
                if not st:
                    row += "%22s" % "-"
                else:
                    flag = "" if st["wr"] >= st["need"] + 3 else ""
                    row += "%22s" % ("%+.2f / %.0f / %.0f%s" % (st["exp"], st["wr"], st["need"], flag))
            print(row)
        # rank this rule's variants
        best = sorted(((results[(rule, lab, R)], lab, R) for lab, _ in STOPS for R in TARGETS
                       if (rule, lab, R) in results), key=lambda x: -x[0]["exp"])[:3]
        for st, lab, R in best:
            if st["n"] >= 30:
                print("   best: %-14s %gR  n=%-4d exp=%+.3f%%  wr=%.0f%% (need %.0f%%)  pf=%.2f"
                      % (lab, R, st["n"], st["exp"], st["wr"], st["need"], st["pf"]))
        print()

    with open("_triggerlab.json", "w") as fh:
        json.dump({("%s|%s|%g" % k): v for k, v in results.items()}, fh, indent=1)
    print("written _triggerlab.json   (%.0fs)" % (time.time() - t0))


if __name__ == "__main__":
    main()
