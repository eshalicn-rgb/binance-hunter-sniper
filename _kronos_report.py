"""
_kronos_report.py -- turn _kronos_lab*.json into one honest accuracy verdict.

Reads one or more lab outputs (different timeframes) and emits a markdown report.
The whole point is to answer "does the pre-move signal beat a dumb baseline?"
with numbers, including the answer "no".

Verdict rule (deliberately strict):
    a pre-move edge exists ONLY IF, pooled across symbols,
        AUC(model) > AUC(momentum)  AND  AUC(model) > AUC(volatility)
        AND AUC(model) >= 0.55
    anything else prints NO EDGE DETECTED, with the reason.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def _fmt(v, nd=3):
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


def load(paths):
    out = []
    for p in paths:
        try:
            with open(p, "r", encoding="utf-8") as fh:
                d = json.load(fh)
            d["_file"] = os.path.basename(p)
            out.append(d)
        except Exception as e:
            print(f"[skip] {p}: {e}", file=sys.stderr)
    return out


def verdict_for(pooled, events):
    rows = []
    for tag in events:
        k = f"event_{tag}"
        e = pooled.get(k)
        if not e:
            continue
        a_m = e.get("auc_model")
        a_o = e.get("auc_momentum")
        a_v = e.get("auc_volatility")
        if a_m is None:
            rows.append((tag, "no data", None))
            continue
        beats = (a_o is None or a_m > a_o) and (a_v is None or a_m > a_v)
        strong = a_m >= 0.55
        if beats and strong:
            rows.append((tag, "EDGE", a_m))
        elif strong and not beats:
            rows.append((tag, "NO EDGE — baselines match or beat it", a_m))
        else:
            rows.append((tag, "NO EDGE — AUC below 0.55 (near chance)", a_m))
    return rows


def report(labs):
    L = []
    A = L.append
    A("# Kronos pre-move accuracy — measured, not assumed\n")
    A("Every number below is from real Binance spot klines through the vendored "
      "Kronos model on CPU. `sample_count` averages stochastic forecast paths. "
      "A round-trip fee of 0.20% is stated so a gross edge can be judged as tradeable "
      "or not.\n")

    for d in labs:
        tf = d.get("interval", "?")
        A(f"\n## {tf} — {d.get('model','?')} / {d.get('tokenizer','?')}\n")
        A(f"- file: `{d.get('_file')}`")
        A(f"- lookback {d.get('lookback')} bars → forecast {d.get('pred_len')} bars, "
          f"stride {d.get('stride')}, max_context {d.get('max_context')}, "
          f"sample_count {d.get('sample_count')}, fee {d.get('fee_round_trip_pct')}%")
        syms = d.get("symbols", {})
        A(f"- symbols: {len(syms)}\n")

        # per-symbol fidelity
        if syms:
            A("| symbol | windows | MAPE % | dir@1 | pred/act corr |")
            A("|---|---|---|---|---|")
            for s, r in syms.items():
                d1 = (r.get("dir", {}).get("1") or {}).get("model_acc")
                A(f"| {s} | {r.get('windows')} | {_fmt(r.get('mape_mean'),3)} | "
                  f"{_fmt(d1,3)} | {_fmt(r.get('pred_ret_corr'),3)} |")
            A("")

        # pooled directional accuracy
        pooled = d.get("pooled", {})
        dirs = [(k, v) for k, v in pooled.items() if k.startswith("dir_")]
        if dirs:
            A("### Directional accuracy by horizon (pooled)\n")
            A("| horizon | n | Kronos | momentum | beats momentum? |")
            A("|---|---|---|---|---|")
            for k, v in sorted(dirs, key=lambda x: int(x[0].split("_")[1])):
                h = k.split("_")[1]
                m, o = v.get("model_acc"), v.get("momentum_acc")
                beats = "yes" if (m is not None and o is not None and m > o) else "no"
                A(f"| {h} bars | {v.get('n')} | {_fmt(m,4)} | {_fmt(o,4)} | {beats} |")
            A("")
            A("> Note: where the momentum column sits below 0.50 it is *worse than a coin "
              "flip*, so \"beating momentum\" is not evidence of skill. The volatility "
              "control is the bar that actually matters.")

        # pooled pre-move detection
        evs = [(k, v) for k, v in pooled.items() if k.startswith("event_")]
        if evs:
            A("### Pre-move detection (pooled) — can it SEE the move coming?\n")
            A("Event = the forward high reaches +X% within the forecast horizon. "
              "AUC 0.50 = coin flip. The score must beat momentum and volatility.\n")
            A("| event | n | base rate | AUC Kronos | AUC momentum | AUC volatility |")
            A("|---|---|---|---|---|---|")
            for k, v in sorted(evs):
                A(f"| {k.replace('event_','').replace('move','+')}% | {v.get('n')} | "
                  f"{_fmt(v.get('base_rate'),4)} | {_fmt(v.get('auc_model'),4)} | "
                  f"{_fmt(v.get('auc_momentum'),4)} | {_fmt(v.get('auc_volatility'),4)} |")
            A("")
            tags = [k.replace("event_", "") for k, _ in sorted(evs)]
            A("**Verdict per event:**\n")
            for tag, v, auc in verdict_for(pooled, tags):
                A(f"- `{tag}`: **{v}** (AUC {_fmt(auc,4)})")
            A("")

    A("\n## How to read this\n")
    A("- Anything near 0.50 AUC or near the momentum column is **noise**, not a signal.")
    A("- A pre-move signal is only worth wiring into an engine if it beats momentum "
      "*and* volatility, holds up out-of-sample, and clears the 0.20% round-trip fee.")
    A("- Base rate is the share of windows that actually moved; lift over it is the only "
      "reason to bother.")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("labs", nargs="*",
                    default=[os.path.join(HERE, "_kronos_lab_5m.json")])
    ap.add_argument("--out", default=os.path.join(HERE, "_kronos_accuracy.md"))
    a = ap.parse_args()
    paths = a.labs or [os.path.join(HERE, "_kronos_lab_5m.json")]
    labs = load(paths)
    if not labs:
        print("no lab output found", file=sys.stderr)
        return 1
    md = report(labs)
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write(md + "\n")
    print(md)
    print(f"\n[saved] {a.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
