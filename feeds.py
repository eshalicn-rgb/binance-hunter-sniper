#!/usr/bin/env python3
"""
EXTERNAL SOURCE FEEDS — real, keyless crypto intelligence for the Hunter swarm.

Fail-closed: any source that errors contributes nothing and never fabricates a
value. No API keys required anywhere in this file.

Feed              Source                              Caught by
----------------  ----------------------------------  ---------------
News              Binance public CMS announcements    analyst
Trending          CoinGecko /search/trending          analyst
Fear & Greed      alternative.me FNG                  risk_guard
Funding / OI      Binance USD-M futures (fapi)        analyst
Long / Short      Binance USD-M futures (fapi)        risk_guard
Whale tape        Binance aggTrades (block trades)    whale
Whale walls       Binance depth (resting size)        whale
Volume surge      1m kline relative volume            scanner

Whale/wall scanning reuses the trades and order book that scan_market has
already fetched, so it adds zero extra REST weight.
"""
import email.utils
import re
import time
import threading
from collections import defaultdict
from datetime import datetime as _dt

import requests

CMS = "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query"
CG_TRENDING = "https://api.coingecko.com/api/v3/search/trending"
FNG = "https://api.alternative.me/fng/"
FAPI = "https://fapi.binance.com"
FAPI_PREMIUM = FAPI + "/fapi/v1/premiumIndex"
FAPI_OI = FAPI + "/futures/data/openInterestHist"
FAPI_LSR = FAPI + "/futures/data/globalLongShortAccountRatio"

# thresholds
WHALE_MIN_USD = 15000.0   # a single aggressive block trade worth catching
WHALE_MULT = 6.0          # ...or 6x this symbol's median trade notional
WALL_MIN_USD = 30000.0    # resting order worth catching
WALL_MULT = 4.0
WHALE_TAPE_MAX = 60
WALL_MAX = 40
NOTABLE_USD = 50000.0     # at/above this a whale becomes a swarm "catch"
SURGE_NOTABLE = 4.0       # volume ratio that becomes a scanner catch

# ---------------- news / social sources ----------------
RSS_FEEDS = [
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("Cointelegraph", "https://cointelegraph.com/rss"),
    ("Decrypt", "https://decrypt.co/feed"),
    ("The Block", "https://www.theblock.co/rss.xml"),
    # extra coverage — one dead feed must never blank the news panel
    ("Bitcoin Magazine", "https://bitcoinmagazine.com/feed"),
    ("CryptoSlate", "https://cryptoslate.com/feed/"),
]
# Reddit: the Atom endpoint stays reachable where .json answers 403 for
# datacenter IPs. Atom first, JSON only as a fallback.
REDDIT_RSS = "https://www.reddit.com/r/CryptoCurrency/hot/.rss"
REDDIT_URL = "https://www.reddit.com/r/CryptoCurrency/hot.json"

# keyword engine — catalysts that actually move price
KEY_BULL = ("list", "listing", "partnership", "partner", "integrat", "mainnet", "upgrade", "adopt",
            "buyback", "burn", "etf", "approv", "launch", "airdrop", "acquisition", "acquire",
            "collaborat", "staking", "perpetual", "futures listing", "record", "milestone",
            "expand", "grant", "treasury", "institutional", "custody", "surge", "rally",
            "all-time high", "breakout", "funding round", "raises")
KEY_BEAR = ("hack", "exploit", "delist", "lawsuit", "sec charges", "sues", "fraud", "scam",
            "bankrupt", "insolven", "halt", "suspend", "outage", "plunge", "crash", "rug",
            "vulnerab", "breach", "frozen", "depeg", "investigation", "stolen", "drained",
            "liquidation cascade", "downtime")

