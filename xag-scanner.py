#!/usr/bin/env python3
"""
XAG (Silver) Precision Intraday Scanner - Enhanced Version
Optimized for 15m/30m TFs with dynamic ATR risk management, 
session-aware filtering, and liquidity sweep detection.
"""

import ccxt
import pandas as pd
import numpy as np
import ctrader_feed  # silver OHLC sourced from cTrader (XAGUSD), more accurate than Binance perp
from datetime import datetime, timezone
import time
import warnings
import argparse
import sys
import json
import os

warnings.filterwarnings('ignore')

# ============================================
# ARGS
# ============================================

def parse_args():
    parser = argparse.ArgumentParser(
        description='XAG Precision Intraday Scanner — Optimized for 15m/30m Commodity Trading',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('-tf', '--timeframe', type=str, default='15m',
        help='Timeframe to scan: 5m, 15m, or 30m. Default is 15m.')
    parser.add_argument('--loop', type=int, default=0,
        help='Repeat scan every N minutes (0 = single run)')
    parser.add_argument('--account', type=float, default=10000,
        help='Account size in USD (default: 10000)')
    parser.add_argument('--risk', type=float, default=0.01,
        help='Risk per trade as decimal (default: 0.01 = 1%%)')
    parser.add_argument('--no-bias', action='store_true',
        help='Disable macro trend-bias weighting')
    parser.add_argument('-v', '--verbose', action='store_true',
        help='Show all order flow and mathematical filter details per signal')
    parser.add_argument('--min-conf', type=float, default=50.0,
        help='Minimum confidence to display a signal (default: 50)')
    return parser.parse_args()

# ============================================
# EXCHANGE INTERFACE (FUTURES OPTIMIZED)
# ============================================

_EX = {}

def get_exchange():
    if 'futures' not in _EX:
        _EX['futures'] = ccxt.binance({
            'enableRateLimit': True,
            'options': {'defaultType': 'future'}
        })
    return _EX['futures']

# Silver now comes from cTrader (XAGUSD) for price accuracy, since we trade there.
CTRADER_SILVER = 'XAGUSD'

def fetch_ohlcv(symbol, timeframe, limit=350):
    try:
        # Route silver to cTrader; same OHLCV columns the rest of the file expects.
        df = ctrader_feed.get_trendbars(CTRADER_SILVER, timeframe, count=limit)
        if df is None:
            return None
        return df.rename(columns={'timestamp': 'ts'})
    except Exception as e:
        print(f"  ⚠️ fetch_ohlcv({symbol},{timeframe}): {str(e)[:60]}")
        return None

def fetch_order_book_imbalance(symbol, depth_pct=0.003):
    # cTrader L2 depth isn't wired (it's a live subscription, not a trendbar
    # fetch), and mixing Binance's book with cTrader prices would cross venues.
    # Return neutral (1.0) — downstream treats 1.0 as no adjustment, so the
    # order-flow filter degrades cleanly until depth streaming is added.
    return 1.0

# ============================================
# MATHEMATICAL INDICATORS
# ============================================

def gaussian_kernel(x, h):
    return np.exp(-(x**2) / (2 * h**2))

def nadaraya_watson_envelope(price, h, mult, lookback):
    n = len(price)
    if n < lookback:
        return None, None, None
    arr = np.array(price[-lookback:])
    smoothed = np.zeros(lookback)
    for i in range(lookback):
        w = gaussian_kernel(np.arange(lookback) - i, h)
        smoothed[i] = np.sum(arr * w) / np.sum(w)
    mae = np.mean(np.abs(arr - smoothed)) * mult
    mid = smoothed[-1]
    return mid, mid + mae, mid - mae

def rsi(price, period=14):
    if len(price) < period + 1:
        return 50.0
    delta = np.diff(price)
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    avg_gain = np.mean(gain[:period])
    avg_loss = np.mean(loss[:period])
    for i in range(period, len(delta)):
        avg_gain = (avg_gain * (period - 1) + gain[i]) / period
        avg_loss = (avg_loss * (period - 1) + loss[i]) / period
    if avg_loss == 0:
        return 100.0
    return 100 - (100 / (1 + avg_gain / avg_loss))

def ema(price, period):
    if len(price) < period:
        return price[-1]
    k = 2.0 / (period + 1)
    e = price[0]
    for p in price[1:]:
        e = p * k + e * (1 - k)
    return e

def atr(high, low, close, period=14):
    if len(high) < period + 1:
        return (high[-1] - low[-1])
    tr = np.maximum(high[1:] - low[1:],
         np.maximum(np.abs(high[1:] - close[:-1]),
                    np.abs(low[1:] - close[:-1])))
    return np.mean(tr[-period:])

def detect_market_structure(high, low, swing=8):
    if len(high) < swing * 3:
        return 'neutral'
    sh, sl = [], []
    for i in range(swing, len(high) - swing):
        if high[i] == max(high[i-swing:i+swing]):
            sh.append(high[i])
        if low[i] == min(low[i-swing:i+swing]):
            sl.append(low[i])
    if len(sh) >= 2 and len(sl) >= 2:
        if sh[-1] > sh[-2] and sl[-1] > sl[-2]:
            return 'bullish'
        if sh[-1] < sh[-2] and sl[-1] < sl[-2]:
            return 'bearish'
    return 'neutral'

# ============================================
# SESSION AND BIAS UTILITIES
# ============================================

def get_trading_session():
    """Identifies current trading session based on UTC time."""
    now = datetime.now(timezone.utc)
    hour = now.hour
    if 7 <= hour < 12:
        return 'LONDON'
    elif 12 <= hour < 16:
        return 'LONDON_NY_OVERLAP'
    elif 16 <= hour < 21:
        return 'NEW_YORK'
    else:
        return 'ASIAN_QUIET'

def get_xag_trend_bias():
    total_score = 0.0
    results = {}

    for tf, weight in [('2h', 0.4), ('4h', 0.6)]:
        df = fetch_ohlcv('XAG/USDT', tf, limit=60)
        if df is None or len(df) < 30:
            continue
        c = df['close'].values
        h = df['high'].values
        lo = df['low'].values

        rsi_val = rsi(c[-30:], 14)
        rsi_score = (rsi_val - 50) * 2

        ema50 = ema(c, 50)
        ema_score = ((c[-1] - ema50) / ema50) * 1500
        ema_score = float(np.clip(ema_score, -100, 100))

        struct = detect_market_structure(h, lo)
        struct_score = 30 if struct == 'bullish' else (-30 if struct == 'bearish' else 0)

        tf_score = (rsi_score * 0.35 + ema_score * 0.35 + struct_score * 0.30)
        total_score += tf_score * weight

        results[tf] = {
            'rsi': round(rsi_val, 1),
            'price': round(c[-1], 3),
            'structure': struct,
            'tf_score': round(tf_score, 1)
        }

    total_score = float(np.clip(total_score, -100, 100))
    if total_score <= -45: bias = 'BEARISH_STRONG'
    elif total_score <= -15: bias = 'BEARISH'
    elif total_score >= 45: bias = 'BULLISH_STRONG'
    elif total_score >= 15: bias = 'BULLISH'
    else: bias = 'NEUTRAL'

    return bias, round(total_score, 1), results

# ============================================
# REFINED COMMODITY PARAMETERS
# ============================================

TF_PARAMS = {
    '5m': {
        'lookback': 140,
        'bandwidth': 3.0,
        'multiplier': 1.8,
        'rsi_period': 8,
        'ma_period': 40,
        'atr_stop_mult': 1.5,
        'atr_tp_mults': [1.0, 2.0, 3.5]
    },
    '15m': {
        'lookback': 150,       # Refined: Faster reaction
        'bandwidth': 3.0,      # Refined: More responsive
        'multiplier': 2.2,     # Refined: Wider for wick protection
        'rsi_period': 14,      # Refined: Standardized
        'ma_period': 50,
        'atr_stop_mult': 1.5,  # Dynamic ATR multipliers
        'atr_tp_mults': [1.0, 2.0, 3.5]
    },
    '30m': {
        'lookback': 200,       # Refined: Faster reaction
        'bandwidth': 4.0,      # Refined: More responsive
        'multiplier': 2.5,     # Refined: Wider for wick protection
        'rsi_period': 14,      # Refined: Standardized
        'ma_period': 100,
        'atr_stop_mult': 1.5,
        'atr_tp_mults': [1.0, 2.0, 3.5]
    }
}

# ============================================
# ENHANCED SCANNING AND FILTER CORE
# ============================================

def detect_xag_signals(df, tf, bias, use_bias=True):
    p = TF_PARAMS[tf]
    close = df['close'].values
    high  = df['high'].values
    low   = df['low'].values
    vol   = df['volume'].values
    opens = df['open'].values

    if len(close) < p['lookback']:
        return []

    mid, upper, lower = nadaraya_watson_envelope(close, p['bandwidth'], p['multiplier'], p['lookback'])
    if mid is None:
        return []

    rsi_val = rsi(close[-p['rsi_period']-30:], p['rsi_period'])
    current_atr = atr(high, low, close, 14)
    
    # --- Volatility Compression Filter ---
    historical_atr_mean = np.mean([atr(high[:i], low[:i], close[:i], 14) for i in range(len(close)-25, len(close))])
    is_dead_market = current_atr < (historical_atr_mean * 0.70)

    current = close[-1]
    prev    = close[-2]
    candidates = []

    # --- Liquidity Sweep (Wick Trap) Detection ---
    candle_range = high[-1] - low[-1]
    if candle_range > 0:
        # Bearish Wick Rejection at Upper Band
        if high[-1] > upper and current < upper:
            upper_wick = high[-1] - max(current, opens[-1])
            if upper_wick > (candle_range * 0.5):
                candidates.append({
                    'dir': 'SELL', 'type': 'XAG_LIQUIDITY_SWEEP', 'conf': 75, 
                    'desc': f'Bearish wick rejection at upper band (Wick {upper_wick/candle_range:.1%})'
                })
        
        # Bullish Wick Rejection at Lower Band
        if low[-1] < lower and current > lower:
            lower_wick = min(current, opens[-1]) - low[-1]
            if lower_wick > (candle_range * 0.5):
                candidates.append({
                    'dir': 'BUY', 'type': 'XAG_LIQUIDITY_SWEEP', 'conf': 75, 
                    'desc': f'Bullish wick rejection at lower band (Wick {lower_wick/candle_range:.1%})'
                })

    # Standard Envelope logic checks
    if not candidates:
        if current > lower and prev <= lower and rsi_val < 48:
            conf = min(80, (48 - rsi_val) * 1.8 + 50)
            candidates.append({'dir': 'BUY', 'type': 'XAG_BANDS_BUY', 'conf': conf, 'desc': f'Silver recovery inside lower band (RSI {rsi_val:.0f})'})

        if current < upper and prev >= upper and rsi_val > 52:
            conf = min(80, (rsi_val - 52) * 1.8 + 50)
            candidates.append({'dir': 'SELL', 'type': 'XAG_BANDS_SELL', 'conf': conf, 'desc': f'Silver rejection from upper band (RSI {rsi_val:.0f})'})

    if not candidates:
        return []

    ob_imbalance = fetch_order_book_imbalance('XAG/USDT', depth_pct=0.003)
    session = get_trading_session()

    signals = []
    for sig in candidates:
        c = sig['conf']
        notes = []
        skip = False

        # Session Filtering
        if session == 'ASIAN_QUIET':
            c -= 15
            notes.append("⚠️ Low liquidity Asian session - Reduced confidence")
        elif session == 'LONDON_NY_OVERLAP':
            c += 10
            notes.append("🔥 Peak volatility session (London-NY Overlap) - High probability")

        if is_dead_market:
            c -= 20
            notes.append("⚠️ Commodities Volatility Compressed (ATR Filter activated)")

        # Order Book Verification
        if sig['dir'] == 'BUY':
            if ob_imbalance >= 1.35:
                c += 15
                notes.append(f"🔥 Passive Bid Wall: {ob_imbalance:.2f}x buy advantage")
            elif ob_imbalance <= 0.65:
                c -= 20
                notes.append(f"⚠️ Heavy Ask Walls overhead: {ob_imbalance:.2f}x ratio")
        else:
            if ob_imbalance <= 0.65:
                c += 15
                notes.append(f"🔥 Passive Ask Wall: {1/ob_imbalance:.2f}x sell advantage")
            elif ob_imbalance >= 1.35:
                c -= 20
                notes.append(f"⚠️ Heavy Bid Walls beneath: {ob_imbalance:.2f}x ratio")

        # Macro Trend Overlays
        if use_bias:
            if bias in ('BEARISH_STRONG', 'BEARISH'):
                if sig['dir'] == 'SELL':
                    c += 15
                    notes.append(f"✅ Aligns with Macro Bias: {bias}")
                else:
                    c -= 25
                    notes.append(f"❌ Counter-trend BUY suppressed by Macro Bias: {bias}")
                    if bias == 'BEARISH_STRONG': skip = True
            elif bias in ('BULLISH_STRONG', 'BULLISH'):
                if sig['dir'] == 'BUY':
                    c += 15
                    notes.append(f"✅ Aligns with Macro Bias: {bias}")
                else:
                    c -= 25
                    notes.append(f"❌ Counter-trend SELL suppressed by Macro Bias: {bias}")
                    if bias == 'BULLISH_STRONG': skip = True

        if len(vol) > 10:
            avg_vol = np.mean(vol[-10:])
            if vol[-1] > avg_vol * 1.4:
                c += 8
                notes.append(f"📈 Momentum Volume confirmed ({vol[-1]/avg_vol:.1f}x normal)")

        if skip or c < 50:
            continue

        signals.append({
            'dir': sig['dir'],
            'type': sig['type'],
            'desc': sig['desc'],
            'conf': round(np.clip(c, 0, 100), 1),
            'notes': notes,
            'price': current,
            'rsi': round(rsi_val, 1),
            'atr': current_atr,
            'ob_ratio': round(ob_imbalance, 2)
        })

    return signals

# ============================================
# COMPILER AND EXECUTION PRINTS
# ============================================

def build_trade_plan(sig, tf, account_size, risk_pct):
    p = TF_PARAMS[tf]
    price = sig['price']
    direction = sig['dir']
    current_atr = sig['atr']

    atr_stop_mult = p['atr_stop_mult']
    tp_mults = p['atr_tp_mults']

    if direction == 'BUY':
        entry = price
        stop  = price - (current_atr * atr_stop_mult)
        tp1   = entry + (current_atr * tp_mults[0])
        tp2   = entry + (current_atr * tp_mults[1])
        tp3   = entry + (current_atr * tp_mults[2])
    else:
        entry = price
        stop  = price + (current_atr * atr_stop_mult)
        tp1   = entry - (current_atr * tp_mults[0])
        tp2   = entry - (current_atr * tp_mults[1])
        tp3   = entry - (current_atr * tp_mults[2])

    risk_per_unit = abs(entry - stop)
    dollar_risk   = account_size * risk_pct
    pos_units     = dollar_risk / risk_per_unit if risk_per_unit > 0 else 0
    pos_value     = pos_units * entry

    return {
        'entry': round(entry, 3),
        'stop':  round(stop, 3),
        'tp1':   round(tp1, 3),
        'tp2':   round(tp2, 3),
        'tp3':   round(tp3, 3),
        'units': round(pos_units, 2),
        'value': round(pos_value, 2),
        'risk_$': round(dollar_risk, 2)
    }

def print_signal(sig, plan, tf, verbose=False):
    emoji = '🟢' if sig['dir'] == 'BUY' else '🔴'
    print(f"\n  {emoji} [{tf}] XAG/USDT (Silver) Futures — {sig['dir']}  |  Conf: {sig['conf']}%")
    print(f"     Type: {sig['type']} | {sig['desc']}")
    print(f"     Price: {sig['price']} | RSI: {sig['rsi']} | ATR: {sig['atr']:.4f}")
    print(f"     📍 Entry: {plan['entry']} | 🛑 Stop: {plan['stop']} (${plan['risk_$']:.2f} risk)")
    print(f"     🎯 TP1: {plan['tp1']} | TP2: {plan['tp2']} | TP3: {plan['tp3']}")
    print(f"     📊 Size: {plan['units']} units (${plan['value']:,.2f} value)")
    if verbose:
        print("     Audit Trail:")
        for n in sig['notes']:
            print(f"       {n}")

# ============================================
# FEED OUTPUT (shared alerts.json)
# ============================================

def get_feed_path():
    # Resolve repo-root/data/alerts.json from this file's location,
    # so it works regardless of the process cwd (this script lives at the repo root).
    repo_root = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(repo_root, 'data', 'alerts.json')

def build_feed_entry(sig, plan, tf):
    direction = 'buy' if sig['dir'] == 'BUY' else 'sell'
    return {
        'timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
        'symbol': 'XAGUSD',
        'timeframe': tf,
        'direction': direction,
        'rsi': sig['rsi'],
        'price': plan['entry'],
        'pivot_level': None,
        'pivot_distance': None,
        'confidence': round(sig['conf'], 1),
        'sl': plan['stop'],
        'tp': plan['tp1'],
        'signal_source': 'xag_scanner'
    }

def write_to_feed(entries):
    if not entries:
        return
    feed_path = get_feed_path()
    try:
        os.makedirs(os.path.dirname(feed_path), exist_ok=True)
    except (PermissionError, OSError):
        feed_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'alerts.json')

    existing = []
    if os.path.exists(feed_path):
        with open(feed_path, 'r') as f:
            try:
                existing = json.load(f)
            except json.JSONDecodeError:
                existing = []

    combined = (entries + existing)[:500]
    tmp_path = feed_path + '.tmp'
    try:
        with open(tmp_path, 'w') as f:
            json.dump(combined, f, indent=2)
        os.replace(tmp_path, feed_path)
        print(f"✅ Wrote {len(entries)} signal(s) to {feed_path}")
    except (PermissionError, OSError) as e:
        print(f"⚠️ Could not write to feed: {e}")

