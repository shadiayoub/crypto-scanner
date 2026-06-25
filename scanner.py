#!/usr/bin/env python3
"""
Multi-Asset Scanner with Nadaraya-Watson Envelope
Supports both long-term and short-term timeframes via command-line arguments
Includes Bitcoin Market Filter for trend reversal detection

Usage:
    python scanner.py                    # Default: 1h timeframe
    python scanner.py -tf 15m            # 15-minute timeframe
    python scanner.py -tf 5m             # 5-minute timeframe
    python scanner.py -tf 4h             # 4-hour timeframe
    python scanner.py -tf 1h -v          # 1h with verbose output
    python scanner.py --help             # Show help
"""

import ccxt
import pandas as pd
import numpy as np
from datetime import datetime
import time
import warnings
import argparse
import sys
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
  python scanner.py --no-btc-filter    # Disable Bitcoin market filter
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
        '--no-btc-filter',
        action='store_true',
        help='Disable Bitcoin market filter (use at your own risk)'
    )
    
    parser.add_argument(
        '--btc-threshold',
        type=float,
        default=1.5,
        help='BTC price change threshold to trigger filter reversal (default: 1.5%%)'
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
    'ONDO/USDT', 'ORDI/USDT', 'PENGU/USDT', 'PNUT/USDT',
    'POL/USDT', 'PUMP/USDT', 'RENDER/USDT', 'S/USDT',
    'SHIB/USDT', 'STX/USDT', 'TAO/USDT', 'TIA/USDT', 'TRUMP/USDT',
    'TRX/USDT', 'UNI/USDT', 'VIRTUAL/USDT', 'WLD/USDT', 
    'ZEC/USDT'
]

# Futures symbols (for metals and other perpetuals)
FUTURES_SYMBOLS = [
    'XAU/USDT:USDT',  # Gold perpetual
    'XAG/USDT:USDT'   # Silver perpetual
]

# Define metals for special handling
METAL_SYMBOLS = ['XAU/USDT:USDT', 'XAG/USDT:USDT']

# Combine all symbols
SYMBOLS = SPOT_SYMBOLS + FUTURES_SYMBOLS

# ============================================
# TIMEFRAME-SPECIFIC PARAMETERS
# ============================================

def get_timeframe_params(timeframe, is_metal=False):
    """
    Returns optimized parameters for each timeframe
    For metals, uses reduced lookback due to limited historical data
    """
    # Base parameters
    if is_metal:
        # Metals have limited data (only ~50 bars on Binance Futures)
        params = {
            'lookback': 40,  # Much smaller for metals
            'bandwidth': 4.0,
            'multiplier': 2.5,
            'rsi_period': 10,
            'ma_period': 30,
            'confirmation_timeframe': '1h',
            'max_positions': 5,
            'risk_per_trade': 0.015,
            'stop_distance': 0.02,
            'target_1_pct': 0.02,
            'target_2_pct': 0.035,
            'target_3_pct': 0.05,
            'filters': ['ma', 'confirmation']  # Volume filter disabled for metals
        }
    else:
        # Standard parameters for crypto
        params = {
            'lookback': 500,
            'bandwidth': 6.0,
            'multiplier': 3.0,
            'rsi_period': 14,
            'ma_period': 200,
            'confirmation_timeframe': '15m',
            'max_positions': 3,
            'risk_per_trade': 0.02,
            'stop_distance': 0.025,
            'target_1_pct': 0.03,
            'target_2_pct': 0.05,
            'target_3_pct': 0.07,
            'filters': ['volume', 'ma', 'confirmation']
        }
    
    # Adjust based on timeframe for non-metals
    if not is_metal:
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
                'stop_distance': 0.015,
                'target_1_pct': 0.015,
                'target_2_pct': 0.025,
                'target_3_pct': 0.04,
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
                'stop_distance': 0.03,
                'target_1_pct': 0.04,
                'target_2_pct': 0.07,
                'target_3_pct': 0.10,
            })
    
    return params

# ============================================
# BITCOIN MARKET FILTER (HIGHER TIMEFRAME)
# ============================================