# ticker -> project names, for headlines that use the name instead of the ticker
COIN_ALIASES = {
    "BTC": ("bitcoin",), "ETH": ("ethereum", "ether"), "SOL": ("solana",), "BNB": ("binance coin",),
    "XRP": ("ripple",), "ADA": ("cardano",), "DOGE": ("dogecoin",), "AVAX": ("avalanche",),
    "DOT": ("polkadot",), "LINK": ("chainlink",), "MATIC": ("polygon",), "ARB": ("arbitrum",),
    "OP": ("optimism",), "SUI": ("sui network",), "APT": ("aptos",), "TIA": ("celestia",),
    "INJ": ("injective",), "NEAR": ("near protocol",), "PEPE": ("pepe",), "ZEC": ("zcash",),
    "AAVE": ("aave",), "UNI": ("uniswap",), "ATOM": ("cosmos",), "FIL": ("filecoin",),
    "XLM": ("stellar",), "ALGO": ("algorand",), "VET": ("vechain",), "ICP": ("internet computer",),
    "RNDR": ("render",), "WIF": ("dogwifhat",), "BONK": ("bonk",), "SEI": ("sei network",),
    "JUP": ("jupiter",), "PYTH": ("pyth",), "STRK": ("starknet",), "ENA": ("ethena",),
    "TAO": ("bittensor",), "FET": ("fetch.ai",), "GRT": ("the graph",), "SAND": ("sandbox",),
    "MANA": ("decentraland",), "CRV": ("curve",), "LDO": ("lido",), "SNX": ("synthetix",),
    "MKR": ("maker",), "COMP": ("compound",), "GALA": ("gala",), "IMX": ("immutable",),
    "STX": ("stacks",), "RUNE": ("thorchain",), "KAS": ("kaspa",), "FTM": ("fantom",),
    "ZIL": ("zilliqa",), "LTC": ("litecoin",), "ETC": ("ethereum classic",),
}
# bases that are ordinary English words: only match with an explicit $ prefix
GENERIC_ONLY = {"LINK", "NEAR", "ONE", "AI", "OP", "S", "ARK", "MASK", "GRASS"}
CATALYST_MIN = 4          # news/social strength required to fire a catalyst entry


