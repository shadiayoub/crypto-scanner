# 📊 Multi-Asset Scanner with Position Sizing

A professional-grade cryptocurrency and metals scanner powered by the **Nadaraya-Watson Envelope** indicator, designed for Breakout Prop and similar prop firm trading environments.

---

## 📁 Repository Structure

```
scanner-bot/
├── scanner.py              # Unified scanner (all timeframes via CLI)
├── usage.txt               # Quick reference for commands
├── README.md               # This file
└── logs.txt                # Optional log file
```

---

## 🎯 Overview

This scanner automatically detects **mean-reversion trading opportunities** across 58+ assets (56 cryptocurrencies + 2 precious metals) using advanced statistical methods. It provides:

- 📈 **Real-time signal detection** with confidence scoring
- 💰 **Automated position sizing** based on account risk
- 🎯 **Suggested entry/exit levels** with 3 risk/reward targets
- 🔍 **Multi-filter confirmation** (Volume, MA, timeframe alignment)
- ⏱️ **Single script** supports all timeframes via command-line arguments

---

## 🚀 Features

### Core Scanning
- **Nadaraya-Watson Envelope** (adaptive bandwidth per timeframe)
- **RSI** for momentum confirmation (period adjusts per timeframe)
- **5 Signal Types**: Crossover, Oversold/Overbought Bounce, Envelope Extreme
- **58+ Assets**: Top cryptocurrencies + Gold (XAU) & Silver (XAG) futures

### Filter System
*Note: The **BTC filter** state is displayed for context only and does not affect signal generation.*

Signals are generated purely based on the following components:

| Filter / Indicator | Impact | Description |
|--------------------|--------|-------------|
| **Nadaraya-Watson Envelope** | Core | Primary mean-reversion boundary detection |
| **RSI** | Core | Momentum confirmation |
| **Volume** | +6-12% | Confirms unusual trading activity with direction analysis |
| **MA Trend** | +8% or -15% | Aligns signals with trend (MA50 or MA200 depending on TF) |
| **Timeframe Confirmation** | +15% or -15% | Higher/lower timeframe alignment |
| **Squeeze Momentum (NEW)** | Modifies | Identifies periods of consolidation before a breakout |
| **SMRE Statistical Filters (NEW)** | Modifies | Advanced statistical filtering for enhanced accuracy |
| **RSI Divergence** | -20% | Detects RSI/Price mismatches |
| **Price Velocity** | -15% | Filters capitulation/blow-off moves |

### Position Management
- **Risk-based sizing** (adjustable per timeframe)
- **Confidence scaling** (0.5x - 1.5x position size)
- **3 Take-Profit targets** (conservative → aggressive)
- **Max position cap** (30-50% of account)

### Output
- **Signal Summary** table with all detected signals
- **Trading Plans** with entry, stop loss, and 3 take profit levels
- **Risk/Reward ratios** for all targets
- **Filter breakdown** showing why each signal triggered

---

## 📦 Installation

### 1. Clone or Download
```bash
git clone https://github.com/shadiayoub/crypto-scanner
cd scanner-bot
```

### 2. Install Dependencies
```bash
pip install ccxt pandas numpy
```

### 3. Ready to Use
The scanner is pre-configured with optimized parameters for each timeframe. No additional setup required.

---

## ▶️ Usage

### Basic Commands

```bash
# Default: 1h timeframe
python scanner.py

# 15-minute timeframe (day trading)
python scanner.py -tf 15m

# 5-minute timeframe (scalping)
python scanner.py -tf 5m

# 4-hour timeframe (swing trading)
python scanner.py -tf 4h

# 1-day timeframe (position trading)
python scanner.py -tf 1d
```

### Advanced Options

```bash
# Verbose mode (shows all symbols, not just signals)
python scanner.py -tf 15m -v

# Custom account size and risk
python scanner.py -tf 30m --account-size 50000 --risk 0.015

# Max concurrent positions
python scanner.py -tf 5m --max-positions 8

# List all available timeframes
python scanner.py --list-timeframes

# Help
python scanner.py --help
```

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

