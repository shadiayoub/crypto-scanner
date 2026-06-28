# 📊 Multi-Asset Scanner with Position Sizing

A professional-grade cryptocurrency and metals scanner powered by the **Nadaraya-Watson Envelope** indicator, designed for Breakout Prop and similar prop firm trading environments.

---

## 📁 Repository Structure

```
scanner-bot/
├── scanner.py              # Multi-asset scanner (all timeframes via CLI)
├── btc-scanner.py          # BTC-focused intraday scanner (15m/30m, trend-aware)
├── usage.txt               # Quick reference for commands
├── README.md               # This file
└── logs.txt                # Optional log file
```

---

## 🎯 Overview

This repository contains two scanners:

| Scanner | Focus | Best For |
|---------|-------|----------|
| `scanner.py` | 53 assets (51 crypto + 2 metals) | Swing/position trading, multi-asset scanning |
| `btc-scanner.py` | BTC/USDT only | Intraday trading, riding the dominant BTC trend |

Both use the **Nadaraya-Watson Envelope** as their core signal engine, with layered confirmation filters and automated position sizing.

---

## 🚀 BTC Intraday Scanner (`btc-scanner.py`)

### Overview

Purpose-built for catching BTC's **intraday directional moves** on 15m and 30m timeframes. The key design principle: detect the macro trend first (from 1h + 4h data), then only surface signals that **trade with that trend** — suppressing counter-trend noise.

In a bearish market (like current BTC conditions), the scanner prioritises SELL signals and applies a confidence penalty to counter-trend BUYs, unless RSI is at extreme oversold levels (< 20) that suggest a bounce.

### Trend Bias System

Before scanning for entries, the scanner reads 1h and 4h BTC candles and calculates a composite trend score from:

- **RSI** vs 50 midpoint
- **Price vs EMA50** (above/below)
- **Short-term momentum** (5-bar change)
- **Market structure** (Higher Highs/Lows or Lower Highs/Lows)

The 4h reading is weighted 60%, 1h weighted 40%, producing a score from -100 (strongly bearish) to +100 (strongly bullish).

| Bias | Score | Effect on Signals |
|------|-------|-------------------|
| `BEARISH_STRONG` | ≤ -60 | SELL +25% conf, BUY -30% (suppressed unless RSI < 20) |
| `BEARISH` | -20 to -60 | SELL +15% conf, BUY -30% (suppressed unless RSI < 20) |
| `NEUTRAL` | -20 to +20 | All signals equal weight |
| `BULLISH` | +20 to +60 | BUY +15% conf, SELL -30% (suppressed unless RSI > 80) |
| `BULLISH_STRONG` | ≥ +60 | BUY +25% conf, SELL -30% (suppressed unless RSI > 80) |

### Signal Types (15m / 30m)

| Signal | Condition |
|--------|-----------|
| `BUY_CROSS_LOWER` | Price crosses above lower NW band + RSI < 50 |
| `SELL_CROSS_UPPER` | Price crosses below upper NW band + RSI > 50 |
| `BUY_OVERSOLD` | RSI < 30 + price near lower band |
| `SELL_OVERBOUGHT` | RSI > 70 + price near upper band |
| `BUY_EXTREME` | Price > 1.5% below lower band |
| `SELL_EXTREME` | Price > 1.5% above upper band |

### Filter Stack

Signals pass through 8 filters after the base signal fires. Each adjusts confidence up or down:

| Filter | Boosts | Penalises |
|--------|--------|-----------|
| **Trend Bias** | Signal matches macro trend | Counter-trend signal |
| **Volume** | > 1.8x avg with direction match | > 1.8x avg against signal direction |
| **MA Alignment** | Price above MA (BUY) / below MA (SELL) | Opposite |
| **1h RSI Confirmation** | Oversold on 1h for BUY / overbought for SELL | Contradicts signal direction |
| **Squeeze Momentum** | Squeeze release in signal direction | Release in opposite direction |
| **Hurst Exponent** | H > 0.55 (trending market) | — |
| **Market Structure** | HH/HL for BUY / LH/LL for SELL | Structure contradicts signal |
| **Order Block / FVG** | Price in matching OB or FVG zone | — |

Signals below **50% confidence** are dropped.

### Parameters

