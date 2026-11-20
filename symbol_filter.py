"""What the hunter is allowed to hunt.

One place decides which Binance pairs are *not* snipeable, so every path that
builds a candidate list — the full market sweep, the First-Move Radar, the
pre-pump watch, the signal ledger, the alert book — reaches the same answer.
Keeping this in a tiny module (rather than in app.py) means pregainers.py and
signals.py can use it without a circular import.

Two exclusions, for two different reasons:

1. Pegged assets have no volatility to snipe: USD stablecoins, fiat pegs and
   gold/commodity pegs. A "pump" there is a peg wobble, not a move. This is
   quote-agnostic on purpose: USDCUSDT, USDTTRY, EURUSDT and PAXGUSDT are all
   pegs wherever they are quoted, so the check must not depend on the "USDT"
   suffix alone.
2. Tokenised equities and ETFs (Binance quotes them as "<TICKER>B" + USDT,
   e.g. GOOGLBUSDT, QQQBUSDT, MSTRBUSDT) move on equity-session news and stop
   when Wall Street closes. The hunter's exits are built for 24/7 crypto
   volatility, so a pre-pump there is a stock gapping and the plan behind it
   describes nothing. Excluding them keeps the small-cap radar crypto-only.

Real crypto bases that happen to end in "B" (BNB, ARB, SHIB, CKB, DGB, TRB,
PENGB, BB, ZMB, QNTB...) are deliberately NOT in the tokenised set.
"""

# Quote assets Binance actually lists. Longest first — base_of() strips the
# first match, so "BTCUSDT" must be tested before any shorter suffix.
QUOTES = (
    "USDT", "FDUSD", "USDC", "TUSD", "BUSD", "BIDR", "IDRT", "USDP", "DAI",
    "BTC", "ETH", "BNB", "TRY", "EUR", "GBP", "BRL", "ARS", "ZAR", "NGN",
    "RUB", "UAH", "PLN", "RON", "CZK", "JPY", "AUD", "BKRW", "BVND",
)

# Pegged assets — no volatility to snipe, so they are never hunted or listed.
STABLE_BASES = {
    # USD stablecoins (incl. the newer synthetic / yield-bearing pegs)
    "USDT", "USDC", "FDUSD", "TUSD", "USDP", "USDD", "USDE", "USDS", "USDG",
    "USDY", "PYUSD", "GUSD", "SUSD", "BUSD", "DAI", "FRAX", "USTC", "UST",
    "MIM", "LUSD", "USD1", "XUSD", "USDR", "USDX", "USD0", "USDT0", "USDF",
    "USDB", "USDA", "USDH", "USDQ", "USDL", "AUSD", "RLUSD", "GHO", "DOLA",
    "ALUSD", "CRVUSD", "SUSDE", "SUSDS", "BUIDL", "USDBC", "USDCE", "USDJ",
    "USDK", "USDO", "USDPT", "USDV", "USDZ", "VUSD", "ZUSD", "EURC", "EURS",
    "EURT", "GYEN", "JPYC", "XSGD", "XIDR", "BRZ", "CADC", "TRYB", "BIDR",
    # fiat bases Binance quotes directly against crypto
    "EUR", "EURI", "AEUR", "GBP", "TRY", "BRL", "ARS", "ZAR", "NGN", "RUB",
    "UAH", "PLN", "RON", "CZK", "JPY", "AUD", "IDRT", "BKRW",
    # gold / commodity pegs
    "XAUT", "PAXG", "USD",
}

# Binance tokenised equity / ETF receipts. Built from a live exchangeInfo sweep
# (TRADING, USDT quote, base ending in "B", 1-5 char stem) and then filtered by
# hand to keep the genuine crypto bases out of it.
TOKENISED_BASES = frozenset("""
AAPLB ADBEB AGPUB ALABB AMATB AMCB AMDB AMZNB ARMB ASMLB ASTSB AVGOB AXTIB
BABAB BMNRB BNCB CBRSB COHRB COINB CRCLB CRDOB CRMB CRWDB CRWVB CYPHB DELLB
DJTB DRAMB EWYB FLNCB FWDIB GLWB GMEB GOOGLB GPROB GSB HIMSB HOODB HPEB IBMB
INTCB INTWB IRENB JPMB KORUB LITEB LLYB MDBB METAB MRNAB MRVLB MSFTB MSTRB MUB
MUUB MVLLB NBISB NFLXB NOKB NVDAB ORCLB PDDB PLTRB PYPLB QCOMB QQQB RDDTB RKLBB
SECZB SHAZB SKHYB SMCIB SMHB SNDKB SNXXB SOXLB SOXSB SPCXB SPYB SQQQB STXB
TQQQB TSLAB TSMB USARB USDEB UVXYB WDCB WENB
""".split())


def base_of(symbol):
    """Base asset of a Binance pair, without trusting one quote suffix."""
    s = (symbol or "").upper().replace("/", "").replace("-", "")
    for q in QUOTES:
        if s.endswith(q) and len(s) > len(q):
            return s[: -len(q)]
    return s


def is_pegged(symbol):
    """True for a pegged asset (stablecoin / fiat / commodity) — never hunted.

    Quote-agnostic: the base is resolved first, then judged. That catches
    USDCUSDT, USDTTRY, EURUSDT, FDUSDUSDT and bare stablecoin bases alike.
    """
    base = base_of(symbol)
    if not base:
        return False
    return base in STABLE_BASES or base.endswith("USD")


def is_tokenised(symbol):
    """True for a tokenised equity/ETF receipt — never hunted."""
    return base_of(symbol) in TOKENISED_BASES


def huntable(symbol):
    """The single question every candidate list should ask."""
    return bool(symbol) and not is_pegged(symbol) and not is_tokenised(symbol)
