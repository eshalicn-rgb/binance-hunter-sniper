"""
_kronos_lab.py -- measure the ACCURACY of a Kronos-based pre-move hunter.

Question this answers, with numbers:
  1. Can Kronos forecast the next H bars?            -> MAPE / correlation
  2. Does its SIGN beat dumb baselines?              -> directional accuracy @ h
  3. Can it DETECT a move before it happens?         -> ROC-AUC / precision / lift
  4. Would that detection actually be tradeable?     -> net of 0.20% round-trip fee

Baselines used as controls (a real edge must beat ALL of them):
  - base rate      (always predict the majority class)
  - momentum       (sign of the trailing h-bar return)
  - random anchor  (fraction of windows that move, no skill)

Data: real Binance spot klines (public REST, no key).
Model: NeoQuasar Kronos (shiyu-coder/Kronos), CPU.
"""
import os, sys, json, math, time, argparse
import numpy as np
import pandas as pd
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
KRONOS = os.path.join(HERE, "vendor", "Kronos")
sys.path.insert(0, KRONOS)

FEE_ROUND_TRIP = 0.20  # % -- matches signals.FEE_ROUND_TRIP

BINANCE_HOSTS = [
    "https://api.binance.com",
    "https://data-api.binance.vision",
]
INTERVAL_MS = {
    "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000,
    "30m": 1_800_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000,
}


