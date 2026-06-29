# XAG/USDT Silver Scanner

A Python intraday scanner for **XAG/USDT** (Silver perpetual futures) on Binance USDT-M.
Signals on 1h and 4h timeframes, filtered against a macro trend bias derived from Daily + Weekly candles.
Incorporates Gann 8ths S/R levels, Gold/Silver ratio bias, daily pivot points, and an ATR volatility regime filter.

---

## Requirements

```
pip install ccxt pandas numpy
```

Python 3.8+. No API key required — all data is fetched from Binance public endpoints.

---

## Quick Start

```bash
# Scan both 1h and 4h (default)
python xag_scanner.py

# Single timeframe
python xag_scanner.py -tf 1h
python xag_scanner.py -tf 4h

# Run on a loop every 15 minutes
python xag_scanner.py --loop 15

# Verbose output (show all filter notes per signal)
python xag_scanner.py -v

# Only show signals with ≥ 65% confidence
python xag_scanner.py --min-conf 65

# Set account size and risk per trade
python xag_scanner.py --account 25000 --risk 0.015

# Disable macro trend bias (treat BUY and SELL equally)
python xag_scanner.py --no-bias
```

---

## CLI Reference

| Flag | Default | Description |
|---|---|---|
| `-tf`, `--timeframe` | both | Timeframe to scan: `1h` or `4h`. Omit for both. |
| `--loop N` | `0` | Repeat scan every N minutes. `0` = single run. |
| `--account` | `10000` | Account size in USD, used for position sizing. |
| `--risk` | `0.01` | Risk per trade as a decimal (0.01 = 1%). |
| `--no-bias` | off | Disables macro trend-bias filter; all signals equal weight. |
| `--min-conf` | `50` | Minimum confidence % to display a signal. |
| `-v`, `--verbose` | off | Print all filter notes for each signal. |

---

## Market

| Property | Value |
|---|---|
| Exchange | Binance USDT-M Futures |
| Symbol | `XAG/USDT` (Silver perpetual) |
| Entry timeframes | 1h, 4h |
| Macro bias timeframes | Daily (1d), Weekly (1w) |
| Confirmation RSI | 4h (for 1h signals), Daily (for 4h signals) |

> **Note:** XAG/USDT is a futures perpetual, not spot. The scanner uses `ccxt.binance` with `defaultType: future`. No position or margin settings are touched — it is read-only.

---

## Architecture

The scan runs in four steps each cycle:

1. **Macro trend bias** — fetches Daily and Weekly candles, computes a composite score from RSI, EMA50 deviation, short-term momentum, and market structure. Adjusted by the live Gold/Silver ratio and a seasonality modifier. Outputs one of: `BEARISH_STRONG / BEARISH / NEUTRAL / BULLISH / BULLISH_STRONG`.

2. **Reference levels** — fetches the 52-week daily OHLCV to compute Gann 8ths levels, and yesterday's OHLC to compute classic daily pivot points (PP, R1–R3, S1–S3).

3. **Signal detection** — scans the entry timeframe(s), runs each raw candidate through the full filter stack, and scores it 0–100.

4. **Trade plan** — builds entry, stop, and three TP levels for each qualifying signal, with position size in oz.

---

## Indicators

### Nadaraya-Watson Envelope
Gaussian-kernel weighted smoothing of price, producing a mid line with upper and lower bands scaled by mean absolute error. Primary signal trigger — crossovers and extremes relative to the bands generate raw candidates.

| Parameter | 1h | 4h |
|---|---|---|
| Bandwidth (h) | 5.0 | 7.0 |
| Multiplier | 2.0 | 2.5 |
| Lookback | 150 bars | 200 bars |

### RSI (Wilder Smoothing)
Wilder's smoothed RSI. Used on the entry timeframe for raw signal generation, and on the confirmation timeframe as a filter.

| Parameter | 1h | 4h |
|---|---|---|
| Period | 14 | 14 |
| Confirmation TF | 4h RSI | Daily RSI |