| Timeframe | Lookback | Bandwidth | Multiplier | RSI | MA | Stop | TP1/TP2/TP3 |
|-----------|----------|-----------|------------|-----|-----|------|-------------|
| **15m** | 150 | 3.0 | 1.8 | 8 | 50 | 0.8% | 0.8%/1.5%/2.5% |
| **30m** | 200 | 4.0 | 2.2 | 10 | 100 | 1.2% | 1.2%/2.2%/3.5% |

Tighter than `scanner.py` — sized for BTC's intraday volatility, not swing moves.

### Usage

```bash
# Both 15m and 30m (default)
python btc-scanner.py

# Single timeframe
python btc-scanner.py -tf 15m
python btc-scanner.py -tf 30m

# Loop mode — repeat every N minutes (ideal for live monitoring)
python btc-scanner.py --loop 5
python btc-scanner.py -tf 15m --loop 15

# Custom account and risk
python btc-scanner.py --account 5000 --risk 0.01

# Only show high-confidence signals
python btc-scanner.py --min-conf 65

# Verbose: show full filter reasoning per signal
python btc-scanner.py -v

# Disable trend bias (treat BUY and SELL equally)
python btc-scanner.py --no-bias
```

### Command-Line Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `-tf` | Timeframe: `15m` or `30m`. Omit for both. | both |
| `--loop N` | Repeat every N minutes. 0 = single run. | 0 |
| `--account` | Account size in USD | 10000 |
| `--risk` | Risk per trade as decimal (0.01 = 1%) | 0.01 |
| `--min-conf` | Minimum confidence to display a signal | 50 |
| `--no-bias` | Disable trend-bias weighting | False |
| `-v, --verbose` | Show all filter notes per signal | False |

### Sample Output

```
======================================================================
  📡 BTC INTRADAY SCANNER — 2026-06-28 09:15 UTC
  Account: $10,000  |  Risk: 1.0%/trade  |  Bias: ON
  Timeframes: 15m + 30m
======================================================================

  🔍 Fetching BTC macro trend (1h + 4h)...

======================================================================
  🔴🔴  BTC MACRO TREND: BEARISH_STRONG  (score: -72)  🔴🔴
======================================================================
  [1h] Price: $104,200.00 | RSI: 38.2 | EMA50: $107,450.00 | Structure: 📉BEARISH | Score: -55
  [4h] Price: $104,200.00 | RSI: 31.5 | EMA50: $110,200.00 | Structure: 📉BEARISH | Score: -80
======================================================================

  ⏱️  Scanning BTC/USDT [15m]...

  🔴 [15m] BTC/USDT — SELL  |  Conf: 78.5%  |  Cross below upper band (RSI 68)
     Price: $104,850.00  |  RSI(15m): 68.0  |  RSI(1h): 38.2  |  MA: $104,200.00
     NW Band: Lower $103,100  |  Mid $104,000  |  Upper $104,800

     📍 Entry   : $104,796.00
     🛑 Stop    : $105,645.00  (risk $87.00 = 0.9% of account)
     🎯 TP1     : $103,938.00  (+0.82%)  R:R 1.0
     🎯 TP2     : $102,700.00  (+2.0%)   R:R 2.4
     🎯 TP3     : $101,076.00  (+3.5%)   R:R 4.2
     📊 Size    : 0.009600 BTC  ($1,006.00)
```

### Scheduling (Cron)

```bash
# 15m scan every 15 minutes
*/15 * * * * cd /path/to/scanner && python btc-scanner.py -tf 15m >> logs.txt

# 30m scan every 30 minutes
*/30 * * * * cd /path/to/scanner && python btc-scanner.py -tf 30m >> logs.txt

# Both, every 15 minutes (recommended)
*/15 * * * * cd /path/to/scanner && python btc-scanner.py >> logs.txt
```

Or use the built-in loop:

```bash
# Runs continuously in a screen/tmux session
python btc-scanner.py --loop 15
```

---

## 📊 Multi-Asset Scanner (`scanner.py`)

### Overview

Scans 53 assets (51 cryptocurrencies + Gold and Silver perpetuals) across any timeframe from 1m to 1d. Mean-reversion focused, with Squeeze Momentum, SMRE statistical filters, and built-in Smart Money Concepts (BOS, CHoCH, Order Blocks, FVGs).

*Note: The **BTC filter** state is displayed for context only and does not affect signal generation.*

### Features

