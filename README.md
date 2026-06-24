# 📊 Enhanced Multi-Asset Scanner with Position Sizing

A professional-grade cryptocurrency and metals scanner powered by the **Nadaraya-Watson Envelope** indicator, designed for Breakout Prop and similar prop firm trading environments.

---

## 📁 Repository Structure

```
scanner-bot/
├── scanner.py              # Long-term version (1H+ timeframes)
├── short-tf-scanner.py     # Short-term version (5m-30m timeframes)
├── README.md               # This file
└── logs.txt                # Optional log file
```

---

## 🎯 Overview

This scanner automatically detects **mean-reversion trading opportunities** across 58+ assets (56 cryptocurrencies + 2 precious metals) using advanced statistical methods. It provides:

- 📈 **Real-time signal detection** with confidence scoring
- 💰 **Automated position sizing** based on account risk
- 🎯 **Suggested entry/exit levels** with risk/reward ratios
- 🔍 **Multi-filter confirmation** (Volume, MA, timeframe alignment)

---

## 🚀 Two Versions for Different Trading Styles

### 📊 Version 1: Long-Term (`scanner.py`)
**Designed for swing trading and position trading**

| Parameter | Value |
|-----------|-------|
| **Timeframe** | 1H (primary) |
| **Lookback** | 500 bars |
| **Bandwidth** | 6.0 |
| **Multiplier** | 3.0 |
| **RSI Period** | 14 |
| **MA Period** | 200 |
| **Max Positions** | 3 |
| **Risk per Trade** | 2.0% |
| **Stop Distance** | 2.5% |
| **Target 1** | 3-5% |
| **Target 2** | 5-10% |
| **Best For** | Swing trading, position trading |

**Filters**: Volume ✓ | MA200 ✓ | 15m Confirmation ✓

### ⚡ Version 2: Short-Term (`short-tf-scanner.py`)
**Designed for day trading and scalping**

| Parameter | Value |
|-----------|-------|
| **Timeframe** | 5m, 15m, or 30m |
| **Lookback** | 200 bars |
| **Bandwidth** | 4.0 |
| **Multiplier** | 2.5 |
| **RSI Period** | 10 |
| **MA Period** | 50 |
| **Max Positions** | 5 |
| **Risk per Trade** | 1.5% |
| **Stop Distance** | 1.5% |
| **Target 1** | 1.5-3% |
| **Target 2** | 3-6% |
| **Best For** | Day trading, scalping |

**Filters**: Volume ✓ | MA50 ✓ | 1H Confirmation ✓

---

## 🧪 Supported Assets

### Cryptocurrencies (56)
BTC, ETH, SOL, XRP, DOGE, LINK, AVAX, SUI, NEAR, PEPE, WIF, ARB, OP, AAVE, ADA, AIXBT, ALGO, APT, ASTER, ATOM, BCH, BNB, BONK, CRV, DOT, ETC, FIL, FLOKI, HBAR, INJ, JTO, JUP, KAITO, LDO, LIT, LTC, ONDO, ORDI, PENGU, PNUT, POL, PUMP, RENDER, S, SHIB, STX, TAO, TIA, TRUMP, TRX, UNI, VIRTUAL, WLD, ZEC

### Precious Metals (2)
- **XAU/USDT:USDT** (Gold Perpetual)
- **XAG/USDT:USDT** (Silver Perpetual)

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

### 3. Configure Settings

#### For Long-Term Version (`scanner.py`):
```python
# Account Settings
ACCOUNT_SIZE = 10000        # Your account size in USD
MAX_RISK_PER_TRADE = 0.02   # 2% risk per trade
MAX_POSITIONS = 3           # Max concurrent positions

# Indicator Settings
TIMEFRAME = '1h'            # Primary timeframe
BANDWIDTH = 6.0             # N-W Envelope bandwidth
MULTIPLIER = 3.0            # Envelope multiplier
```

#### For Short-Term Version (`short-tf-scanner.py`):
```python
# Account Settings
ACCOUNT_SIZE = 10000        # Your account size in USD
MAX_RISK_PER_TRADE = 0.015  # 1.5% risk per trade
MAX_POSITIONS = 5           # Max concurrent positions

# Timeframe Selection (choose one)
TIMEFRAME = '15m'           # Options: '5m', '15m', '30m'

# Indicator Settings (optimized for short-term)
BANDWIDTH = 4.0
MULTIPLIER = 2.5
RSI_PERIOD = 10
MA_PERIOD = 50
```

---

## ▶️ Usage

### Long-Term Scanner
```bash
python scanner.py
```

### Short-Term Scanner
```bash
python short-tf-scanner.py
```

### Schedule Examples

#### Long-Term (Every 2 Hours)
```bash
# Add to crontab (Linux/Mac)
0 */2 * * * cd /path/to/scanner && python scanner.py >> logs.txt
```

