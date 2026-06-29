# 📡 BTC Precision 5m Intraday Liquidity Scanner

An institutional-grade intraday trading scanner for Bitcoin (`BTC/USDT`) utilizing the Binance spot market via the `ccxt` library. This scanner goes beyond raw technical analysis by combining macro trend bias tracking, kernel-smoothed volatility envelopes, live order book liquidity depth, and an approximation of Cumulative Volume Delta (CVD) to filter out noise and capture high-probability execution zones on the 5-minute timeframe.

## 🚀 Core Architectural Pillars

1. **Nadaraya-Watson Envelopes:** Uses non-parametric Gaussian kernel smoothing to establish dynamic, adaptive support and resistance bands optimized for highly reactive lower timeframes (5m).
2. **Order Book Depth Analysis:** Queries the live limit order book to calculate real-time buy/sell pressure imbalance within $0.5\%$ of the mid-market price. It penalizes signals that fight active order walls.
3. **Approximated CVD (Cumulative Volume Delta):** Evaluates aggressive market order flow (Market Buys vs. Market Sells) over the past 5 minutes to detect volume delta absorption and distribution divergences.
4. **ATR Volatility Expansion Filter:** Measures relative Average True Range contraction to detect flat consolidation. If volatility drops below $75\%$ of its normal historical average, the scanner dynamically down-scores or filters signals to prevent "death by a thousand cuts" in sideways markets.
5. **Multi-Timeframe Structural Guard:** Automatically evaluates both a macro trend matrix ($1\text{h} + 4\text{h}$ blended scores) and immediate intermediate momentum via the $15\text{m}$ EMA Ribbon ($9, 21, 55$).

---

## 🛠️ Installation & Setup

### 1. Prerequisites
Ensure you have Python 3.8+ installed on your system.

### 2. Install Dependencies
Install the required quantitative and exchange interface libraries:
```bash
pip install ccxt pandas numpy

```

### 3. File Deployment

Save the provided script file as `btc-scanner.py` and ensure it is executable (on Linux/macOS):

```bash
chmod +x btc-scanner.py

```

---

## 💻 Usage & Command-Line Interfaces

You can customize the environment criteria directly via CLI arguments.

### Running a Standard 5-Minute Scan (Single Run)

```bash
python btc-scanner.py -tf 5m

```

### Running with Granular Order-Flow Logic Disclosed (`--verbose`)

To visually inspect the exact points added or subtracted by order book walls, CVD metrics, or MTF alignment filters:

```bash
python btc-scanner.py -tf 5m --verbose

```

### Setting Custom Account Size & Risk Profiles

Simulates precise positioning sizes based on dynamic risk targets:

```bash
python btc-scanner.py -tf 5m --account 25000 --risk 0.015

```

*Sets account parameter to $25,000 USD risking 1.5% per trade scenario.*

### Filtering by Minimum Confidence (`--min-conf`)

Suppresses any signal scoring below the supplied confidence threshold, so only high-conviction setups are printed:

```bash
python btc-scanner.py -tf 5m --min-conf 70
```

*Only displays signals with a confidence score of 70% or higher (default: 50).*

### Overriding Macro Bias (Pure Range Trading)

```bash
python btc-scanner.py -tf 5m --no-bias

```

---

## 🎯 Understanding Output Metrics & Signals

When a signal triggers, the script prints a structured execution module:

* **Conf (%) Score:** The matrix baseline starts at a default indicator threshold. Points are algorithmically added by order walls, high-frequency volume spikes, or trend confluence, and deducted for counter-trend or low-volatility conditions.
* **Order Book Balance:** A metric of `1.50x` indicates passive buy liquidity outweighs sell walls by $50\%$ inside the immediate order book depth.
* **CVD Delta:** Net aggressive balance. A negative percentage during a support touch highlights heavy panic selling being safely absorbed by passive buyers.
* **Trade Position Sizing:** Automatically structures an entry buffer, an optimized Stop Loss, and 3 specific Take Profit targets with structured risk-to-reward metrics.

---

## ⏰ Production Execution & Automation Strategy

Because the 5-minute timeframe relies heavily on **closed candlestick parameters** to confirm indicator stability and prevent signal "repainting," running the script mid-candle is inefficient. For optimal performance, execute the script exactly at the opening millisecond of every 5-minute block.

### Option A: Linux/macOS Native Cron (Recommended)

Add a crontab event to trigger the single-scan pipeline precisely on every 5-minute mark:

```bash
crontab -e

```

Add the following line:

```text
*/5 * * * * /usr/bin/python3 /path/to/btc-scanner.py -tf 5m >> /path/to/scanner.log 2>&1

```

### Option B: Built-in Loop Mode

To run inside a persistent terminal or Docker container background environment:

```bash
python btc-scanner.py -tf 5m --loop 5

```

---

## ⚠️ Risk Disclaimer

This tool is built for automated information-gathering, trend identification, and position calculation based on historical and real-time market data structures. Lower timeframes feature inherent liquidity volatility and execution slippage risks. Always audit code criteria thoroughly against a demo account infrastructure before committing real capital.

