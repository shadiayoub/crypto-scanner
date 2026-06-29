#!/usr/bin/env python3
"""
XAG/USDT Intraday Scanner — 1h / 4h
Silver-specific: trend-aware macro bias from Daily + Weekly candles,
Gann 8ths S/R confluence, Gold/Silver ratio bias, daily pivot points,
ATR volatility regime filter, and NW envelope signal engine.

Market: Binance USDT-M Futures (XAG/USDT perpetual)

Usage:
    python xag_scanner.py                   # Scan both 1h and 4h
    python xag_scanner.py -tf 1h            # 1h only
    python xag_scanner.py -tf 4h            # 4h only
    python xag_scanner.py --loop 15         # Repeat every 15 minutes
    python xag_scanner.py --no-bias         # Disable macro trend filter
    python xag_scanner.py --account 5000    # Set account size in USD
    python xag_scanner.py --risk 0.01       # Risk % per trade (default 1%)
    python xag_scanner.py -v                # Verbose: show all filter notes
    python xag_scanner.py --min-conf 60     # Only show signals ≥ 60% conf
"""

import ccxt
import pandas as pd
import numpy as np
from datetime import datetime, timezone
import time
import warnings
import argparse
import sys
warnings.filterwarnings('ignore')

# ============================================================
# ARGS
# ============================================================

