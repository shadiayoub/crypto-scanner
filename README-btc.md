# 📡 BTC Aggressive Scanner v2.0 — Regime-Aware Intraday Engine

An institutional-grade intraday trading scanner for Bitcoin (`BTC/USDT`) utilizing the Binance spot & perpetual markets via the `ccxt` library. This scanner goes beyond raw technical analysis by combining **regime-aware volatility scaling**, **liquidation cascade detection**, **funding rate contrarian signals**, **multi-tier order book intelligence**, and **Kelly-criterion position sizing** to filter out noise and capture high-probability execution zones on the 5m, 15m, and 30m timeframes.

**Optimized for BTC's aggressive, high-volatility character** — the scanner adapts its entire risk framework based on detected market regime, fades liquidation cascades rather than chasing them, and uses extreme funding rates as contrarian fuel signals.

---

## 🚀 Core Architectural Pillars

### 1. Nadaraya-Watson Envelopes
Uses non-parametric Gaussian kernel smoothing to establish dynamic, adaptive support and resistance bands. Parameters are **regime-tuned**: tighter in compressed volatility, wider during expansion.

### 2. Volatility Regime Detection
Classifies the market into four distinct regimes:
| Regime | Character | Stop Multiplier | Strategy |
|--------|-----------|-----------------|----------|
| **Compressed** | Low vol, chop | 0.7× | Tight stops, patience for expansion |
| **Normal** | Balanced | 1.0× | Standard execution |
| **Expansion** | Elevated vol | 1.5× | Widen stops, expect noise |
| **Cascade** | Liquidation-driven | 2.0× | Fade exhaustion, massive stops |

### 3. Liquidation Cascade Detection
Identifies trapped-trader signatures (impulse candles with minimal wicks + volume spikes). The scanner **fades cascades** (+20 confidence when signal opposes the cascade) and **penalizes chasing** (-30 confidence when signal follows the cascade direction).

### 4. Funding Rate Contrarian Signals
Queries Binance perpetual futures funding rates as a **crowded-positioning proxy**:
- **Extreme long funding** → penalizes BUY signals, boosts SELL (short squeeze fuel)
- **Extreme short funding** → penalizes SELL signals, boosts BUY (long squeeze fuel)

### 5. Multi-Tier Order Book Intelligence
Analyzes liquidity depth at four tiers (0.2%, 0.5%, 1%, 2%) to detect:
- **Walls** — concentrated liquidity clusters that act as support/resistance
- **Spoofing patterns** — fake walls that disappear
- **Absorption zones** — where large market orders get eaten by limit liquidity

### 6. Enhanced Delta Profile (Institutional Footprint)
Tracks large-lot trades (>0.5 BTC) separately from retail flow to detect:
- **Institutional accumulation/distribution**
- **Retail/institutional divergence** — weak moves when they disagree

### 7. HTF Structure Alignment Gating
Scores 1h / 4h / Daily market structure confluence (-100 to +100). Signals fighting strong higher-timeframe structure are **hard-gated** (skipped) or heavily penalized.

### 8. Session-Aware Liquidity Profiling
Adjusts confidence and position size based on time-of-day:
| Session | Confidence | Liquidity |
|---------|-----------|-----------|
| Asia (00-08 UTC) | 0.85× | Low — prone to fake-outs |
| London (08-14 UTC) | 0.95× | Medium |
| NY/London Overlap (14-21 UTC) | 1.15× | **High — optimal execution** |
| Weekend | 0.80× | Thin — size down |

### 9. Kelly Criterion Position Sizing
Replaces fixed risk with **half-Kelly sizing**:
- Confidence-adjusted win rate estimation
- Session-liquidity size reduction
- Capped at `--max-risk-pct` (default 2%)

### 10. ATR Volatility Expansion Filter
Measures relative Average True Range contraction. If volatility drops below 75% of its historical average, signals are down-scored to prevent "death by a thousand cuts" in sideways markets.

---

## 🛠️ Installation & Setup

### 1. Prerequisites
Ensure you have Python 3.8+ installed on your system.

### 2. Install Dependencies
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

### Running a Standard 15-Minute Scan (Recommended)
The 15m timeframe is **optimized by default** with regime-aware parameters:
```bash
python btc-scanner.py -tf 15m
```

### Running with Full Microstructure Disclosure (`--verbose`)
Inspect exact points added/subtracted by regime, funding, order book walls, CVD, HTF alignment, and session filters:
```bash
python btc-scanner.py -tf 15m --verbose
```

### Setting Custom Account Size & Risk Profiles
```bash
python btc-scanner.py -tf 15m --account 25000 --risk 0.015 --max-risk-pct 0.02
```
*Sets account to $25,000 USD, baseline risk 1.5%, max Kelly-capped risk 2% per trade.*

### Filtering by Minimum Confidence (`--min-conf`)
Suppress low-conviction setups:
```bash
python btc-scanner.py -tf 15m --min-conf 70
```

