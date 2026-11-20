#!/usr/bin/env python3
"""
CLASSICAL STRUCTURE STRATEGIES — Fibonacci + Gann.

Pure functions over klines. No network, no keys, no state. Every level is derived
from real swing structure in the candles, so a symbol with no structure returns
None instead of inventing a level.

Fibonacci
    retracement 0.236 / 0.382 / 0.5 / 0.618 / 0.786 of the dominant swing leg
    extension   1.272 / 1.618 / 2.0 / 2.618 beyond the leg
    the "golden pocket" is 0.382–0.618 — the highest-probability continuation zone

Gann
    fan ratios   1x8 1x4 1x3 1x2 1x1 2x1 3x1 4x1 8x1 anchored to the swing
                 1x1 (45°) is the trend divider: price above it is bullish
    eighths      the swing range divided by 8 (Gann's 12.5%–87.5% grid)
                 the 50% (4/8) level is the balance point
    square of 9  (sqrt(price) ± k*0.125)^2 — the classic Gann support/resistance wheel
    time cycles  30 45 60 90 144 180 270 360 bars from the anchor — turning points

Both are folded into a single 0-100 confluence score with a LONG / SHORT / NEUTRAL bias.
"""
import math

FIB_RETRACE = ((0.0, "0"), (0.236, "0.236"), (0.382, "0.382"), (0.5, "0.5"),
               (0.618, "0.618"), (0.786, "0.786"), (1.0, "1"))
FIB_EXT = ((1.272, "1.272"), (1.618, "1.618"), (2.0, "2"), (2.618, "2.618"))
GANN_FAN = (("1x8", 8.0), ("1x4", 4.0), ("1x3", 3.0), ("1x2", 2.0), ("1x1", 1.0),
            ("2x1", 0.5), ("3x1", 1.0 / 3.0), ("4x1", 0.25), ("8x1", 0.125))
GANN_EIGHTHS = (0.125, 0.25, 0.375, 0.5, 0.625, 0.75, 0.875)
TIME_CYCLES = (30, 45, 60, 90, 144, 180, 270, 360)
GOLDEN_LO, GOLDEN_HI = 0.382, 0.618


