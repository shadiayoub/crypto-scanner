#!/usr/bin/env python3
"""
BTC Precision 15m Intraday Scanner (Aggressive Regime-Aware Edition)
==================================================================
Optimized for BTC's aggressive, high-volatility character with:
- Multi-regime volatility scaling (compressed / normal / expansion / cascade)
- Liquidation cascade detection & exhaustion fading
- Funding rate contrarian signals
- Multi-tier order book intelligence with wall detection
- HTF structure alignment gating
- Session-aware liquidity profiling
- Kelly-criterion position sizing
- Enhanced 15m parameter tuning

Usage:
    python btc_scanner_v2.py -tf 15m
    python btc_scanner_v2.py -tf 15m --verbose --loop 5
"""

import ccxt
import pandas as pd
import numpy as np
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
        description='BTC Aggressive Scanner — Regime-aware 15m with Microstructure',
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
        help='Show all advanced filter details per signal')
    parser.add_argument('--min-conf', type=float, default=50.0,
        help='Minimum confidence to display a signal (default: 50)')
    parser.add_argument('--max-risk-pct', type=float, default=0.02,
        help='Maximum risk per trade via Kelly sizing (default: 0.02 = 2%%)')
    return parser.parse_args()

# ============================================
# EXCHANGE INTERFACE (CACHED)
# ============================================

_EX = {}

def get_exchange():
    if 'spot' not in _EX:
        _EX['spot'] = ccxt.binance({'enableRateLimit': True})
    return _EX['spot']