### Squeeze Momentum
Bollinger Bands inside Keltner Channel = squeeze (energy coiling). Release = breakout imminent. Signals in the direction of a squeeze release get a +18 confidence boost.

### Hurst Exponent
Computed over the last 80 bars using log-return variance ratio.

| Value | Regime |
|---|---|
| > 0.55 | Trending — momentum trades preferred |
| 0.45–0.55 | Random walk |
| < 0.45 | Mean-reverting — band-fade trades preferred |

### Market Structure
Detects swing highs and lows (swing window = 5 bars) to classify: Higher Highs + Higher Lows = `bullish`, Lower Highs + Lower Lows = `bearish`, otherwise `neutral`.

### Order Blocks & Fair Value Gaps (SMC)
Built-in Smart Money Concepts — no external package required.

- **Order Block**: last candle before a 1.8× average-move impulse.
- **FVG**: 3-bar price gap (imbalance between bar[i].high and bar[i+2].low, or vice versa).

---

## Gann 8ths

The 52-week high and low are divided into 8 equal parts. These levels act as natural support and resistance in Gann theory. They are computed fresh each run from the rolling 365-day daily OHLCV.

```
0/8  = 52-week low         (STRONG)
1/8  = first eighth        (MODERATE)
2/8  = 25%                 (MEDIUM)
3/8  = 37.5%               (MODERATE)
4/8  = 50%   ← key level   (STRONG)
5/8  = 62.5%               (MODERATE)
6/8  = 75%                 (MEDIUM)
7/8  = 87.5%               (MODERATE)
8/8  = 52-week high        (STRONG)
```

**Confidence adjustments when price is within 0.4% of a level:**

| Strength | Boost |
|---|---|
| STRONG (0/8, 4/8, 8/8) | +18 |
| MEDIUM (2/8, 6/8) | +10 |
| MODERATE (all others) | +5 |

The 4/8 (50%) is considered the most powerful level in Gann theory — price either firmly rejects or accelerates through it.

---

## Daily Pivot Points

Classic floor-trader pivots calculated from the **previous day's** high, low, and close:

```
PP = (H + L + C) / 3
R1 = 2×PP − L      S1 = 2×PP − H
R2 = PP + (H − L)  S2 = PP − (H − L)
R3 = H + 2×(PP−L)  S3 = L − 2×(H−PP)
```

If price is within 0.4% of a pivot that confirms the signal direction (e.g. price near S1 on a BUY), confidence gets +12. A neutral proximity adds +5.

---

## Gold/Silver Ratio

The live ratio (XAU price ÷ XAG price) is fetched daily and used as a macro input.

| Ratio | Label | Macro Adjustment |
|---|---|---|
| > 90 | SILVER_CHEAP_EXTREME | +20 bullish bias |
| 80–90 | SILVER_CHEAP | +10 bullish bias |
| 70–80 | NEUTRAL | 0 |
| 60–70 | SILVER_EXPENSIVE | −10 bearish bias |
| < 60 | SILVER_EXPENSIVE_EXTREME | −20 bearish bias |

Applied at 50% weight in the macro score, and again as a direct ±5–10 confidence modifier on individual signals.

> A high ratio (silver cheap relative to gold) is historically associated with mean-reversion rallies in silver. It does not guarantee direction — treat it as a tailwind, not a trigger.

---

## Seasonality

A soft modifier based on calendar month, reflecting historical silver demand patterns:

| Period | Label | Adjustment |
|---|---|---|
| Jan–Apr | SEASONALLY_BULLISH (Q1) | +8 |
| May–Jun | SEASONALLY_NEUTRAL (Q2) | 0 |
| Jul–Sep | SEASONALLY_WEAK (Q3) | −8 |
| Oct–Dec | SEASONALLY_RECOVERING (Q4) | +5 |

Applied at 30% weight in the macro score and as a soft ±4 modifier on signals. Seasonality alone will not generate or kill a signal — it nudges confidence at the margin.

---

## ATR Volatility Regime

ATR is computed and expressed as a percentile of the last 100 ATR readings on the same timeframe. This filters out signals generated during silver's characteristic low-vol compression phases.

