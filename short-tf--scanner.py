import ccxt
import pandas as pd
import numpy as np
from datetime import datetime
import time
import warnings
warnings.filterwarnings('ignore')

# ============================================
# CONFIGURATION - SHORT TERM
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
    'SHIB/USDT', 'STX/USDT', 'TAO/USDT', 'TIA/USDT', 
    'TRX/USDT', 'UNI/USDT', 'VIRTUAL/USDT', 'WLD/USDT', 
    'ZEC/USDT'
]

# Futures symbols (metals)
FUTURES_SYMBOLS = [
    'XAU/USDT:USDT',  # Gold perpetual
    'XAG/USDT:USDT'   # Silver perpetual
]

# Combine all symbols
SYMBOLS = SPOT_SYMBOLS + FUTURES_SYMBOLS

# ============================================
# SHORT-TERM TIMEFRAME CONFIGURATION
# ============================================
# Choose your timeframe: '5m', '15m', '30m'
TIMEFRAME = '30m'  # Change to '5m' or '30m' as needed
TIMEFRAME_HIGHER = '1h'  # For additional confirmation

LOOKBACK = 200  # Reduced from 500 for faster response
BANDWIDTH = 4.0  # Reduced for more sensitivity on short timeframes
MULTIPLIER = 2.5  # Reduced for tighter envelopes
RSI_PERIOD = 10  # Shorter RSI period for faster signals
MA_PERIOD = 50  # Shorter MA for trend filter

# ============================================
# POSITION SIZING CONFIGURATION
# ============================================
ACCOUNT_SIZE = 50000  # $10,000 account
MAX_RISK_PER_TRADE = 0.015  # 1.5% risk per trade (tighter for short-term)
MAX_POSITIONS = 5  # More positions for short-term scalping

# ============================================
# INDICATOR FUNCTIONS
# ============================================

def gaussian_kernel(x, h):
    return np.exp(-(x**2) / (2 * h**2))

def nadaraya_watson_envelope(price, h, mult):
    """Faster version with adjustable lookback"""
    n = len(price)
    if n < LOOKBACK:
        return None, None, None
    
    price_array = np.array(price[-LOOKBACK:])
    smoothed = np.zeros(LOOKBACK)
    for i in range(LOOKBACK):
        w = gaussian_kernel(np.arange(LOOKBACK) - i, h)
        smoothed[i] = np.sum(price_array * w) / np.sum(w)
    
    mae = np.mean(np.abs(price_array - smoothed)) * mult
    middle = smoothed[-1]
    upper = middle + mae
    lower = middle - mae
    
    return middle, upper, lower

def rsi(price, period=10):
    """Shorter RSI for faster signals"""
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

def fetch_data(symbol, timeframe, limit=250):
    """Fetch data with adjusted limit for short timeframes"""
    try:
        is_futures = ':' in symbol
        
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

def check_timeframe_confirmation(symbol, timeframe, rsi_threshold=35):
    """Check higher timeframe confirmation"""
    df = fetch_data(symbol, timeframe, limit=100)
    if df is None or len(df) < 50:
        return False, None
    
    close = df['close'].values
    rsi_val = rsi(close[-RSI_PERIOD-20:], RSI_PERIOD)
    confirms = rsi_val < rsi_threshold
    return confirms, round(rsi_val, 2)

# ============================================
# POSITION SIZING CALCULATOR
# ============================================

def calculate_position_size(price, stop_loss, confidence, account_size=ACCOUNT_SIZE, risk_percent=MAX_RISK_PER_TRADE):
    """Calculate position size with tighter risk for short-term trades"""
    base_risk = account_size * risk_percent
    
    # Confidence multiplier (0.3x to 1.2x for short-term)
    confidence_multiplier = 0.3 + (confidence / 100) * 0.9
    adjusted_risk = base_risk * confidence_multiplier
    
    risk_per_unit = abs(price - stop_loss)
    position_size = adjusted_risk / risk_per_unit if risk_per_unit > 0 else 0
    position_value = position_size * price
    
    # Cap at 30% of account per trade (tighter for short-term)
    max_position_value = account_size * 0.3
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
# SUGGESTED ENTRY/EXIT PRICES
# ============================================