#### Short-Term (Every 15 Minutes)
```bash
*/15 * * * * cd /path/to/scanner && python short-tf-scanner.py >> logs.txt
```

#### Short-Term (Every 5 Minutes - Scalping)
```bash
*/5 * * * * cd /path/to/scanner && python short-tf-scanner.py >> logs.txt
```

---

## 📊 Sample Outputs

### Long-Term Output (1H)

```
====================================================================================================
ENHANCED SCAN: 1h | 2026-06-24 10:00 UTC
Account: $10,000 | Max Risk: 2% per trade | Max Positions: 3
Filters: Volume ✓ | MA200 ✓ | 15m Confirmation ✓
Symbols: 56 Spot + 2 Futures (XAU/XAG)
====================================================================================================

SYMBOL          PRICE      SIGNAL             CONF   RSI      POSITION        FILTERS
--------------------------------------------------------------------------------------------------------------
ETH/USDT        $1663.07   🟢 BUY_OVERSOLD     55.8%  27.05    Inside          📉 Volume 0.9x avg, ⚠️ Below MA200 ($...
XAU/USDT:USDT   $2345.67   🔴 SELL_OVERBOUGHT  72.3%  72.15    Inside          🔥 Volume 1.8x avg, ✅ Above MA200 ($...

====================================================================================================
📊 TRADING PLANS FOR SIGNALS
====================================================================================================

🎯 ETH/USDT - BUY_OVERSOLD (Confidence: 55.8%)
   📍 Entry: $1663.0700
   🛑 Stop Loss: $1624.5000 (Risk: $25.00 | 0.25% of account)
   🎯 Take Profit 1: $1726.0000 (+3.8%) | R:R 1.52
   🎯 Take Profit 2: $1775.0000 (+6.7%) | R:R 2.68
   📊 Position Size: 0.6500 units ($1080.00)
   🔍 Filters: 📉 Volume 0.9x avg, ⚠️ Below MA200 ($1740.99), ✅ 15m confirms (RSI 19.64)

====================================================================================================
SUMMARY: 2 BUY | 1 SELL | 55 NEUTRAL | 58 TOTAL
====================================================================================================
```

### Short-Term Output (15m)

```
====================================================================================================
SHORT-TERM SCAN: 15m | 2026-06-24 14:30 UTC
Account: $10,000 | Max Risk: 1.5% per trade | Max Positions: 5
Filters: Volume ✓ | MA50 ✓ | 1h Confirmation ✓
Symbols: 38 Spot + 2 Futures
Settings: Bandwidth=4.0, Multiplier=2.5, RSI=10
====================================================================================================

SYMBOL          PRICE      SIGNAL             CONF   RSI      POSITION        FILTERS
--------------------------------------------------------------------------------------------------------------
BTC/USDT        $62451.88  🟢 BUY_OVERSOLD     68.5%  32.15    Below Lower     🔥 Volume 2.1x avg, ⚠️ Below MA50 ($...
ETH/USDT        $1663.07   🟢 BUY_OVERSOLD     62.3%  29.87    Inside          📈 Volume 1.4x avg, ✅ 1h confirms (R...
XAU/USDT:USDT   $2345.67   🔴 SELL_OVERBOUGHT  71.2%  68.42    Above Upper     📈 Volume 1.6x avg, ✅ 1h confirms (R...

====================================================================================================
📊 SHORT-TERM TRADING PLANS
====================================================================================================

🎯 BTC/USDT - BUY_OVERSOLD (Confidence: 68.5%)
   📍 Entry: $62451.8800
   🛑 Stop Loss: $61515.1000 (Risk: $15.00 | 0.15% of account)
   🎯 Take Profit 1: $63520.0000 (+1.7%) | R:R 1.13
   🎯 Take Profit 2: $64420.0000 (+3.2%) | R:R 2.13
   📊 Position Size: 0.0160 units ($1000.00)
   🔍 Filters: 🔥 Volume 2.1x avg, ⚠️ Below MA50 ($62500.00), ✅ 1h confirms (RSI 32.15)

====================================================================================================
SUMMARY: 2 BUY | 1 SELL | 37 NEUTRAL | 40 TOTAL
====================================================================================================
```

---

## 📈 Signal Types

| Signal | Condition | Description |
|--------|-----------|-------------|
| **BUY_CROSS** | Price crosses above lower band + RSI < 40/45 | Bullish reversal confirmed |
| **SELL_CROSS** | Price crosses below upper band + RSI > 60/55 | Bearish reversal confirmed |
| **BUY_OVERSOLD** | RSI < 30/35 + Price near lower band | Oversold bounce opportunity |
| **SELL_OVERBOUGHT** | RSI > 70/65 + Price near upper band | Overbought drop opportunity |
| **EXTREME_OVERSOLD** | Price >2-3% below lower band | Capitulation level |
| **EXTREME_OVERBOUGHT** | Price >2-3% above upper band | Exhaustion level |

