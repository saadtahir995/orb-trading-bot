#!/usr/bin/env python3
"""
MEXC Futures API Helper - trading, account, market data
Uses credentials from mexc_config.json
Auth: ApiKey + Request-Time + Signature headers (HMAC-SHA256)
"""
import hmac, hashlib, time, json, os, urllib.request, urllib.parse

CONFIG_PATH = os.path.expanduser("~/.hermes/scripts/mexc_config.json")
BASE = "https://api.mexc.com"

def load_config():
    if not os.path.exists(CONFIG_PATH):
        return {"api_key": "", "secret": ""}
    with open(CONFIG_PATH) as f:
        return json.load(f)

def save_config(api_key, secret):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump({"api_key": api_key, "secret": secret}, f)
    os.chmod(CONFIG_PATH, 0o600)

# --- Futures Auth (different from spot!) ---
# Signature = HMAC-SHA256(secret, api_key + timestamp + paramString)
# Headers: ApiKey, Request-Time, Signature

def futures_sign(api_key, secret, ts, param_string=""):
    sign_str = api_key + ts + param_string
    return hmac.new(secret.encode(), sign_str.encode(), hashlib.sha256).hexdigest()

def futures_request(method, path, params=None, body=None):
    """Make a signed futures API request"""
    cfg = load_config()
    ts = str(int(time.time() * 1000))
    
    param_string = ""
    req_url = BASE + path
    body_bytes = None
    
    if method in ("GET", "DELETE") and params:
        # Sort params alphabetically, join with &
        sorted_params = sorted(params.items())
        param_string = urllib.parse.urlencode(sorted_params)
        req_url = req_url + "?" + param_string
    
    if method == "POST" and body:
        # JSON body string IS the param_string — MUST be identical to what gets sent
        body_str = json.dumps(body)
        param_string = body_str
        body_bytes = body_str.encode()
    
    sig = futures_sign(cfg["api_key"], cfg["secret"], ts, param_string)
    
    headers = {
        "ApiKey": cfg["api_key"],
        "Request-Time": ts,
        "Signature": sig
    }
    
    if body_bytes:
        headers["Content-Type"] = "application/json"
    
    req = urllib.request.Request(req_url, data=body_bytes, headers=headers, method=method)
    
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode())
            if result.get("success") and result.get("code") == 0:
                return result.get("data")
            else:
                return {"error": True, "msg": result.get("message", "Unknown error"), "code": result.get("code")}
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        return {"error": True, "status": e.code, "body": body}
    except Exception as e:
        return {"error": True, "msg": str(e)}


# --- Public Futures Endpoints (no auth needed) ---

def get_contracts():
    """Get all futures contracts"""
    req = urllib.request.Request(BASE + "/api/v1/contract/detail")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            if data.get("success") and data.get("code") == 0:
                return data.get("data", [])
            return []
    except:
        return []

def get_contract(symbol):
    """Get single contract info"""
    contracts = get_contracts()
    for c in contracts:
        if c["symbol"] == symbol:
            return c
    return None

def get_price_precision(symbol):
    """Get the number of decimal places for a symbol's price from contract detail."""
    try:
        url = BASE + "/api/v1/contract/detail/" + symbol
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            if "priceScale" in data:
                return int(data["priceScale"])
    except:
        pass
    # Fallback: try contract list
    contract = get_contract(symbol)
    if contract and "priceScale" in contract:
        return int(contract["priceScale"])
    return 2  # default fallback

def get_futures_price(symbol):
    """Get current mark price"""
    url = BASE + "/api/v1/contract/detail/" + symbol
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except:
        return {}

def get_futures_klines(symbol, interval="Hour4", limit=200):
    """Get klines for futures. interval: Min1, Min5, Min15, Min30, Min60, Hour4, Hour8, Day1, Week1, Month1
    Returns list in Binance-compatible format: [[time, open, high, low, close, vol], ...]
    """
    url = BASE + "/api/v1/contract/kline/fair_price/" + symbol + "?interval=" + interval + "&limit=" + str(limit)
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            if data.get("success") and data.get("code") == 0:
                d = data["data"]
                # MEXC returns {time:[], open:[], close:[], high:[], low:[], vol:[]}
                # Convert to Binance-compatible [[time,open,high,low,close,vol], ...]
                result = []
                for i in range(len(d.get("time", []))):
                    result.append([
                        d["time"][i],
                        str(d["open"][i]),
                        str(d["high"][i]),
                        str(d["low"][i]),
                        str(d["close"][i]),
                        str(d.get("vol", [0]*len(d["time"]))[i])
                    ])
                return result
            return []
    except:
        return []

def get_futures_depth(symbol, limit=20):
    """Get futures order book"""
    url = BASE + "/api/v1/contract/depth/" + symbol + "?limit=" + str(limit)
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            if data.get("success") and data.get("code") == 0:
                return data.get("data", {})
            return {}
    except:
        return {}

def get_futures_ticker(symbol=None):
    """Get futures ticker. symbol optional - omit for all tickers"""
    url = BASE + "/api/v1/contract/ticker"
    if symbol:
        url = url + "?symbol=" + symbol
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            if data.get("success") and data.get("code") == 0:
                return data.get("data", {})
            return {}
    except:
        return {}


