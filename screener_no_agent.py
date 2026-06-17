#!/usr/bin/env python3
"""
screener_no_agent.py — Full 3-step ORB-D1+VOL pipeline for no_agent cron.
Runs the scorer, checks MEXC balance/positions, executes valid signals, and
prints a report to stdout (delivered verbatim by the cron scheduler).
"""

import subprocess, sys, os, time, json

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

try:
    from mexc_api import get_futures_balance, get_open_positions
except ImportError as e:
    print(f"❌ CRITICAL: Could not import mexc_api — {e}")
    sys.exit(1)

# ─── Constants ────────────────────────────────────────────────────────────

COIN_TO_SYMBOL = {
    "BTC": "BTC_USDT", "ETH": "ETH_USDT", "SOL": "SOL_USDT",
    "POL": "POL_USDT", "SHIB": "SHIB_USDT",
    "SUI": "SUI_USDT", "NEAR": "NEAR_USDT", "ARB": "ARB_USDT",
}

LEVERAGE_MAP = {
    "BTC_USDT": 5, "ETH_USDT": 5,
    "SOL_USDT": 3,
    "POL_USDT": 2, "SHIB_USDT": 2,
    "SUI_USDT": 2, "NEAR_USDT": 2, "ARB_USDT": 2,
}

MAX_CONCURRENT = 3
MIN_BALANCE = 10.0

# ─── Helpers ──────────────────────────────────────────────────────────────

def run_script(name, *args, timeout=60):
    """Run one of our scripts in ~/.hermes/scripts/ and return (stdout, stderr, rc)."""
    cmd = [sys.executable, os.path.join(BASE, name)] + list(args)
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return r.stdout, r.stderr, r.returncode


def parse_signals(screener_text: str):
    """Extract coin + direction pairs from the scorer output table."""
    signals = []
    for line in screener_text.splitlines():
        stripped = line.strip()
        if "▲LONG" not in stripped and "▼SHORT" not in stripped:
            continue
        parts = stripped.split()
        if len(parts) < 2:
            continue
        # parts[0] is the row number (e.g. "2"), parts[1] is the coin name
        coin = parts[1]
        direction = "LONG" if "▲LONG" in stripped else "SHORT"
        signals.append((coin, direction))
    return signals


def pkt_now() -> str:
    """Return current time in PKT (UTC+5) as a formatted string."""
    now = time.gmtime(time.time() + 5 * 3600)
    return time.strftime("%Y-%m-%d %H:%M PKT", now)


# ─── Main Pipeline ────────────────────────────────────────────────────────

def main():
    timestamp = pkt_now()
    print(f"📊 CRYPTO SCREENER REPORT | {timestamp}")
    print("=" * 70)
    print()

    # ── Step 1: Score 10 coins ──────────────────────────────────────────
    print("📡 Running ORB-D1+VOL screener...")
    stdout, stderr, rc = run_script("orb_screener_score.py", timeout=60)
    if rc != 0:
        print(f"❌ Screener failed (exit={rc}):\n{stderr[:500]}")
        return
    print(stdout)

    signals = parse_signals(stdout)
    print(f"Signals detected: {len(signals)}")
    for coin, direction in signals:
        print(f"   {coin} → {direction}")
    print()

    # ── Step 2: Check account ───────────────────────────────────────────
    print("💰 Checking MEXC account...")
    try:
        bal = get_futures_balance()
        total = float(bal.get("equity", 0))
        available = float(bal.get("available", 0))
        print(f"   Equity: ${total:.2f} | Available: ${available:.2f}")
    except Exception as e:
        print(f"   ❌ Balance fetch error: {e}")
        available = 0

    try:
        open_positions = get_open_positions()
        print(f"📈 Open positions: {len(open_positions)} / {MAX_CONCURRENT}")
        for p in open_positions:
            sym = p.get("symbol", "?")
            vol = p.get("holdVol", "?")
            entry = p.get("openPrice", "?")
            pnl = p.get("unrealisedPnl", "?")
            pt = p.get("positionType")
            side = "LONG" if (pt == 1 or pt == "1") else "SHORT"
            print(f"   {sym} {side} | Vol: {vol} | Entry: {entry} | PnL: {pnl}")
    except Exception as e:
        print(f"   ❌ Positions fetch error: {e}")
        open_positions = []
    print()

    # ── Step 3: Execute signals ─────────────────────────────────────────
    if available < MIN_BALANCE:
        print(f"⏭️  SKIP — Available balance ${available:.2f} < ${MIN_BALANCE:.2f}")
        print()
        print("⏰ Next run in ~60min")
        return

    open_symbols = {p.get("symbol", "") for p in open_positions}
    slots_left = MAX_CONCURRENT - len(open_positions)

    if slots_left <= 0:
        print(f"⏭️  SKIP — Already at max positions ({MAX_CONCURRENT})")
        print()
        print("⏰ Next run in ~60min")
        return

    if not signals:
        print("✅ No actionable signals this cycle")
        print()
        print("⏰ Next run in ~60min")
        return

    executed = 0
    for coin, direction in signals:
        if executed >= slots_left:
            print(f"⏭️  No more slots — {slots_left} filled")
            break

        symbol = COIN_TO_SYMBOL.get(coin)
        if not symbol:
            print(f"⚠️  Unknown coin: {coin}, skipping")
            continue

        if symbol in open_symbols:
            print(f"⏭️  {coin} ({symbol}) — already in position")
            continue

        leverage = LEVERAGE_MAP.get(symbol, 2)
        action = "buy" if direction == "LONG" else "sell"

        print(f"🚀 EXECUTING: {action.upper()} {symbol} @ {leverage}x (auto 2% risk)")
        out, err, rc = run_script("mexc_api.py", action, symbol, "0", str(leverage), timeout=30)
        print(f"   Result: {out.strip()[:300]}")
        if err and "No" not in err and "Skip" not in err:
            print(f"   Stderr: {err.strip()[:200]}")

        # Verify after 3s
        time.sleep(3)
        v_out, v_err, v_rc = run_script("mexc_api.py", "positions", timeout=15)
        # Check if our symbol appeared
        if symbol in v_out:
            print(f"   ✅ Position confirmed for {symbol}")
        else:
            print(f"   ⚠️  Position NOT found in verification. Output:\n      {v_out.strip()[:300]}")

        open_symbols.add(symbol)
        executed += 1
        print()

    if executed == 0:
        print("⏭️  No new trades executed")

    print("⏰ Next run in ~60min")


if __name__ == "__main__":
    main()
