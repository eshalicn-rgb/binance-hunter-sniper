"""enhance.py - leading evidence for the hunt and the pre-pump.

Pure functions over the 1m klines / ticker the engine already fetched. Nothing
fetches, nothing invents a price, and every function returns a neutral value
instead of raising, so one bad symbol can never stop a scan cycle.
"""
from __future__ import annotations


def _f(x, default=0.0):
    try:
        v = float(x)
        return v if v == v and abs(v) != float("inf") else default
    except (TypeError, ValueError):
        return default


def _ok(k) -> bool:
    return bool(k) and len(k) >= 30


def resample(k, factor):
    """Aggregate 1m klines into `factor`-minute bars (no extra REST call)."""
    if not k:
        return []
    out, bucket = [], []
    for row in k:
        bucket.append(row)
        if len(bucket) == factor:
            out.append([
                bucket[0][0],
                _f(bucket[0][1]),
                max(_f(r[2]) for r in bucket),
                min(_f(r[3]) for r in bucket),
                _f(bucket[-1][4]),
                sum(_f(r[5]) for r in bucket),
                bucket[-1][6],
            ])
            bucket = []
    return out


def pct_change(bars, n):
    if not bars or len(bars) < n + 1:
        return 0.0
    a = _f(bars[-n - 1][4])
    b = _f(bars[-1][4])
    return ((b - a) / a * 100.0) if a > 0 else 0.0


def momentum_stack(k):
    """1m / 5m / 15m move, and whether all three point the same way."""
    if not _ok(k):
        return {"m1": 0.0, "m5": 0.0, "m15": 0.0, "aligned": False, "score": 0}
    m1 = pct_change(k, 5)
    m5 = pct_change(resample(k, 5), 1)
    m15 = pct_change(resample(k, 15), 1)
    aligned = m1 > 0 and m5 > 0 and m15 > 0
    score = 0
    if aligned:
        score = 6
    elif m5 > 0 and m15 > 0:
        score = 3
    elif m1 > 0 and m5 > 0:
        score = 2
    return {"m1": round(m1, 3), "m5": round(m5, 3), "m15": round(m15, 3),
            "aligned": aligned, "score": score}


def squeeze(k, lookback=120):
    """Bollinger width vs its own recent history: 1.0 = tightest band seen.

    A coil is a band at the bottom of its range, not a fixed percentage: a thin
    altcoin is always 'wide' in absolute terms, so the percentile is the read.
    """
    if not _ok(k):
        return {"width_pct": None, "percentile": None, "tight": False}
    closes = [_f(r[4]) for r in k[-lookback:]]
    if len(closes) < 30:
        return {"width_pct": None, "percentile": None, "tight": False}
    widths = []
    for i in range(20, len(closes)):
        win = closes[i - 20:i]
        mean = sum(win) / len(win)
        var = sum((c - mean) ** 2 for c in win) / len(win)
        widths.append((var ** 0.5) / mean if mean > 0 else 0.0)
    if not widths:
        return {"width_pct": None, "percentile": None, "tight": False}
    cur = widths[-1]
    pct = sum(1 for w in widths if w <= cur) / len(widths)
    return {"width_pct": round(cur * 100, 3),
            "percentile": round(pct, 3),
            "tight": pct <= 0.25}


def rel_strength(sym_m5, btc_m5):
    """How much this coin is outperforming BTC over the same 5 minutes."""
    d = _f(sym_m5) - _f(btc_m5)
    return {"delta": round(d, 3), "leading": d >= 1.0, "lagging": d <= -1.0}


def breakout(k, high24=0.0):
    """Distance to the 24h high and to the local range top, in percent."""
    price = _f(k[-1][4]) if k else 0.0
    if price <= 0:
        return {"to_high24": None, "to_range": None, "at_range": False}
    win = k[-60:] or k
    r_hi = max(_f(r[2]) for r in win)
    to24 = ((high24 - price) / high24 * 100.0) if high24 > 0 else None
    to_range = ((r_hi - price) / r_hi * 100.0) if r_hi > 0 else None
    return {"to_high24": None if to24 is None else round(to24, 2),
            "to_range": None if to_range is None else round(to_range, 2),
            "at_range": to_range is not None and to_range <= 0.5}


def tier(score):
    """Named bands so a card says 'primed', not just a number."""
    s = int(score or 0)
    if s >= 85:
        return "IGNITING"
    if s >= 72:
        return "PRIMED"
    if s >= 60:
        return "COILED"
    if s >= 48:
        return "WATCH"
    return "QUIET"


def read(k, high24=0.0, btc_m5=0.0):
    """One pass over the candles, all the leading reads together."""
    if not _ok(k):
        return None
    mom = momentum_stack(k)
    sq = squeeze(k)
    br = breakout(k, high24)
    rs = rel_strength(mom["m5"], btc_m5)
    return {"mom": mom, "squeeze": sq, "breakout": br, "rs": rs}


def prepump_boost(reads):
    """0-15 extra pre-pump points, each one named. None reads earn nothing."""
    if not reads:
        return 0, []
    boost, whys = 0, []
    sq = reads["squeeze"]
    if sq["percentile"] is not None:
        if sq["tight"]:
            boost += 6
            whys.append("band squeeze p%.0f" % (sq["percentile"] * 100))
        elif sq["percentile"] <= 0.35:
            boost += 3
            whys.append("band tightening p%.0f" % (sq["percentile"] * 100))
    mom = reads["mom"]
    if mom["aligned"]:
        boost += 4
        whys.append("1m/5m/15m aligned")
    elif mom["m5"] > 0 and mom["m15"] > 0:
        boost += 2
        whys.append("5m/15m up")
    if reads["rs"]["leading"]:
        boost += 3
        whys.append("+%.1f%% vs BTC" % reads["rs"]["delta"])
    if reads["breakout"]["at_range"]:
        boost += 2
        whys.append("at range top")
    return min(15, boost), whys


def hunt_boost(reads):
    """Bounded -6..+6 confluence for the order-flow score of a live move."""
    if not reads:
        return 0, []
    adj, whys = 0, []
    mom = reads["mom"]
    if mom["aligned"]:
        adj += 3
        whys.append("3-tf aligned")
    elif mom["m5"] > 0 and mom["m15"] > 0:
        adj += 1
    if reads["rs"]["leading"]:
        adj += 2
        whys.append("RS +%.1f%%" % reads["rs"]["delta"])
    elif reads["rs"]["lagging"]:
        adj -= 3
        whys.append("RS %.1f%% vs BTC" % reads["rs"]["delta"])
    if reads["squeeze"]["tight"]:
        adj += 1
        whys.append("squeeze")
    return max(-6, min(6, adj)), whys
