# Binance-Hunter Enhancement Plan

This document lists the enhancements applied to the cloned `G:\Binance-Hunter` project.
The original project at `G:\GrokMT5Bot\binance_hunter` was NOT modified.

## Phase 1: Security (COMPLETED)

### Blanked secrets in `.env`
- `BINANCE_API_KEY` — emptied (was a live key)
- `BINANCE_API_SECRET` — emptied (was a live secret)
- `TELEGRAM_BOT_TOKEN` — emptied (was a live token)
- `TELEGRAM_CHAT_ID` — emptied
- `TELEGRAM_PREPUMP_CHAT_ID` — emptied
- `ALTFINS_API_KEY` — emptied (was a live key)

### Added `.gitignore`
- `.env`, `*.log`, `*.pid`, `*.json`, `__pycache__/`, `*.pyc`, `*.bak`, `*.old`, `.hunter/`, `secrets/`

### Removed from clone
- `.git` directory (no git history carried over)
- `hunter.pid`

---

## Phase 2: Strategy Enhancements (PLANNED)

### 2.1 Positive expectancy rework
All three backtest evals were REJECTED with negative expectancy (-0.72% to -3.34% per trade) and 75.6% max drawdown.
- Rework entry logic to target positive expectancy (>0% per trade)
- Target max drawdown < 15% (was 75.6%)
- Add slippage/friction modeling to backtests
- Extend test period to 5+ years across multiple regimes

### 2.2 Risk rule tightening
- Daily loss cap: keep -15% but consider reducing to -10%
- Max position fraction: 65% is aggressive for small accounts; consider 30-50%
- Risk per trade: 10% is aggressive; consider 2-5% until expectancy is proven
- Add correlation check to avoid multiple positions in same-sector coins

---

## Phase 3: Dashboard Enhancements (PLANNED)

### 3.1 Buy / Sell buttons with confirmation
- Add "Buy" and "Sell" buttons to the Trade Plan panel
- Confirmation dialog before sending to `/enter` API
- Visual feedback (toast) on success/failure

### 3.2 Equity curve / drawdown visualization
- Add an equity curve panel (canvas or SVG)
- Track daily P&L history from `/api/results`
- Show drawdown from peak
- Color code: green for new equity highs, red for drawdown

### 3.3 Position P&L progression
- Show unrealized P&L for open positions
- Mini sparkline per position showing P&L over time
- Time-in-position counter

### 3.4 Emergency kill switch
- Prominent red "KILL SWITCH" button
- Calls `/toggle` to pause + optional cancel all open orders
- Visual alert when active

### 3.5 Dark / light theme toggle
- CSS variables already defined; add theme switcher
- Persist preference in localStorage

### 3.6 Asset extraction
- Move inline CSS to `static/css/style.css`
- Move inline JS to `static/js/dashboard.js`
- Keep dashboard.html clean

### 3.7 Offline chart fallback
- If TradingView CDN fails, show a lightweight canvas candle chart from `/api/chart/<symbol>`
- Already have `/api/chart` endpoint; just need the renderer

---

## Phase 4: Code Cleanup (PLANNED)

- [ ] Archive or remove dead `_*.py` / `fix*.py` test scripts (move to `archive/`)
- [ ] Write root `README.md` with setup instructions
- [ ] Document `.env` required variables (example file `.env.example`)
- [ ] Remove `nify.py` if unused (verify first)

---

## Implementation Status

| Area | Status |
|------|--------|
| Security (blanked secrets, .gitignore) | ✅ DONE |
| Strategy rework | ⏳ PLANNED |
| Dashboard buy/sell buttons | ⏳ PLANNED |
| Equity curve / drawdown | ⏳ PLANNED |
| Emergency kill switch | ⏳ PLANNED |
| Dark/light theme | ⏳ PLANNED |
| Asset extraction | ⏳ PLANNED |
| Code cleanup | ⏳ PLANNED |
