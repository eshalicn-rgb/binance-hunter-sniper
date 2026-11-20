#!/usr/bin/env python3
"""
MARKET STRUCTURE · VOLUME · TIME  —  the real structural read behind every signal.

Pure functions over klines. No network, no keys, no state. Anything that cannot be
measured returns None instead of inventing a level or a pattern.

Three modules, then one alignment:

STRUCTURE
    swing sequence labelled HH / HL / LH / LL straight off fractal pivots
    trend state      UPTREND / DOWNTREND / RANGE   (from the last two labels)
    BOS              break of structure — the last close taking out the most
                     recent swing high (bullish) or swing low (bearish)
    CHoCH            change of character — the first BOS against the trend
    each break is volume-checked against the 20-bar baseline

VOLUME PROFILE
    volume-at-price histogram over the window
    POC (point of control) · value area high / low at 70%
    where price sits: above / inside / below the value area

TIME ALGORITHM
    session of the last bar (Asia / London / New York / Late)
    leg symmetry — the current leg's bar count against the previous leg's
                    (Gann's 1.0 / 1.618 / 2.618 time relations)
    Gann time cycles counted from the last pivot

ALIGNMENT
    structure direction × volume confirmation × time due. When all three agree the
    read is "aligned" and the signal is worth acting on. When they disagree the
    opposition is named and the signal is refused — that is the whole point.

The hunted timeframe is always carried on the result as `timeframe`, so a signal
can say which timeframe it was actually found on.
"""
import math

# reuse the pivot / ATR primitives so structure and Fib/Gann never disagree
try:
    import ta
except Exception:                                    # pragma: no cover
    ta = None

TIME_CYCLES = (30, 45, 60, 90, 144, 180, 270, 360)
TIME_TOL = 3                 # bars either side of a Gann cycle that counts as "due"
STRUCT_MIN = 62              # alignment score at or above this is an actionable bullish read
CONFLICT_MIN = 55            # a structural cluster at or above this blocks the opposite way


