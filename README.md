# 📊 Enhanced Multi-Asset Scanner with Position Sizing

A professional-grade cryptocurrency and metals scanner powered by the **Nadaraya-Watson Envelope** indicator, designed for Breakout Prop and similar prop firm trading environments.

---

## 🎯 Overview

This scanner automatically detects **mean-reversion trading opportunities** across 58+ assets (56 cryptocurrencies + 2 precious metals) using advanced statistical methods. It provides:

- 📈 **Real-time signal detection** with confidence scoring
- 💰 **Automated position sizing** based on account risk
- 🎯 **Suggested entry/exit levels** with risk/reward ratios
- 🔍 **Multi-filter confirmation** (Volume, MA200, 15m timeframe)

---

## 🚀 Features

### Core Scanning
- **Nadaraya-Watson Envelope** (Bandwidth: 6, Multiplier: 3)
- **RSI (14)** for momentum confirmation
- **3 Signal Types**: Crossover, Oversold/Overbought Bounce, Envelope Extreme
- **58+ Assets**: Top cryptocurrencies + Gold (XAU) & Silver (XAG) futures

### Filter System
| Filter | Impact | Description |
|--------|--------|-------------|
| **Volume** | +5-10% | Confirms unusual trading activity |
| **MA200** | +8% or -5% | Aligns signals with long-term trend |
| **15m Confirmation** | +12% or -3% | Lower timeframe alignment |

### Position Management
- **Risk-based sizing** (default 2% per trade)
- **Confidence scaling** (0.5x - 1.5x position size)
- **Max position cap** (50% of account)
- **Min position** ($50 to avoid dust)

### Output
- **Signal Summary** table with all detected signals
- **Trading Plans** with entry, stop loss, and take profit levels
- **Risk/Reward ratios** for both conservative and aggressive targets
- **Filter breakdown** showing why each signal triggered

---

## 📦 Installation

### 1. Clone or Download
```bash
git clone <your-repo-url> # Replace with your actual repository URL
cd scanner-bot
```

### 2. Install Dependencies
```bash
pip install ccxt pandas numpy
```

### 3. Configure Settings
Edit the configuration section in `scanner.py`:

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

---

## ▶️ Usage

### Basic Run
```bash
python scanner.py
```

### Schedule Every 2 Hours (Recommended)
```bash
# Add to crontab (Linux/Mac)
0 */2 * * * cd /path/to/scanner && python scanner.py >> logs.txt

# Windows Task Scheduler: Create task to run every 2 hours
```

---

## 📊 Sample Output

```
====================================================================================================
ENHANCED SCAN: 1h | 2026-06-24 10:00 UTC
Account: $10,000 | Max Risk: 2% per trade | Max Positions: 3
Filters: Volume ✓ | MA200 ✓ | 15m Confirmation ✓
Symbols: 56 Spot + 2 Futures (XAU/XAG)
====================================================================================================

SYMBOL          PRICE      SIGNAL             CONF   RSI      POSITION        FILTERS
--------------------------------------------------------------------------------------------------------------
XAU/USDT:USDT   $2345.67   🔴 SELL_OVERBOUGHT 72.3%  72.15    Inside          🔥 Volume 1.8x avg, ✅ Above MA200 ($...
ETH/USDT        $1663.07   🟢 BUY_OVERSOLD     55.8%  27.05    Inside          📉 Volume 0.9x avg, ⚠️ Below MA200 ($...
ETC/USDT        $6.97      🟢 BUY_OVERSOLD     65.7%  18.75   Inside          📉 Volume 0.8x avg, ⚠️ Below MA200 ($...

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

🟢 TOP BUY SIGNALS (with trading plan):
   ETC/USDT: Deep oversold (RSI 18.8) near lower band
      Entry: $6.9700 | Stop: $6.7970 | TP1: $7.3170 | TP2: $7.5240
      Size: 144.92 units ($1010.00) | Risk: $25.00

🔴 TOP SELL SIGNALS (with trading plan):
   XAU/USDT:USDT: Overbought (RSI 72.2) near upper band
      Entry: $2345.6700 | Stop: $2392.5834 | TP1: $2266.7300 | TP2: $2208.2100
      Size: 0.0425 units ($100.00) | Risk: $25.00
====================================================================================================
```

