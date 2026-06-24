import ccxt
import pandas as pd
import numpy as np
from datetime import datetime
import time
import warnings
warnings.filterwarnings('ignore')

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

# Combine all symbols
SYMBOLS = SPOT_SYMBOLS + FUTURES_SYMBOLS

TIMEFRAME = '1h'
TIMEFRAME_15M = '15m'
LOOKBACK = 500
BANDWIDTH = 6.0
MULTIPLIER = 3.0
RSI_PERIOD = 14
MA_PERIOD = 200

# ============================================
# POSITION SIZING CONFIGURATION
# ============================================
ACCOUNT_SIZE = 10000  # $10,000 account (adjust to your size)
MAX_RISK_PER_TRADE = 0.02  # 2% of account = $200 risk per trade
MAX_POSITIONS = 3  # Maximum number of concurrent positions

# ============================================
# INDICATOR FUNCTIONS
# ============================================

def gaussian_kernel(x, h):
    return np.exp(-(x**2) / (2 * h**2))

def nadaraya_watson_envelope(price, h, mult):
    n = len(price)
    if n < 500:
        return None, None, None
    
    price_array = np.array(price[-500:])
    smoothed = np.zeros(500)
    for i in range(500):
        w = gaussian_kernel(np.arange(500) - i, h)
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
    """
    Fetch data from Binance — automatically handles spot and futures
    """
    try:
        # Determine if it's a futures symbol (contains ':')
        is_futures = ':' in symbol
        
        if is_futures:
            # Use futures exchange
            exchange = ccxt.binanceusdm({
                'enableRateLimit': True,
                'options': {
                    'defaultType': 'future'
                }
            })
        else:
            # Use spot exchange
            exchange = ccxt.binance({
                'enableRateLimit': True,
                'options': {
                    'defaultType': 'spot'
                }
            })
        
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        return df
        
    except Exception as e:
        print(f"⚠️ {symbol}: fetch error - {str(e)[:60]}")
        return None