# ============================================
# MAIN MATRIX CONTROL RUN
# ============================================

def run_scan(timeframes, account_size, risk_pct, use_bias, verbose, min_conf):
    print(f"\n{'='*70}")
    print(f"  📡 XAG ENHANCED ENGINE — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*70}")

    bias, score, bias_details = get_xag_trend_bias()
    icon = '🟢' if 'BULLISH' in bias else ('🔴' if 'BEARISH' in bias else '⚪')
    print(f"  {icon}  MACRO BIAS: {bias} (Score: {score:+.0f}) | Session: {get_trading_session()}")
    print(f"{'='*70}")

    feed_entries = []
    for tf in timeframes:
        print(f"  ⏱️  Scanning [{tf}]...")
        df = fetch_ohlcv('XAG/USDT', tf, limit=TF_PARAMS[tf]['lookback'] + 20)
        if df is None:
            continue

        signals = detect_xag_signals(df, tf, bias, use_bias=use_bias)
        signals = [s for s in signals if s['conf'] >= min_conf]

        if not signals:
            print(f"  ⏳ [{tf}] No qualifying signatures.")
        else:
            for sig in signals:
                plan = build_trade_plan(sig, tf, account_size, risk_pct)
                print_signal(sig, plan, tf, verbose=verbose)
                feed_entries.append(build_feed_entry(sig, plan, tf))

    write_to_feed(feed_entries)
    print(f"{'='*70}\n")

def main():
    args = parse_args()
    if args.timeframe not in ('5m', '15m', '30m'):
        print("❌ System error: Valid timeframes are 5m, 15m, or 30m.")
        sys.exit(1)

    timeframes = [args.timeframe]
    use_bias = not args.no_bias

    if args.loop > 0:
        print(f"🔁 Operational monitoring started. Intervals: {args.loop}m.")
        while True:
            try:
                run_scan(timeframes, args.account, args.risk, use_bias, args.verbose, args.min_conf)
                time.sleep(args.loop * 60)
            except KeyboardInterrupt:
                print("\n👋 Stopped.")
                break
    else:
        run_scan(timeframes, args.account, args.risk, use_bias, args.verbose, args.min_conf)

if __name__ == '__main__':
    main()
