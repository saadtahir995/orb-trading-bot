#!/usr/bin/env python3
"""
Crypto Screener — ORB-D1+VOL Live Scoring
Fetches 4H data from Binance for 10 coins, computes
Opening Range Breakout signals (first daily 4H candle defines range,
followed by breakout detection with volume filter).
"""
import json, math, sys, time, urllib.request
from datetime import datetime, timezone

BASE = "https://api.binance.com"

def load_data(symbol, interval="4h", limit=400):
    url = f"{BASE}/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"  [Error] {symbol}: {e}", file=sys.stderr)
        return None

def _fmt(v):
    if v is None: return "N/A"
    if v >= 100: return f"{v:.0f}"
    if v >= 1: return f"{v:.2f}"
    if v >= 0.001: return f"{v:.4f}"
    return f"{v:.6f}"

def compute_orb(klines):
    """
    ORB-D1+VOL analysis for the last closed candle.
    Returns the signal dict + OR range info.
    """
    n = len(klines)
    if n < 60: return None

    c = [float(x[4]) for x in klines]
    h = [float(x[2]) for x in klines]
    l = [float(x[3]) for x in klines]
    v = [float(x[5]) for x in klines]
    ts = [x[0] for x in klines]

    # ATR(14) for exit SL/trail reference
    atr = [0.0] * n
    for i in range(1, n):
        tr = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
        if i < 14:
            atr[i] = (atr[i - 1] * (i - 1) + tr) / i if i > 1 else tr
        else:
            atr[i] = (atr[i - 1] * 13 + tr) / 14

    # Volume SMA(20)
    vol_sma20 = [None] * n
    for i in range(19, n):
        vol_sma20[i] = sum(v[i - 19:i + 1]) / 20

    # Day tracking + ORB ranges + breakout signals
    day_id = [-1] * n
    day_or_high = [None] * n
    day_or_low = [None] * n
    day_or_idx = [None] * n
    first_candle_dt = [None] * n  # human-readable OR range label

    current_day_key = None
    current_day_id = -1
    cur_or_h = None
    cur_or_l = None
    cur_or_i = None

    for i in range(n):
        dt = datetime.fromtimestamp(ts[i] / 1000, tz=timezone.utc)
        dk = (dt.year, dt.month, dt.day)
        if dk != current_day_key:
            current_day_key = dk
            current_day_id += 1
            cur_or_h = h[i]
            cur_or_l = l[i]
            cur_or_i = i
            first_candle_dt[i] = dt.strftime("%m/%d")
        day_id[i] = current_day_id
        day_or_high[i] = cur_or_h
        day_or_low[i] = cur_or_l
        day_or_idx[i] = cur_or_i

    # Build signal for LATEST CLOSED candle (last index)
    # But show last 3 candles for context
    results = []
    for idx in range(max(60, n - 5), n):
        p = c[idx]; high = h[idx]; low = l[idx]; vol = v[idx]
        atr_pct = (atr[idx] / p) * 100 if p > 0 else 0

        or_high = day_or_high[idx]
        or_low = day_or_low[idx]
        or_idx = day_or_idx[idx]

        sig_dir = 0
        reason = "WAIT"
        vol_ok = False

        # Volume filter check
        vs = vol_sma20[idx]
        vol_ratio = vol / vs if vs and vs > 0 else 0

        if or_idx is not None and idx > or_idx and or_high is not None and or_low is not None:
            # This candle is NOT the range-setter, so can break out
            if vs and vs > 0 and vol >= vs * 1.5:
                vol_ok = True
                if p > or_high:
                    sig_dir = 1
                    reason = "LONG"
                elif p < or_low:
                    sig_dir = -1
                    reason = "SHORT"
                else:
                    reason = f"RANGE [{_fmt(or_low)}-{_fmt(or_high)}]"
            else:
                reason = f"LOWVOL ({vol_ratio:.1f}x)"
                if p > or_high:
                    reason += " ▲"
                elif p < or_low:
                    reason += " ▼"
        elif or_idx is not None and idx == or_idx:
            reason = f"RANGE ═══ {_fmt(or_low)} - {_fmt(or_high)} ═══"
        elif or_idx is None:
            reason = "NO RANGE"

        results.append({
            "ts": int(ts[idx]),
            "p": round(p, 6), "or_high": round(or_high, 6) if or_high else None,
            "or_low": round(or_low, 6) if or_low else None,
            "vol_ratio": round(vol_ratio, 2), "vol_ok": vol_ok,
            "atr_pct": round(atr_pct, 2),
            "sig": sig_dir, "reason": reason,
            "is_or_candle": or_idx is not None and idx == or_idx,
        })

    return results