def get_futures_exchange():
    if 'futures' not in _EX:
        _EX['futures'] = ccxt.binance({
            'enableRateLimit': True,
            'options': {'defaultType': 'swap'}
        })
    return _EX['futures']

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
    Measures limit order book imbalance within depth_pct of mid price.
    Returns: (ratio, is_thin) where ratio = bids_volume / asks_volume.
    """
    try:
        ex = get_exchange()
        ob = ex.fetch_order_book(symbol, limit=100)
        if not ob['bids'] or not ob['asks']:
            return 1.0, True

        mid = (ob['bids'][0][0] + ob['asks'][0][0]) / 2.0
        lower_bound = mid * (1 - depth_pct)
        upper_bound = mid * (1 + depth_pct)

        bids_vol = sum([b[1] for b in ob['bids'] if b[0] >= lower_bound])
        asks_vol = sum([a[1] for a in ob['asks'] if a[0] <= upper_bound])

        total_vol = bids_vol + asks_vol
        is_thin = total_vol < 2.0

        if asks_vol == 0:
            return 2.0, is_thin
        if bids_vol == 0:
            return 0.0, is_thin
        return bids_vol / asks_vol, is_thin
    except Exception:
        return 1.0, True

def fetch_order_book_imbalance_wide(symbol, depth_pct=0.01):
    """Secondary, wider-depth (default 1%) order book read."""
    try:
        ex = get_exchange()
        ob = ex.fetch_order_book(symbol, limit=200)
        if not ob['bids'] or not ob['asks']:
            return 1.0

        mid = (ob['bids'][0][0] + ob['asks'][0][0]) / 2.0
        lower_bound = mid * (1 - depth_pct)
        upper_bound = mid * (1 + depth_pct)

        bids_vol = sum([b[1] for b in ob['bids'] if b[0] >= lower_bound])
        asks_vol = sum([a[1] for a in ob['asks'] if a[0] <= upper_bound])

        if asks_vol == 0:
            return 2.0
        if bids_vol == 0:
            return 0.0
        return bids_vol / asks_vol
    except Exception:
        return 1.0

def fetch_order_book_profile(symbol, tiers=[0.002, 0.005, 0.01, 0.02]):
    """
    Analyzes order book at multiple depth tiers to detect walls,
    spoofing patterns, and absorption zones.
    Returns: (profile_dict, wall_signals_list)
    """
    try:
        ex = get_exchange()
        ob = ex.fetch_order_book(symbol, limit=500)
        mid = (ob['bids'][0][0] + ob['asks'][0][0]) / 2.0

        profile = {}
        for tier in tiers:
            lower = mid * (1 - tier)
            upper = mid * (1 + tier)

            bids_vol = sum(b[1] for b in ob['bids'] if b[0] >= lower)
            asks_vol = sum(a[1] for a in ob['asks'] if a[0] <= upper)

            ratio = bids_vol / asks_vol if asks_vol > 0 else 2.0
            total = bids_vol + asks_vol

            profile[tier] = {
                'ratio': ratio,
                'total_btc': total,
                'bid_depth': bids_vol,
                'ask_depth': asks_vol
            }

        # Detect walls: significant depth jump between adjacent tiers
        wall_signals = []
        for i in range(len(tiers)-1):
            curr_total = profile[tiers[i]]['total_btc']
            next_total = profile[tiers[i+1]]['total_btc']
            if next_total > curr_total * 3 and next_total > 5.0:
                wall_side = 'BID' if profile[tiers[i+1]]['bid_depth'] > profile[tiers[i+1]]['ask_depth'] else 'ASK'
                wall_signals.append(f"{wall_side} wall at {tiers[i+1]*100:.1f}% depth")

        return profile, wall_signals
    except Exception:
        return {}, []

def fetch_approx_cvd(symbol, lookback_minutes=5):
    """
    Approximates CVD from recent trade data with coverage quality check.
    """
    try:
        ex = get_exchange()
        trades = ex.fetch_trades(symbol, limit=1000)
        if not trades:
            return 0.0, False

        now_ms = ex.milliseconds()
        cutoff_ms = now_ms - (lookback_minutes * 60 * 1000)

        net_delta = 0.0
        total_vol = 0.0
        oldest_in_window = None

        for t in trades:
            if t['timestamp'] >= cutoff_ms:
                vol = t['amount']
                total_vol += vol
                if oldest_in_window is None or t['timestamp'] < oldest_in_window:
                    oldest_in_window = t['timestamp']
                if t['side'] == 'buy':
                    net_delta += vol
                else:
                    net_delta -= vol

        if total_vol == 0:
            return 0.0, False

        if oldest_in_window is None:
            return 0.0, False
        actual_span_ms = now_ms - oldest_in_window
        requested_span_ms = lookback_minutes * 60 * 1000
        coverage_ok = actual_span_ms >= requested_span_ms * 0.8

        return net_delta / total_vol, coverage_ok
    except Exception:
        return 0.0, False

def fetch_trade_delta_profile(symbol, lookback_minutes=15):
    """
    Enhanced CVD tracking large lot delta (institutional footprint)
    and delta divergence detection.
    """
    try:
        ex = get_exchange()
        trades = ex.fetch_trades(symbol, limit=2000)
        now_ms = ex.milliseconds()
        cutoff = now_ms - (lookback_minutes * 60 * 1000)

        delta = 0.0
        large_delta = 0.0
        total_vol = 0.0

        for t in trades:
            if t['timestamp'] >= cutoff:
                vol = t['amount']
                total_vol += vol
                side_mult = 1 if t['side'] == 'buy' else -1
                delta += vol * side_mult

                if vol >= 0.5:  # Large lot threshold
                    large_delta += vol * side_mult

        if total_vol == 0:
            return {'delta_pct': 0, 'large_delta_pct': 0, 'divergence': False, 'coverage_ok': False}

        delta_pct = (delta / total_vol) * 100
        large_delta_pct = (large_delta / total_vol) * 100 if total_vol > 0 else 0

        return {
            'delta_pct': delta_pct,
            'large_delta_pct': large_delta_pct,
            'divergence': abs(large_delta_pct - delta_pct) > 15,
            'coverage_ok': True
        }
    except Exception:
        return {'delta_pct': 0, 'large_delta_pct': 0, 'divergence': False, 'coverage_ok': False}

def fetch_funding_rate_proxy(symbol='BTC/USDT'):
    """
    Uses Binance futures funding rate as contrarian sentiment proxy.
    Extreme funding = crowded positioning = potential reversal fuel.
    """
    try:
        ex = get_futures_exchange()
        funding = ex.fetchFundingRate(symbol)
        rate = funding['fundingRate'] * 100  # Convert to percentage

        if rate > 0.05:
            return 'extreme_long', rate
        elif rate > 0.01:
            return 'elevated_long', rate
        elif rate < -0.05:
            return 'extreme_short', rate
        elif rate < -0.01:
            return 'elevated_short', rate
        return 'neutral', rate
    except Exception:
        return 'neutral', 0.0

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

def detect_volatility_spike(high, low, close, lookback=20, spike_mult=2.2):
    """
    Liquidation-cascade proxy: compares latest candle range vs recent average.
    """
    if len(close) < lookback + 2:
        return False, 1.0, 'neutral'

    ranges = high[-lookback-1:-1] - low[-lookback-1:-1]
    avg_range = np.mean(ranges)
    if avg_range <= 0:
        return False, 1.0, 'neutral'

    last_range = high[-1] - low[-1]
    spike_ratio = last_range / avg_range

    is_spike = spike_ratio >= spike_mult
    direction = 'neutral'
    if is_spike:
        direction = 'up' if close[-1] > close[-2] else 'down'

    return is_spike, round(float(spike_ratio), 2), direction

def detect_liquidation_signature(df):
    """
    Detects liquidation cascade signatures:
    1. Impulse candle with minimal wick (trapped traders)
    2. Volume spike without proportional depth
    3. Rapid follow-through pattern
    """
    close = df['close'].values
    high = df['high'].values
    low = df['low'].values
    vol = df['volume'].values

    if len(close) < 5:
        return {'is_liquidation': False, 'score': 0, 'wick_ratio': 1.0, 'vol_spike': 1.0}

    body = abs(close[-1] - close[-2])
    total_range = high[-1] - low[-1]

    wick_ratio = 1 - (body / total_range) if total_range > 0 else 0
    vol_ma = np.mean(vol[-20:-1]) if len(vol) > 20 else np.mean(vol[:-1])
    vol_spike = vol[-1] / vol_ma if vol_ma > 0 else 1.0

    avg_range = np.mean(high[-10:-1] - low[-10:-1]) if len(high) > 10 else total_range
    range_expansion = total_range / avg_range if avg_range > 0 else 1.0

    liq_score = 0
    if wick_ratio < 0.2 and vol_spike > 2.5:
        liq_score += 50
    if range_expansion > 2.5:
        liq_score += 30
    if vol_spike > 3.0 and wick_ratio < 0.3:
        liq_score += 20

    return {
        'is_liquidation': liq_score > 60,
        'score': liq_score,
        'wick_ratio': wick_ratio,
        'vol_spike': vol_spike,
        'range_expansion': range_expansion
    }

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
# REGIME DETECTION
# ============================================

def detect_volatility_regime(df):
    """
    Classifies BTC into volatility regimes for dynamic parameter adjustment.
    Returns: 'compressed', 'normal', 'expansion', 'cascade'
    """
    close = df['close'].values
    high = df['high'].values
    low = df['low'].values
    vol = df['volume'].values

    if len(close) < 30:
        return 'normal'

    # Realized volatility (annualized)
    returns = np.diff(np.log(close[-30:]))
    rv = np.std(returns) * np.sqrt(365 * 24 * 12) if len(returns) > 1 else 0.5

    # ATR-based regime
    current_atr = atr(high, low, close, 14)
    atr_pct = current_atr / close[-1] if close[-1] > 0 else 0

    if rv < 0.35 and atr_pct < 0.003:
        return 'compressed'
    elif rv > 0.80 or atr_pct > 0.012:
        # Check for cascade signature
        last_range = high[-1] - low[-1]
        avg_range = np.mean(high[-10:-1] - low[-10:-1]) if len(high) > 10 else last_range
        if last_range > avg_range * 3 and vol[-1] > np.mean(vol[-15:-1]) * 2:
            return 'cascade'
        return 'expansion'
    return 'normal'

def get_regime_adjusted_stop(base_stop_pct, regime):
    """Dynamic stop scaling based on detected volatility regime."""
    multipliers = {
        'compressed': 0.7,
        'normal': 1.0,
        'expansion': 1.5,
        'cascade': 2.0
    }
    return base_stop_pct * multipliers.get(regime, 1.0)

def get_session_profile():
    """
    Returns session liquidity profile for time-of-day awareness.
    BTC personality shifts dramatically by session.
    """
    now = datetime.now(timezone.utc)
    hour = now.hour
    weekday = now.weekday()

    # Weekend penalty
    if weekday >= 5:
        return {'liquidity': 'thin', 'conviction_mult': 0.8, 'name': 'Weekend', 'hour': hour}

    if 0 <= hour < 8:
        return {'liquidity': 'low', 'conviction_mult': 0.85, 'name': 'Asia', 'hour': hour}
    elif 8 <= hour < 14:
        return {'liquidity': 'medium', 'conviction_mult': 0.95, 'name': 'London', 'hour': hour}
    elif 14 <= hour < 21:
        return {'liquidity': 'high', 'conviction_mult': 1.15, 'name': 'NY/London', 'hour': hour}
    else:
        return {'liquidity': 'medium', 'conviction_mult': 0.9, 'name': 'NY Close', 'hour': hour}

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

def get_htf_structure_alignment():
    """
    Checks 1h, 4h, and daily structure for confluence.
    Returns alignment score: -100 (all bearish) to +100 (all bullish)
    """
    alignment = 0
    weights = {'1h': 0.3, '4h': 0.4, '1d': 0.3}

    for tf, weight in weights.items():
        df = fetch_ohlcv('BTC/USDT', tf, limit=100)
        if df is None or len(df) < 20:
            continue
        swing = 5 if tf == '1h' else 3
        struct = detect_market_structure(df['high'].values, df['low'].values, swing=swing)
        score = 33 if struct == 'bullish' else (-33 if struct == 'bearish' else 0)
        alignment += score * weight

    return alignment

# ============================================
# TIMEFRAME CONFIGURATION (OPTIMIZED)
# ============================================

TF_PARAMS = {
    '5m': {
        'lookback': 120,
        'bandwidth': 2.5,
        'multiplier': 1.6,
        'rsi_period': 7,
        'ma_period': 30,
        'confirm_tf': '1h',
        'stop_pct': 0.004,
        'tp1_pct': 0.004,
        'tp2_pct': 0.008,
        'tp3_pct': 0.015,
    },
    '15m': {
        'lookback': 180,       # 45h of data for full structure context
        'bandwidth': 2.8,      # Tighter than 3.0 for better responsiveness
        'multiplier': 1.6,     # Tighter bands for earlier reversal catches
        'rsi_period': 7,       # Highly reactive
        'ma_period': 34,       # Fibonacci-aligned dynamic average
        'confirm_tf': '1h',
        'stop_pct': 0.006,     # Tighter baseline for 15m precision
        'tp1_pct': 0.012,      # Wider targets for 15m follow-through
        'tp2_pct': 0.022,
        'tp3_pct': 0.038,
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
# SIGNAL ENGINE (REGIME-AWARE)
# ============================================

def detect_btc_signals(df, tf, bias, use_bias=True):
    p = TF_PARAMS[tf]
    close = df['close'].values
    high  = df['high'].values
    low   = df['low'].values
    vol   = df['volume'].values

    if len(close) < p['lookback']:
        return []

    # --- REGIME DETECTION ---
    regime = detect_volatility_regime(df)

    # --- LIQUIDATION SIGNATURE ---
    liq = detect_liquidation_signature(df)

    # --- SESSION PROFILE ---
    session = get_session_profile()

    mid, upper, lower = nadaraya_watson_envelope(close, p['bandwidth'], p['multiplier'], p['lookback'])
    if mid is None:
        return []

    rsi_val = rsi(close[-p['rsi_period']-30:], p['rsi_period'])
    ma = np.mean(close[-p['ma_period']:]) if len(close) >= p['ma_period'] else np.mean(close)
    squeeze_on, sq_release, sq_bull = squeeze_momentum(high, low, close)
    h_exp = hurst_exponent(close)
    struct = detect_market_structure(high, low)
    ob_zone, fvg_zone = find_ob_and_fvg(high, low, close)

    # --- ATR VOLATILITY METRICS ---
    current_atr = atr(high, low, close, 14)
    tr_full = np.maximum(high[1:] - low[1:],
              np.maximum(np.abs(high[1:] - close[:-1]),
                         np.abs(low[1:] - close[:-1])))
    if len(tr_full) >= 44:
        atr_series = pd.Series(tr_full).rolling(14).mean().values
        avg_atr_long = float(np.nanmean(atr_series[-30:]))
    else:
        avg_atr_long = current_atr
    is_low_vol_chop = current_atr < (avg_atr_long * 0.75) if avg_atr_long > 0 else False

    # --- VOLATILITY SPIKE ---
    is_spike, spike_ratio, spike_dir = detect_volatility_spike(high, low, close)

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

    # Fetch confirmations
    rsi_1h = None
    df1h = fetch_ohlcv('BTC/USDT', p['confirm_tf'], limit=60)
    if df1h is not None and len(df1h) >= 20:
        rsi_1h = rsi(df1h['close'].values[-30:], 14)

    # --- INTERMEDIATE TREND (15m Ribbon) ---
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

    # --- HTF STRUCTURE ALIGNMENT ---
    htf_align = get_htf_structure_alignment()

    # --- ORDER BOOK INTELLIGENCE ---
    ob_imbalance, ob_thin = fetch_order_book_imbalance('BTC/USDT', depth_pct=0.005)
    ob_imbalance_wide = fetch_order_book_imbalance_wide('BTC/USDT', depth_pct=0.01)
    ob_profile, wall_signals = fetch_order_book_profile('BTC/USDT')
    approx_cvd, cvd_coverage_ok = fetch_approx_cvd('BTC/USDT', lookback_minutes=5)
    delta_profile = fetch_trade_delta_profile('BTC/USDT', lookback_minutes=15)

    # --- FUNDING RATE ---
    funding_state, funding_rate = fetch_funding_rate_proxy()

    signals = []
    for sig in candidates:
        c = sig['conf']
        notes = []
        skip = False
        force_widen_stop = False

        # ── REGIME DISPLAY ──
        notes.append(f"📊 Regime: {regime.upper()}")

        # ── VOLATILITY CHOP PROTECTION ──
        if is_low_vol_chop:
            c -= 25
            notes.append("⚠️ Low Volatility Chop (ATR compressed) — Penalty Applied")

        # ── LIQUIDATION CASCADE HANDLING ──
        if liq['is_liquidation']:
            if (sig['dir'] == 'BUY' and close[-1] < close[-2]) or \
               (sig['dir'] == 'SELL' and close[-1] > close[-2]):
                c += 20
                notes.append(f"🔥 Liquidation cascade detected (score: {liq['score']}) — fading exhaustion")
                force_widen_stop = True
            else:
                c -= 30
                notes.append("❌ Chasing liquidation cascade — high stop-out risk")

        # ── VOLATILITY SPIKE ──
        if is_spike:
            if (sig['dir'] == 'BUY' and spike_dir == 'up') or \
               (sig['dir'] == 'SELL' and spike_dir == 'down'):
                c -= 15
                notes.append(f"⚠️ Spike ({spike_ratio:.1f}x) already extended in signal direction")
            elif (sig['dir'] == 'BUY' and spike_dir == 'down') or \
                 (sig['dir'] == 'SELL' and spike_dir == 'up'):
                c += 8
                notes.append(f"🔥 Spike ({spike_ratio:.1f}x) against signal — possible exhaustion")
                force_widen_stop = True

        # ── HTF STRUCTURE ALIGNMENT GATING ──
        if sig['dir'] == 'BUY' and htf_align < -50:
            c -= 25
            notes.append(f"❌ HTF structure strongly bearish ({htf_align:+.0f}) — counter-trend risk")
            if htf_align < -75:
                skip = True
        elif sig['dir'] == 'SELL' and htf_align > 50:
            c -= 25
            notes.append(f"❌ HTF structure strongly bullish ({htf_align:+.0f}) — counter-trend risk")
            if htf_align > 75:
                skip = True
        elif (sig['dir'] == 'BUY' and htf_align > 30) or (sig['dir'] == 'SELL' and htf_align < -30):
            c += 10
            notes.append(f"✅ HTF alignment confirms direction ({htf_align:+.0f})")

        # ── INTERMEDIATE TREND (15m Ribbon) ──
        if tf == '5m' and trend_15m != 'neutral':
            if sig['dir'] == 'BUY' and trend_15m == 'bearish':
                c -= 20
                notes.append("❌ 15m EMA Ribbon BEARISH — fighting trend")
            elif sig['dir'] == 'SELL' and trend_15m == 'bullish':
                c -= 20
                notes.append("❌ 15m EMA Ribbon BULLISH — fighting trend")
            elif (sig['dir'] == 'BUY' and trend_15m == 'bullish') or (sig['dir'] == 'SELL' and trend_15m == 'bearish'):
                c += 10
                notes.append(f"✅ 15m EMA Ribbon confirms ({trend_15m})")

        # ── ORDER BOOK DEPTH IMBALANCE ──
        if sig['dir'] == 'BUY':
            if ob_imbalance >= 1.4:
                c += 15
                notes.append(f"🔥 Book Support: Bid depth {ob_imbalance:.2f}x")
            elif ob_imbalance <= 0.6:
                c -= 20
                notes.append(f"⚠️ Thin Book Support: Ask heavier ({ob_imbalance:.2f}x)")
        else:
            if ob_imbalance <= 0.6:
                c += 15
                notes.append(f"🔥 Book Resistance: Ask depth {1/ob_imbalance:.2f}x heavier")
            elif ob_imbalance >= 1.4:
                c -= 20
                notes.append(f"⚠️ Thin Book Resistance: Bid heavier ({ob_imbalance:.2f}x)")

        # Thin book penalty
        if ob_thin:
            c -= 8
            notes.append("⚠️ Thin top-of-book — imbalance may be unreliable")

        # Wide-depth confirmation
        wide_agrees = (ob_imbalance >= 1.0 and ob_imbalance_wide >= 1.0) or \
                      (ob_imbalance < 1.0 and ob_imbalance_wide < 1.0)
        if sig['dir'] == 'BUY' and ob_imbalance_wide >= 1.2 and wide_agrees:
            c += 6
            notes.append(f"✅ Wide book confirms bid-heavy ({ob_imbalance_wide:.2f}x)")
        elif sig['dir'] == 'SELL' and ob_imbalance_wide <= 0.83 and wide_agrees:
            c += 6
            notes.append(f"✅ Wide book confirms ask-heavy ({ob_imbalance_wide:.2f}x)")
        elif not wide_agrees:
            c -= 6
            notes.append(f"⚠️ Wide book disagrees ({ob_imbalance_wide:.2f}x vs {ob_imbalance:.2f}x)")

        # Wall detection
        for wall in wall_signals:
            if 'BID' in wall and sig['dir'] == 'BUY':
                c += 8
                notes.append(f"🧱 {wall}")
            elif 'ASK' in wall and sig['dir'] == 'SELL':
                c += 8
                notes.append(f"🧱 {wall}")

        # ── DELTA PROFILE (INSTITUTIONAL FOOTPRINT) ──
        if delta_profile['coverage_ok']:
            if sig['dir'] == 'BUY':
                if delta_profile['large_delta_pct'] > 10:
                    c += 12
                    notes.append(f"🔥 Large lot buying: {delta_profile['large_delta_pct']:+.1f}%")
                elif delta_profile['large_delta_pct'] < -15:
                    c -= 15
                    notes.append(f"⚠️ Institutional selling: {delta_profile['large_delta_pct']:+.1f}%")
            else:
                if delta_profile['large_delta_pct'] < -10:
                    c += 12
                    notes.append(f"🔥 Large lot selling: {delta_profile['large_delta_pct']:+.1f}%")
                elif delta_profile['large_delta_pct'] > 15:
                    c -= 15
                    notes.append(f"⚠️ Institutional buying: {delta_profile['large_delta_pct']:+.1f}%")

            if delta_profile['divergence']:
                c -= 10
                notes.append("⚠️ Retail/Institutional delta divergence")

        # ── CVD PRESSURE ──
        cvd_weight = 1.0 if cvd_coverage_ok else 0.5
        if not cvd_coverage_ok:
            notes.append(f"⚠️ CVD window short — weighted {cvd_weight:.0%}")

        if sig['dir'] == 'BUY':
            if approx_cvd > 0.15:
                c += 12 * cvd_weight
                notes.append(f"📈 CVD Bullish: Aggressive buying ({approx_cvd*100:+.1f}%)")
            elif approx_cvd < -0.25:
                c -= 15 * cvd_weight
                notes.append(f"⚠️ CVD Divergence: Dump in progress ({approx_cvd*100:+.1f}%)")
        else:
            if approx_cvd < -0.15:
                c += 12 * cvd_weight
                notes.append(f"📉 CVD Bearish: Aggressive selling ({approx_cvd*100:+.1f}%)")
            elif approx_cvd > 0.25:
                c -= 15 * cvd_weight
                notes.append(f"⚠️ CVD Divergence: Absorption/buying ({approx_cvd*100:+.1f}%)")

        # ── FUNDING RATE CONTRARIAN SIGNAL ──
        if funding_state == 'extreme_long' and sig['dir'] == 'BUY':
            c -= 25
            notes.append(f"⚠️ Extreme funding {funding_rate:+.3f}% — longs overcrowded")
        elif funding_state == 'extreme_short' and sig['dir'] == 'SELL':
            c -= 25
            notes.append(f"⚠️ Extreme funding {funding_rate:+.3f}% — shorts overcrowded")
        elif funding_state == 'extreme_long' and sig['dir'] == 'SELL':
            c += 15
            notes.append(f"🔥 Extreme funding {funding_rate:+.3f}% — short squeeze fuel")
        elif funding_state == 'extreme_short' and sig['dir'] == 'BUY':
            c += 15
            notes.append(f"🔥 Extreme funding {funding_rate:+.3f}% — long squeeze fuel")
        elif funding_state in ('elevated_long', 'elevated_short'):
            notes.append(f"📋 Funding: {funding_state} ({funding_rate:+.3f}%)")

        # ── SESSION AWARENESS ──
        c *= session['conviction_mult']
        if session['liquidity'] == 'thin':
            notes.append(f"⚠️ {session['name']} session — thin liquidity, size down")
        elif session['liquidity'] == 'high':
            notes.append(f"✅ {session['name']} session — optimal execution window")

        # ── MACRO TREND BIAS ──
        if use_bias:
            if bias in ('BEARISH_STRONG', 'BEARISH'):
                if sig['dir'] == 'SELL':
                    boost = 20 if bias == 'BEARISH_STRONG' else 10
                    c += boost
                    notes.append(f"✅ Macro Bias {bias} confirms SELL")
                elif sig['dir'] == 'BUY':
                    if rsi_val < 20:
                        c -= 15
                        notes.append("⚠️ Counter-trend BUY — oversold exception")
                    else:
                        c -= 30
                        notes.append(f"❌ Rejected counter-trend BUY vs {bias}")
                        skip = True
            elif bias in ('BULLISH_STRONG', 'BULLISH'):
                if sig['dir'] == 'BUY':
                    boost = 20 if bias == 'BULLISH_STRONG' else 10
                    c += boost
                    notes.append(f"✅ Macro Bias {bias} confirms BUY")
                elif sig['dir'] == 'SELL':
                    if rsi_val > 80:
                        c -= 15
                        notes.append("⚠️ Counter-trend SELL — overbought exception")
                    else:
                        c -= 30
                        notes.append(f"❌ Rejected counter-trend SELL vs {bias}")
                        skip = True

        if skip:
            continue

        # Volume confirmation
        if len(vol) > 15:
            avg_vol = np.mean(vol[-15:])
            vr = vol[-1] / avg_vol if avg_vol > 0 else 1.0
            if vr > 1.5:
                c += 5
                notes.append(f"📈 Volume spike ({vr:.1f}x avg)")

        # Price vs MA
        if sig['dir'] == 'BUY' and current > ma:
            c += 5
        elif sig['dir'] == 'SELL' and current < ma:
            c += 5

        # Squeeze breakout
        if sq_release:
            if (sig['dir'] == 'BUY' and sq_bull) or (sig['dir'] == 'SELL' and not sq_bull):
                c += 10
                notes.append("🔥 Squeeze Breakout Active")

        # Hurst trend persistence
        if h_exp > 0.55:
            c += 5

        c = float(np.clip(c, 0, 100))

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
            'ob_thin': ob_thin,
            'cvd_pct':  round(approx_cvd * 100, 1),
            'cvd_coverage_ok': cvd_coverage_ok,
            'atr':      round(current_atr, 2),
            'is_spike': is_spike,
            'spike_ratio': spike_ratio,
            'regime': regime,
            'force_widen_stop': force_widen_stop,
            'session': session['name'],
            'htf_align': round(htf_align, 1),
            'funding_state': funding_state,
            'funding_rate': round(funding_rate, 4),
            'liq_score': liq['score'],
            'delta_profile': delta_profile,
        })

    signals.sort(key=lambda x: x['conf'], reverse=True)
    return signals

# ============================================
# TRADE COMPILER (KELLY + REGIME-AWARE)
# ============================================

def kelly_position_size(confidence, account_size, max_risk_pct=0.02,
                        win_rate_estimate=0.55, avg_win_loss_ratio=1.5):
    """
    Kelly Criterion position sizing with half-Kelly safety.
    f = (p*b - q) / b
    """
    p = win_rate_estimate + (confidence - 50) / 100 * 0.2
    p = min(0.75, max(0.25, p))
    q = 1 - p
    b = avg_win_loss_ratio

    kelly = (p * b - q) / b
    kelly = max(0, kelly)
    half_kelly = kelly / 2

    risk_amount = account_size * min(half_kelly, max_risk_pct)
    return risk_amount

def build_trade_plan(sig, tf, account_size, risk_pct, max_risk_pct=0.02):
    """
    Builds entry, stop, and TP levels with regime-adaptive stops
    and Kelly-criterion position sizing.
    """
    p = TF_PARAMS[tf]
    price = sig['price']
    direction = sig['dir']
    regime = sig.get('regime', 'normal')

    # Regime-adjusted stop distance
    base_stop_pct = p['stop_pct']
    adjusted_stop_pct = get_regime_adjusted_stop(base_stop_pct, regime)

    # ATR-based stop
    atr_stop_distance = sig.get('atr', 0) * 1.2
    fixed_stop_distance = price * adjusted_stop_pct
    stop_distance = max(atr_stop_distance, fixed_stop_distance)

    # Liquidation cascade widening
    if sig.get('force_widen_stop') or sig.get('is_spike'):
        stop_distance *= 1.25
        if sig.get('liq_score', 0) > 80:
            stop_distance *= 1.15  # Extra room for violent cascades

    if direction == 'BUY':
        entry = max(price, sig['lower'] * 1.001)
        stop  = min(entry - stop_distance, sig['lower'] * 0.999)
        tp1   = entry * (1 + p['tp1_pct'])
        tp2   = entry * (1 + p['tp2_pct'])
        tp3   = entry * (1 + p['tp3_pct'])
    else:
        entry = min(price, sig['upper'] * 0.999)
        stop  = max(entry + stop_distance, sig['upper'] * 1.001)
        tp1   = entry * (1 - p['tp1_pct'])
        tp2   = entry * (1 - p['tp2_pct'])
        tp3   = entry * (1 - p['tp3_pct'])

    risk_per_unit = abs(entry - stop)

    # Kelly-adjusted dollar risk
    dollar_risk = kelly_position_size(sig['conf'], account_size, max_risk_pct)

    # Session liquidity adjustment
    session_mult = 0.7 if sig.get('session') == 'Weekend' else 1.0
    dollar_risk *= session_mult

    pos_units = dollar_risk / risk_per_unit if risk_per_unit > 0 else 0
    pos_value = min(pos_units * entry, account_size * 0.4)
    pos_units = pos_value / entry

    return {
        'entry':  round(entry, 2),
        'stop':   round(stop, 2),
        'stop_pct_actual': round(abs(entry - stop) / entry * 100, 2),
        'tp1':    round(tp1, 2),
        'tp2':    round(tp2, 2),
        'tp3':    round(tp3, 2),
        'gain1':  round(abs(tp1 - entry) / entry * 100, 2),
        'gain2':  round(abs(tp2 - entry) / entry * 100, 2),
        'gain3':  round(abs(tp3 - entry) / entry * 100, 2),
        'units':  round(pos_units, 5),
        'value':  round(pos_value, 2),
        'risk_$': round(dollar_risk, 2),
        'regime': regime,
        'session_adjusted': session_mult < 1.0,
    }

# ============================================
# INTERFACE PRINTS
# ============================================

def print_signal(sig, plan, tf, verbose=False):
    emoji = '🟢' if sig['dir'] == 'BUY' else '🔴'
    regime_emoji = {'compressed': '📉', 'normal': '➡️', 'expansion': '📈', 'cascade': '⚡'}

    print(f"\n  {emoji} [{tf}] BTC/USDT — {sig['dir']}  |  Conf: {sig['conf']}%  |  {sig['desc']}")
    print(f"     📊 Regime: {regime_emoji.get(sig['regime'], '➡️')} {sig['regime'].upper()} | Session: {sig['session']} | HTF Align: {sig['htf_align']:+.0f}")
    print(f"     💰 Price: ${sig['price']:,.2f} | RSI({tf}): {sig['rsi']} | Funding: {sig['funding_state']} ({sig['funding_rate']:+.4f}%)")
    print(f"     📖 Book: {sig['ob_ratio']}x{' (thin)' if sig.get('ob_thin') else ''} | CVD: {sig['cvd_pct']:+}%{'' if sig.get('cvd_coverage_ok', True) else ' (short)'}")

    if sig.get('is_spike'):
        print(f"     ⚡ Volatility spike: {sig['spike_ratio']}x avg range")
    if sig.get('liq_score', 0) > 0:
        print(f"     🔥 Liquidation score: {sig['liq_score']}/100")
    if sig.get('delta_profile', {}).get('large_delta_pct', 0) != 0:
        ld = sig['delta_profile']['large_delta_pct']
        print(f"     🐋 Large lot delta: {ld:+.1f}%")

    print(f"     📍 Entry   : ${plan['entry']:,.2f}")
    print(f"     🛑 Stop    : ${plan['stop']:,.2f}  (Risk: ${plan['risk_$']:.2f}, {plan['stop_pct_actual']}% — {plan['regime']}-scaled)")
    print(f"     🎯 Target 1: ${plan['tp1']:,.2f}  (+{plan['gain1']}%)")
    print(f"     🎯 Target 2: ${plan['tp2']:,.2f}  (+{plan['gain2']}%)")
    print(f"     🎯 Target 3: ${plan['tp3']:,.2f}  (+{plan['gain3']}%)")
    print(f"     📊 Size: {plan['units']} BTC (${plan['value']:,.2f}){' [Session-adjusted]' if plan['session_adjusted'] else ''}")

    if verbose:
        print("     📝 Validation Logs:")
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
        'symbol': 'BTCUSD',
        'timeframe': tf,
        'direction': direction,
        'rsi': sig['rsi'],
        'price': plan['entry'],
        'current_price': sig['price'],  # spot at generation; entry ('price') is the limit level
        'pivot_level': None,
        'pivot_distance': None,
        'confidence': round(sig['conf'], 1),
        'sl': plan['stop'],
        'tp': plan['tp1'],
        'btc_state': None,  # this signal IS BTC — no separate BTC-state annotation
        'signal_source': 'btc_scanner'
    }

def _json_default(o):
    # Indicator math yields numpy scalars (e.g. int64/float64) that the stdlib
    # JSON encoder rejects; coerce them to native Python numbers.
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(f"Object of type {o.__class__.__name__} is not JSON serializable")

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
    # Never let a feed-write problem crash the scanner loop.
    try:
        with open(tmp_path, 'w') as f:
            json.dump(combined, f, indent=2, default=_json_default)
        os.replace(tmp_path, feed_path)
        print(f"✅ Wrote {len(entries)} signal(s) to {feed_path}")
    except Exception as e:
        print(f"⚠️ Could not write to feed: {e}")

# ============================================
# MAIN SCAN LOOP
# ============================================

def run_scan(timeframes, account_size, risk_pct, use_bias, verbose, min_conf, max_risk_pct):
    print(f"\n{'='*75}")
    print(f"  📡 BTC AGGRESSIVE SCANNER v2.0 — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"  🎯 Regime-Aware | Microstructure-Intelligent | Kelly-Sized")
    print(f"{'='*75}")

    bias, score, bias_details = get_btc_trend_bias()

    icon = '🟢' if 'BULLISH' in bias else ('🔴' if 'BEARISH' in bias else '⚪')
    print(f"  {icon}  BTC MACRO BIAS: {bias} (Score: {score:+.0f})")

    # Show HTF alignment
    htf = get_htf_structure_alignment()
    htf_icon = '🟢' if htf > 30 else ('🔴' if htf < -30 else '⚪')
    print(f"  {htf_icon}  HTF ALIGNMENT: {htf:+.0f} (1h/4h/1d confluence)")

    # Show funding
    funding_state, funding_rate = fetch_funding_rate_proxy()
    fund_icon = '🔥' if 'extreme' in funding_state else '📋'
    print(f"  {fund_icon}  FUNDING: {funding_state} ({funding_rate:+.4f}%)")

    # Session
    session = get_session_profile()
    sess_icon = '✅' if session['liquidity'] == 'high' else ('⚠️' if session['liquidity'] == 'thin' else '➡️')
    print(f"  {sess_icon}  SESSION: {session['name']} ({session['hour']:02d}:00 UTC) — Liquidity: {session['liquidity'].upper()}")

    print(f"{'='*75}")

    feed_entries = []
    for tf in timeframes:
        print(f"  ⏱️  Processing [{tf}] Candlestick & Order Stream Matrix...")
        df = fetch_ohlcv('BTC/USDT', tf, limit=TF_PARAMS[tf]['lookback'] + 30)
        if df is None:
            continue

        # Show current regime
        regime = detect_volatility_regime(df)
        regime_emoji = {'compressed': '📉', 'normal': '➡️', 'expansion': '📈', 'cascade': '⚡'}
        print(f"     Current regime: {regime_emoji.get(regime, '➡️')} {regime.upper()}")

        signals = detect_btc_signals(df, tf, bias, use_bias=use_bias)
        signals = [s for s in signals if s['conf'] >= min_conf]

        if not signals:
            print(f"     ⏳ No qualifying signals above {min_conf}% confidence.")
        else:
            for sig in signals:
                plan = build_trade_plan(sig, tf, account_size, risk_pct, max_risk_pct)
                print_signal(sig, plan, tf, verbose=verbose)
                feed_entries.append(build_feed_entry(sig, plan, tf))

    write_to_feed(feed_entries)
    print(f"{'='*75}\n")

def main():
    args = parse_args()
    if args.timeframe not in ('5m', '15m', '30m'):
        print("❌ Error: Supported timeframes are 5m, 15m, 30m.")
        sys.exit(1)

    timeframes = [args.timeframe]
    use_bias = not args.no_bias

    if args.loop > 0:
        print(f"🔁 Scanner live. Sampling every {args.loop}m. Press Ctrl+C to stop.")
        while True:
            try:
                run_scan(timeframes, args.account, args.risk, use_bias, 
                        args.verbose, args.min_conf, args.max_risk_pct)
                time.sleep(args.loop * 60)
            except KeyboardInterrupt:
                print("\n👋 Scanner halted by user.")
                break
    else:
        run_scan(timeframes, args.account, args.risk, use_bias, 
                args.verbose, args.min_conf, args.max_risk_pct)

if __name__ == '__main__':
    main()