def _f(x, d=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


def atr(klines, n=14):
    """Average true range over the last n bars."""
    if len(klines) < 2:
        return 0.0
    trs = []
    for i in range(1, len(klines)):
        h, l, pc = _f(klines[i][2]), _f(klines[i][3]), _f(klines[i - 1][4])
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if not trs:
        return 0.0
    return sum(trs[-n:]) / len(trs[-n:])


def pivots(klines, lb=3):
    """Fractal swing pivots. Returns (highs, lows) as [(index, price), ...]."""
    highs, lows = [], []
    n = len(klines)
    for i in range(lb, n - lb):
        h = _f(klines[i][2])
        l = _f(klines[i][3])
        win = klines[i - lb:i + lb + 1]
        if h >= max(_f(k[2]) for k in win):
            highs.append((i, h))
        if l <= min(_f(k[3]) for k in win):
            lows.append((i, l))
    return highs, lows


def _dominant_leg(klines, lb=3):
    """The largest completed swing leg = structure the levels are drawn from."""
    highs, lows = pivots(klines, lb)
    if not highs or not lows:
        return None
    # prefer the most recent significant leg: last pivot high and last pivot low
    hi_i, hi = highs[-1]
    lo_i, lo = lows[-1]
    # widen to the extreme of the window each pivot belongs to, so a leg is never a wick
    seg = klines[min(hi_i, lo_i):max(hi_i, lo_i) + 1] or klines
    if not seg:
        return None
    hi = max(_f(k[2]) for k in seg)
    lo = min(_f(k[3]) for k in seg)
    hi_i = max(range(len(seg)), key=lambda i: _f(seg[i][2]))
    lo_i = max(range(len(seg)), key=lambda i: _f(seg[i][3]))
    if hi <= lo:
        return None
    return {"hi": hi, "lo": lo, "hi_i": hi_i, "lo_i": lo_i, "seg": seg,
            "n": len(seg), "up": hi_i > lo_i}


def analyze(symbol, klines, interval="1m"):
    """Full Fib + Gann read of a symbol from its candles. None when there is no structure."""
    if not klines or len(klines) < 20:
        return None
    closes = [_f(k[4]) for k in klines]
    price = closes[-1]
    if price <= 0:
        return None
    leg = _dominant_leg(klines)
    if not leg:
        return None

    hi, lo = leg["hi"], leg["lo"]
    rng = hi - lo
    up = leg["up"]
    levels = []
    reasons = []
    score = 50.0
    score += 10 if up else -10
    reasons.append("swing structure " + ("up" if up else "down"))

    # ---------------- Fibonacci retracement of the leg ----------------
    fib_ret = {}
    for r, lab in FIB_RETRACE:
        p = (lo + rng * r) if up else (hi - rng * r)
        if p > 0:
            fib_ret[lab] = p
            levels.append({"price": p, "label": "Fib " + lab, "kind": "fib"})
    ret_pos = (price - lo) / rng if up else (hi - price) / rng
    ret_pos = max(-1.0, min(2.0, ret_pos))
    if GOLDEN_LO <= ret_pos <= GOLDEN_HI:
        score += 15
        reasons.append("golden pocket %.3f" % ret_pos)
    elif ret_pos > 0.786:
        score -= 10
        reasons.append("deep retrace %.3f" % ret_pos)
    elif ret_pos < 0.236:
        score += 5
        reasons.append("holding the extreme")

    # ---------------- Fibonacci extensions ----------------
    fib_ext = {}
    for r, lab in FIB_EXT:
        p = (lo + rng * r) if up else (hi - rng * r)
        if p > 0:
            fib_ext[lab] = p
            levels.append({"price": p, "label": "Ext " + lab, "kind": "fibe"})
    if price >= fib_ext.get("1.618", 1e18):
        score -= 8
        reasons.append("at the 1.618 extension")

    # ---------------- Gann fan off the swing anchor ----------------
    # the 1x1 (45°) line runs from the swing start to the swing end,
    # so its slope is the leg's own price-per-bar rate.
    bars = max(1, abs(leg["hi_i"] - leg["lo_i"]))
    slope = rng / bars
    anchor_i = leg["lo_i"] if up else leg["hi_i"]
    anchor_p = lo if up else hi
    bars_now = (len(klines) - 1) - anchor_i
    fan = {}
    for name, ratio in GANN_FAN:
        p = anchor_p + (slope * ratio * bars_now) * (1 if up else -1)
        if p > 0:
            fan[name] = p
            levels.append({"price": p, "label": "Gann " + name, "kind": "gann"})
    g1x1 = fan.get("1x1", price)
    if (up and price >= g1x1) or (not up and price <= g1x1):
        score += 12
        reasons.append("beyond the Gann 1x1")
    else:
        score -= 12
        reasons.append("inside the Gann 1x1")

    # ---------------- Gann eighths of the swing range ----------------
    eighths = {}
    for e in GANN_EIGHTHS:
        p = lo + rng * e
        eighths["%.3f" % e] = p
        levels.append({"price": p, "label": "Gann %d/8" % round(e * 8), "kind": "gann8"})
    half = eighths.get("0.500", (lo + hi) / 2)
    if (up and price >= half) or (not up and price <= half):
        score += 8
        reasons.append("holding the Gann 50%")
    else:
        score -= 8
        reasons.append("lost the Gann 50%")

    # ---------------- Gann square of nine ----------------
    sr = math.sqrt(price)
    sq9 = []
    for k in (1, 2, 3, 4):
        for step in (0.125, 0.25):
            dn = (sr - k * step) ** 2
            upv = (sr + k * step) ** 2
            if dn > 0:
                sq9.append({"price": dn, "dir": "S", "step": k * step})
                levels.append({"price": dn, "label": "Sq9 -%.3f" % (k * step), "kind": "sq9"})
            sq9.append({"price": upv, "dir": "R", "step": k * step})
            levels.append({"price": upv, "label": "Sq9 +%.3f" % (k * step), "kind": "sq9"})

    # ---------------- Gann time cycles from the anchor ----------------
    cycles = []
    for c in TIME_CYCLES:
        remain = c - bars_now
        if -2 <= remain <= 30:
            cycles.append({"cycle": c, "bars": remain})
            if remain == 0:
                score += 4
                reasons.append("Gann %d-bar time cycle due now" % c)

    # ---------------- nearest levels either side of price ----------------
    below = sorted([l for l in levels if 0 < l["price"] < price], key=lambda x: -x["price"])
    above = sorted([l for l in levels if l["price"] > price], key=lambda x: x["price"])

    score = max(0.0, min(100.0, score))
    bias = "LONG" if score >= 60 else ("SHORT" if score <= 40 else "NEUTRAL")
    return {
        "symbol": symbol,
        "interval": interval,
        "price": price,
        "atr": round(atr(klines), 10),
        "trend": "UP" if up else "DOWN",
        "swing": {"hi": hi, "lo": lo, "range": rng, "bars": bars},
        "fib": {"retrace": fib_ret, "ext": fib_ext, "position": round(ret_pos, 3)},
        "gann": {"fan": fan, "eighths": eighths, "square9": sq9[:8], "time_cycles": cycles[:4]},
        "nearest": {"support": below[0] if below else None,
                    "resistance": above[0] if above else None},
        "levels": sorted(levels, key=lambda x: x["price"]),
        "score": int(round(score)),
        "bias": bias,
        "reasons": reasons,
    }


def adjust(ta, direction):
    """Turn a Fib/Gann read into a bounded score adjustment for a given trade direction.

    Returns (delta, reason). Neutral structure contributes nothing; confluence with the
    intended direction is what earns the points, opposition takes them away.
    """
    if not ta:
        return 0, ""
    s = int(ta.get("score", 50))
    bias = ta.get("bias", "NEUTRAL")
    if bias == "NEUTRAL":
        return 0, ""
    aligned = (bias == "LONG" and direction == "BUY") or (bias == "SHORT" and direction == "SELL")
    strength = abs(s - 50) / 50.0            # 0.0 .. 1.0
    delta = int(round(6 * strength))
    if aligned:
        return delta, "fib/gann confluence"
    return -delta, "fib/gann opposing"


# ---------------------------------------------------------------------------
# Pre-pump radar: how close is a symbol to moving, BEFORE it moves.
# This is deliberately the opposite question to order_flow_score — that one
# measures a move already in progress, this one measures the compression that
# precedes it. Every point is earned by a measured signal and names its reason.
# ---------------------------------------------------------------------------
PREPUMP_MIN = 55          # at or above this a symbol counts as "coiled"


def prepump(symbol, klines, order_book=None, ticker=None, volume_ratio=0.0,
            buy_ratio=0.5, catalyst=0.0, ta_read=None):
    """0-100 'about to move' pressure read. None when there is not enough history."""
    if not klines or len(klines) < 45:
        return None
    k = klines
    closes = [_f(x[4]) for x in k]
    highs = [_f(x[2]) for x in k]
    lows = [_f(x[3]) for x in k]
    vols = [_f(x[5]) for x in k]
    price = closes[-1]
    if price <= 0:
        return None

    score = 0.0
    reasons = []

    # 1) volume ramp — last 5 bars against the 20-bar baseline before them (0-20)
    # shifted thresholds downward so moderate acceleration earns points earlier
    base = vols[-25:-5] or vols[:-5]
    base_avg = (sum(base) / len(base)) if base else 0.0
    recent = vols[-5:]
    recent_avg = (sum(recent) / len(recent)) if recent else 0.0
    ramp = (recent_avg / base_avg) if base_avg > 0 else 0.0
    if ramp >= 2.2:
        score += 20; reasons.append("volume ramp %.1fx" % ramp)
    elif ramp >= 1.7:
        score += 16; reasons.append("volume ramp %.1fx" % ramp)
    elif ramp >= 1.2:
        score += 11; reasons.append("volume building %.1fx" % ramp)
    elif ramp >= 0.9:
        score += 6; reasons.append("volume uptick %.1fx" % ramp)

    # 1b) very early acceleration — if the last 3 bars are already climbing
    # (rewarded separately so a modest 3-bar surge isn't drowned by the 5-bar avg)
    try:
        if len(vols) >= 4 and vols[-1] >= vols[-2] >= vols[-3]:
            early = (vols[-1] / vols[-4]) if vols[-4] > 0 else 0.0
            if early >= 1.5:
                score += 5; reasons.append("early vol accel %.1fx" % early)
            elif early >= 1.3:
                score += 3; reasons.append("early vol uptick %.1fx" % early)
    except Exception:
        pass

    # 2) volatility state: a quiet base that has started to expand (0-15)
    a_recent = atr(k[-14:], 14) or 0.0
    a_base = atr(k[-45:-14], 14) or 0.0
    volx = (a_recent / a_base) if a_base > 0 else 0.0
    if volx >= 1.8 and a_recent > 0:
        score += 15; reasons.append("volatility expansion x%.1f" % volx)
    elif volx >= 1.3:
        score += 9; reasons.append("volatility expanding x%.1f" % volx)
    elif volx <= 0.75:
        score += 5; reasons.append("volatility squeeze")

    # 3) higher lows — the accumulation staircase (0-12)
    _highs, plows = pivots(k, 3)
    if len(plows) >= 3:
        tail = [p for _i, p in plows[-4:]]
        ups = sum(1 for i in range(1, len(tail)) if tail[i] > tail[i - 1])
        if ups >= 3:
            score += 12; reasons.append("higher lows x%d" % ups)
        elif ups == 2:
            score += 8; reasons.append("higher lows x2")
        elif ups == 1:
            score += 4; reasons.append("first higher low")

    # 4) bid stacking — real money parked under the price (0-12)
    try:
        bids = (order_book or {}).get("bids") or []
        asks = (order_book or {}).get("asks") or []
        if bids and asks:
            mid = (_f(bids[0][0]) + _f(asks[0][0])) / 2.0
            if mid > 0:
                lo, hi = mid * 0.995, mid * 1.005
                bd = sum(_f(b[1]) * _f(b[0]) for b in bids if _f(b[0]) >= lo)
                ad = sum(_f(a2[1]) * _f(a2[0]) for a2 in asks if _f(a2[0]) <= hi)
                tot = bd + ad
                imb = ((bd - ad) / tot) if tot > 0 else 0.0
                if imb >= 0.30:
                    score += 12; reasons.append("bid stacking %.2f" % imb)
                elif imb >= 0.15:
                    score += 8; reasons.append("bids heavy %.2f" % imb)
                elif imb >= 0.05:
                    score += 4; reasons.append("mild bid lean %.2f" % imb)
    except Exception:
        pass

    # 5) trade-count acceleration — more people showing up (0-10)
    try:
        tc = [_f(x[8]) for x in k]
        b_tc = tc[-25:-5] or tc[:-5]
        b_avg = (sum(b_tc) / len(b_tc)) if b_tc else 0.0
        r_avg = (sum(tc[-5:]) / 5.0) if len(tc) >= 5 else 0.0
        acc = (r_avg / b_avg) if b_avg > 0 else 0.0
        if acc >= 2.0:
            score += 10; reasons.append("trade count %.1fx" % acc)
        elif acc >= 1.5:
            score += 7; reasons.append("trade count %.1fx" % acc)
        elif acc >= 1.2:
            score += 4; reasons.append("trade count rising")
    except Exception:
        pass

    # 6) proximity to the 24h high — where breakouts actually come from (0-10)
    try:
        hi24 = _f((ticker or {}).get("highPrice")) if ticker else 0.0
        if hi24 > 0:
            dist = (hi24 - price) / hi24
            if dist <= 0.005:
                score += 10; reasons.append("at 24h high")
            elif dist <= 0.02:
                score += 8; reasons.append("%.1f%% under 24h high" % (dist * 100))
            elif dist <= 0.04:
                score += 5; reasons.append("%.1f%% under 24h high" % (dist * 100))
    except Exception:
        pass

    # 7) pressing the local range high (0-8)
    try:
        win = k[-60:] or k
        r_hi = max(_f(x[2]) for x in win)
        if r_hi > 0:
            d = (r_hi - price) / r_hi
            if d <= 0.003:
                score += 8; reasons.append("breaking local high")
            elif d <= 0.012:
                score += 5; reasons.append("pressing local high")
    except Exception:
        pass

    # 8) Fib/Gann structure holding the base up (0-8)
    try:
        if ta_read:
            pos = (ta_read.get("fib") or {}).get("position")
            near = ta_read.get("nearest") or {}
            sup = (near.get("support") or {}).get("price")
            if pos is not None and GOLDEN_LO <= pos <= GOLDEN_HI:
                score += 5; reasons.append("golden pocket %.3f" % pos)
            if sup and (price - _f(sup)) / price <= 0.015:
                score += 3; reasons.append("on Fib/Gann support")
    except Exception:
        pass

    # 9) catalyst or one-sided aggression (0-5)
    try:
        if catalyst and float(catalyst) >= 6:
            score += 5; reasons.append("news catalyst %.0f" % float(catalyst))
        elif buy_ratio >= 0.65:
            score += 3; reasons.append("buy aggression %.2f" % buy_ratio)
        elif buy_ratio <= 0.35:
            score += 2; reasons.append("sell exhaustion %.2f" % buy_ratio)
    except Exception:
        pass

    score = max(0.0, min(100.0, score))
    br = float(buy_ratio or 0.0)
    # long-only hunter: a bearish coil is not a hunt, so it carries no direction
    # rather than a "SELL" that would read as a short signal beside the trade table.
    return {"symbol": symbol, "score": int(round(score)), "ramp": round(ramp, 2),
            "buy_ratio": round(br, 3),
            "direction": "BUY" if br >= 0.5 else None,
            "bullish": br >= 0.5,
            "reasons": reasons[:6], "coiled": score >= PREPUMP_MIN}