COINS = [
    ("BTCUSDT", "BTC"), ("ETHUSDT", "ETH"), ("SOLUSDT", "SOL"),
    ("POLUSDT", "POL"),
    ("SHIBUSDT", "SHIB"),
    ("SUIUSDT", "SUI"), ("NEARUSDT", "NEAR"), ("ARBUSDT", "ARB"),
]


def main():
    pkt_offset = 5 * 3600
    now_pkt = time.strftime("%Y-%m-%d %H:%M PKT", time.gmtime(time.time() + pkt_offset))
    print(f"📊 ORB-D1+VOL SCREENER | {now_pkt}")
    print(f"  Strategy: Opening Range Breakout (1st 4H of UTC day) + Volume filter (>1.5× SMA20)")
    print(f"{'='*80}")
    print(f"  {'#':>2} {'Coin':<6} {'Price':>10} {'OR-High':>10} {'OR-Low':>10} {'Vol/SMA':>8} {'ATR%':>6} {'Sig':>6} {'Status':>20}")
    print(f"  {'-'*80}")

    longs = []; shorts = []; total = 0; no_data = 0

    for idx, (sym, name) in enumerate(COINS, 1):
        k = load_data(sym)
        if not k or len(k) < 60:
            print(f"  {idx:>2} {name:<6} {'NO DATA':>10}")
            no_data += 1; continue
        ind = compute_orb(k)
        if not ind:
            print(f"  {idx:>2} {name:<6} {'NO IND':>10}")
            no_data += 1; continue

        cur = ind[-1]  # latest closed candle
        total += 1

        sig_str = "▲LONG" if cur['sig'] == 1 else ("▼SHORT" if cur['sig'] == -1 else " — ")
        if cur['sig'] == 1:
            status = "✅ ENTRY"
            longs.append((name, cur))
        elif cur['sig'] == -1:
            status = "🔻 ENTRY"
            shorts.append((name, cur))
        else:
            status = cur['reason'][:20] if cur['reason'] else "WAIT"

        or_h_s = _fmt(cur['or_high']) if cur['or_high'] else "N/A"
        or_l_s = _fmt(cur['or_low']) if cur['or_low'] else "N/A"
        p_s = _fmt(cur['p'])
        vol_s = f"{cur['vol_ratio']:.1f}x" if cur['vol_ratio'] else "N/A"
        atr_s = f"{cur['atr_pct']:.2f}%" if cur['atr_pct'] else "N/A"

        print(f"  {idx:>2} {name:<6} {p_s:>10} {or_h_s:>10} {or_l_s:>10} {vol_s:>8} {atr_s:>6} {sig_str:>6} {status:>20}")
        time.sleep(0.15)

    print(f"  {'='*80}")
    print(f"  Scanned: {total} coins | No data: {no_data}")
    print()

    if longs:
        print(f"✅ LONG ENTRIES ({len(longs)}):")
        for name, cur in longs:
            pfx = "$" + _fmt(cur['p'])
            print(f"    {name:<6} {pfx:>10} Range: {_fmt(cur['or_low'])}-{_fmt(cur['or_high'])} "
                  f"Vol: {cur['vol_ratio']:.1f}x ATR: {cur['atr_pct']:.2f}%")
    else:
        print("✅ No LONG entries")

    if shorts:
        print(f"\n🔻 SHORT ENTRIES ({len(shorts)}):")
        for name, cur in shorts:
            pfx = "$" + _fmt(cur['p'])
            print(f"    {name:<6} {pfx:>10} Range: {_fmt(cur['or_low'])}-{_fmt(cur['or_high'])} "
                  f"Vol: {cur['vol_ratio']:.1f}x ATR: {cur['atr_pct']:.2f}%")
    else:
        print("\n🔻 No SHORT entries")


if __name__ == "__main__":
    main()