# --------------------------------------------------------------------------- data
def fetch_klines(symbol, interval, bars, end_ms=None):
    """Page backwards until we have `bars` real klines. Returns a DataFrame."""
    step = INTERVAL_MS[interval]
    out = []
    end = end_ms if end_ms is not None else int(time.time() * 1000)
    host_ix = 0
    while len(out) < bars:
        want = min(1000, bars - len(out))
        start = end - want * step
        params = dict(symbol=symbol, interval=interval, limit=want,
                      startTime=start, endTime=end)
        for attempt in range(2 * len(BINANCE_HOSTS)):
            host = BINANCE_HOSTS[(host_ix + attempt // 2) % len(BINANCE_HOSTS)]
            try:
                r = requests.get(host + "/api/v3/klines", params=params, timeout=20)
                if r.status_code == 200:
                    rows = r.json()
                    host_ix = (host_ix + attempt // 2) % len(BINANCE_HOSTS)
                    break
                if r.status_code in (418, 429):
                    time.sleep(2)
                    continue
                raise RuntimeError(f"HTTP {r.status_code}: {r.text[:160]}")
            except Exception as e:
                if attempt == 2 * len(BINANCE_HOSTS) - 1:
                    raise
                time.sleep(0.6)
        else:
            raise RuntimeError("klines fetch failed on all hosts")
        if not rows:
            break
        out = rows + out
        end = rows[0][0] - step
        time.sleep(0.12)
    df = pd.DataFrame(out, columns=[
        "ts", "open", "high", "low", "close", "volume", "closeTime",
        "amount", "trades", "takerBase", "takerQuote", "ignore"])
    df = df.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
    for c in ("open", "high", "low", "close", "volume", "amount"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["timestamp"] = pd.to_datetime(df["ts"], unit="ms")
    return df.tail(bars).reset_index(drop=True)


# --------------------------------------------------------------------------- metrics
def safe_auc(y, s):
    """Rank-based ROC-AUC, no sklearn."""
    y = np.asarray(y, float); s = np.asarray(s, float)
    n_pos, n_neg = int((y == 1).sum()), int((y == 0).sum())
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    order = np.argsort(s, kind="mergesort")
    ranks = np.empty(len(s), float)
    ranks[order] = np.arange(1, len(s) + 1)
    # average ranks for ties
    s_sorted = s[order]
    i = 0
    while i < len(s_sorted):
        j = i
        while j + 1 < len(s_sorted) and s_sorted[j + 1] == s_sorted[i]:
            j += 1
        if j > i:
            ranks[order[i:j + 1]] = (i + 1 + j + 1) / 2.0
        i = j + 1
    return (ranks[y == 1].sum() - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)


def roc_points(y, s):
    y = np.asarray(y, float); s = np.asarray(s, float)
    order = np.argsort(-s, kind="mergesort")
    y = y[order]
    tp = np.cumsum(y); fp = np.cumsum(1 - y)
    P = max(y.sum(), 1); N = max((1 - y).sum(), 1)
    tpr = tp / P; fpr = fp / N
    return np.concatenate([[0], fpr]), np.concatenate([[0], tpr])


def auc_from_points(fpr, tpr):
    return float(np.trapezoid(tpr, fpr))


def precision_at_fraction(y, s, frac):
    n = max(1, int(round(len(s) * frac)))
    idx = np.argsort(-np.asarray(s, float), kind="mergesort")[:n]
    return float(np.asarray(y, float)[idx].mean()), n


# --------------------------------------------------------------------------- main
def run(symbols, interval, bars, lookback, pred_len, stride, model_name,
        tokenizer_name, sample_count, horizons, events, out_json,
        limit_windows=None, max_context=2048, batch_size=64):
    # A horizon must fit inside the forecast window: asking for h=24 while
    # pred_len=12 would index past the predicted path. Clamp instead of crashing.
    horizons = sorted({int(h) for h in horizons if 0 < int(h) <= pred_len})
    if not horizons:
        raise ValueError(f"pred_len={pred_len} is too short for any horizon; use pred_len >= 1")

    from model import Kronos, KronosTokenizer, KronosPredictor

    t_load = time.time()
    print(f"[kronos] loading {model_name} / {tokenizer_name} ...", flush=True)
    tok = KronosTokenizer.from_pretrained(tokenizer_name)
    mdl = Kronos.from_pretrained(model_name)
    pred = KronosPredictor(mdl, tok, max_context=int(max_context))
    print(f"[kronos] loaded in {time.time()-t_load:.1f}s  device={pred.device} "
          f"max_context={pred.max_context}", flush=True)

    report = {
        "model": model_name, "tokenizer": tokenizer_name,
        "interval": interval, "lookback": lookback, "pred_len": pred_len,
        "stride": stride, "sample_count": sample_count,
        "max_context": int(max_context),
        "fee_round_trip_pct": FEE_ROUND_TRIP,
        "symbols": {}, "pooled": {},
    }
    pooled = {k: [] for k in
              ["dir_hit", "dir_base", "dir_mom", "pred_ret", "act_ret", "mape",
               "score", "score_mom", "score_vol"]}
    ev_pool = {e["tag"]: [] for e in events}

    for sym in symbols:
        try:
            df = fetch_klines(sym, interval, bars)
        except Exception as e:
            print(f"[{sym}] DATA FAIL: {e}", flush=True)
            continue
        n = len(df)
        if n < lookback + pred_len + 10:
            print(f"[{sym}] only {n} bars, skip", flush=True)
            continue

        anchors = list(range(lookback, n - pred_len, stride))
        if limit_windows:
            anchors = anchors[:limit_windows]
        print(f"[{sym}] {n} bars {df['timestamp'].iloc[0]} -> "
              f"{df['timestamp'].iloc[-1]} | {len(anchors)} windows", flush=True)

        df_list, xt_list, yt_list, meta = [], [], [], []
        for t in anchors:
            hist = df.iloc[t - lookback:t]
            fut = df.iloc[t:t + pred_len]
            df_list.append(hist[["open", "high", "low", "close",
                                 "volume", "amount"]].reset_index(drop=True))
            xt_list.append(hist["timestamp"].reset_index(drop=True))
            yt_list.append(fut["timestamp"].reset_index(drop=True))
            meta.append((t, float(df["close"].iloc[t - 1])))

        t0 = time.time()
        preds = []
        B = max(1, batch_size)
        for i in range(0, len(df_list), B):
            preds.extend(pred.predict_batch(
                df_list[i:i + B], xt_list[i:i + B], yt_list[i:i + B],
                pred_len=pred_len, T=1.0, top_p=0.9,
                sample_count=sample_count, verbose=False))
        dt = time.time() - t0
        print(f"[{sym}] predicted {len(preds)} windows in {dt:.1f}s "
              f"({dt/max(1,len(preds)):.2f}s/win)", flush=True)

        rows = []
        for (t, px0), pr in zip(meta, preds):
            act = df.iloc[t:t + pred_len]
            pr = np.asarray(pr, float)
            pc = pr[:, 3]                      # predicted close column
            ph = pr[:, 1]                      # predicted high
            a_c = act["close"].to_numpy(float)
            a_h = act["high"].to_numpy(float)
            a_l = act["low"].to_numpy(float)
            act_ret_h = a_c / px0 - 1.0
            p_ret_h = pc / px0 - 1.0
            row = {"t": int(t), "px0": px0,
                   "mape": float(np.mean(np.abs(pc - a_c) / a_c)) * 100.0,
                   "pred_max_up": float(ph.max() / px0 - 1.0) * 100.0,
                   "act_max_up": float(a_h.max() / px0 - 1.0) * 100.0,
                   "act_max_dn": float(a_l.min() / px0 - 1.0) * 100.0,
                   "act_ret": float(act_ret_h[-1]) * 100.0,
                   "pred_ret": float(p_ret_h[-1]) * 100.0}
            for h in horizons:
                row[f"pred_{h}"] = float(p_ret_h[h - 1]) * 100.0
                row[f"act_{h}"] = float(act_ret_h[h - 1]) * 100.0
            # trailing momentum + vol over the same horizon (controls)
            k = horizons[-1]
            row["mom"] = float(df["close"].iloc[t - 1] / df["close"].iloc[t - 1 - k] - 1.0) * 100.0
            tail = df["close"].iloc[t - 1 - k:t].to_numpy(float)
            row["vol"] = float(np.std(np.diff(tail) / tail[:-1])) * 100.0
            rows.append(row)

        sdf = pd.DataFrame(rows)
        rep = {"windows": len(sdf), "secs": round(dt, 1),
               "mape_mean": float(sdf["mape"].mean()),
               "mape_median": float(sdf["mape"].median()),
               "pred_ret_corr": float(np.corrcoef(sdf["pred_ret"], sdf["act_ret"])[0, 1])
               if sdf["pred_ret"].std() > 0 else float("nan"),
               "dir": {}, "events": {}}

        # ---- directional accuracy at each horizon, vs baselines
        for h in horizons:
            up = (sdf[f"act_{h}"] > 0).to_numpy(float)
            hit = ((sdf[f"pred_{h}"] > 0) == (up > 0)).astype(float)
            mom = (((sdf["mom"] > 0) == (up > 0))).astype(float)
            base = max(up.mean(), 1 - up.mean())
            rep["dir"][str(h)] = {
                "n": int(len(sdf)),
                "model_acc": float(hit.mean()),
                "momentum_acc": float(mom.mean()),
                "base_rate_majority": float(base),
                "up_rate": float(up.mean()),
                "mean_act_ret": float(sdf[f"act_{h}"].mean()),
                "mean_pred_ret": float(sdf[f"pred_{h}"].mean()),
            }
            pooled["dir_hit"].append(hit)
            pooled["dir_mom"].append(mom)

        # ---- pre-move detection: does the model SEE the move coming?
        sdf["score"] = sdf["pred_max_up"]
        sdf["score_mom"] = sdf["mom"]
        sdf["score_vol"] = sdf["vol"]
        for ev in events:
            y = (sdf["act_max_up"] >= ev["move_pct"]).astype(int).to_numpy()
            if y.sum() == 0 or y.sum() == len(y):
                rep["events"][ev["tag"]] = {"n": len(y), "base_rate": float(y.mean()),
                                            "auc": None, "note": "degenerate"}
                continue
            a_model = safe_auc(y, sdf["score"])
            a_mom = safe_auc(y, sdf["score_mom"])
            a_vol = safe_auc(y, sdf["score_vol"])
            prec10, nprec = precision_at_fraction(y, sdf["score"], 0.10)
            prec20, _ = precision_at_fraction(y, sdf["score"], 0.20)
            base = float(y.mean())
            rep["events"][ev["tag"]] = {
                "n": int(len(y)), "base_rate": round(base, 4),
                "auc_model": round(a_model, 4),
                "auc_momentum": round(a_mom, 4),
                "auc_volatility": round(a_vol, 4),
                "prec_top10": round(prec10, 4), "prec_top10_n": nprec,
                "prec_top20": round(prec20, 4),
                "lift_top10": round(prec10 / base, 3) if base > 0 else None,
                "recall_top10": round(prec10 * nprec / max(1, y.sum()), 4),
                "mean_move_when_flagged": round(
                    float(sdf.loc[np.argsort(-sdf["score"])[:nprec], "act_max_up"].mean()), 3),
                "mean_move_all": round(float(sdf["act_max_up"].mean()), 3),
            }
            ev_pool[ev["tag"]].append((y, sdf["score"].to_numpy(),
                                       sdf["score_mom"].to_numpy(),
                                       sdf["score_vol"].to_numpy()))
        report["symbols"][sym] = rep
        print(f"[{sym}] MAPE {rep['mape_mean']:.3f}% | "
              f"dir@1 {rep['dir'].get('1',{}).get('model_acc')} | "
              f"events {list(rep['events'])}", flush=True)

    # ---- pooled across symbols
    pool = {}
    for h_i, h in enumerate(horizons):
        hits = np.concatenate([x for x in pooled["dir_hit"][h_i::len(horizons)]]) \
            if pooled["dir_hit"] else np.array([])
        moms = np.concatenate([x for x in pooled["dir_mom"][h_i::len(horizons)]]) \
            if pooled["dir_mom"] else np.array([])
        if len(hits):
            pool[f"dir_{h}"] = {"n": int(len(hits)),
                                "model_acc": round(float(hits.mean()), 4),
                                "momentum_acc": round(float(moms.mean()), 4)}
    for ev in events:
        if not ev_pool[ev["tag"]]:
            continue
        y = np.concatenate([a for a, _, _, _ in ev_pool[ev["tag"]]])
        sm = np.concatenate([b for _, b, _, _ in ev_pool[ev["tag"]]])
        so = np.concatenate([c for _, _, c, _ in ev_pool[ev["tag"]]])
        sv = np.concatenate([d for _, _, _, d in ev_pool[ev["tag"]]])
        fpr, tpr = roc_points(y, sm)
        pool[f"event_{ev['tag']}"] = {
            "n": int(len(y)), "base_rate": round(float(y.mean()), 4),
            "auc_model": round(safe_auc(y, sm), 4),
            "auc_momentum": round(safe_auc(y, so), 4),
            "auc_volatility": round(safe_auc(y, sv), 4),
            "auc_model_trapz": round(auc_from_points(fpr, tpr), 4),
        }
    report["pooled"] = pool

    with open(out_json, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, default=float)
    print(f"\n[saved] {out_json}", flush=True)
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="BTCUSDT,ETHUSDT,SOLUSDT")
    ap.add_argument("--interval", default="5m")
    ap.add_argument("--bars", type=int, default=3000)
    ap.add_argument("--lookback", type=int, default=400)
    ap.add_argument("--pred-len", type=int, default=24)
    ap.add_argument("--stride", type=int, default=12)
    ap.add_argument("--model", default="NeoQuasar/Kronos-mini")
    ap.add_argument("--tokenizer", default="NeoQuasar/Kronos-Tokenizer-2k")
    ap.add_argument("--sample-count", type=int, default=1)
    ap.add_argument("--max-context", type=int, default=2048)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--max-windows", type=int, default=0)
    ap.add_argument("--out", default=os.path.join(HERE, "_kronos_lab.json"))
    a = ap.parse_args()
    rep = run(
        symbols=[s.strip() for s in a.symbols.split(",") if s.strip()],
        interval=a.interval, bars=a.bars, lookback=a.lookback,
        pred_len=a.pred_len, stride=a.stride, model_name=a.model,
        tokenizer_name=a.tokenizer, sample_count=a.sample_count,
        horizons=[1, 3, 6, 12, 24],
        events=[{"tag": "move1", "move_pct": 1.0},
                {"tag": "move2", "move_pct": 2.0},
                {"tag": "move3", "move_pct": 3.0}],
        out_json=a.out, limit_windows=a.max_windows or None,
        max_context=a.max_context, batch_size=a.batch)
    print("\n===== POOLED =====")
    for k, v in rep["pooled"].items():
        print(f"  {k:<22} {json.dumps(v)}")


if __name__ == "__main__":
    main()
