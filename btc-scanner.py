#!/usr/bin/env python3
"""
BTC Precision 5m Intraday Scanner (with Order Book Depth, CVD & Volatility Filters)
Trend-aware: detects current BTC macro bias from 1h+4h and immediate 15m structural trend,
then combines technical indicators with live order book supply/demand dynamics.

Usage:
    python btc_scanner.py -tf 5m
    python btc_scanner.py -tf 5m --verbose
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
# ARGS
# ============================================

def parse_args():
    parser = argparse.ArgumentParser(
        description='BTC Intraday Scanner — 5m/15m/30m with Order Book and CVD metrics',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('-tf', '--timeframe', type=str, default='5m',
        help='Timeframe to scan: 5m, 15m, or 30m. Default is 5m.')
    parser.add_argument('--loop', type=int, default=0,
        help='Repeat scan every N minutes (0 = single run)')
    parser.add_argument('--account', type=float, default=10000,
        help='Account size in USD (default: 10000)')
    parser.add_argument('--risk', type=float, default=0.01,
        help='Risk per trade as decimal (default: 0.01 = 1%%)')
    parser.add_argument('--no-bias', action='store_true',
        help='Disable macro trend-bias weighting')
    parser.add_argument('-v', '--verbose', action='store_true',
        help='Show all advanced filter details per signal')
    parser.add_argument('--min-conf', type=float, default=50.0,
        help='Minimum confidence to display a signal (default: 50)')
    return parser.parse_args()

# ============================================
# EXCHANGE INTERFACE (CACHED)
# ============================================

_EX = {}

def get_exchange():
    if 'spot' not in _EX:
        _EX['spot'] = ccxt.binance({'enableRateLimit': True})
    return _EX['spot']

def fetch_ohlcv(symbol, timeframe, limit=350):
    try:
        ex = get_exchange()
        raw = ex.fetch_ohlcv(symbol, timeframe, limit=limit)
        df = pd.DataFrame(raw, columns=['ts','open','high','low','close','volume'])
        return df
    except Exception as e:
        print(f"  ⚠️ fetch_ohlcv({symbol},{timeframe}): {str(e)[:60]}")
        return None

def fetch_order_book_imbalance(symbol, depth_pct=0.005):
    """
    Measures limit order book imbalance within depth_pct (default 0.5%) of mid price.
    Returns: ratio (bids_volume / asks_volume)
    """
    try:
        ex = get_exchange()
        ob = ex.fetch_order_book(symbol, limit=50)
        if not ob['bids'] or not ob['asks']:
            return 1.0
        
        mid = (ob['bids'][0][0] + ob['asks'][0][0]) / 2.0
        lower_bound = mid * (1 - depth_pct)
        upper_bound = mid * (1 + depth_pct)
        
        bids_vol = sum([b[1] for b in ob['bids'] if b[0] >= lower_bound])
        asks_vol = sum([a[1] for a in ob['asks'] if a[0] <= upper_bound])
        
        if asks_vol == 0:
            return 2.0
        return bids_vol / asks_vol
    except Exception:
        return 1.0

def fetch_approx_cvd(symbol, lookback_minutes=5):
    """
    Approximates Cumulative Volume Delta (Market Buys - Market Sells) from recent trade data.
    Returns: cvd_ratio (net_buys / total_volume) -> >0 is bullish buying pressure, <0 is selling pressure.
    """
    try:
        ex = get_exchange()
        trades = ex.fetch_trades(symbol, limit=200)
        if not trades:
            return 0.0
        
        now_ms = ex.milliseconds()
        cutoff_ms = now_ms - (lookback_minutes * 60 * 1000)
        
        net_delta = 0.0
        total_vol = 0.0
        
        for t in trades:
            if t['timestamp'] >= cutoff_ms:
                vol = t['amount']
                total_vol += vol
                if t['side'] == 'buy':
                    net_delta += vol
                else:
                    net_delta -= vol
                    
        if total_vol == 0:
            return 0.0
        return net_delta / total_vol
    except Exception:
        return 0.0

# ============================================
# TECHNICAL INDICATORS
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

def squeeze_momentum(high, low, close, bb_period=20, bb_mult=2.0, kc_mult=1.5):
    if len(close) < bb_period + 2:
        return False, False, False
    sma = np.mean(close[-bb_period:])
    std = np.std(close[-bb_period:])
    bb_upper = sma + bb_mult * std
    bb_lower = sma - bb_mult * std
    atr_val = atr(high, low, close, bb_period)
    kc_upper = sma + kc_mult * atr_val
    kc_lower = sma - kc_mult * atr_val
    squeeze_on = (bb_upper < kc_upper) and (bb_lower > kc_lower)
    release = False
    if len(close) > 2:
        if (close[-1] > kc_upper and close[-2] <= kc_upper) or \
           (close[-1] < kc_lower and close[-2] >= kc_lower):
            release = True
    mom_bullish = close[-1] > sma
    return squeeze_on, release, mom_bullish

def hurst_exponent(price, window=80):
    if len(price) < window:
        return 0.5
    lr = np.diff(np.log(price[-window:]))
    if len(lr) < 4:
        return 0.5
    var_full = np.var(lr)
    var_half = np.var(lr[:len(lr)//2])
    if var_full > 0 and var_half > 0:
        h = 0.5 * np.log(var_full / var_half) / np.log(2)
        return float(np.clip(h, 0.0, 1.0))
    return 0.5

def detect_market_structure(high, low, swing=10):
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

def find_ob_and_fvg(high, low, close, lookback=30):
    ob_zone = (None, None, None)
    fvg_zone = (None, None, None)
    if len(close) < lookback + 3:
        return ob_zone, fvg_zone
    avg_move = np.mean(np.abs(np.diff(close[-lookback:])))
    for i in range(len(close)-1, max(0, len(close)-lookback), -1):
        try:
            move = abs(close[i] - close[i-1])
            if move > avg_move * 1.8:
                if close[i] > close[i-1]:
                    ob_zone = (float(low[i-1]), float(high[i-1]), 'bullish')
                else:
                    ob_zone = (float(low[i-1]), float(high[i-1]), 'bearish')
                break
        except (IndexError, ValueError):
            continue
    for i in range(len(high)-3, max(0, len(high)-lookback), -1):
        try:
            if high[i] < low[i+2]:
                fvg_zone = (float(high[i]), float(low[i+2]), 'bullish')
                break
            elif low[i] > high[i+2]:
                fvg_zone = (float(high[i+2]), float(low[i]), 'bearish')
                break
        except (IndexError, ValueError):
            continue
    return ob_zone, fvg_zone

# ============================================
# TREND BIAS (MACRO)
# ============================================

def get_btc_trend_bias():
    results = {}
    total_score = 0.0

    for tf, weight in [('1h', 0.4), ('4h', 0.6)]:
        df = fetch_ohlcv('BTC/USDT', tf, limit=50)
        if df is None or len(df) < 20:
            continue
        c = df['close'].values
        h = df['high'].values
        lo = df['low'].values

        rsi_val = rsi(c[-30:], 14)
        rsi_score = (rsi_val - 50) * 2

        ema50 = ema(c, 50)
        ema_score = ((c[-1] - ema50) / ema50) * 1000
        ema_score = float(np.clip(ema_score, -100, 100))

        mom = (c[-1] - c[-6]) / c[-6] * 100 if len(c) >= 6 else 0
        mom_score = float(np.clip(mom * 10, -100, 100))

        struct = detect_market_structure(h, lo)
        struct_score = 30 if struct == 'bullish' else (-30 if struct == 'bearish' else 0)

        tf_score = (rsi_score * 0.3 + ema_score * 0.3 + mom_score * 0.25 + struct_score * 0.15)
        total_score += tf_score * weight

        results[tf] = {
            'rsi': round(rsi_val, 1),
            'ema50': round(ema50, 2),
            'price': round(c[-1], 2),
            'structure': struct,
            'tf_score': round(tf_score, 1)
        }

    total_score = float(np.clip(total_score, -100, 100))

    if total_score <= -60:
        bias = 'BEARISH_STRONG'
    elif total_score <= -20:
        bias = 'BEARISH'
    elif total_score >= 60:
        bias = 'BULLISH_STRONG'
    elif total_score >= 20:
        bias = 'BULLISH'
    else:
        bias = 'NEUTRAL'

    return bias, round(total_score, 1), results

# ============================================
# TIMEFRAME CONFIGURATION
# ============================================

TF_PARAMS = {
    '5m': {
        'lookback': 120,       # Fast localized data processing
        'bandwidth': 2.5,      # Tight envelope for 5m high frequency noise
        'multiplier': 1.6,     # Narrow bands optimized to catch wick touches
        'rsi_period': 7,       # Highly reactive RSI
        'ma_period': 30,       # Near-term dynamic average line
        'confirm_tf': '1h',
        'stop_pct': 0.004,     # Precision 0.4% baseline stop loss
        'tp1_pct': 0.004,      # 1:1 R:R target 1 scale out
        'tp2_pct': 0.008,
        'tp3_pct': 0.015,
    },
    '15m': {
        'lookback': 150,
        'bandwidth': 3.0,
        'multiplier': 1.8,
        'rsi_period': 8,
        'ma_period': 50,
        'confirm_tf': '1h',
        'stop_pct': 0.008,
        'tp1_pct': 0.008,
        'tp2_pct': 0.015,
        'tp3_pct': 0.025,
    },
    '30m': {
        'lookback': 200,
        'bandwidth': 4.0,
        'multiplier': 2.2,
        'rsi_period': 10,
        'ma_period': 100,
        'confirm_tf': '1h',
        'stop_pct': 0.012,
        'tp1_pct': 0.012,
        'tp2_pct': 0.022,
        'tp3_pct': 0.035,
    }
}

# ============================================
# SIGNAL ENGINE
# ============================================

def detect_btc_signals(df, tf, bias, use_bias=True):
    p = TF_PARAMS[tf]
    close = df['close'].values
    high  = df['high'].values
    low   = df['low'].values
    vol   = df['volume'].values

    if len(close) < p['lookback']:
        return []

    mid, upper, lower = nadaraya_watson_envelope(close, p['bandwidth'], p['multiplier'], p['lookback'])
    if mid is None:
        return []

    rsi_val = rsi(close[-p['rsi_period']-30:], p['rsi_period'])
    ma = np.mean(close[-p['ma_period']:]) if len(close) >= p['ma_period'] else np.mean(close)
    squeeze_on, sq_release, sq_bull = squeeze_momentum(high, low, close)
    h_exp = hurst_exponent(close)
    struct = detect_market_structure(high, low)
    ob_zone, fvg_zone = find_ob_and_fvg(high, low, close)

    # --- ADVANCED METRIC 1: ATR Volatility Expansion Baseline ---
    current_atr = atr(high, low, close, 14)
    avg_atr_long = np.mean([atr(high[:i], low[:i], close[:i], 14) for i in range(len(close)-30, len(close))])
    is_low_vol_chop = current_atr < (avg_atr_long * 0.75)  # Volatility is compressed below normal levels

    current = close[-1]
    prev    = close[-2]

    candidates = []

    # 1. Lower band crossover (BUY)
    if current > lower and prev <= lower and rsi_val < 50:
        conf = min(80, (50 - rsi_val) * 1.5 + 50)
        candidates.append({'dir': 'BUY', 'type': 'BUY_CROSS_LOWER', 'conf': conf,
                           'desc': f'Cross above lower band (RSI {rsi_val:.0f})'})

    # 2. Upper band crossover (SELL)
    if current < upper and prev >= upper and rsi_val > 50:
        conf = min(80, (rsi_val - 50) * 1.5 + 50)
        candidates.append({'dir': 'SELL', 'type': 'SELL_CROSS_UPPER', 'conf': conf,
                           'desc': f'Cross below upper band (RSI {rsi_val:.0f})'})

    # 3. Oversold near lower band (BUY)
    if rsi_val < 30 and current < lower * 1.025:
        conf = min(75, (30 - rsi_val) * 2.5 + 35)
        candidates.append({'dir': 'BUY', 'type': 'BUY_OVERSOLD', 'conf': conf,
                           'desc': f'Oversold RSI {rsi_val:.0f} at lower band'})

    # 4. Overbought near upper band (SELL)
    if rsi_val > 70 and current > upper * 0.975:
        conf = min(75, (rsi_val - 70) * 2.5 + 35)
        candidates.append({'dir': 'SELL', 'type': 'SELL_OVERBOUGHT', 'conf': conf,
                           'desc': f'Overbought RSI {rsi_val:.0f} at upper band'})

    if not candidates:
        return []

    # Fetch confirmations outside data loop
    rsi_1h = None
    df1h = fetch_ohlcv('BTC/USDT', p['confirm_tf'], limit=60)
    if df1h is not None and len(df1h) >= 20:
        rsi_1h = rsi(df1h['close'].values[-30:], 14)

    # --- ADVANCED METRIC 2: Intermediate Trend Alignment (15m Ribbon) ---
    trend_15m = 'neutral'
    if tf == '5m':
        df15 = fetch_ohlcv('BTC/USDT', '15m', limit=60)
        if df15 is not None and len(df15) >= 50:
            c15 = df15['close'].values
            ema9 = ema(c15, 9)
            ema21 = ema(c15, 21)
            ema55 = ema(c15, 55)
            if ema9 > ema21 > ema55:
                trend_15m = 'bullish'
            elif ema9 < ema21 < ema55:
                trend_15m = 'bearish'

    # --- ADVANCED METRIC 3 & 4: Order Book Imbalance & CVD ---
    ob_imbalance = fetch_order_book_imbalance('BTC/USDT', depth_pct=0.005)
    approx_cvd = fetch_approx_cvd('BTC/USDT', lookback_minutes=5)

    signals = []
    for sig in candidates:
        c = sig['conf']
        notes = []
        skip = False

        # Apply Volatility Chop Protection
        if is_low_vol_chop:
            c -= 25
            notes.append("⚠️ Low Volatility Chop detected (ATR compressed) — Penalty Applied")

        # ── INTERMEDIATE TREND (15m Ribbon Protection) ─────────────
        if tf == '5m' and trend_15m != 'neutral':
            if sig['dir'] == 'BUY' and trend_15m == 'bearish':
                c -= 20
                notes.append("❌ Blown out 15m EMA Ribbon Trend is BEARISH. Fighting trend.")
            elif sig['dir'] == 'SELL' and trend_15m == 'bullish':
                c -= 20
                notes.append("❌ Blown out 15m EMA Ribbon Trend is BULLISH. Fighting trend.")
            elif (sig['dir'] == 'BUY' and trend_15m == 'bullish') or (sig['dir'] == 'SELL' and trend_15m == 'bearish'):
                c += 10
                notes.append(f"✅ Fast 15m EMA Ribbon confirms direction ({trend_15m})")

        # ── ORDER BOOK DEPTH IMBALANCE ──────────────────────────────
        if sig['dir'] == 'BUY':
            if ob_imbalance >= 1.4:
                c += 15
                notes.append(f"🔥 Order Book Support: Buy wall depth ratio {ob_imbalance:.2f}x")
            elif ob_imbalance <= 0.6:
                c -= 20
                notes.append(f"⚠️ Thin Order Book Support: Ask side heavier ({ob_imbalance:.2f}x)")
        else:
            if ob_imbalance <= 0.6:
                c += 15
                notes.append(f"🔥 Order Book Resistance: Sell wall depth ratio {1/ob_imbalance:.2f}x heavier")
            elif ob_imbalance >= 1.4:
                c -= 20
                notes.append(f"⚠️ Thin Order Book Resistance: Bid side heavier ({ob_imbalance:.2f}x)")

        # ── CUMULATIVE VOLUME DELTA (CVD) PRESSURE ─────────────────
        if sig['dir'] == 'BUY':
            if approx_cvd > 0.15:
                c += 12
                notes.append(f"📈 CVD Bullish: Aggressive market buying pressure ({approx_cvd*100:+.1f}%)")
            elif approx_cvd < -0.25:
                c -= 15
                notes.append(f"⚠️ CVD Divergence Warning: Aggressive market dump taking place ({approx_cvd*100:+.1f}%)")
        else:
            if approx_cvd < -0.15:
                c += 12
                notes.append(f"📉 CVD Bearish: Aggressive market selling pressure ({approx_cvd*100:+.1f}%)")
            elif approx_cvd > 0.25:
                c -= 15
                notes.append(f"⚠️ CVD Divergence Warning: Aggressive absorption/buying taking place ({approx_cvd*100:+.1f}%)")

        # ── MACRO TREND BIAS ──────────────────────────────────────────
        if use_bias:
            if bias in ('BEARISH_STRONG', 'BEARISH'):
                if sig['dir'] == 'SELL':
                    boost = 20 if bias == 'BEARISH_STRONG' else 10
                    c += boost
                    notes.append(f"✅ Macro Bias {bias} confirms SELL")
                elif sig['dir'] == 'BUY':
                    if rsi_val < 20:
                        c -= 15
                        notes.append("⚠️ Counter-trend BUY accepted exclusively due to oversold conditions")
                    else:
                        c -= 30
                        notes.append(f"❌ Rejected counter-trend BUY against macro {bias}")
                        skip = True
            elif bias in ('BULLISH_STRONG', 'BULLISH'):
                if sig['dir'] == 'BUY':
                    boost = 20 if bias == 'BULLISH_STRONG' else 10
                    c += boost
                    notes.append(f"✅ Macro Bias {bias} confirms BUY")
                elif sig['dir'] == 'SELL':
                    if rsi_val > 80:
                        c -= 15
                        notes.append("⚠️ Counter-trend SELL accepted exclusively due to overbought conditions")
                    else:
                        c -= 30
                        notes.append(f"❌ Rejected counter-trend SELL against macro {bias}")
                        skip = True

        if skip or c < 50:
            continue

        # Basic volume confirmation logic
        if len(vol) > 15:
            avg_vol = np.mean(vol[-15:])
            vr = vol[-1] / avg_vol if avg_vol > 0 else 1.0
            if vr > 1.5:
                c += 5
                notes.append(f"📈 Local volume spike ({vr:.1f}x avg)")

        # Market structure / Indicators scoring updates
        if sig['dir'] == 'BUY' and current > ma:
            c += 5
        elif sig['dir'] == 'SELL' and current < ma:
            c += 5

        if sq_release:
            if (sig['dir'] == 'BUY' and sq_bull) or (sig['dir'] == 'SELL' and not sq_bull):
                c += 10
                notes.append("🔥 Squeeze Breakout Active")

        if h_exp > 0.55:
            c += 5

        c = float(np.clip(c, 0, 100))
        if c < min_conf:
            continue

        signals.append({
            'dir':     sig['dir'],
            'type':    sig['type'],
            'desc':    sig['desc'],
            'conf':    round(c, 1),
            'notes':   notes,
            'price':   current,
            'rsi':     round(rsi_val, 1),
            'rsi_1h':  round(rsi_1h, 1) if rsi_1h else None,
            'mid':     round(mid, 2),
            'upper':   round(upper, 2),
            'lower':   round(lower, 2),
            'ma':      round(ma, 2),
            'ob_ratio': round(ob_imbalance, 2),
            'cvd_pct':  round(approx_cvd * 100, 1)
        })

    signals.sort(key=lambda x: x['conf'], reverse=True)
    return signals

# ============================================
# TRADE COMPILER
# ============================================

def build_trade_plan(sig, tf, account_size, risk_pct):
    p = TF_PARAMS[tf]
    price = sig['price']
    direction = sig['dir']

    if direction == 'BUY':
        entry = max(price, sig['lower'] * 1.001)
        stop  = min(price * (1 - p['stop_pct']), sig['lower'] * 0.999)
        tp1   = entry * (1 + p['tp1_pct'])
        tp2   = entry * (1 + p['tp2_pct'])
        tp3   = entry * (1 + p['tp3_pct'])
    else:
        entry = min(price, sig['upper'] * 0.999)
        stop  = max(price * (1 + p['stop_pct']), sig['upper'] * 1.001)
        tp1   = entry * (1 - p['tp1_pct'])
        tp2   = entry * (1 - p['tp2_pct'])
        tp3   = entry * (1 - p['tp3_pct'])

    risk_per_unit = abs(entry - stop)
    dollar_risk   = account_size * risk_pct * (0.5 + sig['conf'] / 100 * 0.8)
    pos_units     = dollar_risk / risk_per_unit if risk_per_unit > 0 else 0
    pos_value     = min(pos_units * entry, account_size * 0.4)
    pos_units     = pos_value / entry

    return {
        'entry':  round(entry, 2),
        'stop':   round(stop, 2),
        'tp1':    round(tp1, 2),
        'tp2':    round(tp2, 2),
        'tp3':    round(tp3, 2),
        'gain1':  round(abs(tp1 - entry) / entry * 100, 2),
        'gain2':  round(abs(tp2 - entry) / entry * 100, 2),
        'gain3':  round(abs(tp3 - entry) / entry * 100, 2),
        'units':  round(pos_units, 5),
        'value':  round(pos_value, 2),
        'risk_$': round(dollar_risk, 2),
    }

# ============================================
# INTERFACE PRINTS
# ============================================

def print_signal(sig, plan, tf, verbose=False):
    emoji = '🟢' if sig['dir'] == 'BUY' else '🔴'
    print(f"\n  {emoji} [{tf}] BTC/USDT — {sig['dir']}  |  Conf: {sig['conf']}%  |  {sig['desc']}")
    print(f"     Price: ${sig['price']:,.2f} | RSI({tf}): {sig['rsi']} | Book Balance: {sig['ob_ratio']}x | CVD Delta: {sig['cvd_pct']:+}%")
    print(f"     📍 Entry   : ${plan['entry']:,.2f}")
    print(f"     🛑 Stop    : ${plan['stop']:,.2f}  (Risk: ${plan['risk_$']:.2f})")
    print(f"     🎯 Target 1: ${plan['tp1']:,.2f}  (+{plan['gain1']}%)")
    print(f"     🎯 Target 2: ${plan['tp2']:,.2f}  (+{plan['gain2']}%)")
    print(f"     🎯 Target 3: ${plan['tp3']:,.2f}  (+{plan['gain3']}%)")
    print(f"     📊 Allocation: {plan['units']} BTC (${plan['value']:,.2f})")
    if verbose:
        print("     Order Validation Logs:")
        for n in sig['notes']:
            print(f"       {n}")

# ============================================
# MAIN SCAN LOOP
# ============================================

def run_scan(timeframes, account_size, risk_pct, use_bias, verbose, min_conf):
    print(f"\n{'='*70}")
    print(f"  📡 BTC LIQUIDITY ENGINE — {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*70}")

    bias, score, bias_details = get_btc_trend_bias()
    
    icon = '🟢' if 'BULLISH' in bias else ('🔴' if 'BEARISH' in bias else '⚪')
    print(f"  {icon}  BTC MACRO MATRIX BIAS: {bias} (Score: {score:+.0f})")
    print(f"{'='*70}")

    for tf in timeframes:
        print(f"  ⏱️  Processing Candlestick & Order Stream Matrix [{tf}]...")
        df = fetch_ohlcv('BTC/USDT', tf, limit=TF_PARAMS[tf]['lookback'] + 30)
        if df is None:
            continue

        signals = detect_btc_signals(df, tf, bias, use_bias=use_bias)
        signals = [s for s in signals if s['conf'] >= min_conf]

        if not signals:
            print(f"  ⏳ [{tf}] No qualifying order-flow confirmation signals.")
        else:
            for sig in signals:
                plan = build_trade_plan(sig, tf, account_size, risk_pct)
                print_signal(sig, plan, tf, verbose=verbose)
    print(f"{'='*70}\n")

def main():
    args = parse_args()
    if args.timeframe not in ('5m', '15m', '30m'):
        print("❌ Error: Supported timeframes are 5m, 15m, 30m.")
        sys.exit(1)

    timeframes = [args.timeframe]
    use_bias = not args.no_bias

    if args.loop > 0:
        print(f"🔁 Scanner live in memory. Sampling matrix every {args.loop}m.")
        while True:
            try:
                run_scan(timeframes, args.account, args.risk, use_bias, args.verbose, args.min_conf)
                time.sleep(args.loop * 60)
            except KeyboardInterrupt:
                break
    else:
        run_scan(timeframes, args.account, args.risk, use_bias, args.verbose, args.min_conf)

if __name__ == '__main__':
    main()