class FeedsHub:
    def __init__(self):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": "BinanceHunter/1.0"})
        self.lock = threading.Lock()

        self.news = []          # [{title, ts, code}]
        self.trending = []      # [{symbol, name, rank, chg24h}]
        self.fng = {}           # {value, label, ts}
        self.futures = {}       # symbol -> {funding, oi_usd, oi_chg_pct, lsr, long_pct}
        self.whales = []        # newest first
        self.walls = []         # newest first
        self.volume_surge = []
        self.catches = []       # agent "caught" events, newest first
        self.headlines = []     # official + news RSS + social, newest first
        self.catalysts = []     # keyword-matched coin catalysts
        self.news_scores = {}   # symbol -> keyword catalyst strength
        self._last = {}
        self._error = {}

    # ---------------- plumbing ----------------
    def _get(self, url, params=None, timeout=8):
        try:
            r = self.s.get(url, params=params, timeout=timeout)
            if r.status_code == 200:
                self._error.pop(url, None)      # health reflects the LAST attempt
                return r.json()
            self._error[url] = "HTTP %s" % r.status_code
        except Exception as e:
            self._error[url] = type(e).__name__
        return None

    def _due(self, key, ttl):
        return (time.time() - self._last.get(key, 0.0)) >= ttl

    def _mark(self, key):
        self._last[key] = time.time()

    @staticmethod
    def _median(xs):
        s = sorted(xs)
        n = len(s)
        if not n:
            return 0.0
        return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0

    # ---------------- news ----------------
    def refresh_news(self, ttl=180):
        if not self._due("news", ttl):
            return self.news
        self._mark("news")
        j = self._get(CMS, {"type": 1, "pageNo": 1, "pageSize": 20, "catalogId": 48})
        out = []
        try:
            for cat in ((j or {}).get("data", {}) or {}).get("catalogs", []) or []:
                for a in cat.get("articles", []) or []:
                    title = (a.get("title") or "").strip()
                    if title:
                        out.append({"title": title, "ts": a.get("releaseDate", 0),
                                    "code": a.get("code", "")})
        except Exception:
            out = []
        if out:
            with self.lock:
                self.news = out
        return self.news

    # ---------------- trending ----------------
    def refresh_trending(self, ttl=300):
        if not self._due("trending", ttl):
            return self.trending
        self._mark("trending")
        j = self._get(CG_TRENDING)
        out = []
        try:
            for i, c in enumerate((j or {}).get("coins", []) or []):
                it = c.get("item", {}) or {}
                data = it.get("data", {}) or {}
                pc = (data.get("price_change_percentage_24h") or {}).get("usd")
                out.append({
                    "symbol": (it.get("symbol") or "").upper(),
                    "name": it.get("name", ""),
                    "rank": it.get("market_cap_rank") or (i + 1),
                    "chg24h": round(float(pc), 2) if pc is not None else None,
                })
        except Exception:
            out = []
        if out:
            with self.lock:
                self.trending = out
        return self.trending

    # ---------------- fear & greed ----------------
    def refresh_fng(self, ttl=600):
        if not self._due("fng", ttl):
            return self.fng
        self._mark("fng")
        j = self._get(FNG, {"limit": 1})
        try:
            d = (j or {}).get("data", [])[0]
            self.fng = {"value": int(d.get("value", 0)),
                        "label": d.get("value_classification", ""),
                        "ts": int(d.get("timestamp", 0))}
        except Exception:
            pass
        return self.fng

    # ---------------- futures (funding / OI / long-short) ----------------
    def refresh_futures(self, symbols, ttl=90):
        if not self._due("futures", ttl):
            return self.futures
        self._mark("futures")
        out = {}
        for sym in symbols[:6]:
            rec = {}
            prem = self._get(FAPI_PREMIUM, {"symbol": sym})
            try:
                rec["funding"] = round(float(prem.get("lastFundingRate", 0)) * 100, 4)
            except Exception:
                pass
            oi = self._get(FAPI_OI, {"symbol": sym, "period": "5m", "limit": 2})
            try:
                rec["oi"] = float(oi[-1].get("sumOpenInterest", 0))
                rec["oi_usd"] = float(oi[-1].get("sumOpenInterestValue", 0))
                prev = float(oi[-2].get("sumOpenInterestValue", 0)) if len(oi) > 1 else 0.0
                rec["oi_chg_pct"] = round((rec["oi_usd"] - prev) / prev * 100, 3) if prev > 0 else 0.0
            except Exception:
                pass
            lsr = self._get(FAPI_LSR, {"symbol": sym, "period": "5m", "limit": 1})
            try:
                rec["lsr"] = round(float(lsr[-1].get("longShortRatio", 0)), 3)
                rec["long_pct"] = round(float(lsr[-1].get("longAccount", 0)) * 100, 1)
            except Exception:
                pass
            if rec:
                out[sym] = rec
        if out:
            with self.lock:
                self.futures = out
        return self.futures

    # ---------------- news / social / keyword engine ----------------
    def _get_text(self, url, params=None, timeout=10):
        try:
            r = self.s.get(url, params=params, timeout=timeout)
            if r.status_code == 200:
                self._error.pop(url, None)      # health reflects the LAST attempt
                return r.text
            self._error[url] = "HTTP %s" % r.status_code
        except Exception as e:
            self._error[url] = type(e).__name__
        return None

    @staticmethod
    def _clean_html(s):
        s = s or ""
        # RSS wraps titles/descriptions in CDATA. Unwrap it BEFORE stripping
        # tags: "<![CDATA[ ... ]]>" starts with "<" and ends with ">", so a naive
        # tag strip eats the whole title and the item is dropped as empty.
        s = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", s, flags=re.S)
        s = re.sub(r"<[^>]+>", "", s)
        s = s.replace("]]>", "")
        for a, b in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&#39;", "'"),
                     ("&quot;", '"'), ("&nbsp;", " "), ("&#8217;", "'"), ("&#8216;", "'")):
            s = s.replace(a, b)
        return re.sub(r"\s+", " ", s).strip()

    @staticmethod
    def _parse_date(s):
        s = (s or "").strip()
        if not s:
            return 0
        try:
            return int(email.utils.parsedate_to_datetime(s).timestamp() * 1000)
        except Exception:
            pass
        try:            # Atom / ISO-8601 (Reddit .rss, <updated>/<published>)
            return int(_dt.fromisoformat(s.replace("Z", "+00:00")).timestamp() * 1000)
        except Exception:
            return 0

    def _rss_items(self, xml, limit=20):
        """Handles both RSS <item> and Atom <entry> documents."""
        out = []
        if not xml:
            return out
        for m in re.finditer(r"<(item|entry)\b[^>]*>(.*?)</\1>", xml, re.S):
            blk = m.group(2)
            t = re.search(r"<title[^>]*>(.*?)</title>", blk, re.S)
            if not t:
                continue
            title = self._clean_html(t.group(1))
            if not title:
                continue
            d = (re.search(r"<pubDate>(.*?)</pubDate>", blk, re.S)
                 or re.search(r"<(?:published|updated)>(.*?)</(?:published|updated)>", blk, re.S))
            l = re.search(r"<link>(.*?)</link>", blk, re.S)
            if not l:                                   # Atom puts the URL in the tag
                l = re.search(r"<link[^>]*\bhref=[\"']([^\"']+)[\"']", blk)
            out.append({"title": title,
                        "ts": self._parse_date(d.group(1)) if d else 0,
                        "url": self._clean_html(l.group(1)) if l else ""})
        return out[:limit]

    def refresh_headlines(self, ttl=240):
        """Official Binance announcements + crypto news RSS + Reddit social, unified."""
        if not self._due("headlines", ttl):
            return self.headlines
        self._mark("headlines")
        rows = []
        for n in self.news[:20]:
            rows.append({"kind": "official", "source": "Binance",
                         "title": n.get("title", ""), "ts": n.get("ts", 0),
                         "url": ("https://www.binance.com/en/support/announcement/" + n["code"])
                                if n.get("code") else ""})
        for name, url in RSS_FEEDS:
            for it in self._rss_items(self._get_text(url), limit=15):
                rows.append({"kind": "news", "source": name, "title": it["title"],
                             "ts": it["ts"], "url": it["url"]})
        # Reddit: Atom first (open), JSON only if the Atom read came back empty
        social = self._rss_items(self._get_text(REDDIT_RSS), limit=30)
        for it in social:
            rows.append({"kind": "social", "source": "r/CryptoCurrency",
                         "title": it["title"], "ts": it["ts"], "url": it["url"]})
        if not social:
            j = self._get(REDDIT_URL, {"limit": 40})
            try:
                for c in ((j or {}).get("data", {}) or {}).get("children", []) or []:
                    d = c.get("data", {}) or {}
                    title = (d.get("title") or "").strip()
                    if title:
                        rows.append({"kind": "social", "source": "r/CryptoCurrency",
                                     "title": title,
                                     "ts": int(float(d.get("created_utc") or 0) * 1000),
                                     "url": "https://www.reddit.com" + (d.get("permalink") or "")})
            except Exception:
                pass
        if rows:
            rows.sort(key=lambda x: x.get("ts", 0), reverse=True)
            with self.lock:
                # keep room for every source: 20 official + 6x15 news + 30 social
                self.headlines = rows[:180]
        return self.headlines

    def _match_bases(self, text, uni_set):
        """Keyword-match a headline to the coin universe. Returns a set of USDT symbols."""
        low = text.lower()
        hit = set()
        for base in uni_set:
            alias_hit = any(a in low for a in COIN_ALIASES.get(base, ()))
            if base in GENERIC_ONLY:
                tick_hit = bool(re.search(r"\$" + re.escape(base) + r"\b", text))
            else:
                tick_hit = bool(re.search(r"\$" + re.escape(base) + r"\b", text)
                               or re.search(r"\b" + re.escape(base) + r"\b", text))
            if tick_hit or alias_hit:
                hit.add(base + "USDT")
        return hit

    def rebuild_catalysts(self, universe):
        """Score every headline with the bull/bear keyword engine and map it onto coins."""
        uni = {s[:-4] for s in (universe or []) if s.endswith("USDT") and s[:-4]}
        scores = defaultdict(float)
        cats = []
        for h in self.headlines:
            text = h.get("title", "")
            low = text.lower()
            bull = sum(1 for k in KEY_BULL if k in low)
            bear = sum(1 for k in KEY_BEAR if k in low)
            if not bull and not bear:
                continue
            weight = 2.0 if h.get("kind") == "official" else 1.5 if h.get("kind") == "news" else 1.0
            magnitude = (bull - bear) * weight
            for sym in self._match_bases(text, uni):
                scores[sym] += magnitude
                d = "BULL" if magnitude > 0 else "BEAR"
                cats.append({"symbol": sym, "dir": d, "kind": h.get("kind", "news"),
                             "source": h.get("source", ""), "title": text,
                             "url": h.get("url", ""), "ts": h.get("ts", 0),
                             "strength": round(magnitude, 1)})
        cats.sort(key=lambda x: (-abs(x["strength"]), -x["ts"]))
        with self.lock:
            self.news_scores = {k: round(v, 2) for k, v in scores.items()}
            self.catalysts = cats[:60]
        return self.news_scores

    def news_score(self, symbol):
        try:
            return float(self.news_scores.get(symbol, 0) or 0)
        except (TypeError, ValueError):
            return 0.0

    def catalyst(self, symbol):
        """Newest BULL catalyst for a symbol (or None)."""
        for c in self.catalysts:
            if c["symbol"] == symbol and c["dir"] == "BULL":
                return c
        return None

    # ---------------- whale tape ----------------
    def scan_whales(self, symbol, trades, price):
        """Detect aggressive block trades. Uses trades already fetched by scan_market."""
        parsed = []
        for t in trades or []:
            try:
                p = float(t.get("p", 0))
                q = float(t.get("q", 0))
            except (TypeError, ValueError):
                continue
            if p <= 0 or q <= 0:
                continue
            parsed.append((p * q, p, q, bool(t.get("m", False)), int(t.get("T", 0) or 0)))
        if not parsed:
            return []
        med = self._median([x[0] for x in parsed])
        thr = max(WHALE_MIN_USD, med * WHALE_MULT)
        caught = []
        for notional, p, q, maker, ts in parsed:
            if notional >= thr:
                caught.append({
                    "symbol": symbol,
                    "side": "SELL" if maker else "BUY",
                    "notional": round(notional, 2),
                    "price": p, "qty": q,
                    "ts": ts or int(time.time() * 1000),
                })
        if caught:
            caught.sort(key=lambda x: x["notional"], reverse=True)
            with self.lock:
                self.whales = (caught + self.whales)[:WHALE_TAPE_MAX]
        return caught

    # ---------------- whale walls ----------------
    def scan_walls(self, symbol, order_book):
        if not order_book:
            return []
        levels = []
        for side, arr in (("BID", order_book.get("bids", []) or []),
                          ("ASK", order_book.get("asks", []) or [])):
            for lv in arr[:50]:
                try:
                    p = float(lv[0])
                    q = float(lv[1])
                except (TypeError, ValueError, IndexError):
                    continue
                if p > 0 and q > 0:
                    levels.append((p * q, side, p, q))
        if not levels:
            return []
        med = self._median([x[0] for x in levels])
        thr = max(WALL_MIN_USD, med * WALL_MULT)
        caught = [{"symbol": symbol, "side": s, "notional": round(n, 2), "price": p, "qty": q}
                  for n, s, p, q in levels if n >= thr]
        if caught:
            caught.sort(key=lambda x: x["notional"], reverse=True)
            with self.lock:
                self.walls = (caught[:WALL_MAX] + self.walls)[:WALL_MAX]
        return caught

    # ---------------- volume surge (no network) ----------------
    def set_volume_surge(self, results):
        rows = []
        for r in results or []:
            try:
                vr = float(r.get("volume_ratio", 0) or 0)
            except (TypeError, ValueError):
                continue
            if vr >= 2.0:
                rows.append({"symbol": r.get("symbol"), "volume_ratio": round(vr, 2),
                             "momentum_5m": r.get("momentum_5m", 0),
                             "price": r.get("current_price"),
                             "score": r.get("order_flow_score", 0)})
        rows.sort(key=lambda x: x["volume_ratio"], reverse=True)
        with self.lock:
            self.volume_surge = rows[:25]
        return self.volume_surge

    # ---------------- scoring bias ----------------
    def trending_set(self):
        return {(t.get("symbol") or "").upper() for t in self.trending}

    def whale_net(self, symbol):
        net = 0.0
        for w in self.whales:
            if w["symbol"] == symbol:
                net += w["notional"] if w["side"] == "BUY" else -w["notional"]
        return net

    def bias(self, symbol, base):
        """Bounded feed contribution to a symbol's score + human-readable flags."""
        flags = []
        adj = 0
        net = self.whale_net(symbol)
        if net > 0:
            adj += 4
            flags.append("whale+")
        elif net < 0:
            adj -= 4
            flags.append("whale-")
        if base and base in self.trending_set():
            adj += 3
            flags.append("trending")
        f = self.futures.get(symbol)
        if f:
            if f.get("oi_chg_pct", 0) > 1.0:
                adj += 2
                flags.append("OI+")
            if abs(f.get("funding", 0)) > 0.05:
                adj -= 2
                flags.append("funding")
        ns = self.news_score(symbol)
        if ns >= 4:
            adj += 6
            flags.append("news+")
        elif ns > 0:
            adj += 3
            flags.append("news")
        elif ns <= -4:
            adj -= 6
            flags.append("news!")
        elif ns < 0:
            adj -= 3
            flags.append("news-")
        return max(-10, min(10, adj)), flags

    # ---------------- agent catches ----------------
    def record_catch(self, agent, kind, detail, symbol=""):
        with self.lock:
            self.catches = ([{"ts": int(time.time() * 1000), "agent": agent,
                              "kind": kind, "symbol": symbol, "detail": detail}]
                            + self.catches)[:40]

    # ---------------- API snapshot ----------------
    def snapshot(self):
        def ok(x):
            return "ok" if x else "waiting"

        def note(url, n, unit="rows"):
            """Why a source is green or grey — the last error, never a guess."""
            if n:
                return "%d %s" % (n, unit)
            return self._error.get(url) or "no rows"

        def hl(source):
            return [h for h in self.headlines if h.get("source") == source]

        sources = [{"name": "Binance Announcements", "kind": "news",
                    "status": ok(self.news), "note": note(CMS, len(self.news), "announcements")}]
        for _name, _url in RSS_FEEDS:
            _n = len(hl(_name))
            sources.append({"name": "%s RSS" % _name, "kind": "headlines",
                            "status": ok(_n), "note": note(_url, _n)})
        _n = len([h for h in self.headlines if h.get("kind") == "social"])
        sources.append({"name": "Reddit r/CryptoCurrency", "kind": "social",
                        "status": ok(_n), "note": note(REDDIT_RSS, _n)})
        sources += [
            {"name": "Keyword Catalyst Engine", "kind": "catalysts",
             "status": ok(self.catalysts), "note": "%d catalysts" % len(self.catalysts)},
            {"name": "CoinGecko Trending", "kind": "trending",
             "status": ok(self.trending), "note": "%d coins" % len(self.trending)},
            {"name": "Fear & Greed Index", "kind": "sentiment",
             "status": ok(self.fng), "note": (self.fng or {}).get("label") or "—"},
            {"name": "Binance Futures OI/Funding/LSR", "kind": "derivatives",
             "status": ok(self.futures), "note": "%d markets" % len(self.futures)},
            {"name": "Binance aggTrades — whale tape", "kind": "whales",
             "status": ok(self.whales), "note": "%d blocks" % len(self.whales)},
            {"name": "Binance depth — whale walls", "kind": "walls",
             "status": ok(self.walls), "note": "%d walls" % len(self.walls)},
            {"name": "1m klines — volume surge", "kind": "volume",
             "status": ok(self.volume_surge), "note": "%d surging" % len(self.volume_surge)},
        ]
        return {
            "news": self.news[:12],
            "headlines": self.headlines[:30],
            "catalysts": self.catalysts[:24],
            "trending": self.trending[:12],
            "fng": self.fng,
            "futures": self.futures,
            "whales": self.whales[:25],
            "walls": self.walls[:15],
            "volume_surge": self.volume_surge[:20],
            "catches": self.catches[:20],
            "sources": sources,
        }
