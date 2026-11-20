import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import structure

# fetch real 1m klines straight from Binance to verify the struct keys the scan reads
import requests
def klines(sym, n=200):
    r = requests.get("https://api.binance.com/api/v3/klines",
                     params={"symbol": sym, "interval": "1m", "limit": n}, timeout=15)
    return r.json()

for sym in ("BTCUSDT", "ETHUSDT", "ARBUSDT", "DOGEUSDT"):
    st = structure.hunt_multi(sym, klines(sym))
    keys = ("symbol", "tf", "timeframe", "price", "state", "labels", "bos", "choch",
            "swing_hi", "swing_lo", "vp", "time", "align", "patterns", "trigger",
            "target", "invalidation", "atr", "score", "bullish", "reasons",
            "ladder", "tf_count", "bull_tfs", "multi_tf")
    missing = [k for k in ("symbol", "tf", "price", "state", "labels", "bos", "choch",
                           "swing_hi", "swing_lo", "vp", "time", "align", "patterns",
                           "trigger", "target", "invalidation", "atr", "score",
                           "bullish", "reasons", "ladder", "tf_count", "multi_tf")
               if k not in st]
    print("%-9s tf=%-4s score=%-3s bull=%-5s aligned=%-5s ladder=%s missing=%s" % (
        sym, st.get("tf"), st.get("score"), st.get("bullish"),
        (st.get("align") or {}).get("aligned"),
        st.get("ladder"),
        missing or "none"))