def get_btc_market_state_higher_tf(timeframe, threshold=1.5):
    """
    Analyze Bitcoin's trend using HIGHER TIMEFRAMES
    Returns: (state, change_pct, timeframe_used)
    """
    try:
        # Determine which higher timeframe to use
        if timeframe in ['1m', '5m', '15m']:
            # For short-term signals, check 1h and 4h
            tfs_to_check = ['1h', '4h']
        elif timeframe in ['30m', '1h']:
            # For medium-term signals, check 4h and 1d
            tfs_to_check = ['4h', '1d']
        else:
            # For long-term signals, check 1d
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
            
            # Calculate changes
            change_5 = ((current_price - price_5_ago) / price_5_ago) * 100
            change_10 = ((current_price - price_10_ago) / price_10_ago) * 100
            avg_change = (change_5 + change_10) / 2
            
            # Determine state for this timeframe
            if avg_change > threshold * 2:
                state = 'strong_bullish'
            elif avg_change > threshold:
                state = 'bullish'
            elif avg_change < -threshold * 2:
                state = 'strong_bearish'
            elif avg_change < -threshold:
                state = 'bearish'
            else:
                state = 'neutral'
            
            states.append(state)
            changes.append(avg_change)
        
        # If we have multiple timeframes, use the more bearish/bullish one
        # (higher timeframe takes precedence)
        if len(states) >= 2:
            # Prioritize: strong_bearish > bearish > neutral > bullish > strong_bullish
            priority = {'strong_bearish': 0, 'bearish': 1, 'neutral': 2, 'bullish': 3, 'strong_bullish': 4}
            
            # Get the most bearish or bullish state (whichever is more extreme)
            worst_state = min(states, key=lambda x: priority.get(x, 2))
            worst_change = changes[states.index(worst_state)]
            
            return worst_state, worst_change, tfs_to_check[0]
        elif len(states) == 1:
            return states[0], changes[0], tfs_to_check[0]
        else:
            return 'neutral', 0.0, 'unknown'
        
    except Exception as e:
        print(f"⚠️ BTC higher TF filter error: {str(e)[:60]}")
        return 'neutral', 0.0, 'unknown'

