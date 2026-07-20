# Trading Tools

Utility scripts for monitoring and managing the DeepSeek AI Trading Strategy.

## Emulated Order Monitoring

### monitor_emulated_orders.sh
Comprehensive dashboard showing real-time status of emulated orders (Stop Loss and Take Profit).

**Usage:**
```bash
./tools/monitor_emulated_orders.sh
```

**Displays:**
- Current BTC price
- Stop Loss trigger price and distance
- Take Profit target price and distance
- Current position and unrealized P&L
- Order Emulator status
- Recent activity

### check_emulated_status.sh
Quick status check for currently active emulated orders.

**Usage:**
```bash
./tools/check_emulated_status.sh
```

**Displays:**
- Active Stop Loss orders
- Active Take Profit orders
- Latest price update

## Real-Time Monitoring Commands

**Monitor order triggers:**
```bash
tail -f logs/trader.log | grep --line-buffered -E "(OrderEmulator|OrderTriggered|PositionClosed)"
```

**Watch price updates:**
```bash
tail -f logs/trader.log | grep --line-buffered "Current Price:"
```

**Monitor all emulated order activity:**
```bash
tail -f logs/trader.log | grep --line-buffered "EMULATED"
```

## Signal Calibration (Phase 2)

### score_signals.py
Scores the quality of DeepSeek's signals against realized price paths. The
strategy writes one JSONL record per evaluated signal (including HOLDs and
skipped trades) to `logs/signal_log.jsonl`; this tool replays each BUY/SELL
signal's bracket (SL vs TP, first hit wins) on real klines and reports
win rate, expectancy in R, and profit factor — overall, per confidence
level, per side, and split by regime alignment.

**Usage:**
```bash
# collect data first (shadow mode, no orders placed):
SIGNAL_ONLY_MODE=true python main_live.py

# after a few weeks (100+ signals), score the dataset:
python tools/score_signals.py
python tools/score_signals.py --max-bars 192   # 48h window instead of 24h
```

**Reading the verdict:**
- `avgR > 0` with n >= 30 (aim for 100+) suggests the signal has real edge
- HIGH should outperform MEDIUM/LOW if "confidence" means anything
- regime-aligned should beat counter-regime if the 4h filter adds value

## Notes

- Emulated orders are managed by NautilusTrader's OrderEmulator
- Orders are monitored in real-time via order book and quote ticks
- When triggered, orders are automatically submitted to Binance
- The trading service must be running for emulated orders to execute