def parse_args():
    parser = argparse.ArgumentParser(
        description='XAG/USDT Silver Scanner — 1h/4h with macro bias',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('-tf', '--timeframe', type=str, default=None,
        help='Single timeframe: 1h or 4h. Omit for both.')
    parser.add_argument('--loop', type=int, default=0,
        help='Repeat every N minutes (0 = single run)')
    parser.add_argument('--account', type=float, default=10000,
        help='Account size in USD (default: 10000)')
    parser.add_argument('--risk', type=float, default=0.01,
        help='Risk per trade as decimal (default: 0.01 = 1%%)')
    parser.add_argument('--no-bias', action='store_true',
        help='Disable macro trend-bias filter')
    parser.add_argument('-v', '--verbose', action='store_true',
        help='Show all filter notes per signal')
    parser.add_argument('--min-conf', type=float, default=50.0,
        help='Minimum confidence to display (default: 50)')
    return parser.parse_args()

# ============================================================
# EXCHANGE — Binance USDT-M Futures
# ============================================================

_EX = {}

def get_exchange():
    if 'futures' not in _EX:
        _EX['futures'] = ccxt.binance({
            'enableRateLimit': True,
            'options': {'defaultType': 'future'},
        })
    return _EX['futures']

def fetch_ohlcv(symbol, timeframe, limit=350):
    try:
        ex = get_exchange()
        raw = ex.fetch_ohlcv(symbol, timeframe, limit=limit)
        if not raw:
            return None
        df = pd.DataFrame(raw, columns=['ts','open','high','low','close','volume'])
        df = df.dropna()
        return df
    except Exception as e:
        print(f"  ⚠️  fetch_ohlcv({symbol},{timeframe}): {str(e)[:80]}")
        return None

# ============================================================
# INDICATORS
# ============================================================

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
    return mid, mid + mae, mid - mae   # mid, upper, lower

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
        return float(price[-1])
    k = 2.0 / (period + 1)
    e = float(price[0])
    for p in price[1:]:
        e = p * k + e * (1 - k)
    return e

def atr(high, low, close, period=14):
    if len(high) < period + 1:
        return float(high[-1] - low[-1])
    tr = np.maximum(high[1:] - low[1:],
         np.maximum(np.abs(high[1:] - close[:-1]),
                    np.abs(low[1:] - close[:-1])))
    return float(np.mean(tr[-period:]))

def atr_percentile(high, low, close, period=14, window=100):
    """
    Returns current ATR as a percentile of the last `window` ATR readings.
    < 25th pct = low volatility regime (avoid signals)
    > 75th pct = high volatility regime (tighten stops)
    """
    if len(close) < window + period + 1:
        return 50.0
    atrs = []
    for i in range(window, 0, -1):
        h_sl = high[-(i + period):-i] if i > 0 else high[-(i + period):]
        l_sl = low[-(i + period):-i]  if i > 0 else low[-(i + period):]
        c_sl = close[-(i + period + 1):-(i)] if i > 0 else close[-(i + period + 1):]
        if len(h_sl) >= period + 1:
            atrs.append(atr(h_sl, l_sl, c_sl, period))
    if not atrs:
        return 50.0
    current_atr = atr(high, low, close, period)
    pct = float(np.sum(np.array(atrs) < current_atr) / len(atrs) * 100)
    return round(pct, 1)

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

def detect_market_structure(high, low, swing=5):
    """Returns 'bullish', 'bearish', or 'neutral'. Swing=5 for 1h/4h silver."""
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
    ob_zone  = (None, None, None)
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

# ============================================================
# GANN 8THS LEVELS
# ============================================================

def gann_eighths(pivot_low, pivot_high):
    """
    Divides the range between a key low and high into 8 equal parts.
    These price levels act as natural S/R in Gann theory.
    Returns a dict of {label: price} for the 9 levels (0/8 through 8/8).
    The 4/8 (50%) and 2/8 (25%) / 6/8 (75%) are the strongest.
    """
    rng = pivot_high - pivot_low
    levels = {}
    for i in range(9):
        label = f"{i}/8"
        price = pivot_low + (rng * i / 8)
        levels[label] = round(price, 4)
    return levels

def nearest_gann_level(price, levels, tolerance_pct=0.003):
    """
    Returns (label, level_price, distance_pct) for the nearest Gann level
    within tolerance. Returns None if no level is nearby.
    Marks the level strength: '4/8' and '8/8'/'0/8' are strongest,
    '2/8' and '6/8' are strong, rest are moderate.
    """
    STRONG_LEVELS = {'0/8', '4/8', '8/8'}
    MEDIUM_LEVELS = {'2/8', '6/8'}

    best = None
    best_dist = float('inf')
    for label, lvl in levels.items():
        dist = abs(price - lvl) / price
        if dist < tolerance_pct and dist < best_dist:
            best_dist = dist
            strength = 'STRONG' if label in STRONG_LEVELS else \
                       ('MEDIUM' if label in MEDIUM_LEVELS else 'MODERATE')
            best = (label, lvl, round(dist * 100, 3), strength)
    return best

def get_gann_52w_levels(df_daily):
    """
    Compute Gann 8ths from the rolling 52-week (365-day candle) high/low.
    Uses daily OHLCV. Returns levels dict or empty dict.
    """
    if df_daily is None or len(df_daily) < 20:
        return {}
    lookback = min(365, len(df_daily))
    subset = df_daily.tail(lookback)
    pivot_low  = float(subset['low'].min())
    pivot_high = float(subset['high'].max())
    return gann_eighths(pivot_low, pivot_high)

# ============================================================
# DAILY PIVOT POINTS
# ============================================================

def daily_pivots(df_daily):
    """
    Classic floor-trader pivot points from previous day's OHLC.
    Returns dict: PP, R1, R2, R3, S1, S2, S3
    """
    if df_daily is None or len(df_daily) < 2:
        return {}
    prev = df_daily.iloc[-2]
    H = float(prev['high'])
    L = float(prev['low'])
    C = float(prev['close'])
    PP = (H + L + C) / 3
    R1 = 2 * PP - L
    S1 = 2 * PP - H
    R2 = PP + (H - L)
    S2 = PP - (H - L)
    R3 = H + 2 * (PP - L)
    S3 = L - 2 * (H - PP)
    return {
        'PP': round(PP, 4),
        'R1': round(R1, 4), 'R2': round(R2, 4), 'R3': round(R3, 4),
        'S1': round(S1, 4), 'S2': round(S2, 4), 'S3': round(S3, 4),
    }

def nearest_pivot(price, pivots, tolerance_pct=0.003):
    """
    Returns (label, level, distance_pct) for nearest pivot level, or None.
    """
    best = None
    best_dist = float('inf')
    for label, lvl in pivots.items():
        dist = abs(price - lvl) / price
        if dist < tolerance_pct and dist < best_dist:
            best_dist = dist
            best = (label, lvl, round(dist * 100, 3))
    return best

# ============================================================
# GOLD / SILVER RATIO BIAS
# ============================================================

def get_gold_silver_ratio():
    """
    Fetches XAU/USDT and XAG/USDT from Binance futures.
    Returns (ratio, bias_label, score_adjustment)
    Historically:
      ratio > 85  → silver cheap vs gold → potential silver bull bias
      ratio < 65  → silver expensive vs gold → potential silver bear bias
      65–85       → neutral
    """
    try:
        xau_df = fetch_ohlcv('XAU/USDT', '1d', limit=5)
        xag_df = fetch_ohlcv('XAG/USDT', '1d', limit=5)
        if xau_df is None or xag_df is None:
            return None, 'UNKNOWN', 0
        xau_price = float(xau_df['close'].iloc[-1])
        xag_price = float(xag_df['close'].iloc[-1])
        if xag_price <= 0:
            return None, 'UNKNOWN', 0
        ratio = round(xau_price / xag_price, 2)
        if ratio > 90:
            return ratio, 'SILVER_CHEAP_EXTREME', +20   # strong bullish bias for XAG
        elif ratio > 80:
            return ratio, 'SILVER_CHEAP', +10
        elif ratio < 60:
            return ratio, 'SILVER_EXPENSIVE_EXTREME', -20
        elif ratio < 70:
            return ratio, 'SILVER_EXPENSIVE', -10
        else:
            return ratio, 'NEUTRAL', 0
    except Exception as e:
        print(f"  ⚠️  Gold/Silver ratio fetch failed: {str(e)[:60]}")
        return None, 'UNKNOWN', 0

# ============================================================
# SEASONALITY
# ============================================================

def silver_seasonality():
    """
    Returns (label, score_adj) based on calendar month.
    Based on historical silver seasonal patterns:
      Jan–Apr:  mild bullish (Q1 industrial demand, Chinese New Year)
      May–Jun:  neutral to bearish (consolidation)
      Jul–Sep:  weakest period historically
      Oct–Dec:  recovery / year-end rally
    """
    month = datetime.now(timezone.utc).month
    if month in (1, 2, 3, 4):
        return 'SEASONALLY_BULLISH (Q1)', +8
    elif month in (5, 6):
        return 'SEASONALLY_NEUTRAL (Q2)', 0
    elif month in (7, 8, 9):
        return 'SEASONALLY_WEAK (Q3)', -8
    else:
        return 'SEASONALLY_RECOVERING (Q4)', +5

# ============================================================
# MACRO TREND BIAS (Daily + Weekly)
# ============================================================

def get_xag_trend_bias():
    """
    Reads daily and weekly XAG/USDT candles to determine macro trend.
    Returns:
        bias:     'BEARISH_STRONG' | 'BEARISH' | 'NEUTRAL' | 'BULLISH' | 'BULLISH_STRONG'
        score:    float -100..+100
        details:  dict with sub-readings per timeframe
        gs_ratio: (ratio, label, adj) gold/silver ratio
        season:   (label, adj) seasonality
    """
    results = {}
    total_score = 0.0

    for tf, weight in [('1d', 0.5), ('1w', 0.5)]:
        df = fetch_ohlcv('XAG/USDT', tf, limit=60)
        if df is None or len(df) < 10:
            continue
        c  = df['close'].values
        h  = df['high'].values
        lo = df['low'].values

        rsi_val   = rsi(c[-30:], 14)
        rsi_score = (rsi_val - 50) * 2

        ema50     = ema(c, min(50, len(c)))
        ema_score = float(np.clip(((c[-1] - ema50) / ema50) * 1000, -100, 100))

        mom       = (c[-1] - c[-6]) / c[-6] * 100 if len(c) >= 6 else 0
        mom_score = float(np.clip(mom * 10, -100, 100))

        struct       = detect_market_structure(h, lo, swing=3)
        struct_score = 30 if struct == 'bullish' else (-30 if struct == 'bearish' else 0)

        tf_score    = (rsi_score * 0.3 + ema_score * 0.3 + mom_score * 0.25 + struct_score * 0.15)
        total_score += tf_score * weight

        results[tf] = {
            'rsi':       round(rsi_val, 1),
            'ema50':     round(ema50, 4),
            'price':     round(c[-1], 4),
            'structure': struct,
            'tf_score':  round(tf_score, 1)
        }

    # Gold/Silver ratio adjustment
    gs_ratio, gs_label, gs_adj = get_gold_silver_ratio()
    total_score += gs_adj * 0.5   # moderate weight; not the primary signal

    # Seasonality adjustment (light touch)
    season_label, season_adj = silver_seasonality()
    total_score += season_adj * 0.3

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

    return bias, round(total_score, 1), results, (gs_ratio, gs_label, gs_adj), (season_label, season_adj)

# ============================================================
# TIMEFRAME PARAMS — tuned for XAG 1h / 4h
# ============================================================

TF_PARAMS = {
    '1h': {
        'lookback':    150,
        'bandwidth':   5.0,    # wider NW envelope for slower silver moves
        'multiplier':  2.0,
        'rsi_period':  14,     # standard RSI for hourly
        'ma_period':   50,
        'confirm_tf':  '4h',   # 4h RSI confirmation
        'stop_pct':    0.010,  # 1.0% stop for 1h silver
        'tp1_pct':     0.010,
        'tp2_pct':     0.020,
        'tp3_pct':     0.035,
        'atr_period':  14,
    },
    '4h': {
        'lookback':    200,
        'bandwidth':   7.0,
        'multiplier':  2.5,
        'rsi_period':  14,
        'ma_period':   50,
        'confirm_tf':  '1d',   # daily RSI confirmation
        'stop_pct':    0.018,  # 1.8% stop for 4h
        'tp1_pct':     0.018,
        'tp2_pct':     0.035,
        'tp3_pct':     0.060,
        'atr_period':  14,
    }
}

# ============================================================
# SIGNAL DETECTION
# ============================================================

def detect_xag_signals(df, tf, bias, use_bias, gann_levels, pivots, gs_ratio_adj, season_adj):
    """
    Core signal engine for XAG/USDT intraday (1h/4h).
    Incorporates: NW envelope, RSI, squeeze, Hurst, market structure,
    OB/FVG, Gann 8ths, daily pivots, ATR regime, G/S ratio, seasonality.
    """
    p = TF_PARAMS[tf]
    close  = df['close'].values.astype(float)
    high   = df['high'].values.astype(float)
    low    = df['low'].values.astype(float)
    vol    = df['volume'].values.astype(float)

    if len(close) < p['lookback']:
        return []

    # --- Core indicators ---
    mid, upper, lower = nadaraya_watson_envelope(close, p['bandwidth'], p['multiplier'], p['lookback'])
    if mid is None:
        return []

    rsi_val     = rsi(close[-p['rsi_period']-30:], p['rsi_period'])
    ma          = np.mean(close[-p['ma_period']:]) if len(close) >= p['ma_period'] else np.mean(close)
    squeeze_on, sq_release, sq_bull = squeeze_momentum(high, low, close)
    h_exp       = hurst_exponent(close)
    struct      = detect_market_structure(high, low)
    ob_zone, fvg_zone = find_ob_and_fvg(high, low, close)

    # ATR volatility regime
    atr_val = atr(high, low, close, p['atr_period'])
    atr_pct = atr_percentile(high, low, close, p['atr_period'], window=100)

    current = close[-1]
    prev    = close[-2]

    # --- Raw candidates ---
    candidates = []

    # 1. Lower band crossover (BUY)
    if current > lower and prev <= lower and rsi_val < 55:
        conf = min(80, (50 - rsi_val) * 1.5 + 50)
        candidates.append({'dir': 'BUY', 'type': 'BUY_CROSS_LOWER', 'conf': conf,
                           'desc': f'Cross above lower NW band (RSI {rsi_val:.0f})'})

    # 2. Upper band crossover (SELL)
    if current < upper and prev >= upper and rsi_val > 45:
        conf = min(80, (rsi_val - 50) * 1.5 + 50)
        candidates.append({'dir': 'SELL', 'type': 'SELL_CROSS_UPPER', 'conf': conf,
                           'desc': f'Cross below upper NW band (RSI {rsi_val:.0f})'})

    # 3. Oversold at/below lower band (BUY)
    if rsi_val < 30 and current <= lower * 1.02:
        conf = min(75, (30 - rsi_val) * 2.5 + 35)
        candidates.append({'dir': 'BUY', 'type': 'BUY_OVERSOLD', 'conf': conf,
                           'desc': f'Oversold RSI {rsi_val:.0f} at lower band'})

    # 4. Overbought at/above upper band (SELL)
    if rsi_val > 70 and current >= upper * 0.98:
        conf = min(75, (rsi_val - 70) * 2.5 + 35)
        candidates.append({'dir': 'SELL', 'type': 'SELL_OVERBOUGHT', 'conf': conf,
                           'desc': f'Overbought RSI {rsi_val:.0f} at upper band'})

    # 5. Price extreme below lower band (BUY)
    if lower > 0 and current < lower * 0.985:
        candidates.append({'dir': 'BUY', 'type': 'BUY_EXTREME', 'conf': 58,
                           'desc': f'Price {abs((current-lower)/lower*100):.1f}% below lower band'})

    # 6. Price extreme above upper band (SELL)
    if upper > 0 and current > upper * 1.015:
        candidates.append({'dir': 'SELL', 'type': 'SELL_EXTREME', 'conf': 58,
                           'desc': f'Price {abs((current-upper)/upper*100):.1f}% above upper band'})

    if not candidates:
        return []

    # --- Confirmation RSI from higher timeframe ---
    rsi_htf = None
    df_htf = fetch_ohlcv('XAG/USDT', p['confirm_tf'], limit=60)
    if df_htf is not None and len(df_htf) >= 20:
        rsi_htf = rsi(df_htf['close'].values[-30:], 14)

    # --- Apply filters to each candidate ---
    signals = []
    for sig in candidates:
        c      = sig['conf']
        notes  = []
        skip   = False

        # ── ATR VOLATILITY REGIME ─────────────────────────────────────
        # Silver in low-vol compression (ATR < 25th pct) → signals less reliable
        if atr_pct < 20:
            c -= 20
            notes.append(f"⚠️  ATR pct {atr_pct:.0f}th — very low vol, signal unreliable")
            if c < 40:
                skip = True
        elif atr_pct < 35:
            c -= 8
            notes.append(f"📉 ATR pct {atr_pct:.0f}th — subdued volatility")
        elif atr_pct > 85:
            # Very high vol: good for momentum trades, widen mental stop
            if (sig['dir'] == 'BUY' and current > ma) or (sig['dir'] == 'SELL' and current < ma):
                c += 8
                notes.append(f"🔥 ATR pct {atr_pct:.0f}th — high vol momentum confirmed")
            else:
                notes.append(f"⚠️  ATR pct {atr_pct:.0f}th — high vol, could be exhaustion")
        else:
            notes.append(f"✅ ATR pct {atr_pct:.0f}th — normal vol")
        if skip:
            continue

        # ── MACRO TREND BIAS ──────────────────────────────────────────
        if use_bias:
            if bias in ('BEARISH_STRONG', 'BEARISH'):
                if sig['dir'] == 'SELL':
                    boost = 25 if bias == 'BEARISH_STRONG' else 15
                    c += boost
                    notes.append(f"✅ Bias {bias} confirms SELL +{boost}")
                elif sig['dir'] == 'BUY':
                    if rsi_val < 25:
                        c -= 8
                        notes.append(f"⚠️  Counter-trend BUY vs {bias} (extreme oversold, partial ok)")
                    else:
                        c -= 28
                        notes.append(f"❌ Counter-trend BUY vs {bias}")
                        if c < 50:
                            skip = True
            elif bias in ('BULLISH_STRONG', 'BULLISH'):
                if sig['dir'] == 'BUY':
                    boost = 25 if bias == 'BULLISH_STRONG' else 15
                    c += boost
                    notes.append(f"✅ Bias {bias} confirms BUY +{boost}")
                elif sig['dir'] == 'SELL':
                    if rsi_val > 78:
                        c -= 8
                        notes.append(f"⚠️  Counter-trend SELL vs {bias} (extreme overbought, partial ok)")
                    else:
                        c -= 28
                        notes.append(f"❌ Counter-trend SELL vs {bias}")
                        if c < 50:
                            skip = True
            else:
                notes.append("⚪ Macro bias NEUTRAL — equal weight")
        if skip:
            continue

        # ── GOLD/SILVER RATIO ─────────────────────────────────────────
        if gs_ratio_adj != 0:
            if (sig['dir'] == 'BUY' and gs_ratio_adj > 0) or \
               (sig['dir'] == 'SELL' and gs_ratio_adj < 0):
                adj = abs(gs_ratio_adj) // 2   # apply half the ratio score
                c  += adj
                notes.append(f"✅ G/S ratio supports {sig['dir']} (+{adj:.0f})")
            elif (sig['dir'] == 'BUY' and gs_ratio_adj < 0) or \
                 (sig['dir'] == 'SELL' and gs_ratio_adj > 0):
                adj = abs(gs_ratio_adj) // 2
                c  -= adj
                notes.append(f"⚠️  G/S ratio contradicts {sig['dir']} (-{adj:.0f})")

        # ── SEASONALITY ───────────────────────────────────────────────
        if season_adj != 0:
            if (sig['dir'] == 'BUY' and season_adj > 0) or \
               (sig['dir'] == 'SELL' and season_adj < 0):
                notes.append(f"✅ Seasonality aligns with {sig['dir']}")
                c += abs(season_adj) * 0.5
            elif (sig['dir'] == 'BUY' and season_adj < 0) or \
                 (sig['dir'] == 'SELL' and season_adj > 0):
                notes.append(f"⚠️  Seasonality opposes {sig['dir']}")
                c -= abs(season_adj) * 0.5

        # ── GANN 8THS LEVELS ──────────────────────────────────────────
        if gann_levels:
            gann_hit = nearest_gann_level(current, gann_levels, tolerance_pct=0.004)
            if gann_hit:
                label, lvl, dist_pct, strength = gann_hit
                if strength == 'STRONG':
                    boost = 18
                elif strength == 'MEDIUM':
                    boost = 10
                else:
                    boost = 5
                c += boost
                notes.append(f"✅ Gann {label} level ${lvl:.3f} ({strength}) — {dist_pct:.2f}% away +{boost}")
            else:
                # Check if between two Gann levels (mid-zone = less conviction)
                notes.append("⚪ No nearby Gann level")

        # ── DAILY PIVOT POINTS ────────────────────────────────────────
        if pivots:
            piv_hit = nearest_pivot(current, pivots, tolerance_pct=0.004)
            if piv_hit:
                p_label, p_lvl, p_dist = piv_hit
                is_resistance = p_label.startswith('R') or p_label == 'PP'
                is_support    = p_label.startswith('S') or p_label == 'PP'
                if (sig['dir'] == 'BUY' and is_support) or \
                   (sig['dir'] == 'SELL' and is_resistance):
                    c += 12
                    notes.append(f"✅ Daily pivot {p_label}=${p_lvl:.3f} confirms {sig['dir']} +12")
                else:
                    c += 5
                    notes.append(f"📍 Near pivot {p_label}=${p_lvl:.3f}")

        # ── VOLUME ────────────────────────────────────────────────────
        if len(vol) > 15:
            avg_vol = np.mean(vol[-15:])
            vr      = vol[-1] / avg_vol if avg_vol > 0 else 1.0
            p5_chg  = (current - close[-5]) / close[-5] * 100 if len(close) >= 5 else 0
            if vr > 1.8:
                if (sig['dir'] == 'BUY' and p5_chg < -2) or \
                   (sig['dir'] == 'SELL' and p5_chg > 2):
                    c -= 18
                    notes.append(f"⚠️  High vol {vr:.1f}x against signal (potential exhaustion)")
                else:
                    c += 12
                    notes.append(f"🔥 Volume {vr:.1f}x avg — momentum")
            elif vr > 1.3:
                c += 5
                notes.append(f"📈 Volume {vr:.1f}x avg")
            else:
                notes.append(f"📉 Volume light {vr:.1f}x")

        # ── MA ALIGNMENT ──────────────────────────────────────────────
        ma_period = TF_PARAMS[tf]['ma_period']
        if sig['dir'] == 'BUY':
            if current > ma:
                c += 8
                notes.append(f"✅ Above MA{ma_period}")
            else:
                c -= 10
                notes.append(f"⚠️  Below MA{ma_period}")
        else:
            if current < ma:
                c += 8
                notes.append(f"✅ Below MA{ma_period}")
            else:
                c -= 10
                notes.append(f"⚠️  Above MA{ma_period}")

        # ── HIGHER TF RSI CONFIRMATION ────────────────────────────────
        confirm_tf = TF_PARAMS[tf]['confirm_tf']
        if rsi_htf is not None:
            if sig['dir'] == 'BUY':
                if rsi_htf < 40:
                    c += 15
                    notes.append(f"✅ {confirm_tf} RSI {rsi_htf:.0f} oversold — confirms BUY")
                elif rsi_htf > 65:
                    c -= 18
                    notes.append(f"⚠️  {confirm_tf} RSI {rsi_htf:.0f} overbought — BUY risky")
                    if rsi_htf > 75:
                        skip = True
                else:
                    notes.append(f"⚪ {confirm_tf} RSI {rsi_htf:.0f}")
            else:
                if rsi_htf > 60:
                    c += 15
                    notes.append(f"✅ {confirm_tf} RSI {rsi_htf:.0f} overbought — confirms SELL")
                elif rsi_htf < 35:
                    c -= 18
                    notes.append(f"⚠️  {confirm_tf} RSI {rsi_htf:.0f} oversold — SELL risky")
                    if rsi_htf < 25:
                        skip = True
                else:
                    notes.append(f"⚪ {confirm_tf} RSI {rsi_htf:.0f}")
        if skip:
            continue

        # ── SQUEEZE MOMENTUM ──────────────────────────────────────────
        if sq_release:
            if (sig['dir'] == 'BUY' and sq_bull) or \
               (sig['dir'] == 'SELL' and not sq_bull):
                c += 18
                notes.append("🔥 Squeeze RELEASE in signal direction")
            else:
                c -= 10
                notes.append("⚠️  Squeeze release opposite direction")
        elif squeeze_on:
            notes.append("📊 Squeeze ON — energy coiling (wait for release)")
        else:
            c -= 4
            notes.append("⚪ No squeeze")

        # ── HURST EXPONENT ────────────────────────────────────────────
        if h_exp > 0.55:
            c += 8
            notes.append(f"✅ Hurst {h_exp:.2f} — trending regime")
        elif h_exp < 0.45:
            notes.append(f"⚪ Hurst {h_exp:.2f} — mean-reverting (band trades preferred)")
        else:
            notes.append(f"⚪ Hurst {h_exp:.2f} — random walk")

        # ── MARKET STRUCTURE ──────────────────────────────────────────
        if sig['dir'] == 'BUY' and struct == 'bullish':
            c += 10
            notes.append("✅ Structure: Higher Highs / Higher Lows")
        elif sig['dir'] == 'SELL' and struct == 'bearish':
            c += 10
            notes.append("✅ Structure: Lower Highs / Lower Lows")
        elif (sig['dir'] == 'BUY' and struct == 'bearish') or \
             (sig['dir'] == 'SELL' and struct == 'bullish'):
            c -= 10
            notes.append(f"⚠️  Structure {struct} contradicts signal")

        # ── ORDER BLOCK ───────────────────────────────────────────────
        ob_low, ob_high, ob_dir = ob_zone
        if ob_low is not None:
            in_ob = ob_low <= current <= ob_high * 1.01
            if in_ob and ob_dir == ('bullish' if sig['dir'] == 'BUY' else 'bearish'):
                c += 10
                notes.append(f"✅ In {ob_dir} Order Block ${ob_low:.3f}-${ob_high:.3f}")
            elif in_ob:
                notes.append(f"⚠️  In {ob_dir} OB (opposite direction)")

        # ── FVG ───────────────────────────────────────────────────────
        fvg_lo, fvg_hi, fvg_dir = fvg_zone
        if fvg_lo is not None:
            in_fvg       = fvg_lo <= current <= fvg_hi
            expected_fvg = 'bullish' if sig['dir'] == 'BUY' else 'bearish'
            if in_fvg and fvg_dir == expected_fvg:
                c += 10
                notes.append(f"✅ In {fvg_dir} FVG ${fvg_lo:.3f}-${fvg_hi:.3f}")

        # ── FINAL ─────────────────────────────────────────────────────
        c = float(np.clip(c, 0, 100))
        if c < 50:
            continue

        signals.append({
            'dir':        sig['dir'],
            'type':       sig['type'],
            'desc':       sig['desc'],
            'conf':       round(c, 1),
            'notes':      notes,
            'price':      current,
            'rsi':        round(rsi_val, 1),
            'rsi_htf':    round(rsi_htf, 1) if rsi_htf else None,
            'mid':        round(mid, 4),
            'upper':      round(upper, 4),
            'lower':      round(lower, 4),
            'ma':         round(ma, 4),
            'atr':        round(atr_val, 4),
            'atr_pct':    atr_pct,
            'squeeze_on': squeeze_on,
            'sq_release': sq_release,
            'hurst':      round(h_exp, 2),
            'struct':     struct,
        })

    signals.sort(key=lambda x: x['conf'], reverse=True)
    return signals

# ============================================================
# TRADE PLAN
# ============================================================

def build_trade_plan(sig, tf, account_size, risk_pct):
    p       = TF_PARAMS[tf]
    price   = sig['price']
    direction = sig['dir']

    if direction == 'BUY':
        entry = max(price, sig['lower'] * 1.002)
        stop  = min(price * (1 - p['stop_pct']), sig['lower'] * 0.997)
        tp1   = entry * (1 + p['tp1_pct'])
        tp2   = entry * (1 + p['tp2_pct'])
        tp3   = entry * (1 + p['tp3_pct'])
    else:
        entry = min(price, sig['upper'] * 0.998)
        stop  = max(price * (1 + p['stop_pct']), sig['upper'] * 1.003)
        tp1   = entry * (1 - p['tp1_pct'])
        tp2   = entry * (1 - p['tp2_pct'])
        tp3   = entry * (1 - p['tp3_pct'])

    risk_per_unit = abs(entry - stop)
    dollar_risk   = account_size * risk_pct * (0.5 + sig['conf'] / 100 * 0.8)
    pos_oz        = dollar_risk / risk_per_unit if risk_per_unit > 0 else 0
    pos_value     = pos_oz * entry
    pos_value     = min(pos_value, account_size * 0.4)  # max 40% per trade
    pos_oz        = pos_value / entry

    def gain(t):
        return round(abs(t - entry) / entry * 100, 3)
    def rr(t):
        return round(abs(t - entry) / risk_per_unit, 2) if risk_per_unit > 0 else 0

    return {
        'entry':  round(entry, 4),
        'stop':   round(stop, 4),
        'tp1':    round(tp1, 4),
        'tp2':    round(tp2, 4),
        'tp3':    round(tp3, 4),
        'gain1':  gain(tp1),
        'gain2':  gain(tp2),
        'gain3':  gain(tp3),
        'rr1':    rr(tp1),
        'rr2':    rr(tp2),
        'rr3':    rr(tp3),
        'oz':     round(pos_oz, 2),
        'value':  round(pos_value, 2),
        'risk_$': round(dollar_risk, 2),
        'risk_%': round(dollar_risk / account_size * 100, 2),
    }

# ============================================================
# DISPLAY
# ============================================================

BIAS_COLORS = {
    'BEARISH_STRONG': '🔴🔴',
    'BEARISH':        '🔴',
    'NEUTRAL':        '⚪',
    'BULLISH':        '🟢',
    'BULLISH_STRONG': '🟢🟢',
}

def print_bias_header(bias, score, details, gs_info, season_info, gann_levels, pivots):
    icon = BIAS_COLORS.get(bias, '⚪')
    gs_ratio, gs_label, gs_adj = gs_info
    season_label, season_adj  = season_info

    print(f"\n{'='*72}")
    print(f"  {icon}  XAG MACRO TREND: {bias}  (score: {score:+.0f})  {icon}")
    print(f"{'='*72}")

    for tf, d in details.items():
        struct_icon = '📈' if d['structure'] == 'bullish' else \
                      ('📉' if d['structure'] == 'bearish' else '➡️')
        print(f"  [{tf}] Price: ${d['price']:.4f}  |  RSI: {d['rsi']}  |  "
              f"EMA50: ${d['ema50']:.4f}  |  Structure: {struct_icon}{d['structure'].upper()}  "
              f"|  Score: {d['tf_score']:+.1f}")

    # Gold/Silver ratio
    if gs_ratio:
        gs_icon = '🟡' if gs_adj > 0 else ('🔵' if gs_adj < 0 else '⚪')
        print(f"\n  {gs_icon} Gold/Silver Ratio: {gs_ratio:.1f}  [{gs_label}]  "
              f"({'bullish' if gs_adj > 0 else ('bearish' if gs_adj < 0 else 'neutral')} for XAG)")
    else:
        print(f"\n  ⚪ Gold/Silver Ratio: unavailable")

    # Seasonality
    s_icon = '📅'
    print(f"  {s_icon} Seasonality: {season_label}")

    # Gann levels summary (key ones)
    if gann_levels:
        key_labels = ['0/8', '2/8', '4/8', '6/8', '8/8']
        gann_str = '  |  '.join([f"{l}=${gann_levels[l]:.3f}" for l in key_labels if l in gann_levels])
        print(f"\n  📐 Gann 52W Levels: {gann_str}")

    # Daily pivots summary
    if pivots:
        piv_str = '  |  '.join([f"{k}=${v:.3f}" for k, v in pivots.items()])
        print(f"  📍 Daily Pivots: {piv_str}")

    print(f"{'='*72}\n")

def print_signal(sig, plan, tf, verbose=False):
    emoji     = '🟢' if sig['dir'] == 'BUY' else '🔴'
    confirm_tf = TF_PARAMS[tf]['confirm_tf']

    print(f"\n  {emoji} [{tf}] XAG/USDT — {sig['dir']}  |  Conf: {sig['conf']}%  |  {sig['desc']}")
    print(f"     Price: ${sig['price']:.4f}  |  RSI({tf}): {sig['rsi']}  |  "
          f"RSI({confirm_tf}): {sig['rsi_htf']}  |  MA50: ${sig['ma']:.4f}")
    print(f"     NW Band: Lower ${sig['lower']:.4f}  |  Mid ${sig['mid']:.4f}  |  Upper ${sig['upper']:.4f}")
    print(f"     ATR: ${sig['atr']:.4f}  |  ATR pct: {sig['atr_pct']:.0f}th  |  "
          f"Hurst: {sig['hurst']}  |  Structure: {sig['struct'].upper()}")
    if sig['sq_release']:
        print(f"     🔥 SQUEEZE RELEASE")
    elif sig['squeeze_on']:
        print(f"     📊 Squeeze ON (coiling)")
    print()
    print(f"     📍 Entry   : ${plan['entry']:.4f}")
    print(f"     🛑 Stop    : ${plan['stop']:.4f}  "
          f"(risk ${plan['risk_$']:.2f} = {plan['risk_%']:.1f}% of account)")
    print(f"     🎯 TP1     : ${plan['tp1']:.4f}  (+{plan['gain1']}%)  R:R {plan['rr1']:.1f}")
    print(f"     🎯 TP2     : ${plan['tp2']:.4f}  (+{plan['gain2']}%)  R:R {plan['rr2']:.1f}")
    print(f"     🎯 TP3     : ${plan['tp3']:.4f}  (+{plan['gain3']}%)  R:R {plan['rr3']:.1f}")
    print(f"     📊 Size    : {plan['oz']:.2f} oz XAG  (${plan['value']:,.2f})")

    if verbose:
        print(f"\n     Filter log:")
        for n in sig['notes']:
            print(f"       {n}")

def print_no_signals(tf, bias):
    trend_msg = {
        'BEARISH_STRONG': "Macro strongly bearish — waiting for confirmed SELL setups.",
        'BEARISH':        "Macro bearish — prioritizing SELL signals.",
        'NEUTRAL':        "Macro neutral — waiting for directional conviction.",
        'BULLISH':        "Macro bullish — prioritizing BUY signals.",
        'BULLISH_STRONG': "Macro strongly bullish — waiting for confirmed BUY setups.",
    }.get(bias, "No directional bias detected.")
    print(f"\n  ⏳ [{tf}] No qualifying XAG signals above threshold.")
    print(f"     {trend_msg}")

# ============================================================
# MAIN SCAN
# ============================================================

def run_scan(timeframes, account_size, risk_pct, use_bias, verbose, min_conf):
    print(f"\n{'='*72}")
    print(f"  🥈 XAG/USDT SILVER SCANNER — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"  Account: ${account_size:,.0f}  |  Risk: {risk_pct*100:.1f}%/trade  "
          f"|  Bias: {'ON' if use_bias else 'OFF'}")
    print(f"  Timeframes: {' + '.join(timeframes)}  |  Market: Binance USDT-M Futures")
    print(f"{'='*72}")

    # --- Step 1: Macro trend ---
    print("\n  🔍 Fetching XAG macro trend (Daily + Weekly) + Gold/Silver ratio...")
    bias, score, bias_details, gs_info, season_info = get_xag_trend_bias()

    # --- Step 2: Gann 8ths + Daily pivots (from daily OHLCV) ---
    print("  📐 Computing Gann 8ths from 52-week range...")
    df_daily = fetch_ohlcv('XAG/USDT', '1d', limit=400)
    gann_levels = get_gann_52w_levels(df_daily)
    pivots      = daily_pivots(df_daily)

    print_bias_header(bias, score, bias_details, gs_info, season_info, gann_levels, pivots)

    all_signals = []
    gs_ratio, gs_label, gs_adj = gs_info
    season_label, season_adj   = season_info

    # --- Step 3: Scan each timeframe ---
    for tf in timeframes:
        print(f"\n  ⏱️   Scanning XAG/USDT [{tf}]...")
        df = fetch_ohlcv('XAG/USDT', tf, limit=TF_PARAMS[tf]['lookback'] + 50)
        if df is None or len(df) < TF_PARAMS[tf]['lookback']:
            print(f"  ❌ [{tf}] Insufficient data")
            continue

        signals = detect_xag_signals(
            df, tf, bias, use_bias,
            gann_levels, pivots, gs_adj, season_adj
        )
        signals = [s for s in signals if s['conf'] >= min_conf]

        if not signals:
            print_no_signals(tf, bias)
        else:
            for sig in signals:
                plan = build_trade_plan(sig, tf, account_size, risk_pct)
                print_signal(sig, plan, tf, verbose=verbose)
                all_signals.append({'tf': tf, 'sig': sig, 'plan': plan})

    # --- Step 4: Summary ---
    print(f"\n{'='*72}")
    buys  = [x for x in all_signals if x['sig']['dir'] == 'BUY']
    sells = [x for x in all_signals if x['sig']['dir'] == 'SELL']
    print(f"  SUMMARY: {len(buys)} BUY  |  {len(sells)} SELL  |  Bias: {bias} ({score:+.0f})")

    if gs_info[0]:
        print(f"  G/S Ratio: {gs_info[0]:.1f} [{gs_info[1]}]  |  {season_info[0]}")

    if bias in ('BEARISH', 'BEARISH_STRONG') and buys and not sells:
        print(f"  ⚠️  BUY signals exist but macro is {bias}. Size down or skip.")
    if bias in ('BULLISH', 'BULLISH_STRONG') and sells and not buys:
        print(f"  ⚠️  SELL signals exist but macro is {bias}. Size down or skip.")

    print(f"{'='*72}\n")
    return all_signals

# ============================================================
# ENTRY POINT
# ============================================================

def main():
    args = parse_args()

    if args.timeframe:
        if args.timeframe not in ('1h', '4h'):
            print(f"❌ This scanner supports 1h and 4h only. Got: {args.timeframe}")
            sys.exit(1)
        timeframes = [args.timeframe]
    else:
        timeframes = ['1h', '4h']

    use_bias = not args.no_bias

    if args.loop > 0:
        print(f"🔁 Loop mode: scanning every {args.loop} minutes. Ctrl+C to stop.")
        while True:
            try:
                run_scan(timeframes, args.account, args.risk, use_bias, args.verbose, args.min_conf)
                print(f"  ⏰ Next scan in {args.loop}m. Sleeping...\n")
                time.sleep(args.loop * 60)
            except KeyboardInterrupt:
                print("\n👋 Scanner stopped.")
                break
    else:
        run_scan(timeframes, args.account, args.risk, use_bias, args.verbose, args.min_conf)

if __name__ == '__main__':
    main()