| ATR Percentile | Regime | Effect on Confidence |
|---|---|---|
| < 20th | Very low vol | −20 (may skip signal entirely) |
| 20–35th | Subdued | −8 |
| 35–85th | Normal | 0 |
| > 85th (with momentum) | High vol, confirmed | +8 |
| > 85th (against momentum) | High vol, exhaustion risk | note only |

---

## Signal Generation

Raw candidates are generated from six conditions against the NW envelope:

| Type | Condition | Base Conf |
|---|---|---|
| `BUY_CROSS_LOWER` | Price crosses above lower band, RSI < 55 | 50–80 |
| `SELL_CROSS_UPPER` | Price crosses below upper band, RSI > 45 | 50–80 |
| `BUY_OVERSOLD` | RSI < 30 and price ≤ lower band × 1.02 | 35–75 |
| `SELL_OVERBOUGHT` | RSI > 70 and price ≥ upper band × 0.98 | 35–75 |
| `BUY_EXTREME` | Price > 1.5% below lower band | 58 |
| `SELL_EXTREME` | Price > 1.5% above upper band | 58 |

Each candidate then passes through the filter stack:

```
ATR regime → Macro bias → G/S ratio → Seasonality →
Gann levels → Daily pivots → Volume → MA alignment →
HTF RSI → Squeeze → Hurst → Market structure → OB/FVG
```

Final confidence is clamped 0–100. Any signal below 50 after filtering is discarded.

---

## Macro Trend Bias

Composite score from Daily and Weekly candles (equal 50/50 weight):

```
tf_score = RSI deviation (×0.30)
         + EMA50 deviation (×0.30)
         + 5-bar momentum (×0.25)
         + Market structure score (×0.15)

total = tf_score_daily×0.50 + tf_score_weekly×0.50
      + G/S ratio adjustment×0.50
      + Seasonality adjustment×0.30
```

| Score | Bias |
|---|---|
| ≥ +60 | BULLISH_STRONG |
| +20 to +60 | BULLISH |
| −20 to +20 | NEUTRAL |
| −60 to −20 | BEARISH |
| ≤ −60 | BEARISH_STRONG |

When bias is active (default), counter-trend signals lose 28 confidence points and are dropped if they fall below 50. Extreme RSI readings (< 25 for BUY in bear bias, > 78 for SELL in bull bias) allow counter-trend signals through with a reduced −8 penalty.

---

## Trade Plan

Entry, stop, and three take-profit levels are calculated per signal.

**1h parameters:**

| Parameter | Value |
|---|---|
| Stop | 1.0% from entry |
| TP1 | 1.0% |
| TP2 | 2.0% |
| TP3 | 3.5% |

**4h parameters:**

| Parameter | Value |
|---|---|
| Stop | 1.8% from entry |
| TP1 | 1.8% |
| TP2 | 3.5% |
| TP3 | 6.0% |

Position size (in oz) is calculated from account size × risk % × a confidence scalar (higher-confidence signals are sized slightly larger). Maximum per-trade allocation is capped at 40% of account.

---

## Sample Output