def check_timeframe_confirmation(symbol, timeframe, rsi_threshold=35):
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
    """
    Calculate position size based on:
    - Risk per trade (fixed % of account)
    - Stop loss distance
    - Signal confidence (adjusts risk)
    - Maximum position limit
    """
    # Base risk amount
    base_risk = account_size * risk_percent
    
    # Adjust risk based on confidence (scale 0.5x to 1.5x)
    confidence_multiplier = 0.5 + (confidence / 100) * 1.0  # 50% confidence = 1.0x, 90% = 1.4x
    adjusted_risk = base_risk * confidence_multiplier
    
    # Calculate risk per unit (stop loss distance)
    risk_per_unit = abs(price - stop_loss)
    
    # Position size (units)
    position_size = adjusted_risk / risk_per_unit if risk_per_unit > 0 else 0
    
    # Position value
    position_value = position_size * price
    
    # Cap position to 50% of account per trade
    max_position_value = account_size * 0.5
    if position_value > max_position_value:
        position_size = max_position_value / price
        position_value = max_position_value
    
    # Minimum position (to avoid dust)
    min_position_value = 50  # $50 minimum
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
    """
    Calculate suggested entry, stop loss, and take profit levels
    """
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
        # ENTRY: Current price or slightly above lower band
        entry = max(price, lower * 1.005)  # Slight premium to avoid fake breakout
        result['entry'] = round(entry, 4)
        
        # STOP LOSS: Below recent swing low or lower band
        stop = min(price * 0.975, lower * 0.99)  # 2.5% below or lower band
        result['stop_loss'] = round(stop, 4)
        
        # TAKE PROFIT 1: Conservative (3-5% gain)
        tp1 = entry * (1 + (0.03 + (confidence / 100) * 0.02))  # 3-5%
        result['take_profit_1'] = round(tp1, 4)
        
        # TAKE PROFIT 2: Aggressive (5-10% gain)
        tp2 = entry * (1 + (0.05 + (confidence / 100) * 0.05))  # 5-10%
        result['take_profit_2'] = round(tp2, 4)
        
        # Calculate risk/reward
        risk = entry - stop
        if risk > 0:
            result['target_1_gain'] = round((tp1 - entry) / entry * 100, 2)
            result['target_2_gain'] = round((tp2 - entry) / entry * 100, 2)
            result['risk_reward_1'] = round((tp1 - entry) / risk, 2)
            result['risk_reward_2'] = round((tp2 - entry) / risk, 2)
        
    elif signal_type.startswith('SELL'):
        # ENTRY: Current price or slightly below upper band
        entry = min(price, upper * 0.995)  # Slight discount to avoid fake breakdown
        result['entry'] = round(entry, 4)
        
        # STOP LOSS: Above recent swing high or upper band
        stop = max(price * 1.025, upper * 1.01)  # 2.5% above or upper band
        result['stop_loss'] = round(stop, 4)
        
        # TAKE PROFIT 1: Conservative (3-5% gain)
        tp1 = entry * (1 - (0.03 + (confidence / 100) * 0.02))
        result['take_profit_1'] = round(tp1, 4)
        
        # TAKE PROFIT 2: Aggressive (5-10% gain)
        tp2 = entry * (1 - (0.05 + (confidence / 100) * 0.05))
        result['take_profit_2'] = round(tp2, 4)
        
        # Calculate risk/reward
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
    current = price[-1]
    prev = price[-2]
    signals = []
    
    # 1. CROSSOVER SIGNAL
    if current > lower and prev <= lower and rsi_val < 40:
        base_confidence = min(90, (40 - rsi_val) * 2 + 50)
        signals.append({
            'type': 'BUY_CROSS',
            'base_confidence': base_confidence,
            'description': 'Bullish cross above lower band'
        })
    
    if current < upper and prev >= upper and rsi_val > 60:
        base_confidence = min(90, (rsi_val - 60) * 2 + 50)
        signals.append({
            'type': 'SELL_CROSS',
            'base_confidence': base_confidence,
            'description': 'Bearish cross below upper band'
        })
    
    # 2. OVERSOLD/OVERBOUGHT BOUNCE
    if rsi_val < 30 and current < lower * 1.02:
        base_confidence = min(80, (30 - rsi_val) * 3 + 40)
        signals.append({
            'type': 'BUY_OVERSOLD',
            'base_confidence': base_confidence,
            'description': f'Deep oversold (RSI {rsi_val:.1f}) near lower band'
        })
    
    if rsi_val > 70 and current > upper * 0.98:
        base_confidence = min(80, (rsi_val - 70) * 3 + 40)
        signals.append({
            'type': 'SELL_OVERBOUGHT',
            'base_confidence': base_confidence,
            'description': f'Overbought (RSI {rsi_val:.1f}) near upper band'
        })
    
    # 3. ENVELOPE EXTREME
    if lower is not None and lower > 0:
        lower_dist = ((current - lower) / current) * 100
        if lower_dist < -3:
            signals.append({
                'type': 'EXTREME_OVERSOLD',
                'base_confidence': 65,
                'description': f'Price {abs(lower_dist):.1f}% below lower band'
            })
    
    if upper is not None and upper > 0:
        upper_dist = ((upper - current) / current) * 100
        if upper_dist < -3:
            signals.append({
                'type': 'EXTREME_OVERBOUGHT',
                'base_confidence': 65,
                'description': f'Price {abs(upper_dist):.1f}% above upper band'
            })
    
    # APPLY FILTERS
    enhanced_signals = []
    for signal in signals:
        confidence = signal['base_confidence']
        filters_triggered = []
        
        # FILTER 1: Volume
        if len(volume) > 20:
            avg_volume = np.mean(volume[-20:])
            current_volume = volume[-1]
            volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1
            
            if volume_ratio > 1.5:
                confidence += 10
                filters_triggered.append(f"🔥 Volume {volume_ratio:.1f}x avg")
            elif volume_ratio > 1.2:
                confidence += 5
                filters_triggered.append(f"📈 Volume {volume_ratio:.1f}x avg")
            else:
                filters_triggered.append(f"📉 Volume {volume_ratio:.1f}x avg (below threshold)")
        
        # FILTER 2: MA200 Trend
        if len(price) > MA_PERIOD:
            ma_200 = np.mean(price[-MA_PERIOD:])
            
            if signal['type'].startswith('BUY'):
                if current > ma_200:
                    confidence += 8
                    filters_triggered.append(f"✅ Above MA200 (${ma_200:.2f})")
                else:
                    confidence -= 5
                    filters_triggered.append(f"⚠️ Below MA200 (${ma_200:.2f})")
            
            elif signal['type'].startswith('SELL'):
                if current < ma_200:
                    confidence += 8
                    filters_triggered.append(f"✅ Below MA200 (${ma_200:.2f})")
                else:
                    confidence -= 5
                    filters_triggered.append(f"⚠️ Above MA200 (${ma_200:.2f})")
        
        # FILTER 3: 15m Confirmation
        confirms_15m, rsi_15m = check_timeframe_confirmation(symbol, TIMEFRAME_15M)
        if confirms_15m is not None:
            if confirms_15m:
                confidence += 12
                filters_triggered.append(f"✅ 15m confirms (RSI {rsi_15m})")
            else:
                confidence -= 3
                filters_triggered.append(f"⚠️ 15m not confirming (RSI {rsi_15m})")
        
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
# MAIN SCAN FUNCTION WITH POSITION SIZING
# ============================================