def apply_btc_filter_higher_tf(signal_type, confidence, btc_state, btc_change, btc_tf):
    """
    Apply Bitcoin filter based on HIGHER TIMEFRAME trend
    """
    # If neutral, no change
    if btc_state == 'neutral':
        return signal_type, 0, f"BTC {btc_tf} neutral ({btc_change:.1f}%)"
    
    # Define reversal map
    reversal_map = {
        'BUY_OVERSOLD': 'SELL_OVERBOUGHT',
        'SELL_OVERBOUGHT': 'BUY_OVERSOLD',
        'BUY_CROSS': 'SELL_CROSS',
        'SELL_CROSS': 'BUY_CROSS',
        'EXTREME_OVERSOLD': 'EXTREME_OVERBOUGHT',
        'EXTREME_OVERBOUGHT': 'EXTREME_OVERSOLD'
    }
    
    # STRONG bearish: REVERSE all BUY signals
    if btc_state == 'strong_bearish':
        if signal_type.startswith('BUY'):
            new_signal = reversal_map.get(signal_type, signal_type)
            confidence_adj = -20
            message = f"⚠️ BTC {btc_tf} STRONG BEARISH ({btc_change:.1f}%) - SIGNAL REVERSED: {signal_type} → {new_signal}"
            return new_signal, confidence_adj, message
        else:
            # SELL signals are confirmed
            confidence_adj = 10
            message = f"✅ BTC {btc_tf} STRONG BEARISH ({btc_change:.1f}%) - SELL confirmed"
            return signal_type, confidence_adj, message
    
    # Bearish: DOWNGRADE BUY signals, CONFIRM SELL signals
    elif btc_state == 'bearish':
        if signal_type.startswith('BUY'):
            confidence_adj = -20  # Bigger penalty
            message = f"⚠️ BTC {btc_tf} bearish ({btc_change:.1f}%) - BUY downgraded"
            return signal_type, confidence_adj, message
        else:
            confidence_adj = 5
            message = f"✅ BTC {btc_tf} bearish ({btc_change:.1f}%) - SELL confirmed"
            return signal_type, confidence_adj, message
    
    # Strong bullish: REVERSE all SELL signals
    elif btc_state == 'strong_bullish':
        if signal_type.startswith('SELL'):
            new_signal = reversal_map.get(signal_type, signal_type)
            confidence_adj = -20
            message = f"⚠️ BTC {btc_tf} STRONG BULLISH ({btc_change:.1f}%) - SIGNAL REVERSED: {signal_type} → {new_signal}"
            return new_signal, confidence_adj, message
        else:
            confidence_adj = 10
            message = f"✅ BTC {btc_tf} STRONG BULLISH ({btc_change:.1f}%) - BUY confirmed"
            return signal_type, confidence_adj, message
    
    # Bullish: DOWNGRADE SELL signals, CONFIRM BUY signals
    elif btc_state == 'bullish':
        if signal_type.startswith('SELL'):
            confidence_adj = -20
            message = f"⚠️ BTC {btc_tf} bullish ({btc_change:.1f}%) - SELL downgraded"
            return signal_type, confidence_adj, message
        else:
            confidence_adj = 5
            message = f"✅ BTC {btc_tf} bullish ({btc_change:.1f}%) - BUY confirmed"
            return signal_type, confidence_adj, message
    
    return signal_type, 0, f"BTC {btc_tf} neutral ({btc_change:.1f}%)"

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
    if len(price) < period + 1:
        return 50.0
    
    delta = np.diff(price)
    gain = (delta.copy() * 0)
    loss = (delta.copy() * 0)
    gain[delta > 0] = delta[delta > 0]
    loss[delta < 0] = -delta[delta < 0]
    
    avg_gain = np.mean(gain[:period])
    avg_loss = np.mean(loss[:period])
    
    if avg_loss == 0:
        return 100.0
    if avg_gain == 0:
        return 0.0
    
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def fetch_data(symbol, timeframe, limit=550):
    """Fetch data with special handling for metals"""
    try:
        is_futures = ':' in symbol
        is_metal = symbol in METAL_SYMBOLS
        
        # For metals, we need to fetch more data to get enough for lookback
        if is_metal:
            limit = 100
        
        if is_futures:
            exchange = ccxt.binanceusdm({
                'enableRateLimit': True,
                'options': {'defaultType': 'future'}
            })
        else:
            exchange = ccxt.binance({
                'enableRateLimit': True,
                'options': {'defaultType': 'spot'}
            })
        
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        return df
        
    except Exception as e:
        print(f"⚠️ {symbol}: fetch error - {str(e)[:60]}")
        return None

def check_timeframe_confirmation(symbol, timeframe, rsi_period, rsi_threshold=35):
    df = fetch_data(symbol, timeframe, limit=100)
    if df is None or len(df) < 30:
        return False, None
    
    close = df['close'].values
    rsi_val = rsi(close[-rsi_period-20:], rsi_period)
    confirms = rsi_val < rsi_threshold
    return confirms, round(rsi_val, 2)

# ============================================
# POSITION SIZING CALCULATOR
# ============================================

def calculate_position_size(price, stop_loss, confidence, account_size, risk_percent, is_metal=False):
    base_risk = account_size * risk_percent
    
    # Confidence multiplier (adjusted for metals)
    if is_metal:
        confidence_multiplier = 0.3 + (confidence / 100) * 0.7  # Lower for metals
    else:
        confidence_multiplier = 0.5 + (confidence / 100) * 1.0
    
    adjusted_risk = base_risk * confidence_multiplier
    
    risk_per_unit = abs(price - stop_loss)
    position_size = adjusted_risk / risk_per_unit if risk_per_unit > 0 else 0
    position_value = position_size * price
    
    max_position_value = account_size * 0.3 if is_metal else account_size * 0.5
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
# SUGGESTED ENTRY/EXIT PRICES (3 TARGETS)
# ============================================

