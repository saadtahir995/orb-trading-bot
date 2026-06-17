# ORB-D1+VOL Trading Bot

**Opening Range Breakout strategy with volume confirmation filter** for crypto futures.

## Strategy

- **ORB-D1**: The first 4H candle of the UTC day (05:00–09:00 PKT) defines the opening range (OR-high, OR-low)
- **VOL**: Subsequent candles must break the range on **≥1.5× the 20-period volume SMA** for entry
- **Exit**: 2× ATR initial stop-loss → trailing stop at 1.0× ATR activation + 1.0× ATR callback distance
- **Risk**: 2% per trade | 0.04% commission

## Files

| File | Purpose |
|------|---------|
| `orb_screener_score.py` | Live screener — fetches Binance 4H data for 8 coins, computes signals |
| `screener_no_agent.py` | Cron job runner — parses screener output, checks MEXC account, executes trades |
| `mexc_api.py` | MEXC Futures API wrapper — auth, balance, positions, order execution |
| `backtest_365d.py` | 365-day backtest across the screener universe |

## Setup

1. Create `mexc_config.json` in the same directory:
```json
{"api_key": "your_key", "secret": "your_secret"}
```
2. Run the screener:
```bash
python3 orb_screener_score.py
```
3. Run the full pipeline (screener + trade execution):
```bash
python3 screener_no_agent.py
```

## 365-Day Backtest Results (Jun 2025 – Jun 2026)

| Metric | Value |
|--------|-------|
| Win Rate | 59.5% |
| Profit Factor | 1.68 |
| Portfolio CAGR | +134.6% |
| Max Drawdown | 47.1% |

## Live Screener

Runs via Hermes cron every 4 hours (after each non-OR candle closes). Valid signals are forwarded to MEXC futures for automated execution.