### Overriding Macro Bias (Pure Microstructure Mode)
```bash
python btc-scanner.py -tf 15m --no-bias
```

### Live Loop Mode
Run inside a persistent terminal or container:
```bash
python btc-scanner.py -tf 15m --loop 5 --verbose
```

---

## 🎯 Understanding Output Metrics & Signals

When a signal triggers, the scanner prints a structured execution module:

```
🟢 [15m] BTC/USDT — BUY  |  Conf: 78.5%  |  Cross above lower band (RSI 42)
   📊 Regime: ➡️ NORMAL | Session: NY/London | HTF Align: +45
   💰 Price: $67,420.50 | RSI(15m): 42.0 | Funding: neutral (+0.0031%)
   📖 Book: 1.62x | CVD: +12.3%
   🔥 Large lot delta: +18.5%
   📍 Entry   : $67,512.30
   🛑 Stop    : $67,107.20  (Risk: $185.40, 0.60% — normal-scaled)
   🎯 Target 1: $68,322.50  (+1.2%)
   🎯 Target 2: $68,997.80  (+2.2%)
   🎯 Target 3: $70,089.40  (+3.8%)
   📊 Size: 0.02745 BTC ($1,850.60)
   📝 Validation Logs:
     ✅ HTF alignment confirms direction (+45)
     🔥 Book Support: Bid depth 1.62x
     ✅ Wide book confirms bid-heavy (1.45x)
     📈 CVD Bullish: Aggressive buying (+12.3%)
     ✅ Macro Bias BULLISH confirms BUY
     📈 Volume spike (2.1x avg)
```

### Key Metrics Explained

| Metric | Description |
|--------|-------------|
| **Conf (%)** | Composite score: baseline + regime adjustments + book/CVD/funding/HTF/session bonuses/penalties |
| **Regime** | Current volatility regime: `compressed` / `normal` / `expansion` / `cascade` |
| **HTF Align** | 1h/4h/Daily structure confluence score (-100 bearish to +100 bullish) |
| **Funding** | Perpetual funding rate state: `extreme_long` / `elevated_long` / `neutral` / `elevated_short` / `extreme_short` |
| **Book Balance** | Bid/Ask volume ratio within 0.5% depth. `1.50x` = 50% more bid liquidity |
| **CVD Delta** | Net aggressive market order flow. Negative at support = panic selling absorbed by passive buyers |
| **Large Lot Delta** | Institutional footprint (>0.5 BTC trades). Divergence from retail = weak move warning |
| **Liquidation Score** | Cascade intensity (0-100). High score with signal opposition = exhaustion fade opportunity |
| **Stop %** | Regime-scaled ATR stop. `normal-scaled` = 1.0× base, `cascade-scaled` = 2.0× base |

---

## ⏰ Production Execution & Automation Strategy

### Option A: Linux/macOS Cron (Recommended for 15m)
Execute precisely at the opening of every 15-minute block:
```bash
crontab -e
```
Add:
```text
*/15 * * * * /usr/bin/python3 /path/to/btc-scanner.py -tf 15m >> /path/to/scanner.log 2>&1
```

### Option B: Built-in Loop Mode
```bash
python btc-scanner.py -tf 15m --loop 15 --verbose >> scanner.log 2>&1 &
```

### Option C: Systemd Service (Linux)
Create `/etc/systemd/system/btc-scanner.service`:
```ini
[Unit]
Description=BTC Aggressive Scanner
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 /path/to/btc-scanner.py -tf 15m --loop 15 --verbose
Restart=always
RestartSec=60
User=youruser

[Install]
WantedBy=multi-user.target
```
Then:
```bash
sudo systemctl enable btc-scanner
sudo systemctl start btc-scanner
sudo journalctl -u btc-scanner -f
```

---

## 🧠 Strategic Philosophy: Trading BTC's Aggression

Bitcoin in 2026 retains its **fat-tailed, cascade-prone character** despite institutional maturation. This scanner is built around five core principles:

1. **Don't fight the regime.** Compressed volatility requires patience; expansion requires widened stops and reduced size.
2. **Fade liquidations, don't chase them.** The best entries come after cascade exhaustion — when trapped traders have already been stopped out.
3. **Respect HTF structure.** 15m signals against strong 4h/daily trends have poor expectancy. The scanner gates these aggressively.
4. **Use funding as a contrarian gauge.** Extreme funding = crowded trade = reversal setup. The scanner treats funding as fuel, not confirmation.
5. **Book profits aggressively.** BTC's V-shaped recoveries mean unrealized gains can evaporate fast. The 3-tier TP system forces disciplined scaling.

---

## ⚠️ Risk Disclaimer

This tool is built for automated information-gathering, trend identification, and position calculation based on historical and real-time market data structures. Lower timeframes feature inherent liquidity volatility, execution slippage, and funding rate risks. **Always audit code criteria thoroughly against a demo account before committing real capital.**

The scanner's regime detection and liquidation cascade fading are probabilistic edge enhancements, not guarantees. Past performance of any signal framework does not predict future results.