def calculate_entry_exit(price, lower, upper, mid, signal_type, confidence, rsi_val):
    """Calculate entry/exit with tighter stops for short-term"""
    result = {
        'entry': price,
        'stop_loss': None,
        'take_profit_1': None,
        'take_profit_2': None,
        'target_1_gain': None,
        'target_2_gain': None,
        'risk_reward_1': None,
        'risk_reward_2': None
    }
    
    if signal_type.startswith('BUY'):
        entry = max(price, lower * 1.005)
        result['entry'] = round(entry, 4)
        
        # Tighter stop for short-term (1.5% instead of 2.5%)
        stop = min(price * 0.985, lower * 0.995)
        result['stop_loss'] = round(stop, 4)
        
        # Tighter targets for short-term
        tp1 = entry * (1 + (0.015 + (confidence / 100) * 0.015))
        result['take_profit_1'] = round(tp1, 4)
        
        tp2 = entry * (1 + (0.03 + (confidence / 100) * 0.03))
        result['take_profit_2'] = round(tp2, 4)
        
        risk = entry - stop
        if risk > 0:
            result['target_1_gain'] = round((tp1 - entry) / entry * 100, 2)
            result['target_2_gain'] = round((tp2 - entry) / entry * 100, 2)
            result['risk_reward_1'] = round((tp1 - entry) / risk, 2)
            result['risk_reward_2'] = round((tp2 - entry) / risk, 2)
        
    elif signal_type.startswith('SELL'):
        entry = min(price, upper * 0.995)
        result['entry'] = round(entry, 4)
        
        stop = max(price * 1.015, upper * 1.005)
        result['stop_loss'] = round(stop, 4)
        
        tp1 = entry * (1 - (0.015 + (confidence / 100) * 0.015))
        result['take_profit_1'] = round(tp1, 4)
        
        tp2 = entry * (1 - (0.03 + (confidence / 100) * 0.03))
        result['take_profit_2'] = round(tp2, 4)
        
        risk = stop - entry
        if risk > 0:
            result['target_1_gain'] = round((entry - tp1) / entry * 100, 2)
            result['target_2_gain'] = round((entry - tp2) / entry * 100, 2)
            result['risk_reward_1'] = round((entry - tp1) / risk, 2)
            result['risk_reward_2'] = round((entry - tp2) / risk, 2)
    
    return result

# ============================================
# ENHANCED SIGNAL DETECTION
# ============================================