```
========================================================================
  🥈 XAG/USDT SILVER SCANNER — 2025-09-12 08:30 UTC
  Account: $10,000  |  Risk: 1.0%/trade  |  Bias: ON
  Timeframes: 1h + 4h  |  Market: Binance USDT-M Futures
========================================================================

  🔍 Fetching XAG macro trend (Daily + Weekly) + Gold/Silver ratio...
  📐 Computing Gann 8ths from 52-week range...

========================================================================
  🟢🟢  XAG MACRO TREND: BULLISH_STRONG  (score: +64.2)  🟢🟢
========================================================================
  [1d] Price: $30.4100  |  RSI: 58.3  |  EMA50: $28.9200  |  Structure: 📈BULLISH  |  Score: +52.1
  [1w] Price: $30.4100  |  RSI: 61.7  |  EMA50: $27.1500  |  Structure: 📈BULLISH  |  Score: +71.4

  🟡 Gold/Silver Ratio: 87.3  [SILVER_CHEAP]  (bullish for XAG)
  📅 Seasonality: SEASONALLY_WEAK (Q3)

  📐 Gann 52W Levels: 0/8=$24.150  |  2/8=$26.525  |  4/8=$28.900  |  6/8=$31.275  |  8/8=$33.650
  📍 Daily Pivots: PP=$30.283  |  R1=$31.067  |  R2=$31.583  |  ...  |  S1=$29.767
========================================================================


  ⏱️   Scanning XAG/USDT [1h]...

  🟢 [1h] XAG/USDT — BUY  |  Conf: 78.5%  |  Cross above lower NW band (RSI 38)
     Price: $30.1200  |  RSI(1h): 38.0  |  RSI(4h): 42.0  |  MA50: $29.8800
     NW Band: Lower $29.9800  |  Mid $30.3500  |  Upper $30.7200
     ATR: $0.1840  |  ATR pct: 62nd  |  Hurst: 0.57  |  Structure: BULLISH
     📊 Squeeze ON (coiling)

     📍 Entry   : $30.1800
     🛑 Stop    : $29.8800  (risk $72.40 = 0.7% of account)
     🎯 TP1     : $30.4800  (+0.993%)  R:R 1.0
     🎯 TP2     : $30.7800  (+1.987%)  R:R 2.0
     🎯 TP3     : $31.2300  (+3.477%)  R:R 3.5
     📊 Size    : 24.13 oz XAG  ($7,239.77)
```

---

## Scheduling

**Cron — scan every hour on the hour:**
```bash
0 * * * * cd /path/to/scanner && python xag_scanner.py --min-conf 60 >> logs/xag.log 2>&1
```

**Cron — 4h only, every 4 hours:**
```bash
0 0,4,8,12,16,20 * * * cd /path/to/scanner && python xag_scanner.py -tf 4h -v >> logs/xag_4h.log 2>&1
```

**Loop mode (runs in foreground):**
```bash
python xag_scanner.py --loop 60 --min-conf 60 -v
```

---

## Differences from btc_scanner.py

| Property | btc_scanner.py | xag_scanner.py |
|---|---|---|
| Asset | BTC/USDT spot | XAG/USDT perpetual futures |
| Exchange market | Spot | USDT-M Futures |
| Entry timeframes | 15m, 30m | 1h, 4h |
| Macro bias TFs | 1h + 4h | Daily + Weekly |
| HTF RSI confirmation | 1h | 4h (for 1h), Daily (for 4h) |
| NW bandwidth | 3.0 / 4.0 | 5.0 / 7.0 |
| RSI period | 8 / 10 | 14 / 14 |
| Stop % | 0.8% / 1.2% | 1.0% / 1.8% |
| TP3 % | 2.5% / 3.5% | 3.5% / 6.0% |
| Position unit | BTC | oz (troy ounces) |
| Gann 8ths | ✗ | ✅ 52-week range |
| Gold/Silver ratio | ✗ | ✅ live XAU/XAG |
| Daily pivot points | ✗ | ✅ PP, R1–R3, S1–S3 |
| ATR percentile regime | ✗ | ✅ 100-bar lookback |
| Seasonality modifier | ✗ | ✅ calendar-based |

---

## Limitations

- **Futures only.** XAG/USDT does not exist as a Binance spot pair. If Binance delist or suspend the XAG perpetual, the scanner will fail at fetch.
- **Gann levels are static within a run.** The 52-week range is computed once per scan cycle. On a loop, they refresh each iteration.
- **Seasonality is calendar-based.** Historical seasonal patterns can and do fail in trending years. Use as a tiebreaker, not a primary signal.
- **Gold/Silver ratio is a long-horizon indicator.** It should not override short-term technicals — the scanner applies it at reduced weight for this reason.
- **No live order execution.** This is a signal scanner only. All output is informational.

---

## Version

| Version | Date | Notes |
|---|---|---|
| 1.0.0 | 2025 | Initial release. Ported from btc_scanner.py. Added Gann 8ths, G/S ratio, daily pivots, ATR regime, seasonality. |