def scan_with_signals():
    results = []
    
    print(f"\n{'='*100}")
    print(f"ENHANCED SCAN: {TIMEFRAME} | {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"Account: ${ACCOUNT_SIZE:,} | Max Risk: {MAX_RISK_PER_TRADE*100:.0f}% per trade | Max Positions: {MAX_POSITIONS}")
    print(f"Filters: Volume ✓ | MA200 ✓ | 15m Confirmation ✓")
    print(f"Symbols: {len(SPOT_SYMBOLS)} Spot + {len(FUTURES_SYMBOLS)} Futures (XAU/XAG)")
    print(f"{'='*100}\n")
    
    for symbol in SYMBOLS:
        try:
            df = fetch_data(symbol, TIMEFRAME, LOOKBACK+50)
            if df is None or len(df) < 500:
                print(f"⚠️ {symbol}: Insufficient data... Continuing scan 🔍")
                continue
            
            close = df['close'].values
            volume = df['volume'].values
            
            mid, upper, lower = nadaraya_watson_envelope(close, BANDWIDTH, MULTIPLIER)
            
            if mid is None:
                continue
            
            rsi_val = rsi(close[-RSI_PERIOD-50:], RSI_PERIOD)
            current_price = close[-1]
            
            signals = detect_signals(close, volume, rsi_val, lower, upper, mid, symbol)
            
            if signals:
                best = signals[0]
                
                # Calculate position size and entry/exit
                entry_exit = calculate_entry_exit(
                    current_price, lower, upper, mid,
                    best['type'], best['confidence'], rsi_val
                )
                
                position_size = calculate_position_size(
                    current_price, entry_exit['stop_loss'], best['confidence']
                )
                
                # Price position
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
    
    # DISPLAY - Detailed Trading Plan for Signals
    signals_df = df_results[df_results['signal_type'].str.startswith(('BUY', 'SELL'))]
    
    if len(signals_df) > 0:
        print(f"\n{'='*100}")
        print("📊 TRADING PLANS FOR SIGNALS")
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
        print("\n🟢 TOP BUY SIGNALS (with trading plan):")
        for _, row in buy_signals.head(2).iterrows():
            print(f"   {row['symbol']}: {row['description']}")
            print(f"      Entry: ${row['entry']:.4f} | Stop: ${row['stop_loss']:.4f} | TP1: ${row['tp1']:.4f} | TP2: ${row['tp2']:.4f}")
            print(f"      Size: {row['position_size']:.4f} units (${row['position_value']:.2f}) | Risk: ${row['risk_amount']:.2f}")
    
    if len(sell_signals) > 0:
        print("\n🔴 TOP SELL SIGNALS (with trading plan):")
        for _, row in sell_signals.head(2).iterrows():
            print(f"   {row['symbol']}: {row['description']}")
            print(f"      Entry: ${row['entry']:.4f} | Stop: ${row['stop_loss']:.4f} | TP1: ${row['tp1']:.4f} | TP2: ${row['tp2']:.4f}")
            print(f"      Size: {row['position_size']:.4f} units (${row['position_value']:.2f}) | Risk: ${row['risk_amount']:.2f}")
    
    print(f"{'='*100}")
    return df_results

# ============================================
# RUN
# ============================================
if __name__ == "__main__":
    print("🔍 Starting Enhanced Multi-Asset Scanner with Position Sizing...")
    print(f"Scanning {len(SYMBOLS)} symbols on {TIMEFRAME} timeframe\n")
    
    start_time = time.time()
    results = scan_with_signals()
    elapsed = time.time() - start_time
    
    print(f"\n⏱️ Scan completed in {elapsed:.2f} seconds")
