#!/usr/bin/env python3
"""
BTC Intraday Scanner — 5m / 15m / 30m
Trend-aware: detects current BTC macro bias (Bearish/Bullish) from 1h+4h,
then weights signals accordingly so you only trade WITH the dominant move.

Usage:
    python btc_scanner.py                  # Scan all timeframes (5m, 15m, 30m)
    python btc_scanner.py -tf 5m           # 5m only
    python btc_scanner.py -tf 15m          # 15m only
    python btc_scanner.py --loop 5         # Repeat every 5 minutes
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
        description='BTC Intraday Scanner — 5m/15m/30m with trend bias',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('-tf', '--timeframe', type=str, default=None,
        help='Single timeframe: 5m, 15m or 30m. Omit to scan all.')
    parser.add_argument('--both', action='store_true',
        help='Explicitly scan all default timeframes (when -tf not set)')
    parser.add_argument('--loop', type=int, default=0,
        help='Repeat scan every N minutes (0 = single run)')
    parser.add_argument('--account', type=float, default=10000,
        help='Account size in USD (default: 10000)')
    parser.add_argument('--risk', type=float, default=0.01,
        help='Risk per trade as decimal (default: 0.01 = 1%%)')
    parser.add_argument('--no-bias', action='store_true',
        help='Disable trend-bias weighting (treat BUY and SELL equally)')
    parser.add_argument('-v', '--verbose', action='store_true',
        help='Show all filter details per signal')
    parser.add_argument('--min-conf', type=float, default=50.0,
        help='Minimum confidence to display a signal (default: 50)')
    return parser.parse_args()

# ============================================
# EXCHANGE (CACHED)
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

# ============================================
# INDICATORS
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
# TIMEFRAME PARAMS (5m ADDED & TUNED)
# ============================================

TF_PARAMS = {
    '5m': {
        'lookback': 120,       # Shorter window for hyper-localized 5m momentum
        'bandwidth': 2.5,      # Tighter bandwidth to fit compressed intraday distribution
        'multiplier': 1.6,     # Narrower multiplier targets fast edge touch/reversals
        'rsi_period': 7,       # Highly responsive RSI to catch momentum micro-turns
        'ma_period': 30,       # Faster trend-alignment boundary
        'confirm_tf': '1h',
        'stop_pct': 0.004,     # Tight 0.4% baseline stop-loss for 5m scalps
        'tp1_pct': 0.005,      # 0.5% Target 1
        'tp2_pct': 0.010,      # 1.0% Target 2
        'tp3_pct': 0.018,      # 1.8% Target 3
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
# SIGNAL DETECTION
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

    # 5. Price extreme beyond band (BUY)
    if lower > 0 and (current - lower) / current * 100 < -1.5:
        candidates.append({'dir': 'BUY', 'type': 'BUY_EXTREME', 'conf': 58,
                           'desc': f'Price {abs((current-lower)/current*100):.1f}% below lower band'})

    # 6. Price extreme beyond band (SELL)
    if upper > 0 and (upper - current) / current * 100 < -1.5:
        candidates.append({'dir': 'SELL', 'type': 'SELL_EXTREME', 'conf': 58,
                           'desc': f'Price {abs((upper-current)/current*100):.1f}% above upper band'})

    if not candidates:
        return []

    rsi_1h = None
    df1h = fetch_ohlcv('BTC/USDT', p['confirm_tf'], limit=60)
    if df1h is not None and len(df1h) >= 20:
        rsi_1h = rsi(df1h['close'].values[-30:], 14)

    signals = []
    for sig in candidates:
        c = sig['conf']
        notes = []
        skip = False

        # ── TREND BIAS ────────────────────────────────────────────────
        if use_bias:
            if bias in ('BEARISH_STRONG', 'BEARISH'):
                if sig['dir'] == 'SELL':
                    boost = 25 if bias == 'BEARISH_STRONG' else 15
                    c += boost
                    notes.append(f"✅ Bias {bias} confirms SELL +{boost}")
                elif sig['dir'] == 'BUY':
                    if rsi_val < 20:
                        c -= 10
                        notes.append(f"⚠️ Counter-trend BUY vs {bias} (RSI extreme, partial ok)")
                    else:
                        c -= 30
                        notes.append(f"❌ Counter-trend BUY vs {bias}")
                        if c < 50:
                            skip = True

            elif bias in ('BULLISH_STRONG', 'BULLISH'):
                if sig['dir'] == 'BUY':
                    boost = 25 if bias == 'BULLISH_STRONG' else 15
                    c += boost
                    notes.append(f"✅ Bias {bias} confirms BUY +{boost}")
                elif sig['dir'] == 'SELL':
                    if rsi_val > 80:
                        c -= 10
                        notes.append(f"⚠️ Counter-trend SELL vs {bias} (RSI extreme, partial ok)")
                    else:
                        c -= 30
                        notes.append(f"❌ Counter-trend SELL vs {bias}")
                        if c < 50:
                            skip = True
            else:
                notes.append("⚪ Bias NEUTRAL — equal weight")
        if skip:
            continue

        # ── VOLUME ────────────────────────────────────────────────────
        if len(vol) > 15:
            avg_vol = np.mean(vol[-15:])
            vr = vol[-1] / avg_vol if avg_vol > 0 else 1.0
            p5_chg = (current - close[-5]) / close[-5] * 100 if len(close) >= 5 else 0
            if vr > 1.8:
                if (sig['dir'] == 'BUY' and p5_chg < -2) or (sig['dir'] == 'SELL' and p5_chg > 2):
                    c -= 20
                    notes.append(f"⚠️ High vol {vr:.1f}x against signal")
                else:
                    c += 12
                    notes.append(f"🔥 Volume {vr:.1f}x avg — momentum")
            elif vr > 1.3:
                c += 5
                notes.append(f"📈 Volume {vr:.1f}x avg")
            else:
                notes.append(f"📉 Volume light {vr:.1f}x avg")

        # ── MA ALIGNMENT ──────────────────────────────────────────────
        if sig['dir'] == 'BUY':
            if current > ma:
                c += 8
                notes.append(f"✅ Above MA{p['ma_period']}")
            else:
                c -= 12
                notes.append(f"⚠️ Below MA{p['ma_period']}")
        else:
            if current < ma:
                c += 8
                notes.append(f"✅ Below MA{p['ma_period']}")
            else:
                c -= 12
                notes.append(f"⚠️ Above MA{p['ma_period']}")

        # ── 1H RSI CONFIRMATION ───────────────────────────────────────
        if rsi_1h is not None:
            if sig['dir'] == 'BUY':
                if rsi_1h < 35:
                    c += 15
                    notes.append(f"✅ 1h RSI {rsi_1h:.0f} oversold — confirms BUY")
                elif rsi_1h > 65:
                    c -= 20
                    notes.append(f"⚠️ 1h RSI {rsi_1h:.0f} overbought — BUY risky")
                    if rsi_1h > 75:
                        skip = True
                else:
                    notes.append(f"⚪ 1h RSI {rsi_1h:.0f}")
            else:
                if rsi_1h > 65:
                    c += 15
                    notes.append(f"✅ 1h RSI {rsi_1h:.0f} overbought — confirms SELL")
                elif rsi_1h < 35:
                    c -= 20
                    notes.append(f"⚠️ 1h RSI {rsi_1h:.0f} oversold — SELL risky")
                    if rsi_1h < 25:
                        skip = True
                else:
                    notes.append(f"⚪ 1h RSI {rsi_1h:.0f}")
        if skip:
            continue

        # ── SQUEEZE MOMENTUM ──────────────────────────────────────────
        if sq_release:
            if (sig['dir'] == 'BUY' and sq_bull) or (sig['dir'] == 'SELL' and not sq_bull):
                c += 18
                notes.append("🔥 Squeeze RELEASE in signal direction")
            else:
                c -= 10
                notes.append("⚠️ Squeeze release opposite direction")
        elif squeeze_on:
            notes.append("📊 Squeeze ON — energy coiling")
        else:
            c -= 5
            notes.append("⚪ No squeeze")

        # ── HURST / TREND QUALITY ─────────────────────────────────────
        if h_exp > 0.55:
            c += 8
            notes.append(f"✅ Hurst {h_exp:.2f} — trending")
        elif h_exp < 0.45:
            notes.append(f"⚪ Hurst {h_exp:.2f} — mean-reverting")
        else:
            notes.append(f"⚪ Hurst {h_exp:.2f} — random walk")

        # ── MARKET STRUCTURE ──────────────────────────────────────────
        if sig['dir'] == 'BUY' and struct == 'bullish':
            c += 10
            notes.append("✅ BTC structure: Higher Highs / Higher Lows")
        elif sig['dir'] == 'SELL' and struct == 'bearish':
            c += 10
            notes.append("✅ BTC structure: Lower Highs / Lower Lows")
        elif (sig['dir'] == 'BUY' and struct == 'bearish') or \
             (sig['dir'] == 'SELL' and struct == 'bullish'):
            c -= 10
            notes.append(f"⚠️ Structure {struct} contradicts signal")

        # ── ORDER BLOCK ───────────────────────────────────────────────
        ob_low, ob_high, ob_dir = ob_zone
        if ob_low is not None:
            in_ob = ob_low <= current <= ob_high * 1.01
            if in_ob and ob_dir == sig['dir'].lower() + 'ish':
                c += 10
                notes.append(f"✅ In {ob_dir} Order Block ${ob_low:.0f}-${ob_high:.0f}")
            elif in_ob:
                notes.append(f"⚠️ In {ob_dir} OB (opposite dir)")

        # ── FVG ───────────────────────────────────────────────────────
        fvg_lo, fvg_hi, fvg_dir = fvg_zone
        if fvg_lo is not None:
            in_fvg = fvg_lo <= current <= fvg_hi
            expected_fvg = 'bullish' if sig['dir'] == 'BUY' else 'bearish'
            if in_fvg and fvg_dir == expected_fvg:
                c += 10
                notes.append(f"✅ In {fvg_dir} FVG ${fvg_lo:.0f}-${fvg_hi:.0f}")

        # ── FINAL ─────────────────────────────────────────────────────
        c = float(np.clip(c, 0, 100))
        if c < 50:
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
            'squeeze_on': squeeze_on,
            'sq_release': sq_release,
            'hurst':   round(h_exp, 2),
            'struct':  struct,
        })

    signals.sort(key=lambda x: x['conf'], reverse=True)
    return signals

# ============================================
# ENTRY / EXIT LEVELS
# ============================================

def build_trade_plan(sig, tf, account_size, risk_pct):
    p = TF_PARAMS[tf]
    price = sig['price']
    direction = sig['dir']

    if direction == 'BUY':
        entry = max(price, sig['lower'] * 1.001)  # Tighter buffer entry for 5m
        stop  = min(price * (1 - p['stop_pct']), sig['lower'] * 0.999)
        tp1   = entry * (1 + p['tp1_pct'])
        tp2   = entry * (1 + p['tp2_pct'])
        tp3   = entry * (1 + p['tp3_pct'])
    else:
        entry = min(price, sig['upper'] * 0.999)  # Tighter buffer entry for 5m
        stop  = max(price * (1 + p['stop_pct']), sig['upper'] * 1.001)
        tp1   = entry * (1 - p['tp1_pct'])
        tp2   = entry * (1 - p['tp2_pct'])
        tp3   = entry * (1 - p['tp3_pct'])

    risk_per_unit = abs(entry - stop)
    dollar_risk   = account_size * risk_pct * (0.5 + sig['conf'] / 100 * 0.8)
    pos_units     = dollar_risk / risk_per_unit if risk_per_unit > 0 else 0
    pos_value     = pos_units * entry
    pos_value     = min(pos_value, account_size * 0.4)
    pos_units     = pos_value / entry

    def gain(t):
        return round(abs(t - entry) / entry * 100, 2)
    def rr(t):
        return round(abs(t - entry) / risk_per_unit, 2) if risk_per_unit > 0 else 0

    return {
        'entry':  round(entry, 2),
        'stop':   round(stop, 2),
        'tp1':    round(tp1, 2),
        'tp2':    round(tp2, 2),
        'tp3':    round(tp3, 2),
        'gain1':  gain(tp1),
        'gain2':  gain(tp2),
        'gain3':  gain(tp3),
        'rr1':    rr(tp1),
        'rr2':    rr(tp2),
        'rr3':    rr(tp3),
        'units':  round(pos_units, 6),
        'value':  round(pos_value, 2),
        'risk_$': round(dollar_risk, 2),
        'risk_%': round(dollar_risk / account_size * 100, 2),
    }

# ============================================
# DISPLAY
# ============================================

BIAS_COLORS = {
    'BEARISH_STRONG': '🔴🔴',
    'BEARISH':        '🔴',
    'NEUTRAL':        '⚪',
    'BULLISH':        '🟢',
    'BULLISH_STRONG': '🟢🟢',
}

def print_bias_header(bias, score, details):
    icon = BIAS_COLORS.get(bias, '⚪')
    print(f"\n{'='*70}")
    print(f"  {icon}  BTC MACRO TREND: {bias}  (score: {score:+.0f})  {icon}")
    print(f"{'='*70}")
    for tf, d in details.items():
        struct_icon = '📈' if d['structure'] == 'bullish' else ('📉' if d['structure'] == 'bearish' else '➡️')
        print(f"  [{tf}] Price: ${d['price']:,.2f} | RSI: {d['rsi']} | EMA50: ${d['ema50']:,.2f} | "
              f"Structure: {struct_icon}{d['structure'].upper()} | Score: {d['tf_score']:+.0f}")
    print(f"{'='*70}\n")

def print_signal(sig, plan, tf, verbose=False):
    emoji = '🟢' if sig['dir'] == 'BUY' else '🔴'
    print(f"\n  {emoji} [{tf}] BTC/USDT — {sig['dir']}  |  Conf: {sig['conf']}%  |  {sig['desc']}")
    print(f"     Price: ${sig['price']:,.2f}  |  RSI({tf}): {sig['rsi']}  |  RSI(1h): {sig['rsi_1h']}"
          f"  |  MA: ${sig['ma']:,.2f}")
    print(f"     NW Band: Lower ${sig['lower']:,.2f}  |  Mid ${sig['mid']:,.2f}  |  Upper ${sig['upper']:,.2f}")
    if sig['sq_release']:
        print(f"     🔥 SQUEEZE RELEASE  |  Hurst: {sig['hurst']}  |  Structure: {sig['struct'].upper()}")
    else:
        sq_str = 'ON (coiling)' if sig['squeeze_on'] else 'off'
        print(f"     Squeeze: {sq_str}  |  Hurst: {sig['hurst']}  |  Structure: {sig['struct'].upper()}")
    print()
    print(f"     📍 Entry   : ${plan['entry']:,.2f}")
    print(f"     🛑 Stop    : ${plan['stop']:,.2f}  (risk ${plan['risk_$']:.2f} = {plan['risk_%']:.1f}% of account)")
    print(f"     🎯 TP1     : ${plan['tp1']:,.2f}  (+{plan['gain1']}%)  R:R {plan['rr1']:.1f}")
    print(f"     🎯 TP2     : ${plan['tp2']:,.2f}  (+{plan['gain2']}%)  R:R {plan['rr2']:.1f}")
    print(f"     🎯 TP3     : ${plan['tp3']:,.2f}  (+{plan['gain3']}%)  R:R {plan['rr3']:.1f}")
    print(f"     📊 Size    : {plan['units']:.6f} BTC  (${plan['value']:,.2f})")
    if verbose:
        print(f"\n     Filter log:")
        for n in sig['notes']:
            print(f"       {n}")

def print_no_signals(tf, bias):
    trend_msg = {
        'BEARISH_STRONG': "Market is STRONGLY BEARISH — waiting for confirmed SELL setups.",
        'BEARISH':        "Market is BEARISH — prioritizing SELL signals.",
        'NEUTRAL':        "Market is NEUTRAL — waiting for directional conviction.",
        'BULLISH':        "Market is BULLISH — prioritizing BUY signals.",
        'BULLISH_STRONG': "Market is STRONGLY BULLISH — waiting for confirmed BUY setups.",
    }.get(bias, "No directional bias detected.")
    print(f"\n  ⏳ [{tf}] No qualifying BTC signals above threshold.")
    print(f"     {trend_msg}")

# ============================================
# MAIN SCAN
# ============================================

def run_scan(timeframes, account_size, risk_pct, use_bias, verbose, min_conf):
    print(f"\n{'='*70}")
    print(f"  📡 BTC INTRADAY SCANNER — {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"  Account: ${account_size:,}  |  Risk: {risk_pct*100:.1f}%/trade  |  Bias: {'ON' if use_bias else 'OFF'}")
    print(f"  Timeframes: {' + '.join(timeframes)}")
    print(f"{'='*70}")

    print("\n  🔍 Fetching BTC macro trend (1h + 4h)...")
    bias, score, bias_details = get_btc_trend_bias()
    print_bias_header(bias, score, bias_details)

    all_signals = []

    for tf in timeframes:
        print(f"\n  ⏱️  Scanning BTC/USDT [{tf}]...")
        df = fetch_ohlcv('BTC/USDT', tf, limit=TF_PARAMS[tf]['lookback'] + 50)
        if df is None or len(df) < TF_PARAMS[tf]['lookback']:
            print(f"  ❌ [{tf}] Insufficient data")
            continue

        signals = detect_btc_signals(df, tf, bias, use_bias=use_bias)
        signals = [s for s in signals if s['conf'] >= min_conf]

        if not signals:
            print_no_signals(tf, bias)
        else:
            for sig in signals:
                plan = build_trade_plan(sig, tf, account_size, risk_pct)
                print_signal(sig, plan, tf, verbose=verbose)
                all_signals.append({'tf': tf, 'sig': sig, 'plan': plan})

    print(f"\n{'='*70}")
    buys  = [x for x in all_signals if x['sig']['dir'] == 'BUY']
    sells = [x for x in all_signals if x['sig']['dir'] == 'SELL']
    print(f"  SUMMARY: {len(buys)} BUY  |  {len(sells)} SELL  |  Bias: {bias} ({score:+.0f})")

    if bias in ('BEARISH', 'BEARISH_STRONG') and buys and not sells:
        print(f"  ⚠️  BUY signals exist but macro trend is {bias}. Size down or skip.")
    if bias in ('BULLISH', 'BULLISH_STRONG') and sells and not buys:
        print(f"  ⚠️  SELL signals exist but macro trend is {bias}. Size down or skip.")

    print(f"{'='*70}\n")
    return all_signals

# ============================================
# ENTRY POINT
# ============================================

def main():
    args = parse_args()

    if args.timeframe:
        if args.timeframe not in ('5m', '15m', '30m'):
            print(f"❌ This scanner supports 5m, 15m, and 30m only. Got: {args.timeframe}")
            sys.exit(1)
        timeframes = [args.timeframe]
    else:
        timeframes = ['5m', '15m', '30m']   # Defaults to checking all three now

    use_bias = not args.no_bias

    if args.loop > 0:
        print(f"🔁 Loop mode: scanning every {args.loop} minutes. Ctrl+C to stop.")
        while True:
            try:
                run_scan(timeframes, args.account, args.risk, use_bias, args.verbose, args.min_conf)
                next_run = datetime.utcnow().strftime('%H:%M UTC')
                print(f"  ⏰ Next scan at +{args.loop}m from {next_run}. Sleeping...\n")
                time.sleep(args.loop * 60)
            except KeyboardInterrupt:
                print("\n👋 Scanner stopped.")
                break
    else:
        run_scan(timeframes, args.account, args.risk, use_bias, args.verbose, args.min_conf)

if __name__ == '__main__':
    main()