# --- Private Futures Endpoints (signed) ---

def get_futures_account():
    """Get futures account assets"""
    return futures_request("GET", "/api/v1/private/account/assets")

def get_futures_balance(currency="USDT"):
    """Get futures balance for a specific currency"""
    assets = get_futures_account()
    if isinstance(assets, list):
        for a in assets:
            if a.get("currency") == currency:
                return {
                    "equity": float(a.get("equity", 0)),
                    "available": float(a.get("availableBalance", 0)),
                    "margin": float(a.get("positionMargin", 0)),
                    "unrealized": float(a.get("unrealized", 0)),
                }
    return {"equity": 0, "available": 0, "margin": 0, "unrealized": 0}

def get_open_positions():
    """Get all open futures positions"""
    return futures_request("GET", "/api/v1/private/position/open_positions")

def get_position(symbol):
    """Get position for a specific symbol"""
    positions = get_open_positions()
    if isinstance(positions, list):
        for p in positions:
            if p.get("symbol") == symbol:
                return p
    return None

def place_futures_order(symbol, side, order_type, vol, price=None, leverage=None, open_type=1, stop_loss=None, take_profit=None):
    """
    Place a futures order with optional TP/SL.
    side: 1=open long, 2=close short, 3=open short, 4=close long
    type: 1=limit, 5=market, 2=PostOnly, 3=IOC, 4=FOK
    open_type: 1=isolated, 2=cross
    vol: number of contracts
    price: required for limit orders
    stop_loss/take_profit: price levels. They use latest price (lossTrend=1, profitTrend=1)
    """
    if order_type == "market" or order_type == 5:
        order_type_num = 5
        price_val = 0
    elif order_type == "limit" or order_type == 1:
        order_type_num = 1
        price_val = price
    else:
        order_type_num = order_type
    
    body = {
        "symbol": symbol,
        "side": side,
        "type": order_type_num,
        "vol": vol,
        "openType": open_type,
    }
    
    if price_val:
        body["price"] = price_val
    if leverage:
        body["leverage"] = leverage
    if stop_loss:
        body["stopLossPrice"] = stop_loss
        body["lossTrend"] = 1
    if take_profit:
        body["takeProfitPrice"] = take_profit
        body["profitTrend"] = 1
    
    return futures_request("POST", "/api/v1/private/order/create", body=body)

def calc_atr(klines, period=14):
    """Calculate ATR(14) from klines. Returns last ATR value in price units."""
    try:
        if len(klines) < period + 1:
            return 0
        highs = [float(k[2]) for k in klines]
        lows = [float(k[3]) for k in klines]
        closes = [float(k[4]) for k in klines]
        n = len(highs)
        atr = [0.0] * n
        for i in range(1, n):
            tr = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
            if i < period:
                atr[i] = (atr[i-1]*(i-1) + tr)/i if i > 1 else tr
            else:
                atr[i] = (atr[i-1]*13 + tr)/14
        return atr[-1]
    except:
        return 0


def place_trailing_stop(symbol, side, vol, entry_price, atr_pct, leverage, open_type=1,
                         trail_activation=1.0, trail_dist=0.40, precision=2, position_mode=2):
    """
    Place a trailing stop order to close an existing position.
    Uses ABSOLUTE callback (backType=2) to match backtest: trail_dist × ATR% × entry_price.
    side: 4=close long, 2=close short
    atr_pct: ATR as % of entry price (e.g., 1.5 for 1.5%)
    trail_activation: multiplier * atr_pct for activation price
    trail_dist: multiplier * atr_pct for callback distance
    precision: price decimal places
    position_mode: 2=one-way, 1=dual-side
    """
    act_pct = trail_activation * atr_pct
    trl_pct = trail_dist * atr_pct

    if side == 4:  # Close long
        active_price = round(entry_price * (1 + act_pct/100), precision)
    else:  # side == 2, Close short
        active_price = round(entry_price * (1 - act_pct/100), precision)

    # Absolute callback value (backType=2) — matches backtest exactly
    # trail distance = trail_dist × atr_pct% × entry_price (fixed dollar amount)
    back_abs_value = round(trail_dist * atr_pct / 100 * entry_price, precision)

    body = {
        "symbol": symbol,
        "leverage": leverage,
        "side": side,
        "vol": vol,
        "openType": open_type,
        "trend": 1,                         # latest price
        "backType": 2,                      # 2=absolute value (matches backtest)
        "backValue": back_abs_value,         # fixed dollar callback distance
        "activePrice": active_price,
        "positionMode": position_mode,
        "reduceOnly": True,
    }

    print(f"  Trailing stop: activates at ${active_price:,.{precision}f}"
          f" | callback ${back_abs_value:,.{precision}f} ({trl_pct:.2f}% of entry)")
    return futures_request("POST", "/api/v1/private/trackorder/place", body=body)


def cancel_futures_order(symbol, order_id):
    """Cancel a futures order"""
    return futures_request("POST", "/api/v1/private/order/cancel", body={
        "symbol": symbol,
        "orderId": order_id
    })

def get_futures_open_orders(symbol=None):
    """Get open futures orders"""
    params = {}
    if symbol:
        params["symbol"] = symbol
    return futures_request("GET", "/api/v1/private/order/openOrders", params=params)