def calculate_entry_exit(price, lower, upper, mid, signal_type, confidence, rsi_val, params, rsi_1h=None):
    """
    Calculate suggested entry, stop loss, and take profit levels
    With entry adjustment for higher timeframe divergence
    """
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
    
    # ============================================
    # ENTRY PRICE ADJUSTMENT FOR DIVERGENCE
    # ============================================
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
# ENHANCED SIGNAL DETECTION WITH HIGHER TIMEFRAME OVERRULE
# ============================================

def detect_signals(price, volume, rsi_val, lower, upper, mid, symbol, params, is_metal=False, btc_state='neutral', btc_change=0, btc_tf='unknown'):
    current = price[-1]
    prev = price[-2]
    signals = []
    
    rsi_period = params['rsi_period']
    ma_period = params['ma_period']
    confirm_tf = params['confirmation_timeframe']
    
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
    if lower is not None and lower > 0:
        lower_dist = ((current - lower) / current) * 100
        if lower_dist < -2:
            signals.append({
                'type': 'EXTREME_OVERSOLD',
                'base_confidence': 60,
                'description': f'Price {abs(lower_dist):.1f}% below lower band'
            })
    
    if upper is not None and upper > 0:
        upper_dist = ((upper - current) / current) * 100
        if upper_dist < -2:
            signals.append({
                'type': 'EXTREME_OVERBOUGHT',
                'base_confidence': 60,
                'description': f'Price {abs(upper_dist):.1f}% above upper band'
            })
    
    # ============================================
    # FETCH HIGHER TIMEFRAME RSI FOR OVERRULE LOGIC
    # ============================================
    confirms_1h, rsi_1h = check_timeframe_confirmation(
        symbol, confirm_tf, rsi_period, rsi_threshold=35
    )
    
    # APPLY FILTERS
    enhanced_signals = []
    for signal in signals:
        confidence = signal['base_confidence']
        filters_triggered = []
        skip_signal = False
        
        # FILTER 1: Volume Analysis (SKIP FOR METALS)
        if not is_metal and len(volume) > 15:
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
        elif is_metal:
            filters_triggered.append(f"💰 Metal: Volume filter bypassed")
        
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
        
        # FILTER 3: Timeframe Confirmation (Standard)
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
        # FILTER 6: HIGHER TIMEFRAME OVERRULE LOGIC
        # ============================================
        if rsi_1h is not None:
            
            # --- SELL SIGNAL OVERRULE ---
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
            
            # --- BUY SIGNAL OVERRULE ---
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
        # FILTER 7: BITCOIN MARKET FILTER
        # ============================================
        # Apply BTC filter (only for non-BTC symbols)
        if symbol != 'BTC/USDT' and btc_state != 'neutral':
            new_signal, btc_confidence_adj, btc_message = apply_btc_filter_higher_tf(
                signal['type'], confidence, btc_state, btc_change, btc_tf
            )
            
            # Update signal type and confidence
            if new_signal != signal['type']:
                signal['type'] = new_signal
                signal['description'] = f"{signal['description']} (REVERSED by BTC filter)"
                filters_triggered.append(btc_message)
            
            confidence += btc_confidence_adj
            filters_triggered.append(f"BTC filter: {btc_message}")
        
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
                'rsi_1h': rsi_1h
            })
    
    enhanced_signals.sort(key=lambda x: x['confidence'], reverse=True)
    return enhanced_signals

# ============================================
# MAIN SCAN FUNCTION
# ============================================