def _f(x, d=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


# ---------------------------------------------------------------------------
# shared primitives (kept local so this module stands on its own)
# ---------------------------------------------------------------------------
def _pivots(klines, lb=3):
    if ta is not None:
        return ta.pivots(klines, lb)
    highs, lows = [], []
    n = len(klines)
    for i in range(lb, n - lb):
        h, l = _f(klines[i][2]), _f(klines[i][3])
        win = klines[i - lb:i + lb + 1]
        if h >= max(_f(k[2]) for k in win):
            highs.append((i, h))
        if l <= min(_f(k[3]) for k in win):
            lows.append((i, l))
    return highs, lows


def _atr(klines, n=14):
    if ta is not None:
        return ta.atr(klines, n)
    if len(klines) < 2:
        return 0.0
    trs = []
    for i in range(1, len(klines)):
        h, l, pc = _f(klines[i][2]), _f(klines[i][3]), _f(klines[i - 1][4])
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return (sum(trs[-n:]) / len(trs[-n:])) if trs else 0.0


def _vol_avg(klines, n=20, skip=1):
    """Baseline bar volume, ignoring the still-forming bar."""
    vols = [_f(b[5]) for b in (klines[:-skip] if skip else klines)]
    tail = vols[-n:]
    return (sum(tail) / len(tail)) if tail else 0.0


def resample(klines, factor):
    """Aggregate 1m bars into `factor`-minute bars. Used to build the TF ladder
    without spending a single extra REST call."""
    if factor <= 1 or not klines:
        return list(klines)
    out = []
    bucket = []
    for bar in klines:
        bucket.append(bar)
        if len(bucket) == factor:
            out.append(_merge(bucket))
            bucket = []
    if bucket and len(bucket) >= max(2, factor // 2):   # keep a mostly-formed tail
        out.append(_merge(bucket))
    return out


def _merge(bars):
    o = _f(bars[0][1])
    h = max(_f(b[2]) for b in bars)
    l = min(_f(b[3]) for b in bars)
    c = _f(bars[-1][4])
    v = sum(_f(b[5]) for b in bars)
    qv = sum(_f(b[7]) for b in bars) if len(bars[0]) > 7 else v
    n = sum(int(_f(b[8])) for b in bars) if len(bars[0]) > 8 else len(bars)
    return [bars[0][0], o, h, l, c, v, bars[-1][6], qv, n]


# ---------------------------------------------------------------------------
# 1. STRUCTURE
# ---------------------------------------------------------------------------
def structure(klines, lb=3):
    """Label the swing sequence and report the last break of structure."""
    if not klines or len(klines) < 20:
        return None
    highs, lows = _pivots(klines, lb)
    if len(highs) < 2 or len(lows) < 2:
        return None

    seq = sorted([(i, p, "H") for i, p in highs] + [(i, p, "L") for i, p in lows])
    alt = []
    for i, p, k in seq:
        if alt and alt[-1][2] == k:
            if (k == "H" and p >= alt[-1][1]) or (k == "L" and p <= alt[-1][1]):
                alt[-1] = (i, p, k)
        else:
            alt.append((i, p, k))
    if len(alt) < 3:
        return None

    swings = []
    prev_h = prev_l = None
    for i, p, k in alt:
        lab = ""
        if k == "H":
            if prev_h is not None:
                lab = "HH" if p > prev_h else "LH"
            prev_h = p
        else:
            if prev_l is not None:
                lab = "HL" if p > prev_l else "LL"
            prev_l = p
        swings.append({"i": i, "p": p, "k": k, "lab": lab})

    labels = [s["lab"] for s in swings if s["lab"]]
    price = _f(klines[-1][4])
    n = len(klines)

    # trend from the last two same-kind labels
    last_h = next((s for s in reversed(swings) if s["k"] == "H"), None)
    last_l = next((s for s in reversed(swings) if s["k"] == "L"), None)
    hs = [s["lab"] for s in swings if s["k"] == "H" and s["lab"]]
    ls = [s["lab"] for s in swings if s["k"] == "L" and s["lab"]]
    up = len(hs) >= 1 and len(ls) >= 1 and hs[-1] == "HH" and ls[-1] == "HL"
    dn = len(hs) >= 1 and len(ls) >= 1 and hs[-1] == "LH" and ls[-1] == "LL"
    state = "UPTREND" if up else ("DOWNTREND" if dn else "RANGE")

    score = 50.0
    reasons = []
    if state == "UPTREND":
        score += 22; reasons.append("HH/HL uptrend")
    elif state == "DOWNTREND":
        score -= 22; reasons.append("LH/LL downtrend")
    else:
        reasons.append("range / mixed swings")

    # ---- break of structure ----
    # the last bar is still forming and may carry zero volume, so fall back to the
    # last completed bar before judging whether the break has participation behind it
    avg_v = _vol_avg(klines, 20)
    v_now = _f(klines[-1][5]) or _f(klines[-2][5]) if len(klines) > 1 else _f(klines[-1][5])
    vol_x = (v_now / avg_v) if avg_v > 0 else 0.0
    bos = None
    if last_h and last_h["i"] < n - 1 and price > last_h["p"]:
        bos = {"dir": "BULLISH", "level": round(last_h["p"], 10),
               "bars_ago": (n - 1) - last_h["i"], "vol_x": round(vol_x, 2),
               "confirmed": vol_x >= 1.2}
    elif last_l and last_l["i"] < n - 1 and price < last_l["p"]:
        bos = {"dir": "BEARISH", "level": round(last_l["p"], 10),
               "bars_ago": (n - 1) - last_l["i"], "vol_x": round(vol_x, 2),
               "confirmed": vol_x >= 1.2}

    if bos:
        if bos["dir"] == "BULLISH":
            score += 14 if bos["confirmed"] else 6
            reasons.append("bullish BOS %.1fx vol" % bos["vol_x"])
        else:
            score -= 14 if bos["confirmed"] else 6
            reasons.append("bearish BOS %.1fx vol" % bos["vol_x"])

    # ---- change of character: a break against the prevailing trend ----
    choch = None
    if bos and ((bos["dir"] == "BULLISH" and dn) or (bos["dir"] == "BEARISH" and up)):
        choch = {"dir": bos["dir"], "level": bos["level"], "bars_ago": bos["bars_ago"]}
        score += 10 if bos["dir"] == "BULLISH" else -10
        reasons.append("CHoCH %s" % bos["dir"].lower())

    # ---- higher lows staircase ----
    if len(ls) >= 3:
        tail = [s["p"] for s in swings if s["k"] == "L"][-4:]
        ups = sum(1 for i in range(1, len(tail)) if tail[i] > tail[i - 1])
        if ups >= 3:
            score += 10; reasons.append("higher lows x%d" % ups)
        elif ups == 2:
            score += 6; reasons.append("higher lows x2")

    score = max(0.0, min(100.0, score))
    return {
        "state": state,
        "labels": labels[-6:],
        "swings": swings[-8:],
        "bos": bos,
        "choch": choch,
        "last_high": round(last_h["p"], 10) if last_h else None,
        "last_low": round(last_l["p"], 10) if last_l else None,
        "last_high_i": last_h["i"] if last_h else None,
        "last_low_i": last_l["i"] if last_l else None,
        "swing_hi": round(max(_f(b[2]) for b in klines), 10),
        "swing_lo": round(min(_f(b[3]) for b in klines), 10),
        "price": round(price, 10),
        "score": int(round(score)),
        "reasons": reasons[:6],
    }


# ---------------------------------------------------------------------------
# 2. VOLUME PROFILE
# ---------------------------------------------------------------------------
def volume_profile(klines, bins=24, window=None):
    """Volume-at-price: point of control and the 70% value area."""
    k = klines[-window:] if window else klines
    if not k or len(k) < 12:
        return None
    hi = max(_f(b[2]) for b in k)
    lo = min(_f(b[3]) for b in k)
    if hi <= lo:
        return None
    step = (hi - lo) / bins
    if step <= 0:
        return None

    vol = [0.0] * bins
    for b in k:
        v = _f(b[5])
        if v <= 0:
            continue
        i0 = int((_f(b[3]) - lo) / step)
        i1 = int((_f(b[2]) - lo) / step)
        i0 = max(0, min(bins - 1, i0))
        i1 = max(0, min(bins - 1, i1))
        share = v / (i1 - i0 + 1)
        for i in range(i0, i1 + 1):
            vol[i] += share

    tot = sum(vol) or 1.0
    poc_i = max(range(bins), key=lambda i: vol[i])
    order = sorted(range(bins), key=lambda i: -vol[i])
    acc, chosen = 0.0, []
    for i in order:
        acc += vol[i]
        chosen.append(i)
        if acc / tot >= 0.70:
            break
    vah_i, val_i = max(chosen), min(chosen)

    price = _f(k[-1][4])
    poc = lo + (poc_i + 0.5) * step
    vah = lo + (vah_i + 1) * step
    val = lo + val_i * step
    span = (vah - val) or step
    pos = (price - val) / span
    zone = "above" if price > vah else ("below" if price < val else "inside")
    return {
        "poc": round(poc, 10), "vah": round(vah, 10), "val": round(val, 10),
        "pos": round(max(-1.0, min(2.0, pos)), 3), "zone": zone,
        "hi": round(hi, 10), "lo": round(lo, 10), "bins": bins,
        "skew": "upper" if poc_i > bins / 2 else ("lower" if poc_i < bins / 2 else "mid"),
    }


# ---------------------------------------------------------------------------
# 3. TIME ALGORITHM
# ---------------------------------------------------------------------------
def _session_of(hour_utc):
    if 0 <= hour_utc < 7:
        return "Asia"
    if 7 <= hour_utc < 12:
        return "London"
    if 12 <= hour_utc < 21:
        return "New York"
    return "Late"


def time_read(klines, lb=3):
    """Session, leg symmetry and Gann cycle position from the bar clock."""
    if not klines or len(klines) < 20:
        return None
    ts = _f(klines[-1][0])
    if ts > 1e11:
        ts /= 1000.0
    hour = int((ts % 86400) // 3600)
    sess = _session_of(hour)

    highs, lows = _pivots(klines, lb)
    seq = sorted([i for i, _ in highs] + [i for i, _ in lows])
    n = len(klines)
    leg_bars = prev_bars = 0
    if len(seq) >= 1:
        leg_bars = (n - 1) - seq[-1]
    if len(seq) >= 2:
        prev_bars = seq[-1] - seq[-2]

    ratio = 0.0
    sym = ""
    if leg_bars > 0 and prev_bars > 0:
        ratio = leg_bars / prev_bars
        for tgt, lab in ((1.0, "equal"), (1.618, "1.618x"), (2.618, "2.618x"), (0.618, "0.618x")):
            if abs(ratio - tgt) <= 0.12:
                sym = lab
                break

    cycle = None
    for c in TIME_CYCLES:
        if abs(leg_bars - c) <= TIME_TOL:
            cycle = c
            break

    score = 0.0
    reasons = []
    if sess in ("London", "New York"):
        score += 5; reasons.append("%s session" % sess)
    if cycle:
        score += 7; reasons.append("Gann %d-bar cycle due" % cycle)
    if sym in ("1.0", "1.618x", "2.618x", "equal"):
        score += 5; reasons.append("time symmetry %s" % (sym or "equal"))
    if not reasons:
        reasons.append("%s session · leg %db" % (sess, leg_bars))

    return {"session": sess, "hour_utc": hour, "leg_bars": leg_bars,
            "prev_bars": prev_bars, "ratio": round(ratio, 3), "symmetry": sym,
            "cycle": cycle, "cycle_due": bool(cycle),
            "score": int(round(min(100.0, 50.0 + score))), "reasons": reasons[:4]}


# ---------------------------------------------------------------------------
# 4. BULLISH CHART PATTERNS
# ---------------------------------------------------------------------------
def patterns(klines, lb=3):
    """Bullish chart patterns only. Each one carries its own trigger, target and
    invalidation so a signal can never be a bare label."""
    if not klines or len(klines) < 40:
        return []
    k = klines
    highs, lows = _pivots(k, lb)
    if len(highs) < 2 or len(lows) < 2:
        return []
    price = _f(k[-1][4])
    atr = _atr(k, 14) or (price * 0.01) or 1e-9
    avg_v = _vol_avg(k, 20)
    last_vx = (_f(k[-1][5]) / avg_v) if avg_v > 0 else 0.0
    out = []

    def add(name, conf, trig, tgt, inv, why):
        if trig <= 0 or inv <= 0 or tgt <= 0:
            return
        out.append({"name": name, "dir": "BULLISH", "conf": int(max(0, min(100, conf))),
                    "trigger": round(trig, 10), "target": round(tgt, 10),
                    "invalidation": round(inv, 10), "why": why,
                    "dist_pct": round((trig - price) / price * 100, 2)})

    # ---- double bottom (W) ----
    if len(lows) >= 2:
        (i1, p1), (i2, p2) = lows[-2], lows[-1]
        if i2 > i1 and p1 > 0 and abs(p2 - p1) / p1 <= 0.025:
            peaks = [p for i, p in highs if i1 < i < i2]
            if peaks:
                neck = max(peaks)
                base = (p1 + p2) / 2
                if neck > base:
                    near = 1.0 - min(1.0, abs(p2 - p1) / p1 / 0.025)
                    conf = 55 + 20 * near + (10 if price > neck else 0) + (8 if last_vx >= 1.3 else 0)
                    add("Double Bottom", conf, neck, neck + (neck - base), min(p1, p2) * 0.995,
                        "two equal lows %.2f%% apart" % (abs(p2 - p1) / p1 * 100))

    # ---- inverse head & shoulders ----
    if len(lows) >= 3:
        (a_i, a), (b_i, b), (c_i, c) = lows[-3], lows[-2], lows[-1]
        if b < a and b < c and a_i < b_i < c_i and a > 0:
            shoulder_gap = abs(a - c) / a
            if shoulder_gap <= 0.035:
                hs = [p for i, p in highs if a_i < i < c_i]
                if hs:
                    neck = max(hs)
                    depth = neck - b
                    conf = 58 + 18 * (1 - min(1.0, shoulder_gap / 0.035)) + (10 if price > neck else 0)
                    add("Inverse H&S", conf, neck, neck + depth, min(a, c) * 0.99,
                        "head %.2f%% below shoulders" % ((min(a, c) - b) / min(a, c) * 100))

    # ---- ascending triangle: flat highs, rising lows ----
    if len(highs) >= 2 and len(lows) >= 2:
        h1, h2 = highs[-2][1], highs[-1][1]
        l1, l2 = lows[-2][1], lows[-1][1]
        if h1 > 0 and l1 > 0 and abs(h2 - h1) / h1 <= 0.012 and l2 > l1:
            flat = h2
            rise = (l2 - l1) / l1
            conf = 52 + min(20.0, rise * 400) + (12 if price > flat else 0)
            add("Ascending Triangle", conf, flat, flat + (flat - l1), l1 * 0.99,
                "flat resistance + rising lows +%.1f%%" % (rise * 100))

    # ---- bull flag / pennant: impulse then tight consolidation ----
    if len(k) >= 30:
        imp = k[-18:-8]
        flag = k[-8:]
        if imp and flag:
            i_lo = min(_f(b[3]) for b in imp)
            i_hi = max(_f(b[2]) for b in imp)
            impulse = (i_hi - i_lo) / i_lo if i_lo > 0 else 0
            f_hi = max(_f(b[2]) for b in flag)
            f_lo = min(_f(b[3]) for b in flag)
            f_range = (f_hi - f_lo) / f_lo if f_lo > 0 else 1
            if impulse >= 0.03 and f_range <= 0.5 * impulse:
                conf = 55 + min(20.0, impulse * 300) + (15 if last_vx >= 1.4 else 0)
                add("Bull Flag", conf, f_hi, f_hi + (i_hi - i_lo), f_lo * 0.995,
                    "impulse +%.1f%%, flag %.1f%% tight" % (impulse * 100, f_range * 100))

    # ---- falling wedge: both lines down, highs falling faster -> convergence ----
    if len(highs) >= 2 and len(lows) >= 2:
        (ih1, ph1), (ih2, ph2) = highs[-2], highs[-1]
        (il1, pl1), (il2, pl2) = lows[-2], lows[-1]
        if ph2 < ph1 and pl2 < pl1 and ih2 > ih1 and il2 > il1:
            h_slope = (ph2 - ph1) / max(1, ih2 - ih1)
            l_slope = (pl2 - pl1) / max(1, il2 - il1)
            if h_slope < l_slope:            # upper line falling faster = converging
                top = ph2
                conf = 50 + min(22.0, abs(h_slope - l_slope) / (atr or 1) * 60) + (10 if price > top else 0)
                add("Falling Wedge", conf, top, top + (top - pl2), pl2 * 0.99,
                    "converging downtrend, apex pressure")

    # ---- breakout / reclaim of the local range ----
    if len(k) >= 25:
        win = k[-25:-1]
        rh = max(_f(b[2]) for b in win)
        if rh > 0 and price > rh and last_vx >= 1.3:
            conf = 58 + min(22.0, (last_vx - 1.3) * 30)
            add("Range Breakout", conf, price, price + (price - rh) * 1.5,
                rh * 0.995, "close above %d-bar high on %.1fx volume" % (len(win), last_vx))

    # ---- rounding bottom ----
    if len(lows) >= 3:
        ps = [p for _, p in lows[-3:]]
        if ps[1] < ps[0] and ps[1] < ps[2] and ps[2] >= ps[0] * 0.995 and ps[0] > 0:
            conf = 50 + (10 if price > max(ps) else 0)
            add("Rounding Bottom", conf, max(ps), max(ps) + (max(ps) - min(ps)), min(ps) * 0.99,
                "three swing lows curving up")

    out.sort(key=lambda x: -x["conf"])
    return out[:4]


# ---------------------------------------------------------------------------
# 5. ALIGNMENT  — structure × volume × time
# ---------------------------------------------------------------------------
def align(s, vp, tm, direction="BUY"):
    """Do structure, volume and time agree on a direction? Names every disagreement."""
    reasons = []
    structure_ok = False
    if s:
        bos_dir = (s.get("bos") or {}).get("dir")
        bos_conf = bool((s.get("bos") or {}).get("confirmed"))
        choch_dir = (s.get("choch") or {}).get("dir")
        if direction == "BUY":
            structure_ok = s["state"] == "UPTREND" \
                or (bos_dir == "BULLISH" and bos_conf) \
                or (choch_dir == "BULLISH" and bos_conf)
        else:
            structure_ok = s["state"] == "DOWNTREND" \
                or (bos_dir == "BEARISH" and bos_conf) \
                or (choch_dir == "BEARISH" and bos_conf)
        if not structure_ok:
            reasons.append("structure %s" % s["state"].lower())

    volume_ok = False
    if vp:
        if direction == "BUY":
            volume_ok = vp["zone"] in ("above", "inside") and vp["pos"] >= 0.0
        else:
            volume_ok = vp["zone"] in ("below", "inside") and vp["pos"] <= 1.0
        if not volume_ok:
            reasons.append("price %s value area" % vp["zone"])
        elif vp["zone"] == "above":
            reasons.append("price above value area")
        elif vp["zone"] == "below":
            reasons.append("price below value area")
        else:
            reasons.append("price inside value area")

    bos = (s or {}).get("bos") or {}
    if bos and bos.get("dir") == ("BULLISH" if direction == "BUY" else "BEARISH"):
        if bos.get("confirmed"):
            reasons.append("break confirmed on volume")
        else:
            reasons.append("break on thin volume")

    time_ok = False
    if tm:
        time_ok = bool(tm.get("cycle_due")) or tm.get("session") in ("London", "New York") \
            or tm.get("symmetry") in ("1.0", "1.618x", "2.618x", "equal")
        if time_ok:
            reasons.append(tm["reasons"][0] if tm.get("reasons") else "time ok")
        else:
            reasons.append("time not due")

    score = 0.0
    score += 40.0 if structure_ok else 0.0
    score += 30.0 if volume_ok else 0.0
    score += 15.0 if time_ok else 0.0
    if bos.get("confirmed"):
        score += 15.0
    score = max(0.0, min(100.0, score))
    return {"structure_ok": structure_ok, "volume_ok": volume_ok, "time_ok": time_ok,
            "aligned": structure_ok and volume_ok, "score": int(round(score)),
            "reasons": reasons[:5]}


# ---------------------------------------------------------------------------
# 6. THE COMBINED READ — and the hunted timeframe
# ---------------------------------------------------------------------------
def hunt(symbol, klines, tf="1m"):
    """One symbol, one timeframe: structure + volume profile + time + bullish patterns."""
    if not klines or len(klines) < 30:
        return None
    s = structure(klines)
    vp = volume_profile(klines)
    tm = time_read(klines)
    pats = patterns(klines)
    if not s and not vp:
        return None

    al = align(s, vp, tm, "BUY")
    price = _f(klines[-1][4])
    atr = _atr(klines, 14)

    # Fib/Gann read off the candles (no extra data source needed)
    ta_read = None
    if ta is not None:
        try:
            ta_read = ta.analyze(symbol, klines, tf)
        except Exception:
            ta_read = None

    # candle-based buy pressure proxy (structure.py has no live order book):
    # fraction of bars that closed at or above their open
    br_closes = [_f(k[4]) for k in klines]
    br_opens = [_f(k[1]) for k in klines]
    n_br = len(br_closes)
    up_bars = sum(1 for c, o in zip(br_closes, br_opens) if c >= o)
    buy_ratio = up_bars / n_br if n_br else 0.5

    score = 0.0
    reasons = []
    if s:
        score += 0.42 * s["score"]
        reasons += s["reasons"][:2]
    score += 0.34 * al["score"]
    if pats:
        score += 0.24 * pats[0]["conf"]
        reasons.append("%s %d%%" % (pats[0]["name"], pats[0]["conf"]))
    reasons += [r for r in al["reasons"] if r not in reasons][:2]

    # measured move: trigger is the structural break, target the range projection
    trig = tgt = inv = None
    if s:
        if s.get("bos") and s["bos"]["dir"] == "BULLISH":
            trig = s["bos"]["level"]
            base = s.get("last_low") or s["swing_lo"]
            tgt = trig + (trig - base)
            inv = base
        elif s.get("last_high"):
            trig = s["last_high"]
            base = s.get("last_low") or s["swing_lo"]
            tgt = trig + (trig - base)
            inv = base
    if (not trig or trig <= 0) and pats:
        trig, tgt, inv = pats[0]["trigger"], pats[0]["target"], pats[0]["invalidation"]
    if not inv or inv <= 0:
        inv = price - 2 * atr if atr else price * 0.95

    score = max(0.0, min(100.0, score))
    bullish = (not s or s["state"] != "DOWNTREND") and al["aligned"] and score >= STRUCT_MIN
    return {
        "symbol": symbol,
        "timeframe": tf,                       # <- the timeframe this signal was hunted on
        "tf": tf,
        "price": round(price, 10),
        "state": (s or {}).get("state", "—"),
        "labels": (s or {}).get("labels", []),
        "bos": (s or {}).get("bos"),
        "choch": (s or {}).get("choch"),
        "swing_hi": (s or {}).get("swing_hi"),
        "swing_lo": (s or {}).get("swing_lo"),
        "vp": vp,
        "time": tm,
        "align": al,
        "patterns": pats,
        "trigger": round(trig, 10) if trig else None,
        "target": round(tgt, 10) if tgt else None,
        "invalidation": round(inv, 10) if inv else None,
        "atr": round(atr, 10),
        "score": int(round(score)),
        "bullish": bool(bullish),
        "buy_ratio": round(buy_ratio, 4),
        "ta": ta_read,
        "reasons": reasons[:6],
    }


# the ladder the hunter reads. Higher timeframes are built by resampling the 1m
# bars already fetched, so the ladder costs nothing extra on the wire.
LADDER = (("1m", 1, 50), ("5m", 5, 30), ("15m", 15, 20), ("1h", 60, 20))


def bullish_gate(analysis, need=0.60, require_bullish_struct=False):
    """The hunter's long-only entry gate, shared by every entry path.

    The hunter buys pumps and never shorts, so every path refuses the same three
    ways: not enough buy-side taker flow, a SHORT Fib/Gann read, or a downtrend.
    The direction is returned from here, so no call site can ever hand a "SELL"
    downstream — a short signal is structurally impossible.

    Returns (ok, reason, direction). `direction` is None when the gate refuses.
    """
    a = analysis or {}
    br = _f(a.get("buy_ratio", 0.5), 0.5)
    if br <= need:
        return False, "not bullish: buy_ratio %.2f (need >%.2f)" % (br, need), None
    t = a.get("ta") or {}
    if t.get("bias") == "SHORT":
        return False, "Fib/Gann SHORT %s/100 opposes BUY" % (t.get("score", ""),), None
    st = a.get("struct") or {}
    if st.get("state") == "DOWNTREND":
        return False, "structure DOWNTREND %s/100 opposes BUY" % (st.get("score", ""),), None
    if require_bullish_struct and st and not st.get("bullish"):
        return False, ("structure not bullish (%s %s/100)"
                       % (st.get("state", "?"), st.get("score", ""))), None
    return True, "", "BUY"


def hunt_multi(symbol, klines_1m, order_book=None, ticker=None, volume_ratio=0.0):
    """Run the read over the whole timeframe ladder and return the best bullish one,
    carrying the ladder so the signal can state WHICH timeframe it was hunted on."""
    if not klines_1m or len(klines_1m) < 50:
        return None
    reads = []
    for name, factor, min_bars in LADDER:
        kk = klines_1m if factor == 1 else resample(klines_1m, factor)
        if len(kk) < min_bars:
            continue
        try:
            r = hunt(symbol, kk, name)
        except Exception:
            r = None
        if r:
            reads.append(r)
    if not reads:
        return None

    ladder = [{"tf": r["tf"], "score": r["score"], "state": r["state"],
               "bullish": r["bullish"]} for r in reads]
    bull = [r for r in reads if r["bullish"]]
    pool = bull or reads
    best = max(pool, key=lambda r: r["score"])
    best = dict(best)
    best["ladder"] = ladder
    best["tf_count"] = len(reads)
    best["bull_tfs"] = [r["tf"] for r in bull]
    # a read confirmed on more than one timeframe is stronger than a single-TF print
    if len(bull) >= 2:
        best["score"] = min(100, best["score"] + 6)
        best["multi_tf"] = True
    else:
        best["multi_tf"] = False
    return best