# --- Technical Analysis (same as spot version) ---

def calc_rsi(closes, period=14):
    """Wilder's smoothed RSI — matches TradingView.
    First average is simple, then smoothed with alpha=1/period.
    """
    if len(closes) < period + 1:
        return 50
    # First: simple average of first 14 gains/losses
    gains, losses = 0, 0
    for i in range(1, period + 1):
        diff = closes[i] - closes[i-1]
        if diff >= 0: gains += diff
        else: losses += abs(diff)
    avg_gain = gains / period
    avg_loss = losses / period
    if avg_loss == 0:
        return 100
    # Subsequent: Wilder's smoothing
    for i in range(period + 1, len(closes)):
        diff = closes[i] - closes[i-1]
        gain = diff if diff >= 0 else 0
        loss = abs(diff) if diff < 0 else 0
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)

def calc_sma(closes, period):
    if len(closes) < period: return None
    return sum(closes[-period:]) / period

def calc_bollinger(closes, period=20, std_dev=2):
    if len(closes) < period: return None, None, None
    sma = sum(closes[-period:]) / period
    variance = sum((c - sma) ** 2 for c in closes[-period:]) / period
    std = variance ** 0.5
    return sma, sma + std_dev * std, sma - std_dev * std

def calc_macd(closes, fast=12, slow=26, signal=9):
    if len(closes) < slow + signal: return 0, 0, 0
    def ema(data, period):
        k = 2 / (period + 1)
        ema_vals = [data[0]]
        for i in range(1, len(data)):
            ema_vals.append(data[i] * k + ema_vals[-1] * (1 - k))
        return ema_vals
    ema_fast = ema(closes, fast)
    ema_slow = ema(closes, slow)
    macd_line = [f - s for f, s in zip(ema_fast, ema_slow)]
    signal_line = ema(macd_line, signal)
    histogram = macd_line[-1] - signal_line[-1]
    return macd_line[-1], signal_line[-1], histogram

def find_support_resistance(klines, lookback=100):
    """Detect swing high/low levels from klines for S/R.
    Returns {supports: [price,...], resistances: [price,...], nearest_support, nearest_resistance}
    """
    highs = [float(k[2]) for k in klines[-lookback:]]
    lows = [float(k[3]) for k in klines[-lookback:]]
    closes = [float(k[4]) for k in klines[-lookback:]]
    current = closes[-1]
    
    # Find swing highs (candle where 2 neighbors have lower highs on each side)
    swing_highs = []
    swing_lows = []
    
    for i in range(2, len(highs) - 2):
        # Swing high: high is higher than 2 neighbors on each side
        if (highs[i] > highs[i-1] and highs[i] > highs[i-2] and 
            highs[i] > highs[i+1] and highs[i] > highs[i+2]):
            swing_highs.append(highs[i])
        # Swing low: low is lower than 2 neighbors on each side
        if (lows[i] < lows[i-1] and lows[i] < lows[i-2] and 
            lows[i] < lows[i+1] and lows[i] < lows[i+2]):
            swing_lows.append(lows[i])
    
    # Cluster nearby levels (within 0.3% of each other)
    def cluster_levels(levels, threshold_pct=0.003):
        if not levels:
            return []
        sorted_levels = sorted(levels)
        clusters = [[sorted_levels[0]]]
        for l in sorted_levels[1:]:
            if abs(l - clusters[-1][0]) / clusters[-1][0] < threshold_pct:
                clusters[-1].append(l)
            else:
                clusters.append([l])
        return [round(sum(c)/len(c), 1) for c in clusters]
    
    resistances = cluster_levels(swing_highs)
    supports = cluster_levels(swing_lows)
    
    # Find nearest levels relative to current price
    above = [r for r in resistances if r > current]
    below = [s for s in supports if s < current]
    
    nearest_resistance = min(above) if above else None
    nearest_support = max(below) if below else None
    
    # Also add 2nd nearest for reference
    second_resistance = None
    second_support = None
    if above and len(above) >= 2:
        sorted_above = sorted(above)
        if len(sorted_above) >= 2:
            second_resistance = sorted_above[1]
    if below and len(below) >= 2:
        sorted_below = sorted(below, reverse=True)
        if len(sorted_below) >= 2:
            second_support = sorted_below[1]
    
    return {
        "supports": supports[:10],
        "resistances": resistances[:10],
        "nearest_support": nearest_support,
        "nearest_resistance": nearest_resistance,
        "second_support": second_support,
        "second_resistance": second_resistance,
    }

