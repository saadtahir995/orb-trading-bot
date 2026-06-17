#!/usr/bin/env python3
"""ORB-D1+VOL backtest over last 365 days only. Fetches data in chunks."""
import json, sys, urllib.request, time, math
from datetime import datetime, timezone, timedelta

BASE = "https://api.binance.com"
INITIAL_CAP = 1000.0
COMMISSION = 0.0004

def load_data_yearly(symbol, interval="4h", days=365):
    """Fetch up to `days` of 4H candles via paginated requests."""
    ms = days * 24 * 3600 * 1000
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - ms
    limit = 1000
    all_k = []
    while start_ms < end_ms:
        url = f"{BASE}/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}&startTime={start_ms}"
        try:
            with urllib.request.urlopen(url, timeout=15) as r:
                batch = json.loads(r.read())
        except Exception as e:
            print(f"  [Error] {symbol}: {e}", file=sys.stderr)
            break
        if not batch:
            break
        all_k.extend(batch)
        start_ms = batch[-1][0] + 1  # next after last candle's open time
        time.sleep(0.1)
    # Trim to exact start boundary
    cutoff = end_ms - ms
    return [k for k in all_k if k[0] >= cutoff]

def compute_orb_backtest(k):
    n = len(k)
    if n < 100:
        return None
    c = [float(x[4]) for x in k]
    h = [float(x[2]) for x in k]
    l = [float(x[3]) for x in k]
    v = [float(x[5]) for x in k]
    ts = [x[0] for x in k]

    # ATR(14)
    atr = [0.0] * n
    for i in range(1, n):
        tr = max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1]))
        if i < 14:
            atr[i] = (atr[i-1]*(i-1)+tr)/i if i > 1 else tr
        else:
            atr[i] = (atr[i-1]*13+tr)/14

    # Volume SMA20
    vsma = [None] * n
    for i in range(19, n):
        vsma[i] = sum(v[i-19:i+1]) / 20

    # Day tracking + OR tracking (live: updates as day progresses)
    day_id = [-1]*n
    day_or_high = [None]*n
    day_or_low = [None]*n
    day_or_idx = [-1]*n
    cur_day = -1
    cur_oh = None
    cur_ol = None
    cur_oi = -1

    for i in range(n):
        dt = datetime.fromtimestamp(ts[i]/1000, tz=timezone.utc)
        if i == 0 or dt.date() != datetime.fromtimestamp(ts[i-1]/1000, tz=timezone.utc).date():
            cur_day += 1
            cur_oh = h[i]
            cur_ol = l[i]
            cur_oi = i
        else:
            cur_oh = max(cur_oh, h[i])
            cur_ol = min(cur_ol, l[i])
        day_id[i] = cur_day
        day_or_high[i] = cur_oh
        day_or_low[i] = cur_ol
        day_or_idx[i] = cur_oi

    # Warm-up: need at least 60 candles before reliable tracking
    start_idx = max(60, n - 2190)  # start from ~365 days ago or later
    if start_idx >= n:
        return None

    bal = INITIAL_CAP
    trades = []
    op = None
    last_trade_day = -1

    for idx in range(start_idx, n):
        ci = c[idx]
        atr_pct = (atr[idx]/ci)*100 if ci > 0 else 0
        if atr_pct <= 0:
            continue

        oi = day_or_idx[idx]
        oh = day_or_high[oi] if oi >= 0 else None
        ol = day_or_low[oi] if oi >= 0 else None

        # ── Position management ──────────────────────────────────────
        if op:
            _, side, ep, sl, ate_val, trailing, hw, lw = op
            if side == "long":
                if trailing:
                    hw = max(hw, ci)
                    new_sl = hw - (1.0 * ate_val / 100 * ep)
                    sl = max(sl, new_sl)
                    if ci <= sl:
                        ret = (sl - ep) / ep - COMMISSION
                        bal *= (1 + ret)
                        trades[-1]["r"] = round(ret * 100, 2)
                        trades[-1]["c"] = "TRAIL"
                        op = None
                        continue
                else:
                    if ci <= sl:
                        ret = (sl - ep) / ep - COMMISSION
                        bal *= (1 + ret)
                        trades[-1]["r"] = round(ret * 100, 2)
                        trades[-1]["c"] = "SL"
                        op = None
                        continue
                    if (ci - ep) / ep * 100 >= 1.0 * ate_val:
                        trailing = True
                        hw = ci
                        sl = ci - (1.0 * ate_val / 100 * ep)
                        op = (idx, "long", ep, sl, ate_val, True, hw, lw)
                        continue
            else:  # short
                if trailing:
                    lw = min(lw, ci)
                    new_sl = lw + (1.0 * ate_val / 100 * ep)
                    sl = min(sl, new_sl)
                    if ci >= sl:
                        ret = (ep - sl) / ep - COMMISSION
                        bal *= (1 + ret)
                        trades[-1]["r"] = round(ret * 100, 2)
                        trades[-1]["c"] = "TRAIL"
                        op = None
                        continue
                else:
                    if ci >= sl:
                        ret = (ep - sl) / ep - COMMISSION
                        bal *= (1 + ret)
                        trades[-1]["r"] = round(ret * 100, 2)
                        trades[-1]["c"] = "SL"
                        op = None
                        continue
                    if (ep - ci) / ep * 100 >= 1.0 * ate_val:
                        trailing = True
                        lw = ci
                        sl = ci + (1.0 * ate_val / 100 * ep)
                        op = (idx, "short", ep, sl, ate_val, True, lw, lw)
                        continue
            continue  # position still open, wait for next candle

        # ── Entry logic: ORB-D1+VOL ──────────────────────────────────
        if oh is None or ol is None:
            continue
        if oi >= 0 and idx == oi:
            continue  # skip range-establishing candle
        if day_id[idx] == last_trade_day:
            continue  # one trade per day

        # Volume filter
        vs = vsma[idx]
        if vs is not None and vs > 0 and v[idx] < vs * 1.5:
            continue

        if ci > oh:  # LONG breakout
            sp = 2.0 * atr_pct
            sl_price = ci * (1 - sp / 100)
            trades.append({"s": "long_orb", "ep": ci, "ts": ts[idx]})
            op = (idx, "long", ci, sl_price, atr_pct, False, ci, ci)
            last_trade_day = day_id[idx]
        elif ci < ol:  # SHORT breakout
            sp = 2.0 * atr_pct
            sl_price = ci * (1 + sp / 100)
            trades.append({"s": "short_orb", "ep": ci, "ts": ts[idx]})
            op = (idx, "short", ci, sl_price, atr_pct, False, ci, ci)
            last_trade_day = day_id[idx]

    # Close any open position
    if op:
        _, side, ep, sl, _, _, _, _ = op
        ret = (c[-1] - ep) / ep if side == "long" else (ep - c[-1]) / ep
        ret -= COMMISSION
        bal *= (1 + ret)
        trades[-1]["r"] = round(ret * 100, 2)
        trades[-1]["c"] = "OPEN"

    return trades, bal, start_idx, n