def scan_with_signals(timeframe, verbose, account_size, risk_percent, max_positions, use_btc_filter=True, btc_threshold=1.5):
    results = []
    
    print(f"\n{'='*110}")
    print(f"📊 MULTI-ASSET SCANNER: {timeframe} | {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*110}")
    print(f"Account: ${account_size:,} | Risk: {risk_percent*100:.1f}% per trade | Max Positions: {max_positions}")
    print(f"Symbols: {len(SPOT_SYMBOLS)} Spot + {len(FUTURES_SYMBOLS)} Futures (XAU/XAG)")
    if use_btc_filter:
        print(f"🐂 Bitcoin Market Filter: ENABLED (threshold: {btc_threshold}%)")
        # Check BTC state for display
        btc_state, btc_change, btc_tf = get_btc_market_state_higher_tf(timeframe, threshold=btc_threshold)
        print(f"   BTC Market State: {btc_state.upper()} ({btc_change:.2f}%) on {btc_tf}")

    else:
        print(f"🐂 Bitcoin Market Filter: DISABLED")
    print(f"{'='*110}\n")
    
    # Get BTC market state once for the entire scan
    btc_state = 'neutral'
    btc_change = 0.0
    if use_btc_filter:
        btc_state, btc_change, btc_tf = get_btc_market_state_higher_tf(timeframe, threshold=btc_threshold)
    
    for symbol in SYMBOLS:
        try:
            is_metal = symbol in METAL_SYMBOLS
            is_btc = symbol == 'BTC/USDT'
            
            # Get parameters (different for metals)
            params = get_timeframe_params(timeframe, is_metal)
            
            # For metals, we need to use the lookback + some buffer
            lookback_needed = params['lookback']
            fetch_limit = lookback_needed + 50
            
            df = fetch_data(symbol, timeframe, limit=fetch_limit)
            
            if df is None or len(df) < max(30, lookback_needed * 0.6):
                if is_metal:
                    print(f"⚠️ {symbol}: Only {len(df) if df is not None else 0} bars (needs ~{lookback_needed * 0.6:.0f} for metal)")
                continue
            
            close = df['close'].values
            volume = df['volume'].values
            
            # If we don't have enough bars for the full lookback, use what we have
            actual_lookback = min(lookback_needed, len(close))
            mid, upper, lower = nadaraya_watson_envelope(
                close, params['bandwidth'], params['multiplier'], actual_lookback
            )
            
            if mid is None:
                continue
            
            rsi_val = rsi(close[-params['rsi_period']-30:], params['rsi_period'])
            current_price = close[-1]
            
            # For BTC, we don't apply BTC filter to itself
            if is_btc:
                btc_state_for_symbol = 'neutral'
                btc_change_for_symbol = 0.0
            else:
                btc_state_for_symbol = btc_state
                btc_change_for_symbol = btc_change
            
            signals = detect_signals(
                close, volume, rsi_val, lower, upper, mid, symbol, params, is_metal,
                btc_state_for_symbol, btc_change_for_symbol
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
                    account_size, risk_percent, is_metal
                )
                
                position = "Inside"
                if current_price < lower:
                    position = "Below Lower"
                elif current_price > upper:
                    position = "Above Upper"
                
                results.append({
                    'symbol': symbol,
                    'price': current_price,
                    'signal_type': best['type'],
                    'confidence': best['confidence'],
                    'description': best['description'],
                    'filters': ', '.join(best['filters']) if best['filters'] else 'None',
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
    
    # DISPLAY - Signal Summary (always show signals)
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
    return df_results

# ============================================
# RUN
# ============================================

def main():
    args = parse_args()
    
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
    
    print("🔍 Starting Multi-Asset Scanner...")
    print(f"   Timeframe: {args.timeframe}")
    print(f"   Account: ${args.account_size:,}")
    print(f"   Risk per trade: {args.risk*100:.1f}%")
    print(f"   Max positions: {args.max_positions}")
    if args.verbose:
        print("   Verbose mode: ON (showing all symbols)")
    if args.no_btc_filter:
        print("   Bitcoin Market Filter: DISABLED")
    else:
        print(f"   Bitcoin Market Filter: ENABLED (threshold: {args.btc_threshold}%)")
    print(f"   Metals: XAU/XAG with reduced lookback ({get_timeframe_params(args.timeframe, True)['lookback']} bars)")
    
    start_time = time.time()
    results = scan_with_signals(
        args.timeframe,
        args.verbose,
        args.account_size,
        args.risk,
        args.max_positions,
        use_btc_filter=not args.no_btc_filter,
        btc_threshold=args.btc_threshold
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