def calc_tp_sl(price, side, sr_levels, leverage=5, precision=2):
    """Calculate TP/SL based on support/resistance levels.
    Enforces R:R >= 1:1 — SL% never exceeds TP%.
    side: 'long' or 'short'
    precision: number of decimal places (from contract priceScale)
    Returns (sl_price, tp_price, sl_reason, tp_reason)
    Returns all None if no valid R:R found (skip trade).
    """
    nearest_sup = sr_levels.get("nearest_support")
    nearest_res = sr_levels.get("nearest_resistance")
    second_sup = sr_levels.get("second_support")
    second_res = sr_levels.get("second_resistance")
    
    if side == "long":
        # Candidates for SL (below current price)
        sl_candidates = []
        if nearest_sup and nearest_sup < price:
            sl_candidates.append(("Swing low", nearest_sup, f"Swing low ${nearest_sup:,.{precision}f}"))
        if second_sup and second_sup < price:
            sl_candidates.append(("2nd swing low", second_sup, f"2nd swing low ${second_sup:,.{precision}f}"))
        sl_candidates.append(("5% fallback", round(price * 0.95, precision), "No S/R (-5% fallback)"))
        
        # Candidates for TP (above current price)
        tp_candidates = []
        if nearest_res and nearest_res > price:
            tp_candidates.append(("Swing high", nearest_res, f"Swing high ${nearest_res:,.{precision}f}"))
        if second_res and second_res > price:
            tp_candidates.append(("2nd swing high", second_res, f"2nd swing high ${second_res:,.{precision}f}"))
        tp_candidates.append(("10% fallback", round(price * 1.10, precision), "No S/R (+10% fallback)"))
        
        best_sl, best_tp, sl_reason, tp_reason = None, None, None, None
        best_diff = None
        
        for sl_label, sl_raw, sl_why in sl_candidates:
            sl = round(sl_raw * 0.998, precision)
            if sl >= price:
                continue
            sl_pct = (price - sl) / price
            for tp_label, tp_raw, tp_why in tp_candidates:
                tp = round(tp_raw, precision)
                if tp <= price:
                    continue
                tp_pct = (tp - price) / price
                # Enforce R:R >= 1:1
                if tp_pct < sl_pct:
                    continue
                diff = tp_pct - sl_pct
                if best_diff is None or diff < best_diff:
                    best_diff = diff
                    best_sl, best_tp = sl, tp
                    sl_reason, tp_reason = sl_why, tp_why
        
        if best_sl is not None:
            sl_pct = (price - best_sl) / price
            if sl_pct <= 0.03:
                return best_sl, best_tp, sl_reason, tp_reason
            # S/R too wide (>3%), cap at 3% symmetric
            capped_sl = round(price * 0.97, precision)
            capped_tp = round(price * 1.03, precision)
            return capped_sl, capped_tp, f"Capped -3% ({sl_reason})", f"Capped +3% ({tp_reason})"
        # Fallback: fixed % with 1:1 R:R
        fallback_sl = round(price * 0.97, precision)
        fallback_tp = round(price * 1.03, precision)
        return fallback_sl, fallback_tp, "Fallback -3%", "Fallback +3%"
        
    else:  # short
        # Candidates for SL (above current price)
        sl_candidates = []
        if nearest_res and nearest_res > price:
            sl_candidates.append(("Swing high", nearest_res, f"Swing high ${nearest_res:,.{precision}f}"))
        if second_res and second_res > price:
            sl_candidates.append(("2nd swing high", second_res, f"2nd swing high ${second_res:,.{precision}f}"))
        sl_candidates.append(("5% fallback", round(price * 1.05, precision), "No S/R (+5% fallback)"))
        
        # Candidates for TP (below current price)
        tp_candidates = []
        if nearest_sup and nearest_sup < price:
            tp_candidates.append(("Swing low", nearest_sup, f"Swing low ${nearest_sup:,.{precision}f}"))
        if second_sup and second_sup < price:
            tp_candidates.append(("2nd swing low", second_sup, f"2nd swing low ${second_sup:,.{precision}f}"))
        tp_candidates.append(("10% fallback", round(price * 0.90, precision), "No S/R (-10% fallback)"))
        
        best_sl, best_tp, sl_reason, tp_reason = None, None, None, None
        best_diff = None
        
        for sl_label, sl_raw, sl_why in sl_candidates:
            sl = round(sl_raw * 1.002, precision)
            if sl <= price:
                continue
            sl_pct = (sl - price) / price
            for tp_label, tp_raw, tp_why in tp_candidates:
                tp = round(tp_raw, precision)
                if tp >= price:
                    continue
                tp_pct = (price - tp) / price
                # Enforce R:R >= 1:1
                if tp_pct < sl_pct:
                    continue
                diff = tp_pct - sl_pct
                if best_diff is None or diff < best_diff:
                    best_diff = diff
                    best_sl, best_tp = sl, tp
                    sl_reason, tp_reason = sl_why, tp_why
        
        if best_sl is not None:
            sl_pct = (best_sl - price) / price
            if sl_pct <= 0.03:
                return best_sl, best_tp, sl_reason, tp_reason
            # S/R too wide (>3%), cap at 3% symmetric
            capped_sl = round(price * 1.03, precision)
            capped_tp = round(price * 0.97, precision)
            return capped_sl, capped_tp, f"Capped +3% ({sl_reason})", f"Capped -3% ({tp_reason})"
        # Fallback: fixed % with 1:1 R:R
        fallback_sl = round(price * 1.03, precision)
        fallback_tp = round(price * 0.97, precision)
        return fallback_sl, fallback_tp, "Fallback +3%", "Fallback -3%"


