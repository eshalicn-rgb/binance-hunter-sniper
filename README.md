# Binance Hunter (Rebuilt)

Autonomous Binance Spot trading agent for small accounts. Runs a Flask dashboard on **port 4564** with real-time market data, multi-timeframe structure analysis, and Telegram push notifications.

⚠️ **Security**: The `.env` file contains placeholder values. You MUST fill in your own API credentials before running. Never commit `.env` to version control.

## Quick Start

```bash
# 1. Install dependencies
pip install flask requests

# 2. Copy example env and fill in your credentials
cp .env.example .env
# Edit .env with your Binance API key/secret, Telegram bot token, etc.

# 3. Run the dashboard
python app.py

# 4. Open http://localhost:4564
```

## Features

### Dashboard (Port 4564)
- **Real-time HUD terminal** with dark/light theme toggle
- **Multi-timeframe structure analysis** (1m/5m/15m/1h/4h/1d) with Fibonacci & Gann levels
- **Order book + volume flow** with live Binance WebSocket data
- **Pre-pump radar** detecting coiled coins before they move
- **Swarm agent monitoring** (10 agents: coordinator, scanner, analyst, etc.)
- **Signal follow-up** with fronttest/backtest statistics
- **Equity curve & drawdown** visualization
- **Buy/Sell buttons** with confirmation dialogs
- **Emergency kill switch** (prominent red button)

### Trading Engine
- **Four entry paths**: Order-flow, Catalyst (news), Pre-pump, First-Move Radar
- **Hard risk limits**: Daily loss -15%, 3 consecutive losses → 30min pause, max position 65% equity
- **Order shaping**: Quantities shaped to Binance LOT_SIZE/MIN_NOTIONAL filters
- **Shadow mode**: `HUNTER_LIVE_ORDERS=0` for paper trading
- **Permission gate**: Probes `apiRestrictions` every 5min, never hammers 401 errors

### External Feeds (Keyless, Fail-Closed)
- News: Binance CMS + RSS (CoinDesk, Cointelegraph, etc.) + Reddit
- Trending: CoinGecko
- Fear & Greed: alternative.me
- Futures: Binance USD-M funding/OI/LSR
- Whale tape/walls from aggTrades & depth

### Validation
- **Fronttest**: Every signal marked against real 1m klines (MFE/MAE measured)
- **Backtest**: Structural rule replayed over symbol history
- **Signal ledger**: JSONL persisted, trimmed at 800 rows

## Architecture

```
app.py              # Core: Flask + Hunter class + BinanceClient
signals.py          # Signal ledger: fronttest + backtest + plan()
structure.py        # Pure kline structure: swings, BOS, CHoCH, volume profile, Gann time
ta.py               # Fibonacci + Gann + prepump coiled score
enhance.py          # Leading reads: momentum stack, squeeze, breakout, rel strength
feeds.py            # External feeds: news, trending, FNG, futures, whale tape/walls
alertbook.py        # Armed price/time alerts
notify.py           # Telegram HTML cards
symbol_filter.py    # huntable() — excludes pegged assets & tokenised equities
pregainers.py       # First-Move Radar via Node market_rank.mjs
regime.py           # Market regime gate
altfins.py          # AltFins bullish chart patterns (paid API)
tgtools.py          # Read-only Telegram command layer
chat.py             # AI CEO chatbrain (Ollama qwen3.5:4b)
```

## Dashboard Layout

| Row | Panels |
|-----|--------|
| 0 | Coin Search |
| 1 | Swarm Agents · Sniper Shortlist · Firing Gates |
| 2 | Chart (TradingView) · Order Book · Volume Flow |
| 3 | Fib & Gann Levels · Trade Plan (with Buy/Sell) · Signal Follow-Up |
| 4 | News & Catalysts · Source Feeds · AltFins |
| 5 | Pre-Pump Radar · Movers |

## API Endpoints

- `/api/status` — Full engine state
- `/api/ta/<symbol>` — Fib/Gann structure read
- `/api/plan/<symbol>` — Trade plan
- `/api/chart/<symbol>` — Candlestick data
- `/api/orderbook/<symbol>` — Live order book
- `/api/recent/<symbol>` — Recent trades
- `/api/signals` — Signal follow-up
- `/api/feeds` — External feeds
- `/api/prepump` — Pre-pump radar
- `/api/backtest/<symbol>` — Per-symbol backtest
- `/enter` — Manual entry (POST)

## Requirements

- Python 3.11+
- Flask, requests
- Node.js (for `pregainers.py` → `tools/market_rank.mjs`)
- Binance API key with Spot trading permission
- Telegram bot token (optional, for push cards)

## Security

- `.env` is in `.gitignore` — never committed
- `.env.example` shows required variables
- `HUNTER_LIVE_ORDERS=0` by default (shadow/paper mode)
- Binance API key should have **Spot trading only, no withdrawals**

## License

Private project — not for distribution.