# Timerange
days = 365
now = datetime.now(timezone.utc)
start_dt = now - timedelta(days=days)

coins = [
    ("BTCUSDT", "BTC"), ("ETHUSDT", "ETH"), ("SOLUSDT", "SOL"),
    ("POLUSDT", "POL"),
    ("SHIBUSDT", "SHIB"),
    ("SUIUSDT", "SUI"), ("NEARUSDT", "NEAR"), ("ARBUSDT", "ARB"),
]

print(f"📊 ORB-D1+VOL — Last 365 days only")
print(f"  Period: {start_dt.strftime('%Y-%m-%d')} → {now.strftime('%Y-%m-%d')}")
print(f"  SL: 2×ATR | Trail: 1.0× act + 1.0× dist | Vol filter: >1.5× SMA20")
print(f"  Risk: 2%/trade | Commission: 0.04%")
print(f"  {'─'*75}")
print(f"  {'Coin':<6} {'Trades':>6} {'Win%':>6} {'PF':>5} {'CAGR':>9} {'Total%':>8} {'AvgW%':>6} {'AvgL%':>6} {'MaxDD':>7}")
print(f"  {'─'*75}")

all_trades = []

for sym, name in coins:
    k = load_data_yearly(sym, days=days)
    result = compute_orb_backtest(k)
    if result is None:
        print(f"  {name:<6} {'NO DATA':>6}")
        continue
    trades, bal, s_idx, n = result

    total = len(trades)
    if total == 0:
        print(f"  {name:<6} {'0 trades':>12}")
        continue

    wins = sum(1 for t in trades if t["r"] > 0)
    losses = total - wins
    wr = wins / total * 100 if total > 0 else 0
    gp = sum(t["r"] for t in trades if t["r"] > 0)
    gl = abs(sum(t["r"] for t in trades if t["r"] <= 0))
    pf = gp / gl if gl > 0 else float("inf")
    avg_w = gp / wins if wins > 0 else 0
    avg_l = gl / losses if losses > 0 else 0
    ret_pct = (bal - INITIAL_CAP) / INITIAL_CAP * 100
    cagr = ((bal / INITIAL_CAP) ** (365.0 / days) - 1) * 100  # annualize

    # Max drawdown
    running_cap = INITIAL_CAP
    peak = INITIAL_CAP
    max_dd = 0.0
    for t in trades:
        running_cap *= (1 + t["r"] / 100)
        if running_cap > peak:
            peak = running_cap
        dd = (peak - running_cap) / peak * 100
        if dd > max_dd:
            max_dd = dd

    print(f"  {name:<6} {total:>6d} {wr:>5.1f}% {pf:>5.2f} {cagr:>+8.1f}% {ret_pct:>+7.1f}% {avg_w:>+5.2f}% {avg_l:>5.2f}% {max_dd:>6.1f}%")
    
    for t in trades:
        all_trades.append(t)
    time.sleep(0.05)