def analyze_futures(symbol, interval="Hour4", limit=200):
    """Full technical analysis from futures klines"""
    klines = get_futures_klines(symbol, interval, limit)
    if not klines:
        return {"error": "No klines data"}
    
    closes = [float(k[4]) for k in klines]
    current_price = float(klines[-1][4])
    volumes = [float(k[5]) for k in klines]
    
    rsi = calc_rsi(closes)
    sma50 = calc_sma(closes, 50)
    sma200 = calc_sma(closes, 200)
    bb_mid, bb_upper, bb_lower = calc_bollinger(closes)
    macd_line, signal_line, macd_hist = calc_macd(closes)
    vol_avg = sum(volumes[-20:]) / min(20, len(volumes))
    vol_ratio = volumes[-1] / vol_avg if vol_avg > 0 else 1
    
    cross = "UNKNOWN"
    if sma50 and sma200:
        cross = "GOLDEN" if sma50 > sma200 else "DEATH"
    
    bb_pos = "UNKNOWN"
    if bb_upper and bb_lower:
        if current_price >= bb_upper: bb_pos = "ABOVE_UPPER"
        elif current_price <= bb_lower: bb_pos = "BELOW_LOWER"
        elif current_price > bb_mid: bb_pos = "UPPER_HALF"
        else: bb_pos = "LOWER_HALF"
    
    precision = get_price_precision(symbol)
    sr = find_support_resistance(klines)
    atr_val = calc_atr(klines)
    atr_pct = (atr_val / current_price) * 100 if current_price > 0 and atr_val > 0 else 0
    
    if atr_pct > 0.1:
        sl_mul, tp_mul = 2.0, 4.0
        atr_long_sl = round(current_price * (1 - sl_mul * atr_pct / 100), precision)
        atr_long_tp = round(current_price * (1 + tp_mul * atr_pct / 100), precision)
        atr_short_sl = round(current_price * (1 + sl_mul * atr_pct / 100), precision)
        atr_short_tp = round(current_price * (1 - tp_mul * atr_pct / 100), precision)
    else:
        atr_long_sl = round(current_price * 0.97, precision)
        atr_long_tp = round(current_price * 1.06, precision)
        atr_short_sl = round(current_price * 1.03, precision)
        atr_short_tp = round(current_price * 0.94, precision)
    
    result = {
        "symbol": symbol,
        "price": current_price,
        "rsi": round(rsi, 1),
        "cross": cross,
        "sma50": round(sma50, 2) if sma50 else None,
        "sma200": round(sma200, 2) if sma200 else None,
        "bb_pos": bb_pos,
        "bb_upper": round(bb_upper, 2) if bb_upper else None,
        "bb_lower": round(bb_lower, 2) if bb_lower else None,
        "macd_hist": round(macd_hist, 4),
        "macd_cross": "BULLISH" if macd_hist > 0 else "BEARISH",
        "vol_ratio": round(vol_ratio, 2),
        "vol_signal": "HIGH" if vol_ratio > 1.5 else "NORMAL",
        "support": sr["nearest_support"],
        "resistance": sr["nearest_resistance"],
        "support_2nd": sr["second_support"],
        "resistance_2nd": sr["second_resistance"],
        "tp_sl_long": {"sl": atr_long_sl, "tp": atr_long_tp},
        "tp_sl_short": {"sl": atr_short_sl, "tp": atr_short_tp},
        "atr_pct": round(atr_pct, 2),
    }
    return result


INTERVALS = {
    "1H": ("Min60", 500),
    "4H": ("Hour4", 200),
    "1D": ("Day1", 200),
}


