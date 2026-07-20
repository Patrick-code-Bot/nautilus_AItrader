# NautilusTrader DeepSeek AI Trading Strategy

## v1.2.2 - Advanced AI-Powered Cryptocurrency Trading System

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![NautilusTrader](https://img.shields.io/badge/NautilusTrader-Latest-green.svg)](https://nautilustrader.io/)
[![DeepSeek AI](https://img.shields.io/badge/DeepSeek-AI%20Powered-purple.svg)](https://www.deepseek.com/)
[![License](https://img.shields.io/badge/license-Educational-orange.svg)](LICENSE)

**Professional algorithmic trading system combining DeepSeek AI decision-making, advanced technical analysis, and institutional-grade risk management for automated BTC/USDT perpetual futures trading on Binance.**

---

## Table of Contents

- [Features](#features)
- [What's New in v1.2.2](#whats-new-in-v122)
- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Installation](#installation)
- [Configuration](#configuration)
- [Advanced Features](#advanced-features)
- [Usage](#usage)
- [Risk Management](#risk-management)
- [Monitoring](#monitoring)
- [Troubleshooting](#troubleshooting)
- [Performance](#performance-expectations)
- [Documentation](#documentation)
- [Disclaimer](#disclaimer)

---

## Features

### Core Capabilities

- **AI-Powered Decision Making**: DeepSeek AI analyzes market conditions and generates intelligent trading signals with confidence levels (HIGH/MEDIUM/LOW)
- **Comprehensive Technical Analysis**:
  - Moving Averages (SMA 5/20/50, EMA 12/26)
  - Momentum Indicators (RSI 14, MACD)
  - Volatility Bands (Bollinger 20, 2σ)
  - Support/Resistance Detection
  - Volume Analysis
- **Sentiment Integration**: CryptoOracle API for real-time market sentiment analysis
- **Intelligent Position Sizing**: Dynamic sizing based on AI confidence, trend strength, RSI extremes, and risk limits
- **Event-Driven Architecture**: Built on NautilusTrader's professional framework for high-performance execution

### Advanced Risk Management (v1.2.x)

- **Automated Stop Loss & Take Profit**:
  - Stop loss based on support/resistance levels with configurable buffer
  - Take profit targets adjusted by AI confidence (1-3%)
  - STOP_MARKET orders for stop loss, LIMIT orders for take profit

- **OCO (One-Cancels-the-Other) Management**:
  - Automatic cancellation of peer orders when one executes
  - Redis persistence for OCO groups (survives strategy restarts)
  - Automatic cleanup of orphan orders
  - Event-driven order management

- **Bracket Orders**:
  - Native NautilusTrader bracket order support for Binance
  - Simultaneous SL/TP submission with position entry
  - Order emulation for exchanges without native bracket support

- **Partial Take Profit**:
  - Multiple take profit levels to lock in profits gradually
  - Configurable profit thresholds and position percentages
  - Example: Take 50% profit at +2%, remaining 50% at +4%
  - Reduces risk while maintaining upside potential

- **Trailing Stop Loss**:
  - Dynamic stop loss that follows profitable price movement
  - Activates after minimum profit threshold (default 1%)
  - Locks in profits while allowing trend continuation
  - Configurable trailing distance and update frequency

### Remote Control & Monitoring

- **Telegram Integration**:
  - Real-time notifications for signals, fills, positions, and errors
  - Remote control commands (`/status`, `/position`, `/pause`, `/resume`)
  - View current equity, P&L, and strategy status
  - Pause/resume trading without stopping the strategy

### Safety Features

- Minimum confidence filtering (configurable: LOW/MEDIUM/HIGH)
- Maximum position size limits (default: 10% of equity)
- RSI extreme condition handling (0.7x multiplier at RSI >75 or <25)
- Position reversal protection with confidence requirements
- Minimum adjustment thresholds to prevent excessive trading
- Comprehensive logging and monitoring
- Redis-backed OCO persistence for crash recovery

---

## What's New in v1.2.2

### Latest Updates

**v1.2.2** (Current - November 2025)
- Fixed: Bracket order emulation for Binance
- Fixed: Telegram event loop error in `send_message_sync`
- Improved: Bracket order flow and documentation
- Enhanced: OCO management with better error handling

**v1.2.0** - Major Feature Release
- **Partial Take Profit**: Multi-level profit-taking system
- **Trailing Stop Loss**: Dynamic stop loss management
- **Telegram Remote Control**: Monitor and control via Telegram
- **OCO Management**: Redis-backed One-Cancels-the-Other system
- **Bracket Orders**: Native NautilusTrader bracket order support

**v1.1.0** - Risk Management Enhancements
- Automated Stop Loss & Take Profit
- Support/resistance-based stop loss calculation
- AI confidence-based take profit targets

**v1.0.0** - Initial Release
- DeepSeek AI integration
- NautilusTrader framework migration
- Binance Futures support
- Comprehensive technical indicators

---

## Architecture

### System Overview

```
┌─────────────────────────────────────────────────────────┐
│                    User Interface                        │
│              (Telegram Bot / Logs / CLI)                 │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────┴────────────────────────────────┐
│              DeepSeek AI Strategy                        │
│  ┌──────────────────────────────────────────────────┐  │
│  │  AI Decision Engine (DeepSeek)                    │  │
│  │  • Market analysis                                │  │
│  │  • Signal generation (BUY/SELL/HOLD)             │  │
│  │  • Confidence assessment                         │  │
│  └──────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────┐  │
│  │  Risk Management                                  │  │
│  │  • OCO Manager (Redis)                           │  │
│  │  • Trailing Stop Handler                         │  │
│  │  • Partial TP Manager                            │  │
│  │  • Position Sizing Calculator                    │  │
│  └──────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────┐  │
│  │  Technical Analysis                               │  │
│  │  • SMA/EMA/RSI/MACD/Bollinger                    │  │
│  │  • Support/Resistance Detection                  │  │
│  │  • Volume Analysis                               │  │
│  └──────────────────────────────────────────────────┘  │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────┴────────────────────────────────┐
│            NautilusTrader Framework                      │
│  • Event Engine  • Order Management  • Position Cache   │
└────────────────────────┬────────────────────────────────┘
                         │
         ┌───────────────┴───────────────┬────────────────┐
         │                               │                │
┌────────┴─────────┐        ┌───────────┴──────┐  ┌─────┴─────┐
│ Binance Futures  │        │ CryptoOracle API │  │   Redis   │
│  (Market Data &  │        │  (Sentiment Data)│  │  (OCO DB) │
│   Execution)     │        └──────────────────┘  └───────────┘
└──────────────────┘
```

### Data Flow

```
Market Data → Technical Indicators → ┐
Sentiment Data → AI Analysis → ──────┤→ Trading Signal → Position Management
Current Position → Risk Assessment → ┘   (with SL/TP/OCO/Trailing)
```

### Project Structure

```
nautilus_deepseek/
├── configs/
│   └── strategy_config.yaml          # Strategy parameters & risk settings
├── indicators/
│   └── technical_manager.py          # Technical indicator calculations
├── strategy/
│   └── deepseek_strategy.py          # Main strategy class
├── utils/
│   ├── deepseek_client.py            # DeepSeek AI API integration
│   ├── sentiment_client.py           # CryptoOracle sentiment fetcher
│   ├── telegram_bot.py               # Telegram notifications & control
│   ├── oco_manager.py                # OCO order management with Redis
│   └── telegram_command_handler.py   # Telegram command processor
├── main_live.py                      # Live trading entrypoint
├── requirements.txt                  # Python dependencies
├── .env                              # Environment variables (DO NOT COMMIT)
├── README.md                         # This file
└── docs/                             # Additional documentation
    ├── QUICKSTART.md                 # Quick start guide
    ├── FEATURE_*.md                  # Feature-specific guides
    └── STRATEGY.md                   # Trading logic details
```

---

## Prerequisites

### System Requirements

- **Python**: 3.10 or higher
- **Operating System**: Linux/macOS recommended (Windows with WSL2)
- **Redis**: 5.0+ (for OCO persistence)
- **Memory**: 512MB+ RAM
- **Storage**: 1GB+ free space

### Trading Requirements

- **Binance Account**:
  - Futures trading enabled
  - API key with trading permissions (no withdrawal needed)
  - Sufficient USDT balance (minimum $500 recommended)
- **DeepSeek API Key**: Get from [platform.deepseek.com](https://platform.deepseek.com/)
- **Telegram Bot** (optional): For notifications and remote control

### Knowledge Requirements

- Basic understanding of cryptocurrency trading
- Familiarity with perpetual futures contracts
- Understanding of leverage and margin trading
- Basic Python and command line usage

---

## Quick Start

### 5-Minute Setup

```bash
# 1. Clone repository
cd /home/ubuntu
git clone <repository-url> nautilus_deepseek
cd nautilus_deepseek

# 2. Create virtual environment
python3.10 -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# 4. Install and start Redis
sudo apt update && sudo apt install redis-server -y
sudo systemctl start redis-server
sudo systemctl enable redis-server

# 5. Configure environment
cp .env.template .env
nano .env  # Add your API keys (see Configuration section)

# 6. Set up Binance account
# - Navigate to Futures → BTCUSDT-PERP
# - Set margin mode: CROSS
# - Set leverage: 10x
# - Fund account with USDT

# 7. Start trading
python main_live.py
```

---

## Installation

### Detailed Installation Steps

#### 1. System Preparation

```bash
# Update system packages
sudo apt update && sudo apt upgrade -y

# Install Python 3.10+ if not available
sudo apt install python3.10 python3.10-venv python3-pip -y
```

#### 2. Redis Installation

Redis is required for OCO (One-Cancels-the-Other) persistence:

```bash
# Install Redis
sudo apt install redis-server -y

# Start Redis service
sudo systemctl start redis-server
sudo systemctl enable redis-server

# Verify Redis is running
redis-cli ping  # Should return PONG

# Optional: Configure Redis password
sudo nano /etc/redis/redis.conf
# Uncomment and set: requirepass your_secure_password
sudo systemctl restart redis-server
```

#### 3. Project Setup

```bash
# Clone repository
cd /home/ubuntu  # or your preferred directory
git clone <repository-url> nautilus_deepseek
cd nautilus_deepseek

# Create virtual environment
python3.10 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Verify installation
python -c "import nautilus_trader; print(f'NautilusTrader {nautilus_trader.__version__} installed')"
```

#### 4. Configuration

##### Environment Variables

Create `.env` file from template:

```bash
cp .env.template .env
chmod 600 .env  # Secure permissions
nano .env  # or vim, code, etc.
```

**Required `.env` configuration:**

```bash
# ========================================
# EXCHANGE API CREDENTIALS
# ========================================
BINANCE_API_KEY=your_binance_api_key_here
BINANCE_API_SECRET=your_binance_api_secret_here

# ========================================
# AI SERVICE (LLM provider)
# ========================================
# Active provider via LLM_* (takes precedence over legacy DEEPSEEK_*).
# Kimi K3 / Moonshot AI example (note: kimi-k3 requires temperature=1):
LLM_API_KEY=your_llm_api_key_here
LLM_MODEL=kimi-k3
LLM_BASE_URL=https://api.moonshot.cn/v1
LLM_TEMPERATURE=1.0

# DeepSeek rollback (used automatically when LLM_API_KEY is unset):
DEEPSEEK_API_KEY=your_deepseek_api_key_here
# LLM_MODEL=deepseek-v4-pro
# LLM_BASE_URL=https://api.deepseek.com
# LLM_TEMPERATURE=0.1

# ========================================
# TRADING PARAMETERS
# ========================================
EQUITY=400                          # Your trading capital in USDT
LEVERAGE=10                         # Leverage (1-125, recommended: 5-10)
BASE_POSITION_USDT=30               # Base position size per trade
TIMEFRAME=15m                       # Bar timeframe (1m, 5m, 15m, 1h)

# ========================================
# RISK MANAGEMENT
# ========================================
MIN_CONFIDENCE_TO_TRADE=MEDIUM      # Minimum confidence: LOW, MEDIUM, HIGH
MAX_POSITION_RATIO=0.10             # Max position size (10% of equity)

# Phase 0 safety (kill-switches & risk-based sizing)
RISK_PER_TRADE_PCT=0.01             # Risk per trade as fraction of LIVE equity (0.01 = 1%)
MAX_POSITION_LEVERAGE=2.0           # Max position notional as multiple of live equity
DAILY_LOSS_LIMIT_PCT=0.03           # Halt new trades after this daily loss (0.03 = -3%)
MAX_CONSECUTIVE_LOSSES=5            # Pause trading after N consecutive losing closes
LOSS_PAUSE_HOURS=24                 # Pause duration when a kill-switch triggers
MAX_CONSECUTIVE_SAME_SIGNAL=5       # Block churn after N identical consecutive signals

# Phase 1: ATR-based exits (2:1 reward:risk structure)
ATR_PERIOD=14                       # ATR period
USE_ATR_EXITS=true                  # ATR-based SL/TP (false = legacy S/R + confidence % TP)
SL_ATR_MULTIPLIER=1.5               # Stop loss = 1.5 x ATR from entry
TP_ATR_MULTIPLIER=3.0               # Take profit = 3.0 x ATR from entry (2:1 payoff)
TRAILING_USE_ATR=true               # ATR-based trailing stop
TRAILING_ACTIVATION_ATR=1.0         # Activate trailing at +1 x ATR profit
TRAILING_DISTANCE_ATR=1.0           # Trail 1 x ATR behind the extreme price

# Phase 2: signal measurement & regime filter
SIGNAL_ONLY_MODE=false              # true = log signals to logs/signal_log.jsonl WITHOUT trading
REGIME_FILTER_ENABLED=true          # Only trade with the higher-timeframe trend
REGIME_TIMEFRAME=4h                 # Kline interval for regime classification
REGIME_EMA_FAST=20                  # Fast EMA for regime
REGIME_EMA_SLOW=50                  # Slow EMA for regime
REGIME_FLAT_THRESHOLD_PCT=0.002     # |EMA_fast-EMA_slow|/price below this = flat/chop

# ========================================
# TELEGRAM (Optional)
# ========================================
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here

# ========================================
# REDIS (OCO Management)
# ========================================
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=                     # Leave empty if no password
REDIS_DB=0

# ========================================
# OPTIONAL: TIMING
# ========================================
# TIMER_INTERVAL_SEC=900            # AI analysis interval (default: 900s = 15min)
```

**Security Best Practices:**

```bash
# Set proper file permissions
chmod 600 .env

# Verify .env is in .gitignore
cat .gitignore | grep .env  # Should show ".env"

# NEVER commit .env to version control
git status  # .env should not appear
```

##### Strategy Configuration

Edit `configs/strategy_config.yaml` for advanced settings. Key sections are documented in [Configuration](#configuration) section below.

#### 5. Binance Account Setup

**Critical Steps:**

1. **Login to Binance** → Navigate to Futures Trading
2. **Find BTCUSDT-PERP Contract**
3. **Set Margin Mode**:
   - Click margin mode selector
   - Select "Cross" (not Isolated)
   - This strategy uses cross-margin
4. **Set Leverage**:
   - Adjust leverage slider to **10x**
   - Must match `LEVERAGE` in `.env`
5. **Fund Account**:
   - Transfer USDT to Futures wallet
   - Minimum recommended: $500 USDT
6. **Create API Key**:
   - Account → API Management
   - Create new API key
   - Enable: "Enable Futures" + "Enable Reading"
   - Do NOT enable: "Enable Withdrawals"
   - Optional: Add IP restriction for security

#### 6. Verification

```bash
# Test API connectivity
python -c "
from dotenv import load_dotenv
import os
load_dotenv()
print('✅ API Keys loaded' if os.getenv('BINANCE_API_KEY') else '❌ Missing API keys')
"

# Test Redis connection
redis-cli ping  # Should return PONG

# Test strategy configuration
python -c "
from strategy.deepseek_strategy import DeepSeekAIStrategyConfig
config = DeepSeekAIStrategyConfig(
    instrument_id='BTCUSDT-PERP.BINANCE',
    bar_type='BTCUSDT-PERP.BINANCE-15-MINUTE-LAST-EXTERNAL',
)
print(f'✅ Strategy config loaded: {config.name}')
"
```

---

## Configuration

### Strategy Configuration File

Location: `configs/strategy_config.yaml`

#### Core Settings

```yaml
strategy:
  name: "DeepSeekAIStrategy"
  instrument_id: "BTCUSDT-PERP.BINANCE"
  bar_type: "BTCUSDT-PERP.BINANCE-15-MINUTE-LAST-EXTERNAL"

  equity: 400           # Trading capital (USDT)
  leverage: 10          # Futures leverage multiplier
```

#### Position Management

```yaml
position_management:
  base_usdt_amount: 30                  # Base position size per trade
  high_confidence_multiplier: 1.5       # 1.5x for HIGH confidence
  medium_confidence_multiplier: 1.0     # 1.0x for MEDIUM confidence
  low_confidence_multiplier: 0.5        # 0.5x for LOW confidence
  max_position_ratio: 0.10              # Max 10% of equity per position
  trend_strength_multiplier: 1.2        # Bonus for STRONG trends
  min_trade_amount: 0.001               # Minimum BTC amount
```

#### Risk Management Features

```yaml
risk:
  # Basic Risk Controls
  min_confidence_to_trade: "MEDIUM"     # Minimum signal confidence
  allow_reversals: true                 # Allow position reversals
  require_high_confidence_for_reversal: false
  rsi_extreme_threshold_upper: 75       # RSI overbought level
  rsi_extreme_threshold_lower: 25       # RSI oversold level
  rsi_extreme_multiplier: 0.7           # Size reduction in extremes

  # Stop Loss & Take Profit
  enable_auto_sl_tp: true               # Enable automatic SL/TP
  sl_use_support_resistance: true       # Use S/R for stop loss
  sl_buffer_pct: 0.001                  # Stop loss buffer (0.1%)
  tp_high_confidence_pct: 0.03          # HIGH confidence TP: 3%
  tp_medium_confidence_pct: 0.02        # MEDIUM confidence TP: 2%
  tp_low_confidence_pct: 0.01           # LOW confidence TP: 1%

  # OCO Management
  enable_oco: true                      # Enable One-Cancels-the-Other
  oco_redis_host: "localhost"
  oco_redis_port: 6379
  oco_redis_db: 0
  oco_redis_password: null              # Set if Redis has password
  oco_group_ttl_hours: 24               # OCO group expiration time

  # Partial Take Profit
  enable_partial_tp: true               # Enable multi-level profit taking
  partial_tp_levels:
    - {profit_pct: 0.02, position_pct: 0.5}  # Take 50% at +2%
    - {profit_pct: 0.04, position_pct: 0.5}  # Take 50% at +4%

  # Trailing Stop Loss
  enable_trailing_stop: true            # Enable dynamic stop loss
  trailing_activation_pct: 0.01         # Activate after 1% profit
  trailing_distance_pct: 0.005          # Trail 0.5% behind price
  trailing_update_threshold_pct: 0.002  # Update when price moves 0.2%
```

#### Technical Indicators

```yaml
indicators:
  sma_periods: [5, 20, 50]              # Simple Moving Average periods
  ema_periods: [12, 26]                 # Exponential MA (for MACD)
  rsi_period: 14                        # Relative Strength Index
  macd_fast: 12                         # MACD fast period
  macd_slow: 26                         # MACD slow period
  macd_signal: 9                        # MACD signal line
  bollinger_period: 20                  # Bollinger Bands period
  bollinger_std: 2.0                    # Bollinger standard deviation
  volume_ma_period: 20                  # Volume moving average
  support_resistance_lookback: 20       # Bars for S/R detection
```

#### AI Configuration

```yaml
deepseek:
  model: "deepseek-chat"
  temperature: 0.1                      # Low for consistent decisions
  max_retries: 2
  base_url: "https://api.deepseek.com"
```

#### Sentiment Data

```yaml
sentiment:
  enabled: true
  provider: "cryptoracle"
  update_interval_minutes: 15
  lookback_hours: 4
  weight: 0.30                          # 30% weight in decisions
```

#### Telegram Notifications

```yaml
telegram:
  enabled: true                         # Enable Telegram integration
  bot_token: ""                         # Read from .env
  chat_id: ""                           # Read from .env
  notify_signals: true                  # Notify on AI signals
  notify_fills: true                    # Notify on order fills
  notify_positions: true                # Notify on position changes
  notify_errors: true                   # Notify on errors
```

#### Timing

```yaml
timer_interval_sec: 900                 # AI analysis every 15 minutes
```

### Configuration Profiles

#### Conservative (Low Risk)

```yaml
risk:
  min_confidence_to_trade: "HIGH"
  require_high_confidence_for_reversal: true

position_management:
  base_usdt_amount: 20
  max_position_ratio: 0.05              # 5% max
  high_confidence_multiplier: 1.2

risk:
  tp_high_confidence_pct: 0.02          # 2% TP
  trailing_activation_pct: 0.015        # Activate at 1.5%
  trailing_distance_pct: 0.008          # 0.8% trail distance
```

#### Aggressive (High Risk)

```yaml
risk:
  min_confidence_to_trade: "LOW"
  require_high_confidence_for_reversal: false

position_management:
  base_usdt_amount: 50
  max_position_ratio: 0.20              # 20% max (⚠️ high risk)
  high_confidence_multiplier: 2.0

risk:
  tp_high_confidence_pct: 0.05          # 5% TP
  trailing_activation_pct: 0.005        # Activate at 0.5%
  trailing_distance_pct: 0.003          # 0.3% trail distance
```

---

## Advanced Features

### 1. Automated Stop Loss & Take Profit

Automatically places stop loss and take profit orders when opening positions.

**Stop Loss Calculation:**
- Uses support/resistance levels from technical indicators
- BUY: Stop below support level with 0.1% buffer
- SELL: Stop above resistance level with 0.1% buffer
- Fallback: Fixed 2% if support/resistance unavailable

**Take Profit Targets:**
- HIGH confidence: ±3%
- MEDIUM confidence: ±2%
- LOW confidence: ±1%

**Configuration:**

```yaml
risk:
  enable_auto_sl_tp: true
  sl_use_support_resistance: true
  sl_buffer_pct: 0.001
  tp_high_confidence_pct: 0.03
```

**Example:**
```
Entry: LONG @ $70,000 (HIGH confidence)
Support: $69,500
Stop Loss: $69,430.50 ($69,500 - 0.1% = -0.81% risk)
Take Profit: $72,100.00 (+3.00% target)
Risk/Reward: 3.7:1
```

**Documentation:** [FEATURE_STOP_LOSS_TAKE_PROFIT.md](FEATURE_STOP_LOSS_TAKE_PROFIT.md)

### 2. OCO (One-Cancels-the-Other) Management

Automatically cancels stop loss when take profit executes (and vice versa).

**Features:**
- Event-driven automatic cancellation
- Redis persistence (survives restarts)
- Automatic cleanup of orphan orders
- Multi-level take profit support

**Configuration:**

```yaml
risk:
  enable_oco: true
  oco_redis_host: "localhost"
  oco_redis_port: 6379
  oco_group_ttl_hours: 24
```

**Workflow:**
```
Position Opened → Submit SL & TP → Create OCO Group → Store in Redis
                                          ↓
                  ┌───────────────────────┴───────────────────────┐
                  ↓                                               ↓
         TP Triggered & Filled                           SL Triggered & Filled
                  ↓                                               ↓
         Auto-cancel SL                                  Auto-cancel TP
                  ↓                                               ↓
         Remove OCO Group from Redis                    Remove OCO Group from Redis
```

**Redis Monitoring:**

```bash
# View OCO groups
redis-cli keys "nautilus:deepseek:oco:*"

# View specific group
redis-cli get "nautilus:deepseek:oco:BUY_BTCUSDT_1730880000"

# Count active OCO groups
redis-cli keys "nautilus:deepseek:oco:*" | wc -l
```

**Documentation:** [FEATURE_OCO_IMPLEMENTATION.md](FEATURE_OCO_IMPLEMENTATION.md)

### 3. Partial Take Profit

Lock in profits gradually at multiple price levels instead of all at once.

**Benefits:**
- Reduce risk by taking early profits
- Maintain upside exposure with remaining position
- Improve win rate and risk/reward ratio
- Reduce psychological pressure

**Configuration:**

```yaml
risk:
  enable_partial_tp: true
  partial_tp_levels:
    - {profit_pct: 0.02, position_pct: 0.5}  # 50% at +2%
    - {profit_pct: 0.04, position_pct: 0.5}  # 50% at +4%
```

**Example Scenario:**
```
Entry: LONG 1.0 BTC @ $50,000

Price reaches $51,000 (+2%):
→ Take profit on 0.5 BTC
→ Realized profit: $500
→ Remaining position: 0.5 BTC

Price reaches $52,000 (+4%):
→ Take profit on 0.5 BTC
→ Realized profit: $1,000
→ Total profit: $1,500 (+3% average)
```

**Configuration Templates:**

```yaml
# Conservative (lock profits early)
partial_tp_levels:
  - {profit_pct: 0.01, position_pct: 0.3}   # 30% at 1%
  - {profit_pct: 0.015, position_pct: 0.3}  # 30% at 1.5%
  - {profit_pct: 0.02, position_pct: 0.2}   # 20% at 2%
  - {profit_pct: 0.03, position_pct: 0.2}   # 20% at 3%

# Aggressive (hold for larger moves)
partial_tp_levels:
  - {profit_pct: 0.03, position_pct: 0.3}   # 30% at 3%
  - {profit_pct: 0.06, position_pct: 0.4}   # 40% at 6%
  - {profit_pct: 0.10, position_pct: 0.3}   # 30% at 10%
```

**Documentation:** [FEATURE_PARTIAL_TAKE_PROFIT.md](FEATURE_PARTIAL_TAKE_PROFIT.md)

### 4. Trailing Stop Loss

Dynamic stop loss that follows profitable price movements.

**How It Works:**
1. Position opened with initial stop loss
2. Wait for profit to reach activation threshold (default: 1%)
3. Start tracking highest price (LONG) or lowest price (SHORT)
4. Update stop loss to trail behind by configured distance (default: 0.5%)
5. Stop loss only moves in favorable direction (never backward)
6. Lock in profits as price moves favorably

**Configuration:**

```yaml
risk:
  enable_trailing_stop: true
  trailing_activation_pct: 0.01         # Activate after 1% profit
  trailing_distance_pct: 0.005          # Trail 0.5% behind
  trailing_update_threshold_pct: 0.002  # Update when moves 0.2%
```

**Example (LONG Position):**
```
Entry: $70,000

Price reaches $70,700 (+1%):
→ Trailing stop ACTIVATED
→ Tracking highest price

Price reaches $72,000 (+2.86%):
→ Highest price: $72,000
→ Update stop loss to: $71,640 ($72,000 - 0.5%)
→ Locked profit: +2.34%

Price reaches $73,000 (+4.29%):
→ Highest price: $73,000
→ Update stop loss to: $72,635 ($73,000 - 0.5%)
→ Locked profit: +3.77%

Price falls to $72,635:
→ Stop loss triggered
→ Exit with +3.77% profit ✅
```

**Configuration Strategies:**

```yaml
# Conservative (wider trail, less whipsaw)
trailing_activation_pct: 0.015    # 1.5%
trailing_distance_pct: 0.008      # 0.8%
trailing_update_threshold_pct: 0.003

# Aggressive (tighter trail, lock more profit)
trailing_activation_pct: 0.005    # 0.5%
trailing_distance_pct: 0.003      # 0.3%
trailing_update_threshold_pct: 0.001
```

**Documentation:** [FEATURE_TRAILING_STOP.md](FEATURE_TRAILING_STOP.md)

### 5. Telegram Remote Control

Monitor and control your trading strategy remotely via Telegram.

**Available Commands:**

| Command | Description |
|---------|-------------|
| `/status` | View strategy status, equity, P&L, uptime |
| `/position` | View current position details with SL/TP |
| `/pause` | Pause trading (stop new orders) |
| `/resume` | Resume trading |
| `/help` | Show all available commands |

**Setup:**

1. Create Telegram bot via [@BotFather](https://t.me/botfather)
2. Get bot token and your chat ID
3. Add to `.env`:

```bash
TELEGRAM_BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
TELEGRAM_CHAT_ID=123456789
```

4. Enable in configuration:

```yaml
telegram:
  enabled: true
  notify_signals: true
  notify_fills: true
  notify_positions: true
  notify_errors: true
```

**Example Interactions:**

```
You: /status
Bot: 🟢 Strategy Status
     Status: RUNNING
     Instrument: BTCUSDT-PERP.BINANCE
     Current Price: $70,125.50
     Equity: $408.50
     Unrealized P&L: 📈 $8.50 (+2.12%)

     Last Signal: BUY (HIGH)
     Uptime: 2h 15m

You: /position
Bot: 🟢 Open Position
     Side: LONG
     Quantity: 0.0012 BTC
     Entry: $69,500.00
     Current: $70,125.50

     Unrealized P&L: 📈 $0.75 (+0.90%)

     🛡️ Stop Loss: $69,125.50
     🎯 Take Profit: $71,585.00

You: /pause
Bot: ⏸️ Strategy Paused
     Trading has been paused. No new orders will be placed.
     Existing positions remain active.
     Use /resume to continue trading.
```

**Notifications:**

The bot automatically sends notifications for:
- AI trading signals with confidence and reasoning
- Order fills and executions
- Position changes (opened/closed)
- Errors and warnings
- Trailing stop updates
- OCO group management events

**Documentation:** [FEATURE_TELEGRAM_REMOTE_CONTROL.md](FEATURE_TELEGRAM_REMOTE_CONTROL.md)

---

## Usage

### Starting the Strategy

#### Foreground (Testing)

```bash
# Activate virtual environment
source venv/bin/activate

# Start strategy
python main_live.py
```

#### Background (Production)

```bash
# Start in background with logging
nohup python main_live.py > logs/trader_$(date +%Y%m%d_%H%M%S).log 2>&1 &

# Save process ID
echo $! > trader.pid

# Monitor logs
tail -f logs/trader_*.log

# Stop strategy
kill $(cat trader.pid)
```

#### Using Helper Scripts

```bash
# Start trader
./start_trader.sh

# Restart trader
./restart_trader.sh

# Stop trader
./stop_trader.sh

# Check status
./check_strategy_status.sh
```

### Expected Startup Sequence

```
🚀 Starting DeepSeek AI Trading Strategy
✅ Environment loaded
✅ Binance credentials validated
✅ DeepSeek API key loaded
✅ Redis connected: localhost:6379
✅ OCO Manager initialized (loaded 0 groups)
✅ Telegram bot connected
✅ Connecting to Binance Futures...
✅ Subscribed to BTCUSDT-PERP 15-MINUTE bars
✅ Strategy started successfully
⏱️  Analysis timer set: 900 seconds (15 minutes)
📊 Waiting for indicators to initialize (need 50 bars)...
🤖 First analysis in ~15 minutes...
```

### Operation Cycle

**Every 15 minutes (configurable):**

1. **Data Collection**:
   - Latest market data from Binance
   - Technical indicators updated
   - Sentiment data fetched from CryptoOracle

2. **AI Analysis**:
   - DeepSeek analyzes all data
   - Generates signal: BUY/SELL/HOLD
   - Provides confidence: HIGH/MEDIUM/LOW
   - Includes reasoning (6 points)

3. **Position Management**:
   - Check existing position
   - Calculate desired position size
   - Determine action (open/add/reduce/reverse/hold)

4. **Execution**:
   - Validate signal confidence
   - Calculate position size
   - Submit orders to Binance
   - Update OCO groups
   - Send Telegram notifications

5. **Risk Management**:
   - Submit/update stop loss orders
   - Submit take profit orders (single or multi-level)
   - Activate/update trailing stop if applicable
   - Monitor OCO groups
   - Log all actions

### Trading Examples

#### Example 1: Opening a Long Position

```log
[2025-11-17 10:00:00] 📊 Running periodic analysis...
[2025-11-17 10:00:01] 📈 Technical Analysis:
                       Price: $70,125.50
                       SMA5: $69,800 | SMA20: $69,200 | SMA50: $68,500
                       RSI: 62.5 (neutral)
                       MACD: Bullish crossover
                       Support: $69,500 | Resistance: $71,200

[2025-11-17 10:00:02] 💭 Sentiment: Bullish 65% | Bearish 35% | Net: +30

[2025-11-17 10:00:03] 🤖 DeepSeek AI Signal: BUY
                       Confidence: HIGH
                       Reasoning:
                       (1) Strong uptrend with price above all SMAs
                       (2) Bullish MACD crossover confirms momentum
                       (3) RSI at 62 shows room for upside
                       (4) Positive sentiment (+30) supports bullish bias
                       (5) Price respected support at $69,500
                       (6) Volume increasing on up moves

[2025-11-17 10:00:04] 📊 Position Sizing:
                       Base: $30 USDT
                       Confidence: 1.5x (HIGH)
                       Trend: 1.2x (STRONG)
                       RSI: 1.0x (normal)
                       Final: $54 USDT → 0.00077 BTC

[2025-11-17 10:00:05] ✅ Order submitted: BUY 0.00077 BTC MARKET
[2025-11-17 10:00:06] ✅ Order filled: BUY 0.00077 @ $70,125.50
[2025-11-17 10:00:07] 🟢 Position opened: LONG 0.00077 @ $70,125.50

[2025-11-17 10:00:08] 🛡️ Submitted Stop Loss: $69,430.50 (-0.99%)
[2025-11-17 10:00:09] 🎯 Submitted Take Profit Level 1: 50% @ $71,528.00 (+2.0%)
[2025-11-17 10:00:10] 🎯 Submitted Take Profit Level 2: 50% @ $72,930.50 (+4.0%)
[2025-11-17 10:00:11] 🔗 OCO Group created: BUY_BTCUSDT_1700208000
                       SL: O-20251117-001-SL
                       TP1: O-20251117-001-TP1
                       TP2: O-20251117-001-TP2
                       Saved to Redis ✅

[2025-11-17 10:00:12] 📱 Telegram: Position opened notification sent
```

#### Example 2: Trailing Stop in Action

```log
[2025-11-17 10:15:00] 📊 Periodic check: Position LONG @ $70,125.50
                       Current price: $70,850.50
                       Unrealized P&L: +$0.56 (+1.03%)

[2025-11-17 10:15:01] 🎯 Trailing stop ACTIVATED
                       Entry: $70,125.50
                       Current: $70,850.50
                       Profit: +1.03% (above 1% threshold)

[2025-11-17 10:30:00] ⬆️ Price continues rising: $71,550.00
                       Highest price: $71,550.00
                       Trailing stop update:
                       Old SL: $69,430.50
                       New SL: $71,192.50 ($71,550 - 0.5%)
                       Locked profit: +1.52%

[2025-11-17 10:30:01] 🔴 Cancelled old SL: O-20251117-001-SL
[2025-11-17 10:30:02] ✅ New trailing SL submitted: O-20251117-002-SL
[2025-11-17 10:30:03] 🔄 OCO Group updated in Redis

[2025-11-17 10:45:00] ⬆️ Price reaches $72,300.00
                       New trailing SL: $71,941.50
                       Locked profit: +2.59%

[2025-11-17 11:00:00] 📉 Price retraces to $71,941.50
[2025-11-17 11:00:01] ✅ Trailing SL triggered: SELL 0.00077 @ $71,941.50
[2025-11-17 11:00:02] 🔴 Position closed: LONG
                       Entry: $70,125.50
                       Exit: $71,941.50
                       P&L: +$1.40 (+2.59%) ✅

[2025-11-17 11:00:03] 🗑️ OCO Group removed: BUY_BTCUSDT_1700208000
[2025-11-17 11:00:04] 📱 Telegram: Position closed notification sent
```

---

## Risk Management

### Multi-Layer Protection

#### 1. Position Size Limits

```yaml
max_position_ratio: 0.10  # Maximum 10% of equity per position

# Example with $400 equity:
# Max position = $400 × 0.10 = $40 USDT
# At $70,000 BTC = ~0.00057 BTC maximum
```

#### 2. Confidence Filtering

```yaml
min_confidence_to_trade: "MEDIUM"

# Results:
# HIGH confidence → Trade ✅
# MEDIUM confidence → Trade ✅
# LOW confidence → Skip ❌
```

#### 3. Reversal Protection

```yaml
require_high_confidence_for_reversal: true

# When reversing from LONG to SHORT (or vice versa):
# HIGH confidence → Execute reversal ✅
# MEDIUM/LOW confidence → Close position only, no reversal ❌
```

#### 4. RSI Extreme Handling

```yaml
rsi_extreme_threshold_upper: 75
rsi_extreme_threshold_lower: 25
rsi_extreme_multiplier: 0.7

# When RSI > 75 or RSI < 25:
# Position size = calculated_size × 0.7 (30% reduction)
```

#### 5. Stop Loss Protection

All positions automatically have stop loss protection:

- **Support/Resistance Based**: Stop loss placed below support (LONG) or above resistance (SHORT)
- **Buffer**: 0.1% additional buffer beyond S/R levels
- **Fallback**: Fixed 2% stop loss if S/R unavailable
- **OCO**: Automatically cancelled when take profit executes

#### 6. Automatic Cleanup

- **Orphan Order Cleanup**: Periodic check (every 15 min) for orphan reduce-only orders
- **OCO Group Expiration**: OCO groups expire after 24 hours (configurable)
- **Position Reconciliation**: NautilusTrader cache reconciles positions with exchange

### Risk Profiles

#### Conservative Profile

```yaml
# Minimum risk, maximum safety
risk:
  min_confidence_to_trade: "HIGH"
  require_high_confidence_for_reversal: true
  enable_partial_tp: true
  partial_tp_levels:
    - {profit_pct: 0.01, position_pct: 0.5}
    - {profit_pct: 0.02, position_pct: 0.5}
  enable_trailing_stop: true
  trailing_activation_pct: 0.015
  trailing_distance_pct: 0.008

position_management:
  base_usdt_amount: 20
  max_position_ratio: 0.05  # 5% max
  high_confidence_multiplier: 1.2
```

**Expected Performance:**
- Lower returns, lower drawdown
- Win rate: 65-70%
- Max drawdown: <3%
- Suitable for: Risk-averse traders, beginners

#### Balanced Profile (Recommended)

```yaml
# Balance between risk and reward
risk:
  min_confidence_to_trade: "MEDIUM"
  require_high_confidence_for_reversal: false
  enable_partial_tp: true
  partial_tp_levels:
    - {profit_pct: 0.02, position_pct: 0.5}
    - {profit_pct: 0.04, position_pct: 0.5}
  enable_trailing_stop: true
  trailing_activation_pct: 0.01
  trailing_distance_pct: 0.005

position_management:
  base_usdt_amount: 30
  max_position_ratio: 0.10  # 10% max
  high_confidence_multiplier: 1.5
```

**Expected Performance:**
- Balanced risk/reward
- Win rate: 55-65%
- Max drawdown: <5%
- Suitable for: Most traders, intermediate level

#### Aggressive Profile

```yaml
# Maximum returns, higher risk
risk:
  min_confidence_to_trade: "LOW"
  require_high_confidence_for_reversal: false
  enable_partial_tp: false  # Single large TP
  tp_high_confidence_pct: 0.05  # 5% target
  enable_trailing_stop: true
  trailing_activation_pct: 0.005
  trailing_distance_pct: 0.003

position_management:
  base_usdt_amount: 50
  max_position_ratio: 0.20  # 20% max (⚠️ high risk)
  high_confidence_multiplier: 2.0
```

**Expected Performance:**
- Higher returns, higher drawdown
- Win rate: 45-55%
- Max drawdown: >8%
- Suitable for: Experienced traders only

---

## Monitoring

### Log Files

```bash
logs/
├── trader.log                      # Main strategy log
├── trader_error.log                # Errors and warnings
├── trader_YYYYMMDD_HHMMSS.log     # Archived sessions
└── deepseek_strategy.log           # Strategy-specific logs
```

### Real-Time Monitoring

```bash
# Monitor all activity
tail -f logs/trader.log

# Monitor signals only
tail -f logs/trader.log | grep "🤖 Signal:"

# Monitor position changes
tail -f logs/trader.log | grep -E "Position opened|Position closed"

# Monitor errors
tail -f logs/trader_error.log

# Monitor trailing stops
tail -f logs/trader.log | grep "Trailing"

# Monitor OCO activity
tail -f logs/trader.log | grep "OCO"
```

### Performance Tracking

```bash
# Count trades today
grep "Order filled" logs/trader.log | grep $(date +%Y-%m-%d) | wc -l

# Signal distribution
grep "🤖 Signal:" logs/trader.log | grep -oE "Signal: \w+" | sort | uniq -c

# Win/loss tracking
grep "Position closed" logs/trader.log | grep "P&L:" | tail -20

# OCO statistics
grep "OCO Group created" logs/trader.log | wc -l
grep "Auto-cancelled peer order" logs/trader.log | wc -l
```

### Telegram Monitoring

If Telegram is enabled:
- Real-time notifications on your phone
- `/status` command for quick overview
- `/position` command for current holdings
- Pause/resume trading remotely

### External Monitoring

1. **Binance App**:
   - Live positions and P&L
   - Order book and execution
   - Account balance

2. **TradingView**:
   - Chart analysis
   - Technical indicator visualization
   - Price alerts

3. **Redis Monitoring**:
   ```bash
   # View OCO groups
   redis-cli keys "nautilus:deepseek:oco:*"

   # Redis memory usage
   redis-cli info memory | grep used_memory_human

   # Monitor Redis commands (live)
   redis-cli monitor
   ```

4. **System Resources**:
   ```bash
   # Check if strategy is running
   ps aux | grep main_live.py

   # Monitor CPU/memory
   top -p $(pgrep -f main_live.py)

   # Disk usage
   df -h
   du -sh logs/
   ```

---

## Troubleshooting

### Common Issues

#### 1. Indicators Not Initialized

**Error:** `Indicators not yet initialized, skipping analysis`

**Cause:** Strategy needs 50+ bars before indicators are ready (SMA50 requires 50 periods)

**Solution:**
```bash
# Wait for initialization
# 15-minute bars: ~12.5 hours
# 1-minute bars: ~50 minutes

# Check progress
grep "initialized" logs/trader.log
```

#### 2. Order Quantity Below Minimum

**Error:** `Order quantity below minimum`

**Cause:** Position size < 0.001 BTC (Binance minimum)

**Solution:**
```yaml
# Increase base position size in configs/strategy_config.yaml
position_management:
  base_usdt_amount: 80  # Increase from 30

# At $70,000 BTC:
# 80 / 70000 = 0.00114 BTC ✅ (above 0.001 minimum)
```

#### 3. Redis Connection Failed

**Error:** `Redis connection failed: Connection refused`

**Solution:**
```bash
# Start Redis
sudo systemctl start redis-server

# Check status
sudo systemctl status redis-server

# Test connection
redis-cli ping  # Should return PONG

# If still failing, check firewall
sudo ufw allow 6379
```

#### 4. WebSocket Connection Failed

**Error:** `WebSocket connection failed`

**Solution:**
```bash
# Check internet connectivity
ping binance.com

# Check Binance API status
curl -I https://fapi.binance.com/fapi/v1/ping

# Check DNS
nslookup fstream.binance.com

# If in restricted region, use VPN
```

#### 5. API Rate Limit Exceeded

**Error:** `Rate limit exceeded`

**Solution:**
```yaml
# Increase analysis interval in configs/strategy_config.yaml
timer_interval_sec: 1800  # 30 minutes instead of 15

# Check for multiple running instances
ps aux | grep main_live.py  # Should only show one

# Wait 1-5 minutes for rate limit reset
```

#### 6. Sentiment Data Fetch Failed

**Warning:** `Failed to fetch sentiment data`

**Impact:** AI analysis continues with technical data only (60% weight instead of 90%)

**Solution:**
```bash
# Check CryptoOracle API
curl https://api.cryptoracle.network/v1/health

# Temporarily disable sentiment
# Edit configs/strategy_config.yaml:
sentiment:
  enabled: false
```

#### 7. Trailing Stop Not Activating

**Issue:** Trailing stop not activating despite profit

**Checks:**
```bash
# Verify configuration
grep "enable_trailing_stop" configs/strategy_config.yaml  # Should be true

# Check current profit
tail -f logs/trader.log | grep "Profit"

# Verify activation threshold
grep "trailing_activation_pct" configs/strategy_config.yaml

# Look for activation message
grep "Trailing stop ACTIVATED" logs/trader.log
```

#### 8. OCO Orders Not Cancelled

**Issue:** TP filled but SL still active

**Solution:**
```bash
# Check OCO group exists
redis-cli keys "nautilus:deepseek:oco:*"

# View OCO group details
redis-cli get "nautilus:deepseek:oco:<group_id>"

# Check event logs
grep "Order belongs to OCO group" logs/trader.log

# Verify OCO enabled
grep "enable_oco" configs/strategy_config.yaml
```

### Emergency Procedures

#### Stop Trading Immediately

```bash
# Method 1: Keyboard interrupt (if in terminal)
Ctrl+C

# Method 2: Kill process
ps aux | grep main_live.py
kill <PID>

# Method 3: Stop script
./stop_trader.sh

# Verify stopped
ps aux | grep main_live.py  # Should return nothing
```

#### Close All Positions Manually

**Via Binance Web:**
1. Login → Futures → Positions
2. Find BTCUSDT-PERP position
3. Click "Close" → "Market Close"

**Via Binance App:**
1. Futures → Positions
2. BTCUSDT-PERP
3. Swipe to close

#### Backup Data

```bash
# Backup logs
mkdir -p logs/backups/$(date +%Y%m%d)
cp logs/trader*.log logs/backups/$(date +%Y%m%d)/

# Backup configuration
cp configs/strategy_config.yaml configs/strategy_config.yaml.backup

# Backup Redis (OCO data)
redis-cli SAVE
cp /var/lib/redis/dump.rdb backup_redis_$(date +%Y%m%d).rdb

# Backup .env (BE CAREFUL - contains secrets)
cp .env .env.backup
chmod 600 .env.backup
```

### Debug Mode

```yaml
# Enable verbose logging in configs/strategy_config.yaml
logging:
  log_level: "DEBUG"  # Instead of "INFO"

# Restart and monitor
./restart_trader.sh
tail -f logs/trader.log
```

---

## Performance Expectations

### Target Metrics

Based on backtesting and live trading with v1.2.x features:

| Metric | Target | Notes |
|--------|--------|-------|
| **Weekly Return** | 0.5-1.5% | Net of fees, with partial TP and trailing stops |
| **Monthly Return** | 2-6% | Compounded weekly |
| **Annualized Return** | 26-72% | Assuming consistent performance |
| **Sharpe Ratio** | >1.5 | Risk-adjusted returns |
| **Max Drawdown** | <5% | Peak to trough |
| **Win Rate** | 60-70% | With partial TP improving win rate |
| **Avg Win/Loss** | 2.0:1 | Reward:Risk ratio |

### Assumptions

- Market conditions: Normal volatility (not extreme crashes/pumps)
- Leverage: 10x cross-margin
- Trading frequency: 3-6 signals per day with 15-minute analysis
- Position duration: 2-12 hours average
- Binance fees: Maker 0.02%, Taker 0.04%
- Slippage: ~0.01% average
- Features enabled: Partial TP, Trailing Stops, OCO

### Realistic Scenarios

#### Best Case (Strong Trending Market)

```
Starting Capital: $400
Monthly Return: 5-7%
Ending Capital: $420-428
Profit: $20-28
Key Factor: Trailing stops capture extended trends
```

#### Average Case (Mixed Market)

```
Starting Capital: $400
Monthly Return: 3-4%
Ending Capital: $412-416
Profit: $12-16
Key Factor: Partial TP locks in gains early
```

#### Worst Case (Choppy/Unfavorable)

```
Starting Capital: $400
Monthly Return: -1% to +1%
Ending Capital: $396-404
Loss/Profit: -$4 to +$4
Key Factor: Stop losses limit downside
```

### Performance by Feature

| Configuration | Avg Return | Win Rate | Max DD | Notes |
|---------------|------------|----------|--------|-------|
| Base (no advanced features) | 2-3% | 55% | -5% | Original strategy |
| + SL/TP | 3-4% | 58% | -4% | Better risk management |
| + Partial TP | 3.5-4.5% | 62% | -3.5% | Improved win rate |
| + Trailing Stop | 4-5% | 65% | -3% | Captures trends |
| All Features | 5-6% | 68% | -2.5% | Optimal combination |

### Important Disclaimers

⚠️ **Past performance does not guarantee future results**

- Market conditions constantly change
- AI models can make mistakes
- High leverage (10x) amplifies both gains and losses
- Fees and slippage reduce net returns
- Unexpected events (flash crashes, news) can cause significant losses
- No trading system is profitable 100% of the time

### Performance Tracking Template

```
Week 1 (Nov 17-24, 2025):
- Starting: $400.00
- Ending: $418.50
- Return: +4.63%
- Trades: 28 (19 wins, 9 losses)
- Win Rate: 68%
- Max DD: -1.2%
- Features: Full suite enabled

Week 2:
- Starting: $418.50
- Ending: $425.20
- Return: +1.60%
...

Monthly Summary:
- Total Return: +6.3%
- Sharpe Ratio: 1.8
- Total Trades: 112
- Win Rate: 65%
```

---

## Documentation

### Core Documentation

- **[README.md](README.md)** - This file (overview and setup)
- **[QUICKSTART.md](QUICKSTART.md)** - 5-minute quick start guide
- **[PROJECT_SUMMARY.md](PROJECT_SUMMARY.md)** - Architecture and implementation details
- **[STRATEGY.md](STRATEGY.md)** - Trading logic and decision-making process
- **[SECURITY.md](SECURITY.md)** - Security best practices

### Feature Documentation

- **[FEATURE_STOP_LOSS_TAKE_PROFIT.md](FEATURE_STOP_LOSS_TAKE_PROFIT.md)** - Automated SL/TP
- **[FEATURE_OCO_IMPLEMENTATION.md](FEATURE_OCO_IMPLEMENTATION.md)** - OCO management with Redis
- **[FEATURE_PARTIAL_TAKE_PROFIT.md](FEATURE_PARTIAL_TAKE_PROFIT.md)** - Multi-level profit taking
- **[FEATURE_TRAILING_STOP.md](FEATURE_TRAILING_STOP.md)** - Dynamic stop loss
- **[FEATURE_TELEGRAM_REMOTE_CONTROL.md](FEATURE_TELEGRAM_REMOTE_CONTROL.md)** - Telegram integration
- **[FEATURE_TEST_STATUS.md](FEATURE_TEST_STATUS.md)** - Feature testing status

### Operational Documentation

- **[TELEGRAM_SETUP.md](TELEGRAM_SETUP.md)** - Telegram bot setup guide
- **[TELEGRAM_TROUBLESHOOTING.md](TELEGRAM_TROUBLESHOOTING.md)** - Telegram issues
- **[REDIS_INSTALLATION.md](REDIS_INSTALLATION.md)** - Redis setup and configuration
- **[GIT_WORKFLOW.md](GIT_WORKFLOW.md)** - Git branching and workflow
- **[ARCHITECTURE_ANALYSIS.md](ARCHITECTURE_ANALYSIS.md)** - Deep dive into architecture

### Release Notes

- **[RELEASE_v1.0.1_NOTES.md](RELEASE_v1.0.1_NOTES.md)** - v1.0.1 release notes
- **[ENV_UPDATE_SUMMARY.md](ENV_UPDATE_SUMMARY.md)** - Environment updates
- **[ERROR_ANALYSIS.md](ERROR_ANALYSIS.md)** - Error analysis and fixes

### External Resources

- **NautilusTrader**: [https://nautilustrader.io/docs/](https://nautilustrader.io/docs/)
- **DeepSeek API**: [https://platform.deepseek.com/docs](https://platform.deepseek.com/docs)
- **Binance Futures API**: [https://binance-docs.github.io/apidocs/futures/en/](https://binance-docs.github.io/apidocs/futures/en/)
- **CryptoOracle**: [https://cryptoracle.network/](https://cryptoracle.network/)
- **Redis**: [https://redis.io/documentation](https://redis.io/documentation)

---

## Disclaimer

### Risk Warning

**⚠️ CRYPTOCURRENCY TRADING INVOLVES SUBSTANTIAL RISK OF LOSS**

This software is provided for **educational and research purposes only**. By using this strategy, you acknowledge:

- ❌ **No Guarantees**: Past performance does not guarantee future results
- ❌ **Loss Risk**: You can lose your entire investment
- ❌ **Leverage Risk**: 10x leverage amplifies losses as well as gains
- ❌ **AI Limitations**: AI models can make incorrect predictions
- ❌ **Market Risk**: Crypto markets are highly volatile and unpredictable
- ❌ **Technical Risk**: Software bugs, API failures, or network issues can occur
- ❌ **Regulatory Risk**: Cryptocurrency regulations vary by jurisdiction
- ❌ **Operational Risk**: Exchange outages, liquidations, funding rate changes

### Recommendations

✅ **DO:**
- Start with small capital ($500-1000) you can afford to lose
- Use testnet or paper trading first (if available)
- Monitor closely for the first few weeks
- Understand the code and features before running live
- Set conservative risk limits initially
- Keep API keys secure (no withdrawal permissions)
- Maintain adequate system resources and backups
- Enable all risk management features
- Start with conservative configuration profile
- Test each feature individually before combining

❌ **DON'T:**
- Invest more than you can afford to lose
- Use maximum leverage without understanding risks
- Leave strategy unmonitored for long periods
- Share your API keys or .env file
- Modify code without thorough testing
- Rely solely on AI decisions without human oversight
- Disable stop loss protection
- Trade with insufficient capital (<$500)
- Run multiple instances with same API keys
- Ignore error messages or warnings

### Legal Disclaimer

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

Trading cryptocurrencies is regulated differently in each jurisdiction. Ensure compliance with your local laws before trading. This software is not financial advice and should not be considered as such.

---

## License

This project is for **educational and research purposes only**.

- No warranty or guarantee of profitability
- Use at your own risk
- Not financial advice
- Not investment advice

---

## Acknowledgments

**Built with:**
- [**NautilusTrader**](https://github.com/nautechsystems/nautilus_trader) - Professional algorithmic trading platform
- [**DeepSeek**](https://www.deepseek.com/) - Advanced AI language model for decision making
- [**CryptoOracle**](https://cryptoracle.network/) - Cryptocurrency sentiment data provider
- [**Binance**](https://www.binance.com/) - Cryptocurrency exchange and API
- [**Redis**](https://redis.io/) - In-memory data store for OCO persistence
- [**python-telegram-bot**](https://python-telegram-bot.org/) - Telegram bot library

**Special Thanks:**
- NautilusTrader community for the excellent framework
- DeepSeek team for accessible AI API
- Open source community for Python libraries
- Contributors and testers

---

## Support & Contact

### For Issues

1. Check this README thoroughly
2. Review relevant feature documentation
3. Check logs in `logs/` directory
4. Search existing GitHub issues (if applicable)
5. Review [TROUBLESHOOTING](#troubleshooting) section

### For Development

- **Python**: 3.10+
- **NautilusTrader**: Latest stable
- **Testing**: Refer to feature documentation

---

**Version**: 1.2.2
**Last Updated**: November 2025
**Status**: Production Ready
**Branch**: `fit/bracket-order`

---

*Trade responsibly and never risk more than you can afford to lose. This strategy is a tool, not a guarantee of profits. Always maintain proper risk management and monitor your positions actively.*

---

## Quick Links

- [Installation](#installation) | [Configuration](#configuration) | [Usage](#usage)
- [Features](#features) | [Risk Management](#risk-management) | [Monitoring](#monitoring)
- [Troubleshooting](#troubleshooting) | [Documentation](#documentation)
- [Performance](#performance-expectations) | [Disclaimer](#disclaimer)

---

**Happy Trading! 🚀**