# Portfolio aggregation (simple average per-trade return)
if all_trades:
    total = len(all_trades)
    wins = sum(1 for t in all_trades if t["r"] > 0)
    losses = total - wins
    wr = wins / total * 100
    gp = sum(t["r"] for t in all_trades if t["r"] > 0)
    gl = abs(sum(t["r"] for t in all_trades if t["r"] <= 0))
    pf = gp / gl if gl > 0 else float("inf")

    # Portfolio compounding (trade each coin in sequence as equal-weight)
    port_bal = INITIAL_CAP
    for coin_trades in [compute_orb_backtest(load_data_yearly(sym, days=days)) for sym, _ in coins]:
        if coin_trades:
            trades, bal, _, _ = coin_trades
            for t in trades:
                port_bal *= (1 + t["r"] / 100)

    port_ret = (port_bal - INITIAL_CAP) / INITIAL_CAP * 100
    port_cagr = ((port_bal / INITIAL_CAP) ** (365.0 / days) - 1) * 100

    running = INITIAL_CAP
    peak = INITIAL_CAP
    max_dd = 0.0
    for coin_trades in [compute_orb_backtest(load_data_yearly(sym, days=days)) for sym, _ in coins]:
        if coin_trades:
            trades, _, _, _ = coin_trades
            for t in trades:
                running *= (1 + t["r"] / 100)
                if running > peak:
                    peak = running
                dd = (peak - running) / peak * 100
                if dd > max_dd:
                    max_dd = dd

    print(f"  {'─'*75}")
    print(f"  {'PORTFOLIO':<6} {total:>6d} {wr:>5.1f}% {pf:>5.2f} {port_cagr:>+8.1f}% {port_ret:>+7.1f}% {'':>6} {'':>6} {max_dd:>6.1f}%")
    print(f"  {'─'*75}")