def analyze_multi_timeframe(symbol):
    """Multi-timeframe analysis: 1H, 4H, 1D. Returns printable string."""
    lines = []
    lines.append(f"📊 {symbol} — Multi-Timeframe Analysis")
    lines.append(f"{'='*60}")
    
    header = f"{'TF':>4} | {'Price':>10} | {'RSI':>6} | {'BB':>12} | {'MACD':>9} | {'Vol':>5} | {'Cross':>8}"
    sep = "-"*4 + "-+-" + "-"*10 + "-+-" + "-"*6 + "-+-" + "-"*12 + "-+-" + "-"*9 + "-+-" + "-"*5 + "-+-" + "-"*8
    lines.append(header)
    lines.append(sep)
    
    all_aligned = True
    for tf_name, (interval, limit) in INTERVALS.items():
        result = analyze_futures(symbol, interval, limit)
        if "error" in result:
            lines.append(f" {tf_name:>3} | ERROR: {result['error']}")
            continue
        
        price = f"${result['price']:,.2f}" if result['price'] < 1000 else f"${result['price']:,.0f}"
        rsi = result['rsi']
        rsi_s = f"{rsi}" + (" 🟢" if rsi < 35 else " 🔴" if rsi > 65 else "  -")
        bb = result['bb_pos'][:12]
        macd = f"{'🟢' if result['macd_hist'] > 0 else '🔴'}{abs(result['macd_hist']):.2f}"
        if len(macd) > 9: macd = macd[:9]
        vol = f"{result['vol_ratio']:.1f}x"
        cross = result.get('cross', '')[:8]
        
        lines.append(f"{tf_name:>4} | {price:>10} | {rsi_s:>6} | {bb:>12} | {macd:>9} | {vol:>5} | {cross:>8}")
    
    lines.append(sep)
    
    # Get S/R levels from 4H (primary)
    sr_result = analyze_futures(symbol, "Hour4", 200)
    if "error" not in sr_result:
        sup = sr_result.get('support')
        res = sr_result.get('resistance')
        sup2 = sr_result.get('support_2nd')
        res2 = sr_result.get('resistance_2nd')
        lines.append(f"")
        lines.append(f"S/R (4H): S2={sup2} | S1={sup} | R1={res} | R2={res2}")
        
        # Direction verdict based on multi-tf alignment
        hours_1 = analyze_futures(symbol, "Min60", 500)
        day_1 = analyze_futures(symbol, "Day1", 200)
        
        if "error" not in hours_1 and "error" not in day_1:
            tf_signals = []
            for name, r in [("1H", hours_1), ("4H", sr_result), ("1D", day_1)]:
                rsi_v = r['rsi']
                bb_p = r['bb_pos']
                if rsi_v < 35 and "LOWER" in bb_p:
                    tf_signals.append(f"🟢 {name} oversold @ lower BB")
                elif rsi_v > 65 and "UPPER" in bb_p:
                    tf_signals.append(f"🔴 {name} overbought @ upper BB")
                else:
                    tf_signals.append(f"⚪ {name} neutral (RSI {rsi_v})")
            
            lines.append(f"")
            for s in tf_signals:
                lines.append(f"  {s}")
            
            # Count alignment
            rsi_1h = hours_1['rsi']
            rsi_4h = sr_result['rsi']
            rsi_1d = day_1['rsi']
            oversold = sum([rsi_1h < 35, rsi_4h < 35, rsi_1d < 35])
            overbought = sum([rsi_1h > 65, rsi_4h > 65, rsi_1d > 65])
            
            if oversold >= 2:
                lines.append(f"  📗 MULTI-TF OVERSOLD ({oversold}/3) — strong buy bias")
            elif overbought >= 2:
                lines.append(f"  📕 MULTI-TF OVERBOUGHT ({overbought}/3) — strong sell bias")
            else:
                lines.append(f"  ⚪ No strong multi-tf alignment — wait")
    
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "init":
        if len(sys.argv) < 4:
            print("Usage: mexc_api.py init <api_key> <secret>")
            sys.exit(1)
        save_config(sys.argv[2], sys.argv[3])
        print("Credentials saved to", CONFIG_PATH)
    
    elif len(sys.argv) > 1 and sys.argv[1] == "account":
        acct = get_futures_account()
        if isinstance(acct, list):
            print("Futures Account Assets:")
            for a in acct:
                eq = float(a.get("equity", 0))
                avail = float(a.get("availableBalance", 0))
                margin = float(a.get("positionMargin", 0))
                if eq > 0 or margin > 0:
                    print(f"  {a['currency']}: equity={eq:.4f} available={avail:.4f} margin={margin:.4f}")
        else:
            print("Error:", acct)
    
    elif len(sys.argv) > 1 and sys.argv[1] == "balance":
        bal = get_futures_balance()
        print(f"USDT: equity={bal['equity']:.4f} available={bal['available']:.4f} margin={bal['margin']:.4f}")
    
    elif len(sys.argv) > 1 and sys.argv[1] == "positions":
        pos = get_open_positions()
        if isinstance(pos, list):
            if not pos:
                print("No open positions")
            # Get current tickers for live mark prices
            ticker_resp = futures_request("GET", "/api/v1/contract/ticker")
            ticker_map = {}
            if isinstance(ticker_resp, dict) and ticker_resp.get("data"):
                for t in ticker_resp["data"]:
                    ticker_map[t["symbol"]] = t
            elif isinstance(ticker_resp, list):
                for t in ticker_resp:
                    ticker_map[t["symbol"]] = t

            for p in pos:
                sym = p.get('symbol')
                pos_side = "LONG" if p.get("positionType") == 1 else "SHORT"
                vol = float(p.get('holdVol', 0))
                entry = float(p.get('holdAvgPrice', 0))
                liq = float(p.get('liquidatePrice', 0))
                lev = p.get('leverage', 0)
                margin = float(p.get('oim', 0))
                pnl_pct = float(p.get('profitRatio', 0)) * 100

                # Live mark price from ticker
                mark = entry
                ticker = ticker_map.get(sym, {})
                if ticker:
                    mark = float(ticker.get('lastPrice', entry))

                # Unrealized PnL in USDT = margin * profitRatio
                upnl = margin * float(p.get('profitRatio', 0))

                print(f"  {sym:12s} | {pos_side:5s} | Vol: {vol:>4.0f} | Entry: ${entry:<8.2f} | Mark: ${mark:<8.2f} | Liq: ${liq:<8.2f} | {lev}x | Margin: ${margin:<6.2f} | PnL: ${upnl:+.4f} ({pnl_pct:+.2f}%)")
            print(f"  {'Total':12s} | {'':5s} | {'':4s} | {'':10s} | {'':10s} | {'':10s} | {'':2s} | Positions: {len(pos)}/3 filled")
        else:
            print("Error:", pos)
    
    elif len(sys.argv) > 1 and sys.argv[1] == "contracts":
        contracts = get_contracts()
        print(f"{len(contracts)} contracts available")
        for c in contracts[:20]:
            print(f"  {c['symbol']:20s} leverage {c['minLeverage']}-{c['maxLeverage']}x  "
                  f"contract size={c['contractSize']}  state={'ACTIVE' if c['state']==0 else c['state']}")
    
    elif len(sys.argv) > 1 and sys.argv[1] == "price":
        sym = sys.argv[2] if len(sys.argv) > 2 else "BTC_USDT"
        ticker = get_futures_ticker(sym)
        if isinstance(ticker, dict) and ticker.get("lastPrice"):
            p = float(ticker["lastPrice"])
            chg = ticker.get("riseFallRate", 0)
            print(f"{sym}: ${p:,.2f}  ({float(chg)*100:+.2f}%)")
        else:
            print(f"Could not get price for {sym}")
    
    elif len(sys.argv) > 1 and sys.argv[1] == "analyze":
        sym = sys.argv[2] if len(sys.argv) > 2 else "BTC_USDT"
        # --json flag: returns structured JSON with all timeframes for cron/scripting
        if len(sys.argv) > 3 and sys.argv[3] == "--json":
            result = {}
            for tf_name, (interval, limit) in INTERVALS.items():
                analysis = analyze_futures(sym, interval, limit)
                if "error" not in analysis:
                    result[tf_name] = analysis
            print(json.dumps(result, indent=2) if result else "{}")
        # Single timeframe flags: --1h, --4h, --1d returns raw JSON
        elif len(sys.argv) > 3 and sys.argv[3] in ["--1h", "--4h", "--1d"]:
            interval_map = {"--1h": "Min60", "--4h": "Hour4", "--1d": "Day1"}
            limit_map = {"--1h": 500, "--4h": 200, "--1d": 200}
            flag = sys.argv[3]
            analysis = analyze_futures(sym, interval_map[flag], limit_map[flag])
            if "error" in analysis:
                print("Error:", analysis["error"])
            else:
                print(json.dumps(analysis, indent=2))
        else:
            # Default: multi-timeframe human-readable table
            print(analyze_multi_timeframe(sym))
    
    elif len(sys.argv) > 1 and sys.argv[1] == "buy":
        sym = sys.argv[2] if len(sys.argv) > 2 else "BTC_USDT"
        usdt_amount = float(sys.argv[3]) if len(sys.argv) > 3 else 10
        lev = int(sys.argv[4]) if len(sys.argv) > 4 else 5
        
        # If amount is 0, auto-calculate 2% of available balance
        if usdt_amount == 0:
            bal = get_futures_balance()
            usdt_amount = bal["available"] * 0.02
            print(f"Auto 2% risk: ${usdt_amount:.2f} (balance: ${bal['available']:.2f})")
        
        contract = get_contract(sym)
        if not contract:
            print(f"Contract {sym} not found")
            sys.exit(1)
        contract_size = float(contract["contractSize"])
        min_vol = int(contract.get("minVol", 1))
        ticker = get_futures_ticker(sym)
        price = float(ticker.get("lastPrice", 0))
        if price == 0:
            print("Could not get price")
            sys.exit(1)
        klines = get_futures_klines(sym, "Hour4", 200)
        precision = get_price_precision(sym)
        
        # ATR-based SL/TP (matches backtest: 2×ATR SL, 4×ATR TP, 1×ATR trail)
        atr_val = calc_atr(klines) if klines else 0
        atr_pct = (atr_val / price) * 100 if price > 0 and atr_val > 0 else 0
        
        if atr_pct > 0.1:
            sl_mul, tp_mul = 2.0, 4.0
            sl_price = round(price * (1 - sl_mul * atr_pct / 100), precision)
            tp_price = round(price * (1 + tp_mul * atr_pct / 100), precision)
            sl_reason = f"{sl_mul}×ATR ({sl_mul*atr_pct:.2f}%)"
            tp_reason = f"{tp_mul}×ATR ({tp_mul*atr_pct:.2f}%)"
        else:
            sl_price = round(price * 0.97, precision)
            tp_price = round(price * 1.06, precision)
            sl_reason = "Fallback -3%"
            tp_reason = "Fallback +6%"
        
        # usdt_amount = risk amount (2% of balance)
        # Position size = risk / SL% so actual loss at SL = risk amount
        sl_pct = max((price - sl_price) / price, 0.001)  # prevent div by zero
        position_size = usdt_amount / sl_pct
        vol = max(min_vol, int(position_size / (contract_size * price)))
        print(f"Buying {vol} contracts of {sym} at ~${price:,.{precision}f}, leverage {lev}x")
        print(f"  Position: ${position_size:,.2f} | Risk: ${usdt_amount:.2f} | Margin: ${position_size/lev:,.2f}")
        print(f"  SL: ${sl_price:,.{precision}f} ({sl_pct*100:.2f}%) ({sl_reason})")
        print(f"  TP: ${tp_price:,.{precision}f} ({(tp_price-price)/price*100:.2f}%) ({tp_reason})")
        # NOTE: No fixed TP order — trailing stop handles ALL profitable exits
        # (matches backtest: <2% of trades exit via TP, the rest via trailing stop)
        result = place_futures_order(sym, side=1, order_type=5, vol=vol, leverage=lev,
                                      stop_loss=sl_price)
        print("Result:", json.dumps(result, indent=2) if isinstance(result, dict) else result)
        
        # Place trailing stop order (1.0×ATR activation, 0.40×ATR absolute callback)
        # Activates when price reaches +1.0×ATR; trails with 0.40×ATR fixed $ callback distance
        if atr_pct > 0.1:
            ts_result = place_trailing_stop(
                sym, side=4, vol=vol, entry_price=price,
                atr_pct=atr_pct, leverage=lev, precision=precision
            )
            print("Trailing Stop Result:", json.dumps(ts_result, indent=2) if isinstance(ts_result, dict) else ts_result)
        else:
            print(f"  Skip trailing stop: ATR% too small ({atr_pct:.2f}%)")

    elif len(sys.argv) > 1 and sys.argv[1] == "sell":
        sym = sys.argv[2] if len(sys.argv) > 2 else "BTC_USDT"
        usdt_amount = float(sys.argv[3]) if len(sys.argv) > 3 else 10
        lev = int(sys.argv[4]) if len(sys.argv) > 4 else 5
        
        # If amount is 0, auto-calculate 2% of available balance
        if usdt_amount == 0:
            bal = get_futures_balance()
            usdt_amount = bal["available"] * 0.02
            print(f"Auto 2% risk: ${usdt_amount:.2f} (balance: ${bal['available']:.2f})")
        
        contract = get_contract(sym)
        if not contract:
            print(f"Contract {sym} not found")
            sys.exit(1)
        contract_size = float(contract["contractSize"])
        min_vol = int(contract.get("minVol", 1))
        ticker = get_futures_ticker(sym)
        price = float(ticker.get("lastPrice", 0))
        if price == 0:
            print("Could not get price")
            sys.exit(1)
        klines = get_futures_klines(sym, "Hour4", 200)
        precision = get_price_precision(sym)
        
        # ATR-based SL/TP (matches backtest: 2×ATR SL, 4×ATR TP, 1×ATR trail)
        atr_val = calc_atr(klines) if klines else 0
        atr_pct = (atr_val / price) * 100 if price > 0 and atr_val > 0 else 0
        
        if atr_pct > 0.1:
            sl_mul, tp_mul = 2.0, 4.0
            sl_price = round(price * (1 + sl_mul * atr_pct / 100), precision)
            tp_price = round(price * (1 - tp_mul * atr_pct / 100), precision)
            sl_reason = f"{sl_mul}×ATR ({sl_mul*atr_pct:.2f}%)"
            tp_reason = f"{tp_mul}×ATR ({tp_mul*atr_pct:.2f}%)"
        else:
            sl_price = round(price * 1.03, precision)
            tp_price = round(price * 0.94, precision)
            sl_reason = "Fallback +3%"
            tp_reason = "Fallback -6%"
        
        # usdt_amount = risk amount (2% of balance)
        # Position size = risk / SL% so actual loss at SL = risk amount
        sl_pct = max((sl_price - price) / price, 0.001)  # prevent div by zero
        position_size = usdt_amount / sl_pct
        vol = max(min_vol, int(position_size / (contract_size * price)))
        print(f"Shorting {vol} contracts of {sym} at ~${price:,.{precision}f}, leverage {lev}x")
        print(f"  Position: ${position_size:,.2f} | Risk: ${usdt_amount:.2f} | Margin: ${position_size/lev:,.2f}")
        print(f"  SL: ${sl_price:,.{precision}f} ({sl_pct*100:.2f}%) ({sl_reason})")
        print(f"  TP: ${tp_price:,.{precision}f} ({(price-tp_price)/price*100:.2f}%) ({tp_reason})")
        # NOTE: No fixed TP order — trailing stop handles ALL profitable exits
        # (matches backtest: <2% of trades exit via TP, the rest via trailing stop)
        result = place_futures_order(sym, side=3, order_type=5, vol=vol, leverage=lev,
                                      stop_loss=sl_price)
        print("Result:", json.dumps(result, indent=2) if isinstance(result, dict) else result)

        # Place trailing stop order (0.40×ATR activation, 0.40×ATR absolute callback) — close short side=2
        if atr_pct > 0.1:
            ts_result = place_trailing_stop(
                sym, side=2, vol=vol, entry_price=price,
                atr_pct=atr_pct, leverage=lev, precision=precision
            )
            print("Trailing Stop Result:", json.dumps(ts_result, indent=2) if isinstance(ts_result, dict) else ts_result)
        else:
            print(f"  Skip trailing stop: ATR% too small ({atr_pct:.2f}%)")

    else:
        print("MEXC Futures API Helper")
        print("Commands:")
        print("  init <key> <secret>    - Save credentials")
        print("  account                - Show futures account assets")
        print("  balance                - Show USDT balance")
        print("  positions              - Show open positions")
        print("  contracts              - List available futures contracts")
        print("  price <symbol>         - Get current mark price")
        print("  analyze <symbol>       - Full technical analysis")
        print("  buy <sym> <usdt> <lev> - Market buy (long) + auto 1×ATR trailing stop")
        print("  sell <sym> <usdt> <lev> - Market sell (short) + auto 1×ATR trailing stop")