*Note: First value is for long-term, second for short-term*

---

## 🛠️ How It Works

### 1. Data Fetching
- Uses **ccxt** library to fetch OHLCV data from Binance
- Automatically handles **spot** (crypto) and **futures** (metals) symbols
- Fetches 200-500 bars depending on version

### 2. Indicator Calculation
- **Nadaraya-Watson Envelope**: Non-parametric regression with Gaussian kernel
- **RSI**: Standard 10-14 period Relative Strength Index
- **MA50/MA200**: Simple Moving Average for trend filter

### 3. Signal Detection
- Scans for multiple signal types simultaneously
- Applies 3 filters to adjust confidence
- Sorts signals by confidence (highest first)

### 4. Position Sizing
- Calculates exact position size based on:
  - Account size
  - Risk per trade (1.5-2% default)
  - Stop loss distance
  - Signal confidence

---

## 🎯 Trading Rules

### When to Enter
1. **Signal appears** with confidence > 50%
2. **RSI alignment**: Buy when RSI < 35-40, Sell when RSI > 55-60
3. **Timeframe confirmation**: Higher or lower timeframe aligns
4. **Volume spike**: Preferably > 1.2-1.3x average

### When to Exit
- **TP1**: Conservative target (1.5-5% gain)
- **TP2**: Aggressive target (3-10% gain)
- **Stop Loss**: Fixed at 1.5-2.5% or band level

### Position Management
- **Max concurrent positions**: 3-5 depending on version
- **Max per position**: 30-50% of account
- **Risk per trade**: 1.5-2% of account (adjustable)

---

## ⚙️ Advanced Configuration

### Choosing the Right Timeframe

| Trading Style | Version | Timeframe | Scan Frequency |
|---------------|---------|-----------|----------------|
| **Scalping** | Short | 5m | Every 5-10 min |
| **Day Trading** | Short | 15m | Every 15-30 min |
| **Day/Swing** | Short | 30m | Every 30-60 min |
| **Swing Trading** | Long | 1h | Every 2 hours |
| **Position Trading** | Long | 4h | Every 4-6 hours |

### Adjusting Parameters for Your Style

```python
# For more signals (aggressive)
BANDWIDTH = 3.5      # Lower = more sensitive
MULTIPLIER = 2.0     # Lower = tighter envelope
RSI_OVERSOLD = 40    # Higher = more buy signals
RSI_OVERBOUGHT = 60  # Lower = more sell signals

# For fewer signals (conservative)
BANDWIDTH = 8.0      # Higher = smoother
MULTIPLIER = 4.0     # Higher = wider envelope
RSI_OVERSOLD = 25    # Lower = fewer buy signals
RSI_OVERBOUGHT = 75  # Higher = fewer sell signals
```

---

## 📊 Version Comparison

| Feature | Long-Term (`scanner.py`) | Short-Term (`short-tf-scanner.py`) |
|---------|--------------------------|-------------------------------------|
| **Timeframes** | 1H, 4H | 5m, 15m, 30m |
| **Lookback** | 500 bars | 200 bars |
| **Bandwidth** | 6.0 | 4.0 |
| **Multiplier** | 3.0 | 2.5 |
| **RSI Period** | 14 | 10 |
| **MA Period** | 200 | 50 |
| **Max Positions** | 3 | 5 |
| **Risk per Trade** | 2.0% | 1.5% |
| **Stop Distance** | 2.5% | 1.5% |
| **Target 1** | 3-5% | 1.5-3% |
| **Target 2** | 5-10% | 3-6% |
| **Confirmation** | 15m | 1H |
| **Best For** | Swing/Position | Day/Scalping |

---

## 🔧 Troubleshooting

### Issue: "Insufficient data" for metals
**Solution**: Metals (XAU/XAG) require futures data. Ensure `ccxt.binanceusdm` is installed.

### Issue: Rate limit errors
**Solution**: The scanner uses `enableRateLimit: True` to respect Binance limits. Reduce scan frequency if errors persist.

### Issue: No signals detected
**Solution**: 
- Check if market conditions are ranging (signals appear more often)
- Adjust `BANDWIDTH` or `MULTIPLIER`
- Lower confidence thresholds temporarily
- For short-term version, ensure you're using the right timeframe

### Issue: Too many signals (short-term)
**Solution**:
- Increase `BANDWIDTH` to 5.0-6.0
- Increase `MULTIPLIER` to 3.0
- Increase `RSI_PERIOD` to 14
- Increase `MAX_RISK_PER_TRADE` to filter by confidence

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
5. **Multi-Timeframe Scanner**: Combine both versions for confluence

---

**Happy Scanning! 📊**
