#!/usr/bin/env python3
"""
Multi-Asset Scanner with Nadaraya-Watson Envelope
Supports both long-term and short-term timeframes via command-line arguments
Includes Squeeze Momentum, SMRE, and Smart Money Concepts (SMC) filters

Usage:
    python scanner.py                    # Default: 1h timeframe
    python scanner.py -tf 15m            # 15-minute timeframe
    python scanner.py -tf 5m             # 5-minute timeframe
    python scanner.py -tf 4h             # 4-hour timeframe
    python scanner.py -tf 1h -v          # 1h with verbose output
    python scanner.py --help             # Show help

SMC Note:
    Smart Money Concepts (BOS, CHoCH, Order Blocks, FVGs) are implemented
    as built-in functions below. No external smc-toolkit dependency needed.
"""

import ccxt
import pandas as pd
import numpy as np
from datetime import datetime
import time
import warnings
import argparse
import sys
import json
import os
warnings.filterwarnings('ignore')
    
# ============================================
# ARGUMENT PARSING
# ============================================

def parse_args():
    parser = argparse.ArgumentParser(
        description='Multi-Asset Scanner with Nadaraya-Watson Envelope',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scanner.py                    # Default: 1h timeframe
  python scanner.py -tf 15m            # 15-minute timeframe
  python scanner.py -tf 5m             # 5-minute timeframe (scalping)
  python scanner.py -tf 30m            # 30-minute timeframe
  python scanner.py -tf 4h             # 4-hour timeframe
  python scanner.py -tf 1h -v          # Verbose mode with all filters
  python scanner.py --list-timeframes  # Show all available timeframes
  python scanner.py --no-smc           # Disable Smart Money Concepts filter
        """
    )
    
    parser.add_argument(
        '-tf', '--timeframe',
        type=str,
        default='1h',
        help='Timeframe to scan (default: 1h). Options: 1m, 5m, 15m, 30m, 1h, 2h, 4h, 6h, 12h, 1d'
    )
    
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enable verbose output (shows all symbols, not just signals)'
    )
    
    parser.add_argument(
        '--list-timeframes',
        action='store_true',
        help='Show all available timeframes and exit'
    )
    
    parser.add_argument(
        '--account-size',
        type=float,
        default=10000,
        help='Account size in USD (default: 10000)'
    )
    
    parser.add_argument(
        '--risk',
        type=float,
        default=0.02,
        help='Risk per trade as percentage (default: 0.02 = 2%%)'
    )
    
    parser.add_argument(
        '--max-positions',
        type=int,
        default=3,
        help='Maximum concurrent positions (default: 3)'
    )
    
    parser.add_argument(
        '--no-squeeze',
        action='store_true',
        help='Disable Squeeze Momentum filter'
    )
    
    parser.add_argument(
        '--no-smre',
        action='store_true',
        help='Disable Statistical Mean-Reversion Engine filter'
    )
    
    parser.add_argument(
        '--no-smc',
        action='store_true',
        help='Disable Smart Money Concepts filter'
    )
    
    return parser.parse_args()

# ============================================
# CONFIGURATION
# ============================================

# Spot symbols (standard)
SPOT_SYMBOLS = [
    'BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'XRP/USDT', 'DOGE/USDT',
    'LINK/USDT', 'AVAX/USDT', 'SUI/USDT', 'NEAR/USDT',
    'WIF/USDT', 'ARB/USDT', 'OP/USDT', 'AAVE/USDT', 'ADA/USDT',
    'AIXBT/USDT', 'ALGO/USDT', 'APT/USDT', 'ASTER/USDT', 'ATOM/USDT',
    'BCH/USDT', 'BNB/USDT', 'BONK/USDT', 'CRV/USDT', 'DOT/USDT',
    'ETC/USDT', 'FIL/USDT', 'HBAR/USDT', 'INJ/USDT', 'JTO/USDT',
    'JUP/USDT', 'KAITO/USDT', 'LDO/USDT', 'LIT/USDT', 'LTC/USDT',
    'ONDO/USDT', 'PENGU/USDT', 'PNUT/USDT',
    'POL/USDT', 'PUMP/USDT', 'RENDER/USDT', 'S/USDT',
    'SHIB/USDT', 'STX/USDT', 'TAO/USDT', 'TIA/USDT',
    'TRX/USDT', 'UNI/USDT', 'VIRTUAL/USDT', 'WLD/USDT', 
    'ZEC/USDT'
]

# Futures symbols (for metals and other perpetuals)
FUTURES_SYMBOLS = [
    'XAU/USDT:USDT',  # Gold perpetual
    'XAG/USDT:USDT'   # Silver perpetual
]

# Combine all symbols
SYMBOLS = SPOT_SYMBOLS + FUTURES_SYMBOLS

# ============================================
# TIMEFRAME-SPECIFIC PARAMETERS
# ============================================

def get_timeframe_params(timeframe):
    """
    Returns optimized parameters for each timeframe
    """
    params = {
        'lookback': 500,
        'bandwidth': 6.0,
        'multiplier': 3.0,
        'rsi_period': 14,
        'ma_period': 200,
        'confirmation_timeframe': '15m',
        'max_positions': 3,
        'risk_per_trade': 0.02,
        'stop_distance': 0.025,  # 2.5%
        'target_1_pct': 0.03,    # 3%
        'target_2_pct': 0.05,    # 5%
        'target_3_pct': 0.07,    # 7%
        'filters': ['volume', 'ma', 'confirmation']
    }
    
    # Short-term timeframes (scalping/day trading)
    if timeframe in ['1m', '5m', '15m']:
        params.update({
            'lookback': 200,
            'bandwidth': 3.5,
            'multiplier': 2.0,
            'rsi_period': 8,
            'ma_period': 50,
            'confirmation_timeframe': '1h',
            'max_positions': 8,
            'risk_per_trade': 0.01,
            'stop_distance': 0.015,  # 1.5%
            'target_1_pct': 0.015,   # 1.5%
            'target_2_pct': 0.025,   # 2.5%
            'target_3_pct': 0.04,    # 4%
        })
    
    # Medium-term timeframes (day trading)
    elif timeframe in ['30m', '1h']:
        params.update({
            'lookback': 300 if timeframe == '30m' else 500,
            'bandwidth': 4.5 if timeframe == '30m' else 6.0,
            'multiplier': 2.5 if timeframe == '30m' else 3.0,
            'rsi_period': 10 if timeframe == '30m' else 14,
            'ma_period': 100 if timeframe == '30m' else 200,
            'confirmation_timeframe': '1h' if timeframe == '30m' else '15m',
            'max_positions': 5 if timeframe == '30m' else 3,
            'risk_per_trade': 0.015 if timeframe == '30m' else 0.02,
            'stop_distance': 0.02 if timeframe == '30m' else 0.025,
            'target_1_pct': 0.02 if timeframe == '30m' else 0.03,
            'target_2_pct': 0.035 if timeframe == '30m' else 0.05,
            'target_3_pct': 0.05 if timeframe == '30m' else 0.07,
        })
    
    # Long-term timeframes (swing/position trading)
    elif timeframe in ['2h', '4h', '6h', '12h', '1d']:
        params.update({
            'lookback': 500,
            'bandwidth': 7.0 if timeframe in ['4h', '6h'] else 8.0,
            'multiplier': 3.5 if timeframe in ['4h', '6h'] else 4.0,
            'rsi_period': 14,
            'ma_period': 200,
            'confirmation_timeframe': '1h',
            'max_positions': 3,
            'risk_per_trade': 0.02,
            'stop_distance': 0.03,   # 3%
            'target_1_pct': 0.04,    # 4%
            'target_2_pct': 0.07,    # 7%
            'target_3_pct': 0.10,    # 10%
        })
    
    return params

# ============================================
# INDICATOR FUNCTIONS
# ============================================

def gaussian_kernel(x, h):
    return np.exp(-(x**2) / (2 * h**2))

def nadaraya_watson_envelope(price, h, mult, lookback):
    n = len(price)
    if n < lookback:
        return None, None, None
    
    price_array = np.array(price[-lookback:])
    smoothed = np.zeros(lookback)
    for i in range(lookback):
        w = gaussian_kernel(np.arange(lookback) - i, h)
        smoothed[i] = np.sum(price_array * w) / np.sum(w)
    
    mae = np.mean(np.abs(price_array - smoothed)) * mult
    middle = smoothed[-1]
    upper = middle + mae
    lower = middle - mae
    
    return middle, upper, lower

def rsi(price, period=14):
    """
    Wilder's RSI with proper recursive smoothing.
    Fix #1: added Wilder's smoothing loop (was only averaging first `period` bars).
    Fix #2: use np.zeros_like instead of delta.copy() * 0.
    """
    if len(price) < period + 1:
        return 50.0

    delta = np.diff(price)
    # Fix #2 — clean initialisation
    gain = np.zeros_like(delta)
    loss = np.zeros_like(delta)
    gain[delta > 0] = delta[delta > 0]
    loss[delta < 0] = -delta[delta < 0]

    # Seed with simple average of first `period` bars
    avg_gain = np.mean(gain[:period])
    avg_loss = np.mean(loss[:period])

    # Fix #1 — Wilder's smoothing for remaining bars
    for i in range(period, len(delta)):
        avg_gain = (avg_gain * (period - 1) + gain[i]) / period
        avg_loss = (avg_loss * (period - 1) + loss[i]) / period

    if avg_loss == 0:
        return 100.0
    if avg_gain == 0:
        return 0.0

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

# ============================================
# SQUEEZE MOMENTUM INDICATOR
# ============================================

def squeeze_momentum(high, low, close, bb_period=20, bb_mult=2, kc_period=20, kc_mult=1.5):
    """
    Calculates Squeeze Momentum (LazyBear style)
    Returns: (squeeze_on, momentum_value, squeeze_release)
    """
    # Bollinger Bands
    sma = np.mean(close[-bb_period:])
    std = np.std(close[-bb_period:])
    bb_upper = sma + (bb_mult * std)
    bb_lower = sma - (bb_mult * std)
    
    # Keltner Channels
    tr = np.zeros(len(close))
    for i in range(1, len(close)):
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i-1]), abs(low[i] - close[i-1]))
    atr = np.mean(tr[-kc_period:])
    kc_upper = sma + (kc_mult * atr)
    kc_lower = sma - (kc_mult * atr)
    
    # Squeeze condition: BB inside KC
    squeeze_on = (bb_upper < kc_upper) and (bb_lower > kc_lower)
    
    # Momentum: price relative to bands
    if len(close) > 20:
        momentum = ((close[-1] - sma) / (sma * 0.01)) * 0.5
    else:
        momentum = 0
    
    # Fix #4 — squeeze_release detects a price breakout through the KC boundary
    # (the old code required squeeze_on=True simultaneously, which is self-contradicting:
    # a release means the squeeze just ENDED, not that it is still active).
    squeeze_release = False
    if len(close) > 2:
        # Upside breakout: current bar closes above KC upper; previous bar did not
        if close[-1] > kc_upper and close[-2] <= kc_upper:
            squeeze_release = True
        # Downside breakout: current bar closes below KC lower; previous bar did not
        elif close[-1] < kc_lower and close[-2] >= kc_lower:
            squeeze_release = True
    
    return squeeze_on, momentum, squeeze_release

# ============================================
# STATISTICAL MEAN-REVERSION ENGINE (SMRE)
# ============================================

def smre_filter(price, window=50, threshold=2.0):
    if len(price) < window:
        return False, 0, 0
    
    mean_val = np.mean(price[-window:])
    std_val = np.std(price[-window:])
    
    if std_val == 0:
        return False, 0, 0
    
    z_score = (price[-1] - mean_val) / std_val
    confidence = min(100, abs(z_score) / threshold * 100)
    is_mean_reverting = abs(z_score) > threshold
    
    return is_mean_reverting, z_score, confidence

def stationarity_test(price, window=100):
    """
    Estimate Hurst exponent via variance scaling of log returns.
    Fix #3: old formula (0.5 * var2/var1) was not a valid Hurst estimator.
    Correct approach: H = 0.5 * log2(var_full / var_half), clamped to [0, 1].
    H < 0.5  → mean-reverting (stationary-like)
    H ≈ 0.5  → random walk
    H > 0.5  → trending
    """
    if len(price) < window:
        return False, 0.5

    log_returns = np.diff(np.log(price[-window:]))
    if len(log_returns) < 4:
        return False, 0.5

    var_full = np.var(log_returns)
    half = len(log_returns) // 2
    var_half = np.var(log_returns[:half])

    if var_full > 0 and var_half > 0:
        # Fix #3 — variance-scaling Hurst estimate
        hurst = 0.5 * np.log(var_full / var_half) / np.log(2)
        hurst = max(0.0, min(1.0, hurst))
    else:
        hurst = 0.5

    is_stationary = hurst < 0.5
    return is_stationary, round(hurst, 2)

def volatility_regime(price, window=50):
    if len(price) < window:
        return 'medium', 50
    
    returns = np.diff(price[-window:])
    if len(returns) < 2:
        return 'medium', 50
    
    current_vol = np.std(returns)
    avg_vol = np.std(np.diff(price[-window*2:])) if len(price) > window*2 else current_vol
    
    if avg_vol == 0:
        return 'medium', 50
    
    vol_ratio = current_vol / avg_vol
    vol_score = min(100, vol_ratio * 50)
    
    if vol_ratio < 0.7:
        regime = 'low'
    elif vol_ratio < 1.3:
        regime = 'medium'
    else:
        regime = 'high'
    
    return regime, round(vol_score, 1)

# ============================================
# SMART MONEY CONCEPTS (SMC) FUNCTIONS
# ============================================

def detect_market_structure(high, low, close, swing_size=10):
    """
    Detect Break of Structure (BOS) and Change of Character (CHoCH)
    Returns: (structure_type, trend_direction, swing_high, swing_low)
    """
    if len(high) < swing_size * 2:
        return 'neutral', 'neutral', None, None
    
    # Find swing highs and lows
    swing_highs = []
    swing_lows = []
    
    for i in range(swing_size, len(high) - swing_size):
        # Swing high
        if high[i] == max(high[i-swing_size:i+swing_size]):
            swing_highs.append((i, high[i]))
        # Swing low
        if low[i] == min(low[i-swing_size:i+swing_size]):
            swing_lows.append((i, low[i]))
    
    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return 'neutral', 'neutral', None, None
    
    # Check for Break of Structure
    last_high = swing_highs[-1][1]
    prev_high = swing_highs[-2][1]
    last_low = swing_lows[-1][1]
    prev_low = swing_lows[-2][1]
    
    # Uptrend: higher highs and higher lows
    if last_high > prev_high and last_low > prev_low:
        structure = 'bos_up'
        trend = 'bullish'
    # Downtrend: lower highs and lower lows
    elif last_high < prev_high and last_low < prev_low:
        structure = 'bos_down'
        trend = 'bearish'
    # Change of Character: break of previous structure
    elif last_high > prev_high and last_low < prev_low:
        structure = 'choch'
        trend = 'neutral'
    else:
        structure = 'neutral'
        trend = 'neutral'
    
    return structure, trend, swing_highs[-1][1], swing_lows[-1][1]

def find_order_block(high, low, close, lookback=50):
    """
    Identify Order Blocks (OB) - the last opposing candle before a strong move
    Returns: (ob_high, ob_low, ob_direction)
    """
    if len(high) < lookback or len(close) < lookback:
        return None, None, None
    
    # Look for the last strong impulsive move
    for i in range(len(high)-1, max(0, len(high)-lookback), -1):
        try:
            price_change = abs(close[i] - close[i-1])
            avg_change = np.mean(np.abs(np.diff(close[-lookback:])))
            
            # Strong move (2x average)
            if price_change > avg_change * 2:
                # Bullish OB: last bearish candle before move
                if close[i] > close[i-1]:
                    ob_high = float(high[i-1])
                    ob_low = float(low[i-1])
                    ob_direction = 'bullish'
                    return ob_high, ob_low, ob_direction
                # Bearish OB: last bullish candle before move
                else:
                    ob_high = float(high[i-1])
                    ob_low = float(low[i-1])
                    ob_direction = 'bearish'
                    return ob_high, ob_low, ob_direction
        except (IndexError, TypeError, ValueError):
            continue
    
    return None, None, None

def find_fair_value_gap(high, low, lookback=50):
    """
    Identify Fair Value Gaps (FVG)
    Returns: (fvg_high, fvg_low, fvg_direction)
    """
    if len(high) < 3 or len(low) < 3:
        return None, None, None
    
    # Look for 3-candle pattern: gap between candle 1 and candle 3
    for i in range(len(high)-3, max(0, len(high)-lookback), -1):
        try:
            # Bullish FVG: high of candle 1 < low of candle 3
            if high[i] < low[i+2]:
                fvg_high = float(low[i+2])
                fvg_low = float(high[i])
                fvg_direction = 'bullish'
                return fvg_high, fvg_low, fvg_direction
            # Bearish FVG: low of candle 1 > high of candle 3
            elif low[i] > high[i+2]:
                fvg_high = float(low[i])
                fvg_low = float(high[i+2])
                fvg_direction = 'bearish'
                return fvg_high, fvg_low, fvg_direction
        except (IndexError, TypeError, ValueError):
            continue
    
    return None, None, None

# ============================================
# CACHED EXCHANGE
# ============================================

_EXCHANGES = {}

def get_exchange(is_futures):
    key = 'futures' if is_futures else 'spot'
    if key not in _EXCHANGES:
        if is_futures:
            _EXCHANGES[key] = ccxt.binanceusdm({
                'enableRateLimit': True,
                'options': {'defaultType': 'future'}
            })
        else:
            _EXCHANGES[key] = ccxt.binance({
                'enableRateLimit': True,
                'options': {'defaultType': 'spot'}
            })
    return _EXCHANGES[key]

def fetch_data(symbol, timeframe, limit=550):
    try:
        is_futures = ':' in symbol
        exchange = get_exchange(is_futures)

        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        return df

    except Exception as e:
        print(f"⚠️ {symbol}: fetch error - {str(e)[:60]}")
        return None

def check_timeframe_confirmation(symbol, timeframe, rsi_period, signal_direction='BUY', rsi_threshold=35):
    """
    Fix #7: original always checked rsi < threshold (bullish confirmation only).
    Now accepts signal_direction so SELL signals check rsi > (100 - threshold).
    """
    df = fetch_data(symbol, timeframe, limit=100)
    if df is None or len(df) < 50:
        return False, None

    close = df['close'].values
    rsi_val = rsi(close[-rsi_period - 20:], rsi_period)

    if signal_direction == 'BUY':
        confirms = rsi_val < rsi_threshold          # oversold on higher TF → bullish
    else:
        confirms = rsi_val > (100 - rsi_threshold)  # overbought on higher TF → bearish

    return confirms, round(rsi_val, 2)

# ============================================
# BTC MARKET STATE (DISPLAY ONLY)
# ============================================

def get_btc_market_state_higher_tf(timeframe, threshold=1.5):
    try:
        if timeframe in ['1m', '5m', '15m']:
            tfs_to_check = ['1h', '4h']
        elif timeframe in ['30m', '1h']:
            tfs_to_check = ['4h', '1d']
        else:
            tfs_to_check = ['1d']
        
        states = []
        changes = []
        
        for tf in tfs_to_check:
            df = fetch_data('BTC/USDT', tf, limit=20)
            if df is None or len(df) < 10:
                continue
            
            close = df['close'].values
            current_price = close[-1]
            price_5_ago = close[-5] if len(close) >= 5 else current_price
            price_10_ago = close[-10] if len(close) >= 10 else current_price
            
            change_5 = ((current_price - price_5_ago) / price_5_ago) * 100
            change_10 = ((current_price - price_10_ago) / price_10_ago) * 100
            avg_change = (change_5 + change_10) / 2
            
            if avg_change > threshold * 2:
                state = 'STRONG_BULLISH'
            elif avg_change > threshold:
                state = 'BULLISH'
            elif avg_change < -threshold * 2:
                state = 'STRONG_BEARISH'
            elif avg_change < -threshold:
                state = 'BEARISH'
            else:
                state = 'NEUTRAL'
            
            states.append(state)
            changes.append(avg_change)
        
        if len(states) >= 2:
            priority = {'STRONG_BEARISH': 0, 'BEARISH': 1, 'NEUTRAL': 2, 'BULLISH': 3, 'STRONG_BULLISH': 4}
            worst_state = min(states, key=lambda x: priority.get(x, 2))
            worst_change = changes[states.index(worst_state)]
            return worst_state, worst_change, tfs_to_check[0]
        elif len(states) == 1:
            return states[0], changes[0], tfs_to_check[0]
        else:
            return 'NEUTRAL', 0.0, 'unknown'
        
    except Exception as e:
        print(f"⚠️ BTC state check error: {str(e)[:60]}")
        return 'NEUTRAL', 0.0, 'unknown'

# ============================================
# POSITION SIZING CALCULATOR
# ============================================

def calculate_position_size(price, stop_loss, confidence, account_size, risk_percent):
    base_risk = account_size * risk_percent
    confidence_multiplier = 0.5 + (confidence / 100) * 1.0
    adjusted_risk = base_risk * confidence_multiplier
    
    risk_per_unit = abs(price - stop_loss)
    position_size = adjusted_risk / risk_per_unit if risk_per_unit > 0 else 0
    position_value = position_size * price
    
    max_position_value = account_size * 0.5
    if position_value > max_position_value:
        position_size = max_position_value / price
        position_value = max_position_value
    
    min_position_value = 50
    if position_value < min_position_value:
        position_size = min_position_value / price
        position_value = min_position_value
    
    return {
        'size': round(position_size, 4),
        'value': round(position_value, 2),
        'risk_amount': round(adjusted_risk, 2),
        'risk_percent': round((adjusted_risk / account_size) * 100, 2),
        'confidence_multiplier': round(confidence_multiplier, 2)
    }

# ============================================
# FEED WRITER
# ============================================

def write_to_feed(signals, timeframe, feed_path="./data/alerts.json"):
    if not signals:
        return
    
    feed_entries = []
    for sig in signals:
        conf = round(sig["confidence"], 1)
        direction = "buy" if "BUY" in sig["signal_type"] else "sell"
        
        # Normalise to cTrader symbol format: base currency + "USD" (e.g. BCH/USDT -> BCHUSD).
        # Handles slash pairs (BCH/USDT), futures (XAU/USDT:USDT), concatenated pairs
        # (BCHUSDT), and is idempotent for already-converted symbols (XAUUSD -> XAUUSD).
        raw_symbol = sig["symbol"]
        if ":" in raw_symbol:
            raw_symbol = raw_symbol.split(":")[0]   # drop futures settlement suffix
        if "/" in raw_symbol:
            symbol = raw_symbol.split("/")[0] + "USD"   # slash pair -> base + USD
        elif raw_symbol.endswith("USDT"):
            symbol = raw_symbol[:-4] + "USD"            # concatenated USDT pair -> base + USD
        else:
            symbol = raw_symbol                          # already USD (or other) -> unchanged

        entry = {
            "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            "symbol": symbol,
            "timeframe": timeframe,
            "direction": direction,
            "rsi": sig["rsi"],
            "price": sig["entry"],
            "pivot_level": None,
            "pivot_distance": None,
            "confidence": conf,
            "sl": sig["stop_loss"],
            "tp": sig["tp1"],
            "signal_source": "signal_scanner"
        }
        feed_entries.append(entry)

    if not feed_entries:
        return

    try:
        os.makedirs(os.path.dirname(feed_path), exist_ok=True)
    except (PermissionError, OSError):
        feed_path = "./alerts.json"
    
    existing = []
    if os.path.exists(feed_path):
        with open(feed_path, "r") as f:
            try:
                existing = json.load(f)
            except json.JSONDecodeError:
                existing = []

    combined = (feed_entries + existing)[:500]
    tmp_path = feed_path + ".tmp"
    try:
        with open(tmp_path, "w") as f:
            json.dump(combined, f, indent=2)
        os.replace(tmp_path, feed_path)
        print(f"✅ Wrote {len(feed_entries)} signals to {feed_path}")
    except (PermissionError, OSError) as e:
        print(f"⚠️ Could not write to feed: {e}")

# ============================================
# SUGGESTED ENTRY/EXIT PRICES (3 TARGETS)
# ============================================

def calculate_entry_exit(price, lower, upper, mid, signal_type, confidence, rsi_val, params, rsi_1h=None):
    result = {
        'entry': price,
        'stop_loss': None,
        'take_profit_1': None,
        'take_profit_2': None,
        'take_profit_3': None,
        'target_1_gain': None,
        'target_2_gain': None,
        'target_3_gain': None,
        'risk_reward_1': None,
        'risk_reward_2': None,
        'risk_reward_3': None
    }
    
    stop_distance = params['stop_distance']
    tp1_pct = params['target_1_pct']
    tp2_pct = params['target_2_pct']
    tp3_pct = params['target_3_pct']
    
    entry_adjustment = 0
    
    if rsi_1h is not None:
        if signal_type.startswith('SELL') and rsi_1h < 30:
            adjustment_pct = ((30 - rsi_1h) / 30) * 0.02
            entry_adjustment = price * adjustment_pct
        elif signal_type.startswith('BUY') and rsi_1h > 70:
            adjustment_pct = ((rsi_1h - 70) / 30) * 0.02
            entry_adjustment = -price * adjustment_pct
    
    adjusted_entry = price + entry_adjustment
    
    if signal_type.startswith('BUY'):
        entry = max(adjusted_entry, lower * 1.005)
        result['entry'] = round(entry, 4)
        
        stop = min(price * (1 - stop_distance), lower * (1 - stop_distance * 0.4))
        result['stop_loss'] = round(stop, 4)
        
        tp1 = min(mid, entry * (1 + tp1_pct * 0.5))
        if tp1 <= entry:
            tp1 = entry * (1 + tp1_pct * 0.5)
        result['take_profit_1'] = round(tp1, 4)
        
        tp2 = entry * (1 + tp1_pct + (confidence / 100) * tp1_pct * 0.5)
        result['take_profit_2'] = round(tp2, 4)
        
        tp3 = entry * (1 + tp2_pct + (confidence / 100) * tp2_pct * 0.5)
        result['take_profit_3'] = round(tp3, 4)
        
        risk = entry - stop
        if risk > 0:
            result['target_1_gain'] = round((tp1 - entry) / entry * 100, 2)
            result['target_2_gain'] = round((tp2 - entry) / entry * 100, 2)
            result['target_3_gain'] = round((tp3 - entry) / entry * 100, 2)
            result['risk_reward_1'] = round((tp1 - entry) / risk, 2)
            result['risk_reward_2'] = round((tp2 - entry) / risk, 2)
            result['risk_reward_3'] = round((tp3 - entry) / risk, 2)
        
    elif signal_type.startswith('SELL'):
        entry = min(adjusted_entry, upper * 0.995)
        result['entry'] = round(entry, 4)
        
        stop = max(price * (1 + stop_distance), upper * (1 + stop_distance * 0.4))
        result['stop_loss'] = round(stop, 4)
        
        tp1 = max(mid, entry * (1 - tp1_pct * 0.5))
        if tp1 >= entry:
            tp1 = entry * (1 - tp1_pct * 0.5)
        result['take_profit_1'] = round(tp1, 4)
        
        tp2 = entry * (1 - tp1_pct - (confidence / 100) * tp1_pct * 0.5)
        result['take_profit_2'] = round(tp2, 4)
        
        tp3 = entry * (1 - tp2_pct - (confidence / 100) * tp2_pct * 0.5)
        result['take_profit_3'] = round(tp3, 4)
        
        risk = stop - entry
        if risk > 0:
            result['target_1_gain'] = round((entry - tp1) / entry * 100, 2)
            result['target_2_gain'] = round((entry - tp2) / entry * 100, 2)
            result['target_3_gain'] = round((entry - tp3) / entry * 100, 2)
            result['risk_reward_1'] = round((entry - tp1) / risk, 2)
            result['risk_reward_2'] = round((entry - tp2) / risk, 2)
            result['risk_reward_3'] = round((entry - tp3) / risk, 2)
    
    return result

# ============================================
# ENHANCED SIGNAL DETECTION WITH SQUEEZE + SMRE + SMC
# ============================================

def detect_signals(price, high, low, volume, rsi_val, lower, upper, mid, symbol, params, use_squeeze=True, use_smre=True, use_smc=True):
    current = price[-1]
    prev = price[-2]
    signals = []
    
    rsi_period = params['rsi_period']
    ma_period = params['ma_period']
    confirm_tf = params['confirmation_timeframe']
    
    # --- CALCULATE SQUEEZE MOMENTUM ---
    squeeze_on, momentum, squeeze_release = squeeze_momentum(high, low, price)
    
    # --- CALCULATE SMRE FILTERS ---
    is_mean_reverting, z_score, smre_confidence = smre_filter(price)
    is_stationary, hurst = stationarity_test(price)
    vol_regime, vol_score = volatility_regime(price)
    
    # --- CALCULATE SMC ---
    structure, trend, swing_high, swing_low = detect_market_structure(high, low, price)
    ob_high, ob_low, ob_direction = find_order_block(high, low, price)
    fvg_high, fvg_low, fvg_direction = find_fair_value_gap(high, low)
    
    # 1. CROSSOVER SIGNAL
    if current > lower and prev <= lower and rsi_val < 45:
        base_confidence = min(85, (45 - rsi_val) * 2 + 45)
        signals.append({
            'type': 'BUY_CROSS',
            'base_confidence': base_confidence,
            'description': 'Bullish cross above lower band'
        })
    
    if current < upper and prev >= upper and rsi_val > 55:
        base_confidence = min(85, (rsi_val - 55) * 2 + 45)
        signals.append({
            'type': 'SELL_CROSS',
            'base_confidence': base_confidence,
            'description': 'Bearish cross below upper band'
        })
    
    # 2. OVERSOLD/OVERBOUGHT BOUNCE
    if rsi_val < 35 and current < lower * 1.03:
        base_confidence = min(75, (35 - rsi_val) * 3 + 35)
        signals.append({
            'type': 'BUY_OVERSOLD',
            'base_confidence': base_confidence,
            'description': f'Oversold (RSI {rsi_val:.1f}) near lower band'
        })
    
    if rsi_val > 65 and current > upper * 0.97:
        base_confidence = min(75, (rsi_val - 65) * 3 + 35)
        signals.append({
            'type': 'SELL_OVERBOUGHT',
            'base_confidence': base_confidence,
            'description': f'Overbought (RSI {rsi_val:.1f}) near upper band'
        })
    
    # 3. ENVELOPE EXTREME
    # Fix #5: renamed variable to upper_excess (negative = price above upper band).
    # Fix #6: signal types now carry BUY_/SELL_ prefix so they reach display and
    #         all startswith('BUY') / startswith('SELL') filter branches below.
    if lower is not None and lower > 0:
        lower_dist = ((current - lower) / current) * 100  # negative = below lower
        if lower_dist < -2:
            signals.append({
                'type': 'BUY_EXTREME_OVERSOLD',
                'base_confidence': 60,
                'description': f'Price {abs(lower_dist):.1f}% below lower band'
            })

    if upper is not None and upper > 0:
        upper_excess = ((upper - current) / current) * 100  # negative = above upper
        if upper_excess < -2:
            signals.append({
                'type': 'SELL_EXTREME_OVERBOUGHT',
                'base_confidence': 60,
                'description': f'Price {abs(upper_excess):.1f}% above upper band'
            })
    
    # ============================================
    # FETCH HIGHER TIMEFRAME RSI
    # ============================================
    # Fix #7: derive direction from the first candidate signal so SELL signals
    # check overbought on the higher TF, not oversold (the old behaviour).
    first_direction = 'BUY' if (signals and signals[0]['type'].startswith('BUY')) else 'SELL'
    confirms_1h, rsi_1h = check_timeframe_confirmation(
        symbol, confirm_tf, rsi_period,
        signal_direction=first_direction,
        rsi_threshold=35
    )
    
    # APPLY FILTERS
    enhanced_signals = []
    for signal in signals:
        confidence = signal['base_confidence']
        filters_triggered = []
        skip_signal = False
        
        # FILTER 1: Volume Analysis
        if len(volume) > 15:
            avg_volume = np.mean(volume[-15:])
            current_volume = volume[-1]
            volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1
            
            price_change = (current - price[-5]) / price[-5] * 100 if len(price) > 5 else 0
            
            if volume_ratio > 1.8:
                if signal['type'].startswith('BUY'):
                    if price_change < -2:
                        confidence -= 25
                        filters_triggered.append(f"⚠️ High volume {volume_ratio:.1f}x on down move")
                        if confidence < 30:
                            skip_signal = True
                    else:
                        confidence += 12
                        filters_triggered.append(f"🔥 Volume {volume_ratio:.1f}x avg")
                elif signal['type'].startswith('SELL'):
                    if price_change > 2:
                        confidence -= 25
                        filters_triggered.append(f"⚠️ High volume {volume_ratio:.1f}x on up move")
                        if confidence < 30:
                            skip_signal = True
                    else:
                        confidence += 12
                        filters_triggered.append(f"🔥 Volume {volume_ratio:.1f}x avg")
            elif volume_ratio > 1.3:
                confidence += 6
                filters_triggered.append(f"📈 Volume {volume_ratio:.1f}x avg")
            else:
                filters_triggered.append(f"📉 Volume {volume_ratio:.1f}x avg")
        
        # FILTER 2: MA Trend Alignment
        if len(price) > ma_period:
            ma = np.mean(price[-ma_period:])
            
            if signal['type'].startswith('BUY'):
                if current > ma:
                    confidence += 8
                    filters_triggered.append(f"✅ Above MA{ma_period} (${ma:.2f})")
                else:
                    confidence -= 15
                    filters_triggered.append(f"⚠️ Below MA{ma_period} (${ma:.2f})")
                    if current < ma * 0.98:
                        confidence -= 10
                        filters_triggered.append(f"⚠️ Far below MA{ma_period}")
            
            elif signal['type'].startswith('SELL'):
                if current < ma:
                    confidence += 8
                    filters_triggered.append(f"✅ Below MA{ma_period} (${ma:.2f})")
                else:
                    confidence -= 15
                    filters_triggered.append(f"⚠️ Above MA{ma_period} (${ma:.2f})")
                    if current > ma * 1.02:
                        confidence -= 10
                        filters_triggered.append(f"⚠️ Far above MA{ma_period}")
        
        # FILTER 3: Timeframe Confirmation
        if confirms_1h is not None:
            if confirms_1h:
                confidence += 15
                filters_triggered.append(f"✅ {confirm_tf} confirms (RSI {rsi_1h})")
            else:
                confidence -= 15
                filters_triggered.append(f"⚠️ {confirm_tf} not confirming (RSI {rsi_1h})")
                if signal['type'].startswith('BUY') and rsi_1h > 45:
                    confidence -= 10
                elif signal['type'].startswith('SELL') and rsi_1h < 55:
                    confidence -= 10
        
        # FILTER 4: RSI Divergence Check
        if len(price) > 20:
            if signal['type'].startswith('BUY') and rsi_val < 30 and current > upper:
                confidence -= 20
                filters_triggered.append("⚠️ RSI/Price divergence")
            
            if signal['type'].startswith('SELL') and rsi_val > 70 and current < lower:
                confidence -= 20
                filters_triggered.append("⚠️ RSI/Price divergence")
        
        # FILTER 5: Price Change Velocity
        if len(price) > 10:
            recent_change = (current / price[-10] - 1) * 100
            if signal['type'].startswith('BUY') and recent_change < -10:
                confidence -= 15
                filters_triggered.append(f"⚠️ Sharp drop {recent_change:.1f}%")
            elif signal['type'].startswith('SELL') and recent_change > 10:
                confidence -= 15
                filters_triggered.append(f"⚠️ Sharp rise {recent_change:.1f}%")
        
        # ============================================
        # FILTER 6: HIGHER TIMEFRAME OVERRULE
        # ============================================
        if rsi_1h is not None:
            if signal['type'].startswith('SELL'):
                if rsi_1h < 30:
                    confidence -= 30
                    filters_triggered.append(f"⚠️ CRITICAL: 1h RSI {rsi_1h} < 30 (oversold) - SELL downgraded")
                    if rsi_1h < 20:
                        confidence -= 10
                        filters_triggered.append(f"⚠️ EXTREME: 1h RSI {rsi_1h} < 20 - SELL likely false")
                    if confidence < 40:
                        skip_signal = True
                        filters_triggered.append("❌ Signal skipped - 1h oversold contradicts SELL")
                elif rsi_1h < 40:
                    confidence -= 15
                    filters_triggered.append(f"⚠️ 1h RSI {rsi_1h} (oversold) - reduce confidence")
            
            elif signal['type'].startswith('BUY'):
                if rsi_1h > 70:
                    confidence -= 30
                    filters_triggered.append(f"⚠️ CRITICAL: 1h RSI {rsi_1h} > 70 (overbought) - BUY downgraded")
                    if rsi_1h > 80:
                        confidence -= 10
                        filters_triggered.append(f"⚠️ EXTREME: 1h RSI {rsi_1h} > 80 - BUY likely false")
                    if confidence < 40:
                        skip_signal = True
                        filters_triggered.append("❌ Signal skipped - 1h overbought contradicts BUY")
                elif rsi_1h > 60:
                    confidence -= 15
                    filters_triggered.append(f"⚠️ 1h RSI {rsi_1h} (overbought) - reduce confidence")
        
        # ============================================
        # FILTER 7: SQUEEZE MOMENTUM
        # ============================================
        if use_squeeze:
            if signal['type'].startswith('BUY'):
                if squeeze_release and current > upper:
                    confidence += 15
                    filters_triggered.append(f"🔥 SQUEEZE RELEASE (upside)")
                elif squeeze_on:
                    filters_triggered.append(f"📊 Squeeze active - waiting for release")
                else:
                    confidence -= 5
                    filters_triggered.append(f"⚠️ No squeeze momentum")
            elif signal['type'].startswith('SELL'):
                if squeeze_release and current < lower:
                    confidence += 15
                    filters_triggered.append(f"🔥 SQUEEZE RELEASE (downside)")
                elif squeeze_on:
                    filters_triggered.append(f"📊 Squeeze active - waiting for release")
                else:
                    confidence -= 5
                    filters_triggered.append(f"⚠️ No squeeze momentum")
        
        # ============================================
        # FILTER 8: SMRE STATISTICAL FILTERS
        # ============================================
        if use_smre:
            if not is_mean_reverting:
                confidence -= 10
                filters_triggered.append(f"⚠️ Z-score {z_score:.2f} (not extreme)")
            else:
                confidence += smre_confidence * 0.1
                filters_triggered.append(f"✅ Z-score {z_score:.2f} (extreme)")
            
            if is_stationary:
                confidence += 8
                filters_triggered.append(f"✅ Stationary (Hurst {hurst:.2f})")
            else:
                confidence -= 8
                filters_triggered.append(f"⚠️ Non-stationary (Hurst {hurst:.2f})")
            
            if vol_regime == 'low':
                confidence += 5
                filters_triggered.append(f"✅ Low volatility ({vol_score:.0f}%)")
            elif vol_regime == 'high':
                confidence -= 10
                filters_triggered.append(f"⚠️ High volatility ({vol_score:.0f}%) - reduce size")
        
        # ============================================
        # FILTER 9: SMART MONEY CONCEPTS (SMC)
        # ============================================
        if use_smc:
            # Market Structure Filter
            if signal['type'].startswith('BUY'):
                if trend == 'bullish':
                    confidence += 10
                    filters_triggered.append(f"✅ Bullish structure (BOS UP)")
                elif trend == 'bearish':
                    confidence -= 15
                    filters_triggered.append(f"⚠️ Bearish structure (BOS DOWN) - BUY against trend")
                else:
                    filters_triggered.append(f"⚪ Neutral structure")
            elif signal['type'].startswith('SELL'):
                if trend == 'bearish':
                    confidence += 10
                    filters_triggered.append(f"✅ Bearish structure (BOS DOWN)")
                elif trend == 'bullish':
                    confidence -= 15
                    filters_triggered.append(f"⚠️ Bullish structure (BOS UP) - SELL against trend")
                else:
                    filters_triggered.append(f"⚪ Neutral structure")
            
            # Order Block Filter
            try:
                if ob_high is not None and ob_low is not None:
                    ob_high_val = float(ob_high)
                    ob_low_val = float(ob_low)
                    if signal['type'].startswith('BUY'):
                        if current >= ob_low_val and current <= ob_high_val * 1.02:
                            confidence += 8
                            filters_triggered.append(f"✅ In Order Block zone (${ob_low_val:.2f}-${ob_high_val:.2f})")
                    elif signal['type'].startswith('SELL'):
                        if current >= ob_low_val and current <= ob_high_val:
                            confidence += 8
                            filters_triggered.append(f"✅ In Order Block zone (${ob_low_val:.2f}-${ob_high_val:.2f})")
                else:
                    filters_triggered.append(f"⚠️ No Order Block detected")
            except (TypeError, ValueError):
                pass
            
            # Fair Value Gap Filter
            try:
                if fvg_high is not None and fvg_low is not None:
                    fvg_high_val = float(fvg_high)
                    fvg_low_val = float(fvg_low)
                    if signal['type'].startswith('BUY') and fvg_direction == 'bullish':
                        if current >= fvg_low_val and current <= fvg_high_val:
                            confidence += 10
                            filters_triggered.append(f"✅ In FVG zone (${fvg_low_val:.2f}-${fvg_high_val:.2f})")
                    elif signal['type'].startswith('SELL') and fvg_direction == 'bearish':
                        if current >= fvg_low_val and current <= fvg_high_val:
                            confidence += 10
                            filters_triggered.append(f"✅ In FVG zone (${fvg_low_val:.2f}-${fvg_high_val:.2f})")
                else:
                    filters_triggered.append(f"⚠️ No FVG detected")
            except (TypeError, ValueError):
                pass
        
        # ============================================
        # FINAL CONFIDENCE CALCULATION
        # ============================================
        confidence = max(0, min(100, confidence))
        
        if confidence < 50:
            skip_signal = True
        
        if not skip_signal:
            enhanced_signals.append({
                'type': signal['type'],
                'confidence': round(confidence, 1),
                'description': signal['description'],
                'filters': filters_triggered,
                'base_confidence': signal['base_confidence'],
                'rsi_1h': rsi_1h,
                'squeeze_on': squeeze_on,
                'squeeze_release': squeeze_release,
                'z_score': round(z_score, 2),
                'hurst': hurst,
                'vol_regime': vol_regime,
                'smc_trend': trend,
                'smc_structure': structure,
                'ob_high': ob_high,
                'ob_low': ob_low,
                'fvg_high': fvg_high,
                'fvg_low': fvg_low
            })
    
    enhanced_signals.sort(key=lambda x: x['confidence'], reverse=True)
    return enhanced_signals

# ============================================
# MAIN SCAN FUNCTION
# ============================================

def scan_with_signals(timeframe, verbose, account_size, risk_percent, max_positions, use_squeeze=True, use_smre=True, use_smc=True):
    params = get_timeframe_params(timeframe)
    results = []
    
    # Get BTC market state for display
    btc_state, btc_change, btc_tf = get_btc_market_state_higher_tf(timeframe, threshold=1.5)
    
    print(f"\n{'='*110}")
    print(f"📊 MULTI-ASSET SCANNER: {timeframe} | {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*110}")
    print(f"Account: ${account_size:,} | Risk: {risk_percent*100:.1f}% per trade | Max Positions: {max_positions}")
    print(f"Parameters: Bandwidth={params['bandwidth']}, Multiplier={params['multiplier']}, RSI={params['rsi_period']}")
    print(f"Confirmation: {params['confirmation_timeframe']} | MA{params['ma_period']} | Targets: {params['target_1_pct']*100:.0f}%/{params['target_2_pct']*100:.0f}%/{params['target_3_pct']*100:.0f}%")
    print(f"Symbols: {len(SPOT_SYMBOLS)} Spot + {len(FUTURES_SYMBOLS)} Futures")
    print(f"BTC Market State: {btc_state} ({btc_change:.2f}%) on {btc_tf}")
    print(f"Filters: Squeeze={'✅' if use_squeeze else '❌'} | SMRE={'✅' if use_smre else '❌'} | SMC={'✅' if use_smc else '❌'}")
    print(f"{'='*110}\n")
    
    for symbol in SYMBOLS:
        try:
            df = fetch_data(symbol, timeframe, params['lookback'] + 50)
            if df is None or len(df) < params['lookback']:
                continue
            
            close = df['close'].values
            high = df['high'].values
            low = df['low'].values
            volume = df['volume'].values
            
            mid, upper, lower = nadaraya_watson_envelope(
                close, params['bandwidth'], params['multiplier'], params['lookback']
            )
            
            if mid is None:
                continue
            
            rsi_val = rsi(close[-params['rsi_period']-30:], params['rsi_period'])
            current_price = close[-1]
            
            signals = detect_signals(
                close, high, low, volume, rsi_val, lower, upper, mid, symbol, params,
                use_squeeze=use_squeeze, use_smre=use_smre, use_smc=use_smc
            )
            
            if signals:
                best = signals[0]
                
                entry_exit = calculate_entry_exit(
                    current_price, lower, upper, mid,
                    best['type'], best['confidence'], rsi_val, params,
                    rsi_1h=best.get('rsi_1h')
                )
                
                position_size = calculate_position_size(
                    current_price, entry_exit['stop_loss'], best['confidence'],
                    account_size, risk_percent
                )
                
                position = "Inside"
                if current_price < lower:
                    position = "Below Lower"
                elif current_price > upper:
                    position = "Above Upper"
                
                # Build filter string with all indicators
                filter_parts = []
                if best.get('filters'):
                    filter_parts.extend(best['filters'])
                if 'squeeze_on' in best:
                    filter_parts.append(f"Squeeze: {'ON' if best['squeeze_on'] else 'OFF'}")
                if 'squeeze_release' in best and best['squeeze_release']:
                    filter_parts.append("🔥 RELEASE")
                if 'z_score' in best:
                    filter_parts.append(f"Z: {best['z_score']:.2f}")
                if 'hurst' in best:
                    filter_parts.append(f"H: {best['hurst']:.2f}")
                if 'vol_regime' in best:
                    filter_parts.append(f"Vol: {best['vol_regime']}")
                if 'smc_trend' in best:
                    filter_parts.append(f"SMC: {best['smc_trend'].upper()}")
                if 'smc_structure' in best and best['smc_structure'] != 'neutral':
                    filter_parts.append(f"Structure: {best['smc_structure'].upper()}")
                
                results.append({
                    'symbol': symbol,
                    'price': current_price,
                    'signal_type': best['type'],
                    'confidence': best['confidence'],
                    'description': best['description'],
                    'filters': ', '.join(filter_parts) if filter_parts else 'None',
                    'rsi': round(rsi_val, 2),
                    'lower': round(lower, 2),
                    'upper': round(upper, 2),
                    'mid': round(mid, 2),
                    'position': position,
                    'entry': entry_exit['entry'],
                    'stop_loss': entry_exit['stop_loss'],
                    'tp1': entry_exit['take_profit_1'],
                    'tp2': entry_exit['take_profit_2'],
                    'tp3': entry_exit['take_profit_3'],
                    'target_1_gain': entry_exit['target_1_gain'],
                    'target_2_gain': entry_exit['target_2_gain'],
                    'target_3_gain': entry_exit['target_3_gain'],
                    'risk_reward_1': entry_exit['risk_reward_1'],
                    'risk_reward_2': entry_exit['risk_reward_2'],
                    'risk_reward_3': entry_exit['risk_reward_3'],
                    'position_size': position_size['size'],
                    'position_value': position_size['value'],
                    'risk_amount': position_size['risk_amount'],
                    'risk_percent': position_size['risk_percent']
                })
            else:
                if verbose:
                    position = "Inside"
                    if current_price < lower:
                        position = "Below Lower"
                    elif current_price > upper:
                        position = "Above Upper"
                    
                    results.append({
                        'symbol': symbol,
                        'price': current_price,
                        'signal_type': 'NEUTRAL',
                        'confidence': 0,
                        'description': 'No signal',
                        'filters': 'N/A',
                        'rsi': round(rsi_val, 2),
                        'lower': round(lower, 2),
                        'upper': round(upper, 2),
                        'mid': round(mid, 2),
                        'position': position,
                        'entry': None,
                        'stop_loss': None,
                        'tp1': None,
                        'tp2': None,
                        'tp3': None,
                        'target_1_gain': None,
                        'target_2_gain': None,
                        'target_3_gain': None,
                        'risk_reward_1': None,
                        'risk_reward_2': None,
                        'risk_reward_3': None,
                        'position_size': None,
                        'position_value': None,
                        'risk_amount': None,
                        'risk_percent': None
                    })
                
        except Exception as e:
            print(f"❌ {symbol}: Error - {str(e)[:80]}")
    
    # Convert to DataFrame and sort
    df_results = pd.DataFrame(results)
    
    if len(df_results) == 0:
        print("No results found")
        return df_results
    
    df_results = df_results.sort_values('confidence', ascending=False)
    
    # DISPLAY - Signal Summary
    signals_df = df_results[df_results['signal_type'].str.startswith(('BUY', 'SELL'))]
    
    if len(signals_df) > 0:
        print(f"{'SYMBOL':<14} {'PRICE':<10} {'SIGNAL':<18} {'CONF':<6} {'RSI':<8} {'POSITION':<15} {'FILTERS'}")
        print("-"*110)
        
        for _, row in signals_df.iterrows():
            emoji = "🔴" if row['signal_type'].startswith('SELL') else "🟢"
            conf_display = f"{row['confidence']}%"
            filters_display = row['filters'][:40] + '...' if len(row['filters']) > 40 else row['filters']
            symbol_display = row['symbol'][:14]
            print(f"{symbol_display:<14} ${row['price']:<9.2f} {emoji} {row['signal_type']:<16} {conf_display:<5}  {row['rsi']:<6}  {row['position']:<15} {filters_display}")
        
        # DISPLAY - Detailed Trading Plans
        print(f"\n{'='*110}")
        print("📊 TRADING PLANS (3 Targets)")
        print(f"{'='*110}\n")
        
        for _, row in signals_df.iterrows():
            print(f"🎯 {row['symbol']} - {row['signal_type']} (Confidence: {row['confidence']}%)")
            print(f"   📍 Entry: ${row['entry']:.4f}")
            print(f"   🛑 Stop Loss: ${row['stop_loss']:.4f} (Risk: ${row['risk_amount']:.2f} | {row['risk_percent']:.2f}% of account)")
            print(f"   🎯 TP1: ${row['tp1']:.4f} (+{row['target_1_gain']:.1f}%) | R:R {row['risk_reward_1']:.2f}")
            print(f"   🎯 TP2: ${row['tp2']:.4f} (+{row['target_2_gain']:.1f}%) | R:R {row['risk_reward_2']:.2f}")
            print(f"   🎯 TP3: ${row['tp3']:.4f} (+{row['target_3_gain']:.1f}%) | R:R {row['risk_reward_3']:.2f}")
            print(f"   📊 Position Size: {row['position_size']:.4f} units (${row['position_value']:.2f})")
            print(f"   🔍 Filters: {row['filters']}")
            print()
    else:
        print("📭 No signals detected in this scan.")
    
    # DISPLAY - Summary
    buy_signals = df_results[df_results['signal_type'].str.startswith('BUY')]
    sell_signals = df_results[df_results['signal_type'].str.startswith('SELL')]
    neutral = df_results[df_results['signal_type'] == 'NEUTRAL']
    
    print(f"\n{'='*110}")
    print(f"SUMMARY: {len(buy_signals)} BUY | {len(sell_signals)} SELL | {len(neutral)} NEUTRAL | {len(df_results)} TOTAL")
    
    if len(buy_signals) > 0:
        print("\n🟢 TOP BUY SIGNALS:")
        for _, row in buy_signals.head(3).iterrows():
            print(f"   {row['symbol']}: {row['description']}")
            print(f"      Entry: ${row['entry']:.4f} | Stop: ${row['stop_loss']:.4f}")
            print(f"      TP1: ${row['tp1']:.4f} | TP2: ${row['tp2']:.4f} | TP3: ${row['tp3']:.4f}")
    
    if len(sell_signals) > 0:
        print("\n🔴 TOP SELL SIGNALS:")
        for _, row in sell_signals.head(3).iterrows():
            print(f"   {row['symbol']}: {row['description']}")
            print(f"      Entry: ${row['entry']:.4f} | Stop: ${row['stop_loss']:.4f}")
            print(f"      TP1: ${row['tp1']:.4f} | TP2: ${row['tp2']:.4f} | TP3: ${row['tp3']:.4f}")
    
    print(f"{'='*110}")

    # Write detected signals to the feed
    write_to_feed(signals_df.to_dict('records'), timeframe)

    # Display BTC state again after scan
    print(f"\n📊 Final BTC Market State: {btc_state} ({btc_change:.2f}%) on {btc_tf}")

    return df_results

# ============================================
# RUN
# ============================================

def main():
    args = parse_args()
    
    # SMC built-in functions are always available; respect --no-smc flag only
    use_smc = not args.no_smc
    
    # List timeframes
    if args.list_timeframes:
        print("\n📊 Available Timeframes:")
        print("  ⏱️ 1m   - Scalping (very active)")
        print("  ⏱️ 5m   - Scalping")
        print("  ⏱️ 15m  - Day trading")
        print("  ⏱️ 30m  - Day/Swing trading")
        print("  ⏱️ 1h   - Swing trading (default)")
        print("  ⏱️ 2h   - Swing trading")
        print("  ⏱️ 4h   - Swing/Position trading")
        print("  ⏱️ 6h   - Position trading")
        print("  ⏱️ 12h  - Position trading")
        print("  ⏱️ 1d   - Long-term position trading")
        print("\n💡 Recommended scan frequencies:")
        print("  1m-15m: Every 5-15 minutes")
        print("  30m-1h: Every 30-60 minutes")
        print("  2h-4h:  Every 2-4 hours")
        print("  6h-1d:  Every 6-24 hours")
        sys.exit(0)
    
    # Validate timeframe
    valid_timeframes = ['1m', '5m', '15m', '30m', '1h', '2h', '4h', '6h', '12h', '1d']
    if args.timeframe not in valid_timeframes:
        print(f"❌ Invalid timeframe: {args.timeframe}")
        print(f"   Valid options: {', '.join(valid_timeframes)}")
        print(f"   Use --list-timeframes for more details")
        sys.exit(1)
    
    print("🔍 Starting Enhanced Multi-Asset Scanner...")
    print(f"   Timeframe: {args.timeframe}")
    print(f"   Account: ${args.account_size:,}")
    print(f"   Risk per trade: {args.risk*100:.1f}%")
    print(f"   Max positions: {args.max_positions}")
    if args.verbose:
        print("   Verbose mode: ON (showing all symbols)")
    print(f"   Squeeze Momentum: {'ENABLED' if not args.no_squeeze else 'DISABLED'}")
    print(f"   SMRE Filters: {'ENABLED' if not args.no_smre else 'DISABLED'}")
    print(f"   SMC Filters: {'ENABLED' if use_smc else 'DISABLED'}")
    
    start_time = time.time()
    results = scan_with_signals(
        args.timeframe,
        args.verbose,
        args.account_size,
        args.risk,
        args.max_positions,
        use_squeeze=not args.no_squeeze,
        use_smre=not args.no_smre,
        use_smc=use_smc
    )
    elapsed = time.time() - start_time
    
    print(f"\n⏱️ Scan completed in {elapsed:.2f} seconds")
    
    if args.timeframe in ['1m', '5m', '15m']:
        print(f"\n💡 Recommended scan frequency: Every {args.timeframe} (or more frequently for scalping)")
    elif args.timeframe in ['30m', '1h']:
        print(f"\n💡 Recommended scan frequency: Every 30-60 minutes")
    elif args.timeframe in ['2h', '4h']:
        print(f"\n💡 Recommended scan frequency: Every {args.timeframe}")
    else:
        print(f"\n💡 Recommended scan frequency: Every {args.timeframe} or daily")

if __name__ == "__main__":
    main()
