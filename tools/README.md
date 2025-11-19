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

## Notes

- Emulated orders are managed by NautilusTrader's OrderEmulator
- Orders are monitored in real-time via order book and quote ticks
- When triggered, orders are automatically submitted to Binance
- The trading service must be running for emulated orders to execute