def detect_signals(price, volume, rsi_val, lower, upper, mid, symbol):
    """Signal detection optimized for short-term trading"""
    current = price[-1]
    prev = price[-2]
    signals = []
    
    # 1. CROSSOVER SIGNAL (faster)
    if current > lower and prev <= lower and rsi_val < 45:  # Less strict RSI
        base_confidence = min(85, (45 - rsi_val) * 2 + 45)
        signals.append({
            'type': 'BUY_CROSS',
            'base_confidence': base_confidence,
            'description': 'Bullish cross above lower band'
        })
    
    if current < upper and prev >= upper and rsi_val > 55:  # Less strict RSI
        base_confidence = min(85, (rsi_val - 55) * 2 + 45)
        signals.append({
            'type': 'SELL_CROSS',
            'base_confidence': base_confidence,
            'description': 'Bearish cross below upper band'
        })
    
    # 2. OVERSOLD/OVERBOUGHT BOUNCE (more sensitive)
    if rsi_val < 35 and current < lower * 1.03:  # More generous threshold
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
    
    # 3. ENVELOPE EXTREME (more sensitive)
    if lower is not None and lower > 0:
        lower_dist = ((current - lower) / current) * 100
        if lower_dist < -2:  # Reduced from -3
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
    
    # APPLY FILTERS (adjusted for short-term)
    enhanced_signals = []
    for signal in signals:
        confidence = signal['base_confidence']
        filters_triggered = []
        
        # FILTER 1: Volume (more sensitive)
        if len(volume) > 15:  # Reduced from 20
            avg_volume = np.mean(volume[-15:])
            current_volume = volume[-1]
            volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1
            
            if volume_ratio > 1.8:  # Higher threshold for short-term
                confidence += 12
                filters_triggered.append(f"🔥 Volume {volume_ratio:.1f}x avg")
            elif volume_ratio > 1.3:
                confidence += 6
                filters_triggered.append(f"📈 Volume {volume_ratio:.1f}x avg")
            else:
                filters_triggered.append(f"📉 Volume {volume_ratio:.1f}x avg")
        
        # FILTER 2: MA50 Trend (shorter than MA200)
        if len(price) > MA_PERIOD:
            ma_50 = np.mean(price[-MA_PERIOD:])
            
            if signal['type'].startswith('BUY'):
                if current > ma_50:
                    confidence += 6
                    filters_triggered.append(f"✅ Above MA50 (${ma_50:.2f})")
                else:
                    confidence -= 3
                    filters_triggered.append(f"⚠️ Below MA50 (${ma_50:.2f})")
            
            elif signal['type'].startswith('SELL'):
                if current < ma_50:
                    confidence += 6
                    filters_triggered.append(f"✅ Below MA50 (${ma_50:.2f})")
                else:
                    confidence -= 3
                    filters_triggered.append(f"⚠️ Above MA50 (${ma_50:.2f})")
        
        # FILTER 3: Higher Timeframe Confirmation (1h)
        confirms_1h, rsi_1h = check_timeframe_confirmation(symbol, TIMEFRAME_HIGHER)
        if confirms_1h is not None:
            if confirms_1h:
                confidence += 10
                filters_triggered.append(f"✅ 1h confirms (RSI {rsi_1h})")
            else:
                confidence -= 5
                filters_triggered.append(f"⚠️ 1h not confirming (RSI {rsi_1h})")
        
        confidence = max(0, min(100, confidence))
        
        enhanced_signals.append({
            'type': signal['type'],
            'confidence': round(confidence, 1),
            'description': signal['description'],
            'filters': filters_triggered,
            'base_confidence': signal['base_confidence']
        })
    
    enhanced_signals.sort(key=lambda x: x['confidence'], reverse=True)
    return enhanced_signals

# ============================================
# MAIN SCAN FUNCTION
# ============================================

