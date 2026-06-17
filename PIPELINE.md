# ORB-D1+VOL Pipeline

## Schedule (UTC → PKT)

| Server (UTC) | PKT (UTC+5) | Candle |
|:--|:--|:--|
| 03:10 | **08:10** | After 1st candle close (range set) |
| 07:10 | **12:10** | After 2nd candle |
| 11:10 | **16:10** | After 3rd candle |
| 15:10 | **20:10** | After 4th candle |
| 19:10 | **00:10** | After 5th candle |
| 23:10 | **04:10** | After 6th candle |

> **Note:** The OR candle (UTC 00:00–04:00 / PKT 05:00–09:00) is the range-setter — no check runs during it since breakouts are impossible.

## 3-Step Flow

```
┌──────────────────────────────────────────────────────────────────┐
│  Step 1: SCORE                                                   │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  orb_screener_score.py                                      │  │
│  │  ├─ Fetch 400 4H candles from Binance (8 coins)            │  │
│  │  ├─ Find first candle of UTC day → OR range (high/low)     │  │
│  │  ├─ Compute Volume SMA(20), ATR(14)                        │  │
│  │  └─ Check last closed candle:                               │  │
│  │      ├─ Price > OR-high AND volume ≥ 1.5× SMA20 → ▲ LONG   │  │
│  │      ├─ Price < OR-low  AND volume ≥ 1.5× SMA20 → ▼ SHORT  │  │
│  │      └─ Else → LOWVOL or RANGE                              │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│  Step 2: CHECK                                                   │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  screener_no_agent.py (after parsing signals)               │  │
│  │  ├─ Check MEXC futures balance (min $10)                   │  │
│  │  ├─ List open positions (max 3 concurrent)                 │  │
│  │  └─ Skip if no slots or low balance                        │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│  Step 3: EXECUTE                                                 │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  For each signal not already in a position:                 │  │
│  │  ├─ mexc_api.py buy/sell <symbol> <qty> <leverage>         │  │
│  │  ├─ Wait 3s, verify position appeared                      │  │
│  │  └─ Report result                                          │  │
│  └────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

## Entry Logic

```
Condition                     → Action
─────────────────────────────────────────────────────────
Price > OR-high, Vol ≥ 1.5×  → LONG @ market
Price < OR-low , Vol ≥ 1.5×  → SHORT @ market
Vol < 1.5×                   → Skip (LOWVOL)
Still in OR candle           → Skip (RANGE SETTING)
Same day as last trade       → Skip (1 trade/day)
Already in position on coin  → Skip
```

## Exit Logic

| Stage | Rule |
|-------|------|
| **Initial SL** | 2× ATR from entry price |
| **Trail activation** | Profit ≥ 1.0× ATR (as % of entry) |
| **Trail distance** | 0.40× ATR callback from peak |

## Watchdog Monitoring

The pipeline is **no_agent=True** — pure Python, no LLM, minimal latency.
- Non-empty stdout = verbatim report delivered to Discord
- Empty stdout = silent (nothing to report)
- Non-zero exit / timeout → error alert sent

## Files Involved

| File | Role |
|------|------|
| `screener_no_agent.py` | Cron entry point: orchestration |
| `orb_screener_score.py` | Signal computation from Binance data |
| `mexc_api.py` | MEXC Futures API (auth, execution) |
| `backtest_365d.py` | Offline backtesting only |
| `mexc_config.json` | API credentials (**not in repo**) |