# Long-term (1d) - Run daily
0 0 * * * cd /path/to/scanner && python scanner.py -tf 1d
```

---

## ⏱️ Timeframe-Specific Parameters

The scanner automatically adjusts its parameters based on the chosen timeframe:

| Timeframe | Lookback | Bandwidth | Multiplier | RSI | MA | Risk | Targets |
|-----------|----------|-----------|------------|-----|-----|------|---------|
| **1m-15m** | 200 | 3.5 | 2.0 | 8 | 50 | 1.0% | 1.5%/2.5%/4% |
| **30m** | 300 | 4.5 | 2.5 | 10 | 100 | 1.5% | 2%/3.5%/5% |
| **1h** | 500 | 6.0 | 3.0 | 14 | 200 | 2.0% | 3%/5%/7% |
| **2h** | 500 | 6.0 | 3.0 | 14 | 200 | 2.0% | 3%/5%/7% |
| **4h-6h** | 500 | 7.0 | 3.5 | 14 | 200 | 2.0% | 4%/7%/10% |
| **12h-1d** | 500 | 8.0 | 4.0 | 14 | 200 | 2.0% | 4%/7%/10% |

### Recommended Scan Frequencies

| Trading Style | Timeframe | Scan Frequency |
|---------------|-----------|----------------|
| **Scalping** | 1m, 5m | Every 5-10 minutes |
| **Day Trading** | 15m | Every 15-30 minutes |
| **Day/Swing** | 30m | Every 30-60 minutes |
| **Swing Trading** | 1h | Every 2 hours |
| **Swing Trading** | 2h, 4h | Every 4 hours |
| **Position Trading** | 6h, 12h | Every 6-12 hours |
| **Long-Term** | 1d | Daily |

---

## 📊 Sample Output

### Scanner Output (15m)

```
==============================================================================================================
📊 MULTI-ASSET SCANNER: 15m | 2026-06-24 14:30 UTC
==============================================================================================================
Account: $10,000 | Risk: 1.5% per trade | Max Positions: 5
Parameters: Bandwidth=3.5, Multiplier=2.0, RSI=8
Confirmation: 1h | MA50 | Targets: 1.5%/2.5%/4.0%
Symbols: 56 Spot + 2 Futures
==============================================================================================================