---

## 📈 Signal Types

| Signal | Condition | Description |
|--------|-----------|-------------|
| **BUY_CROSS** | Price crosses above lower band + RSI < 40 | Bullish reversal confirmed |
| **SELL_CROSS** | Price crosses below upper band + RSI > 60 | Bearish reversal confirmed |
| **BUY_OVERSOLD** | RSI < 30 + Price near lower band | Oversold bounce opportunity |
| **SELL_OVERBOUGHT** | RSI > 70 + Price near upper band | Overbought drop opportunity |
| **EXTREME_OVERSOLD** | Price >3% below lower band | Capitulation level |
| **EXTREME_OVERBOUGHT** | Price >3% above upper band | Exhaustion level |

---

## 🛠️ How It Works

### 1. Data Fetching
- Uses **ccxt** library to fetch OHLCV data from Binance
- Automatically handles **spot** (crypto) and **futures** (metals) symbols
- Fetches 500+ bars for accurate indicator calculation

### 2. Indicator Calculation
- **Nadaraya-Watson Envelope**: Non-parametric regression with Gaussian kernel
- **RSI**: Standard 14-period Relative Strength Index
- **MA200**: 200-period Simple Moving Average for trend filter

### 3. Signal Detection
- Scans for multiple signal types simultaneously
- Applies 3 filters to adjust confidence
- Sorts signals by confidence (highest first)

### 4. Position Sizing
- Calculates exact position size based on:
  - Account size
  - Risk per trade (2% default)
  - Stop loss distance
  - Signal confidence

---

## 🎯 Trading Rules

### When to Enter
1. **Signal appears** with confidence > 50%
2. **RSI alignment**: Buy when RSI < 40, Sell when RSI > 60
3. **15m confirmation**: Lower timeframe aligns
4. **Volume spike**: Preferably > 1.2x average

### When to Exit
- **TP1**: Conservative target (3-5% gain)
- **TP2**: Aggressive target (5-10% gain)
- **Stop Loss**: Fixed at 2.5% or lower/upper band

### Position Management
- **Max 3 concurrent positions**
- **Max 50% of account per position**
- **Risk per trade**: 2% of account (adjustable)

---

## 🧪 Supported Assets

### Cryptocurrencies (56)
BTC, ETH, SOL, XRP, DOGE, LINK, AVAX, SUI, NEAR, PEPE, WIF, ARB, OP, AAVE, ADA, AIXBT, ALGO, APT, ASTER, ATOM, BCH, BNB, BONK, CRV, DOT, ETC, FIL, FLOKI, HBAR, INJ, JTO, JUP, KAITO, LDO, LIT, LTC, ONDO, ORDI, PENGU, PNUT, POL, PUMP, RENDER, S, SHIB, STX, TAO, TIA, TRUMP, TRX, UNI, VIRTUAL, WLD, ZEC

### Precious Metals (2)
- **XAU/USDT:USDT** (Gold Perpetual)
- **XAG/USDT:USDT** (Silver Perpetual)

---

## ⚙️ Advanced Configuration

### Adjusting Confidence Sensitivity
```python
# Volume thresholds
if volume_ratio > 1.5: confidence += 10  # Strong volume
elif volume_ratio > 1.2: confidence += 5  # Moderate volume

# MA200 alignment
if current > ma_200: confidence += 8   # Uptrend
else: confidence -= 5                   # Downtrend

# 15m confirmation
if confirms_15m: confidence += 12      # Confirmed
else: confidence -= 3                  # Not confirmed
```

### Modifying Position Sizing
```python
# Risk per trade (0.02 = 2%)
MAX_RISK_PER_TRADE = 0.02

# Confidence multiplier (50% = 1.0x, 90% = 1.4x)
confidence_multiplier = 0.5 + (confidence / 100) * 1.0

# Max position (50% of account)
max_position_value = account_size * 0.5
```

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

---

## 📝 License

This project is for educational purposes only and is provided 
under the MIT License. Trading involves significant risk.

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

---

**Happy Scanning! 📊**