- **Nadaraya-Watson Envelope** (adaptive bandwidth per timeframe)
- **RSI** for momentum confirmation (period adjusts per timeframe)
- **5 Signal Types**: Crossover, Oversold/Overbought Bounce, Envelope Extreme
- **58+ Assets**: Top cryptocurrencies + Gold (XAU) & Silver (XAG) futures

### Filter System

| Filter / Indicator | Impact | Description |
|--------------------|--------|-------------|
| **Nadaraya-Watson Envelope** | Core | Primary mean-reversion boundary detection |
| **RSI** | Core | Momentum confirmation |
| **Volume** | +6-12% | Confirms unusual trading activity with direction analysis |
| **MA Trend** | +8% or -15% | Aligns signals with trend (MA50 or MA200 depending on TF) |
| **Timeframe Confirmation** | +15% or -15% | Higher/lower timeframe alignment |
| **Squeeze Momentum** | Modifies | Identifies consolidation before breakout |
| **SMRE Statistical Filters** | Modifies | Z-score, Hurst exponent, volatility regime |
| **RSI Divergence** | -20% | Detects RSI/Price mismatches |
| **Price Velocity** | -15% | Filters capitulation/blow-off moves |

### SMC Features

#### Market Structure Filter

| Structure | BUY Signal Impact | SELL Signal Impact |
|-----------|-------------------|--------------------|
| Bullish (BOS UP) | +10% confidence | -15% confidence |
| Bearish (BOS DOWN) | -15% confidence | +10% confidence |
| Neutral | No adjustment | No adjustment |

#### Order Block Filter
Identifies the last opposing candle before a strong move. Adds +8% confidence if price is in an OB zone.

#### Fair Value Gap Filter
Identifies 3-candle institutional gaps. Adds +10% confidence if price is in an FVG zone.

### Usage

```bash
# Default: 1h timeframe, all 53 assets
python scanner.py

# 15-minute timeframe (day trading)
python scanner.py -tf 15m

# 5-minute timeframe (scalping)
python scanner.py -tf 5m

# 4-hour timeframe (swing trading)
python scanner.py -tf 4h

# 1-day timeframe (position trading)
python scanner.py -tf 1d

# Verbose mode (shows all symbols)
python scanner.py -tf 15m -v

# Custom account size and risk
python scanner.py -tf 30m --account-size 50000 --risk 0.015

# Disable individual filters
python scanner.py --no-squeeze --no-smre --no-smc

# Help
python scanner.py --help
```

### Command-Line Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `-tf, --timeframe` | Timeframe to scan | `1h` |
| `-v, --verbose` | Show all symbols, not just signals | `False` |
| `--list-timeframes` | Print available timeframes and exit | — |
| `--account-size` | Account size in USD | `10000` |
| `--risk` | Risk per trade (decimal, e.g. 0.02 = 2%) | `0.02` |
| `--max-positions` | Max concurrent positions | `3` |
| `--no-squeeze` | Disable Squeeze Momentum filter | `False` |
| `--no-smre` | Disable SMRE Statistical filter | `False` |
| `--no-smc` | Disable Smart Money Concepts filter | `False` |

### Timeframe Parameters

| Timeframe | Lookback | Bandwidth | Multiplier | RSI | MA | Risk | Targets |
|-----------|----------|-----------|------------|-----|-----|------|---------|
| **1m-15m** | 200 | 3.5 | 2.0 | 8 | 50 | 1.0% | 1.5%/2.5%/4% |
| **30m** | 300 | 4.5 | 2.5 | 10 | 100 | 1.5% | 2%/3.5%/5% |
| **1h** | 500 | 6.0 | 3.0 | 14 | 200 | 2.0% | 3%/5%/7% |
| **2h** | 500 | 8.0 | 4.0 | 14 | 200 | 2.0% | 4%/7%/10% |
| **4h-6h** | 500 | 7.0 | 3.5 | 14 | 200 | 2.0% | 4%/7%/10% |
| **12h-1d** | 500 | 8.0 | 4.0 | 14 | 200 | 2.0% | 4%/7%/10% |

### Scheduling Examples

```bash
# Scalping (5m) - Run every 5 minutes
*/5 * * * * cd /path/to/scanner && python scanner.py -tf 5m

# Day trading (15m) - Run every 15 minutes
*/15 * * * * cd /path/to/scanner && python scanner.py -tf 15m

# Swing trading (1h) - Run every 2 hours
0 */2 * * * cd /path/to/scanner && python scanner.py -tf 1h

# Position trading (4h) - Run every 4 hours
0 */4 * * * cd /path/to/scanner && python scanner.py -tf 4h
```