SYMBOL          PRICE      SIGNAL             CONF   RSI      POSITION        FILTERS
--------------------------------------------------------------------------------------------------------------
BTC/USDT        $62451.88  🟢 BUY_OVERSOLD     68.5%  32.15    Below Lower     🔥 Volume 2.1x avg, ✅ Above MA50 ($...
ETH/USDT        $1663.07   🟢 BUY_OVERSOLD     62.3%  29.87    Inside          📈 Volume 1.4x avg, ✅ 1h confirms (R...
XAU/USDT:USDT   $4074.40   🔴 SELL_OVERBOUGHT  61.2%  68.42    Above Upper     📈 Volume 1.6x avg, ⚠️ 1h not confirm...

==============================================================================================================
📊 TRADING PLANS (3 Targets)
==============================================================================================================

🎯 BTC/USDT - BUY_OVERSOLD (Confidence: 68.5%)
   📍 Entry: $62451.8800
   🛑 Stop Loss: $61515.1000 (Risk: $150.00 | 1.50% of account)
   🎯 TP1: $63300.0000 (+1.4%) | R:R 0.93
   🎯 TP2: $64100.0000 (+2.6%) | R:R 1.73
   🎯 TP3: $65400.0000 (+4.7%) | R:R 3.13
   📊 Position Size: 0.0967 units ($6000.00)
   🔍 Filters: 🔥 Volume 2.1x avg, ✅ Above MA50 ($62200.00), ✅ 1h confirms (RSI 32.15)

==============================================================================================================
SUMMARY: 2 BUY | 1 SELL | 55 NEUTRAL | 58 TOTAL
==============================================================================================================
```

---

## 📈 Signal Types

| Signal | Condition | Description |
|--------|-----------|-------------|
| **BUY_CROSS** | Price crosses above lower band + RSI < 45 | Bullish reversal confirmed |
| **SELL_CROSS** | Price crosses below upper band + RSI > 55 | Bearish reversal confirmed |
| **BUY_OVERSOLD** | RSI < 35 + Price near lower band | Oversold bounce opportunity |
| **SELL_OVERBOUGHT** | RSI > 65 + Price near upper band | Overbought drop opportunity |
| **EXTREME_OVERSOLD** | Price >2% below lower band | Capitulation level |
| **EXTREME_OVERBOUGHT** | Price >2% above upper band | Exhaustion level |

---

## 🛠️ How It Works

### 1. Data Fetching
- Uses **ccxt** library to fetch OHLCV data from Binance
- Automatically handles **spot** (crypto) and **futures** (metals) symbols
- Fetches appropriate lookback based on timeframe

### 2. Indicator Calculation
- **Nadaraya-Watson Envelope**: Non-parametric regression with Gaussian kernel
- **RSI**: Period adjusts per timeframe (8-14)
- **MA50/MA200**: Trend filter (adjusts per timeframe)

### 3. Signal Detection
- Scans for multiple signal types simultaneously
- Applies multiple filters and indicators to adjust confidence:
  - Volume analysis (with direction detection)
  - MA trend alignment
  - Timeframe confirmation
  - Squeeze Momentum (NEW)
  - SMRE Statistical Filters (NEW)
  - RSI divergence check
  - Price velocity filter
- Only signals with confidence > 50% are shown

### 4. Position Sizing
- Calculates exact position size based on:
  - Account size
  - Risk per trade (1-2% depending on timeframe)
  - Stop loss distance
  - Signal confidence
- 3 take-profit targets with risk/reward ratios

---

## 🎯 Trading Rules

### When to Enter
1. **Signal appears** with confidence > 50%
2. **RSI alignment**: Buy when RSI < 35-40, Sell when RSI > 55-60
3. **Timeframe confirmation**: Higher timeframe aligns
4. **Volume confirmation**: Preferably > 1.3x average with direction alignment

### When to Exit
- **TP1**: Immediate level (middle band or 1.5-2%)
- **TP2**: Conservative target (2-5%)
- **TP3**: Aggressive target (4-10%)
- **Stop Loss**: Fixed at 1.5-3% or band level

### Position Management
- **Max concurrent positions**: 3-8 depending on timeframe
- **Max per position**: 30-50% of account
- **Risk per trade**: 1-2% of account (adjustable via CLI)

---

## 🧪 Supported Assets

### Cryptocurrencies (56)
BTC, ETH, SOL, XRP, DOGE, LINK, AVAX, SUI, NEAR, WIF, ARB, OP, AAVE, ADA, AIXBT, ALGO, APT, ASTER, ATOM, BCH, BNB, BONK, CRV, DOT, ETC, FIL, HBAR, INJ, JTO, JUP, KAITO, LDO, LIT, LTC, ONDO, ORDI, PENGU, PNUT, POL, PUMP, RENDER, S, SHIB, STX, TAO, TIA, TRUMP, TRX, UNI, VIRTUAL, WLD, ZEC

### Precious Metals (2)
- **XAU/USDT:USDT** (Gold Perpetual)
- **XAG/USDT:USDT** (Silver Perpetual)

---

## 🔧 Advanced Configuration

### Command-Line Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `-tf, --timeframe` | Timeframe to scan | `1h` |
| `-v, --verbose` | Show all symbols | `False` |
| `--list-timeframes` | Show available timeframes | - |
| `--account-size` | Account size in USD | `10000` |
| `--risk` | Risk per trade (%) | `0.02` |
| `--max-positions` | Max concurrent positions | `3` |

### Example: Custom Configuration
```bash
python scanner.py -tf 15m --account-size 50000 --risk 0.015 --max-positions 5 -v
```

---

## 📊 Version History

| Version | Changes |
|---------|---------|
| **v3.0** | Unified scanner with CLI arguments, 3 TP targets, enhanced filters |
| **v2.0** | Short-term version added (5m-30m) |
| **v1.0** | Long-term version (1H) |

---

## 🔧 Troubleshooting

### Issue: "Insufficient data" for metals
**Solution**: Metals (XAU/XAG) require futures data. The scanner automatically uses `ccxt.binanceusdm` for futures symbols.

### Issue: Rate limit errors
**Solution**: The scanner uses `enableRateLimit: True` to respect Binance limits. Reduce scan frequency if errors persist.

### Issue: No signals detected
**Solution**:
- Try a different timeframe
- Ensure market conditions are suitable (ranging markets work best)
- Use `-v` flag to see all symbols with their RSI and position

### Issue: Too many signals
**Solution**:
- Use a higher timeframe (1h, 4h)
- Increase risk parameter (less aggressive)
- Use `--max-positions` to limit concurrent trades

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

1. **Add Telegram Alerts**: Get notifications when signals appear
2. **Backtesting Engine**: Test strategy performance historically
3. **Auto-Execution**: Connect to Binance API for automated trading
4. **Web Dashboard**: Visualize signals and performance
5. **Multi-Timeframe Confluence**: Combine signals from multiple TFs

---

**Happy Scanning! 📊**