def scan_short_term():
    results = []
    
    print(f"\n{'='*100}")
    print(f"SHORT-TERM SCAN: {TIMEFRAME} | {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"Account: ${ACCOUNT_SIZE:,} | Max Risk: {MAX_RISK_PER_TRADE*100:.1f}% per trade | Max Positions: {MAX_POSITIONS}")
    print(f"Filters: Volume ✓ | MA50 ✓ | 1h Confirmation ✓")
    print(f"Symbols: {len(SPOT_SYMBOLS)} Spot + {len(FUTURES_SYMBOLS)} Futures")
    print(f"Settings: Bandwidth={BANDWIDTH}, Multiplier={MULTIPLIER}, RSI={RSI_PERIOD}")
    print(f"{'='*100}\n")
    
    for symbol in SYMBOLS:
        try:
            df = fetch_data(symbol, TIMEFRAME, LOOKBACK + 50)
            if df is None or len(df) < LOOKBACK:
                continue
            
            close = df['close'].values
            volume = df['volume'].values
            
            mid, upper, lower = nadaraya_watson_envelope(close, BANDWIDTH, MULTIPLIER)
            
            if mid is None:
                continue
            
            rsi_val = rsi(close[-RSI_PERIOD-30:], RSI_PERIOD)
            current_price = close[-1]
            
            signals = detect_signals(close, volume, rsi_val, lower, upper, mid, symbol)
            
            if signals:
                best = signals[0]
                
                entry_exit = calculate_entry_exit(
                    current_price, lower, upper, mid,
                    best['type'], best['confidence'], rsi_val
                )
                
                position_size = calculate_position_size(
                    current_price, entry_exit['stop_loss'], best['confidence']
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
                    'risk_reward_1': entry_exit['risk_reward_1'],
                    'risk_reward_2': entry_exit['risk_reward_2'],
                    'position_size': position_size['size'],
                    'position_value': position_size['value'],
                    'risk_amount': position_size['risk_amount'],
                    'risk_percent': position_size['risk_percent']
                })
            else:
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
                    'risk_reward_1': None,
                    'risk_reward_2': None,
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
    print(f"{'SYMBOL':<14} {'PRICE':<10} {'SIGNAL':<18} {'CONF':<6} {'RSI':<8} {'POSITION':<15} {'FILTERS'}")
    print("-"*110)
    
    for _, row in df_results.iterrows():
        emoji = "🔴" if row['signal_type'].startswith('SELL') else "🟢" if row['signal_type'].startswith('BUY') else "⚪"
        conf_display = f"{row['confidence']}%" if row['confidence'] > 0 else "---"
        filters_display = row['filters'][:40] + '...' if len(row['filters']) > 40 else row['filters']
        symbol_display = row['symbol'][:14]
        print(f"{symbol_display:<14} ${row['price']:<9.2f} {emoji} {row['signal_type']:<16} {conf_display:<5}  {row['rsi']:<6}  {row['position']:<15} {filters_display}")
    
    # DISPLAY - Detailed Trading Plans
    signals_df = df_results[df_results['signal_type'].str.startswith(('BUY', 'SELL'))]
    
    if len(signals_df) > 0:
        print(f"\n{'='*100}")
        print("📊 SHORT-TERM TRADING PLANS")
        print(f"{'='*100}\n")
        
        for _, row in signals_df.iterrows():
            print(f"🎯 {row['symbol']} - {row['signal_type']} (Confidence: {row['confidence']}%)")
            print(f"   📍 Entry: ${row['entry']:.4f}")
            print(f"   🛑 Stop Loss: ${row['stop_loss']:.4f} (Risk: ${row['risk_amount']:.2f} | {row['risk_percent']:.2f}% of account)")
            print(f"   🎯 Take Profit 1: ${row['tp1']:.4f} (+{row.get('target_1_gain', 0):.1f}%) | R:R {row['risk_reward_1']:.2f}")
            print(f"   🎯 Take Profit 2: ${row['tp2']:.4f} (+{row.get('target_2_gain', 0):.1f}%) | R:R {row['risk_reward_2']:.2f}")
            print(f"   📊 Position Size: {row['position_size']:.4f} units (${row['position_value']:.2f})")
            print(f"   🔍 Filters: {row['filters']}")
            print()
    
    # DISPLAY - Summary
    buy_signals = df_results[df_results['signal_type'].str.startswith('BUY')]
    sell_signals = df_results[df_results['signal_type'].str.startswith('SELL')]
    neutral = df_results[df_results['signal_type'] == 'NEUTRAL']
    
    print(f"\n{'='*100}")
    print(f"SUMMARY: {len(buy_signals)} BUY | {len(sell_signals)} SELL | {len(neutral)} NEUTRAL | {len(df_results)} TOTAL")
    
    if len(buy_signals) > 0:
        print("\n🟢 TOP BUY SIGNALS:")
        for _, row in buy_signals.head(3).iterrows():
            print(f"   {row['symbol']}: {row['description']}")
            print(f"      Entry: ${row['entry']:.4f} | Stop: ${row['stop_loss']:.4f} | TP1: ${row['tp1']:.4f} | TP2: ${row['tp2']:.4f}")
    
    if len(sell_signals) > 0:
        print("\n🔴 TOP SELL SIGNALS:")
        for _, row in sell_signals.head(3).iterrows():
            print(f"   {row['symbol']}: {row['description']}")
            print(f"      Entry: ${row['entry']:.4f} | Stop: ${row['stop_loss']:.4f} | TP1: ${row['tp1']:.4f} | TP2: ${row['tp2']:.4f}")
    
    print(f"{'='*100}")
    return df_results

# ============================================
# RUN
# ============================================
if __name__ == "__main__":
    print("🔍 Starting Short-Term Multi-Asset Scanner...")
    print(f"Scanning {len(SYMBOLS)} symbols on {TIMEFRAME} timeframe\n")
    
    start_time = time.time()
    results = scan_short_term()
    elapsed = time.time() - start_time
    
    print(f"\n⏱️ Scan completed in {elapsed:.2f} seconds")
    print(f"\n💡 Recommended scan frequency: Every {TIMEFRAME}")