---

## 📦 Installation

```bash
git clone https://github.com/shadiayoub/crypto-scanner
cd scanner-bot
pip install ccxt pandas numpy
```

No additional setup required. Both scanners are pre-configured with optimised parameters.

---

## 📈 Signal Types (Both Scanners)

| Signal | Condition | Description |
|--------|-----------|-------------|
| **BUY_CROSS** | Price crosses above lower band + RSI < 45-50 | Bullish reversal confirmed |
| **SELL_CROSS** | Price crosses below upper band + RSI > 50-55 | Bearish reversal confirmed |
| **BUY_OVERSOLD** | RSI < 30-35 + Price near lower band | Oversold bounce opportunity |
| **SELL_OVERBOUGHT** | RSI > 65-70 + Price near upper band | Overbought drop opportunity |
| **BUY_EXTREME** | Price > 1.5-2% below lower band | Capitulation level |
| **SELL_EXTREME** | Price > 1.5-2% above upper band | Exhaustion level |

---

## 🧪 Supported Assets

### `btc-scanner.py`
- **BTC/USDT** (spot, 15m and 30m only)

### `scanner.py` — Cryptocurrencies (51)
BTC, ETH, SOL, XRP, DOGE, LINK, AVAX, SUI, NEAR, WIF, ARB, OP, AAVE, ADA, AIXBT, ALGO, APT, ASTER, ATOM, BCH, BNB, BONK, CRV, DOT, ETC, FIL, HBAR, INJ, JTO, JUP, KAITO, LDO, LIT, LTC, ONDO, ORDI, PENGU, PNUT, POL, PUMP, RENDER, S, SHIB, STX, TAO, TIA, TRX, UNI, VIRTUAL, WLD, ZEC

### `scanner.py` — Precious Metals (2)
- **XAU/USDT:USDT** (Gold Perpetual)
- **XAG/USDT:USDT** (Silver Perpetual)

---

## 🔧 Troubleshooting

### Issue: "Insufficient data" for metals
**Solution**: Metals (XAU/XAG) require futures data. `scanner.py` automatically uses `ccxt.binanceusdm` for futures symbols.

### Issue: Rate limit errors
**Solution**: Both scanners use `enableRateLimit: True`. Reduce scan frequency if errors persist.

### Issue: No signals detected
**Solution**:
- Try a different timeframe
- Use `-v` (scanner.py) or `--min-conf 40` (btc-scanner.py) to see near-miss signals
- In trending markets, `btc-scanner.py --no-bias` will show all signals regardless of trend

### Issue: Too many signals
**Solution**:
- Raise `--min-conf` (e.g. `--min-conf 65`)
- Use a longer timeframe

---

## 📊 Version History

| Version | File | Changes |
|---------|------|---------|
| **v4.0** | `btc-scanner.py` | New BTC-only intraday scanner; trend bias system (1h+4h macro scoring); 15m/30m optimised parameters; loop mode; tighter stops sized for BTC intraday volatility |
| **v3.1** | `scanner.py` | Bug fixes: Wilder's RSI smoothing, corrected Hurst exponent, squeeze release logic, BUY_/SELL_ extreme signal prefixes, directional HTF confirmation, removed broken smc-toolkit dependency (built-in SMC), USDT symbol normalisation, UTC timestamp |
| **v3.0** | `scanner.py` | Unified scanner with CLI arguments, 3 TP targets, enhanced filters |
| **v2.0** | `scanner.py` | Short-term version added (5m-30m) |
| **v1.0** | `scanner.py` | Long-term version (1H) |

---

## 📝 License

This project is for educational purposes only and is provided under the MIT License. Trading involves significant risk.

---

## 🙏 Acknowledgements

- **LuxAlgo** for the original Nadaraya-Watson Envelope indicator
- **ccxt** for exchange connectivity
- **Breakout Prop** for the symbol list

---

## 🚀 Next Steps

1. **Telegram Alerts**: Push notifications when signals appear
2. **Backtesting Engine**: Test strategy performance historically
3. **Auto-Execution**: Connect to Binance API for automated trading
4. **Web Dashboard**: Visualise signals and performance
5. **Multi-Timeframe Confluence**: Combine 15m + 30m signals for higher-conviction entries

---

**Happy Scanning! 📊**
