# XAG Precision Intraday Scanner (Enhanced)

## 1. Overview

This repository contains an advanced Python script designed for precision intraday scanning of XAG (Silver) futures. The core architecture leverages adaptive Nadaraya-Watson envelopes, real-time order book depth metrics, and a suite of custom-built technical indicators to identify high-probability trading opportunities. This enhanced version has been specifically optimized for the 15-minute and 30-minute timeframes, incorporating dynamic risk management, session-aware filtering, and advanced pattern recognition to adapt to the unique volatility profile of the Silver market.

## 2. Core Features and Architecture

The scanner operates by integrating real-time market data with sophisticated mathematical models. It connects to the Binance futures exchange via the `ccxt` library, retrieving both historical OHLCV (Open-High-Low-Close-Volume) data and live order book snapshots. This dual-data approach allows the system to analyze historical price action while simultaneously verifying signals against current market liquidity.

The analytical engine is built upon several key technical indicators. The primary driver is a custom implementation of the Nadaraya-Watson envelope, which uses a Gaussian kernel to create a smoothed price line and adaptive upper and lower boundaries. This is complemented by standard indicators such as the Relative Strength Index (RSI) for momentum, Exponential Moving Average (EMA) for trend direction, and Average True Range (ATR) for volatility measurement. Furthermore, the script includes a proprietary market structure detection algorithm that identifies swing highs and lows to classify the current market phase as bullish, bearish, or neutral.

To provide context for intraday signals, the scanner calculates a Macro Trend Bias. This feature analyzes the 2-hour and 4-hour timeframes, combining RSI, EMA, and market structure data to generate a directional score (e.g., `BULLISH_STRONG`, `BEARISH`). This higher-timeframe perspective acts as a critical filter, suppressing counter-trend signals and boosting confidence in setups that align with the broader market direction.

## 3. Enhancements for 15m and 30m Timeframes

This version of the scanner introduces several critical enhancements designed to improve performance specifically on the 15-minute and 30-minute charts.

### 3.1. Dynamic ATR-Based Risk Management

Traditional fixed-percentage stop losses often fail in highly volatile markets like Silver. This enhanced script replaces fixed percentages with dynamic risk parameters based on the Average True Range (ATR). By calculating stop loss and take profit levels as multiples of the current ATR, the scanner automatically widens its parameters during periods of high volatility to avoid premature exits, and tightens them during quiet periods to protect capital.

### 3.2. Session-Aware Volatility Filtering

Silver trading volume and volatility are heavily influenced by global trading sessions. The scanner now includes a UTC-based session identification module. It actively boosts the confidence score of signals generated during peak liquidity periods, such as the London and New York overlap, while penalizing signals that occur during historically quiet periods, like the late Asian session. This ensures the system focuses on setups with the highest probability of follow-through.

### 3.3. Liquidity Sweep (Wick Trap) Detection

A common characteristic of the Silver market is the "liquidity sweep," where price briefly spikes beyond a key level to trigger stop losses before reversing. The enhanced logic now specifically scans for these patterns at the boundaries of the Nadaraya-Watson envelopes. By analyzing the relationship between the candle's wick length and its total range, the scanner can identify potential bull or bear traps and generate high-confidence counter-trend signals.

## 4. Installation and Setup

To run the XAG Precision Intraday Scanner, you need a Python environment with specific dependencies installed.

**Prerequisites:**
Ensure you have Python 3.7 or higher installed on your system.

**Installation Steps:**
1.  Clone or download the repository containing the `xag-scanner-enhanced.py` script.
2.  Install the required Python packages using `pip`. The primary dependencies are `ccxt`, `pandas`, and `numpy`.

```bash
pip install ccxt pandas numpy
```

## 5. Usage Instructions

The scanner is executed via the command line and accepts several arguments to customize its operation.

**Basic Execution:**
To run a single scan on the default 15-minute timeframe:

```bash
python xag-scanner-enhanced.py
```

**Command-Line Arguments:**

| Argument | Description | Default Value |
| :--- | :--- | :--- |
| `-tf`, `--timeframe` | Specifies the timeframe to scan (`5m`, `15m`, or `30m`). | `15m` |
| `--loop` | Enables continuous monitoring, repeating the scan every N minutes. Set to `0` for a single run. | `0` |
| `--account` | Defines the simulated account size in USD for risk calculations. | `10000` |
| `--risk` | Sets the risk per trade as a decimal (e.g., `0.01` for 1%). | `0.01` |
| `--no-bias` | Disables the macro trend-bias weighting filter. | `False` |
| `-v`, `--verbose` | Enables detailed output, showing the audit trail and mathematical filter details for each signal. | `False` |
| `--min-conf` | Sets the minimum confidence score required to display a signal. | `50.0` |

**Example: Continuous Monitoring with Verbose Output**
To run the scanner continuously on the 30-minute timeframe, updating every 30 minutes, with detailed logging enabled:

```bash
python xag-scanner-enhanced.py -tf 30m --loop 30 --verbose
```

## 6. Disclaimer

This software is for educational and informational purposes only. It does not constitute financial advice. Trading financial markets, particularly leveraged futures contracts, involves significant risk of loss. Always conduct your own research and backtest any strategy before deploying real capital.
