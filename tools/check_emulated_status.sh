#!/bin/bash
echo "=== CURRENT EMULATED ORDERS STATUS ==="
echo ""
echo "Stop Loss Order (O-20251119-145638-001-000-2):"
grep "O-20251119-145638-001-000-2" /home/ubuntu/nautilus_deepseek/logs/trader.log | grep "Emulating StopMarketOrder"
echo ""
echo "Take Profit Order (O-20251119-145638-001-000-3):"
grep "O-20251119-145638-001-000-3" /home/ubuntu/nautilus_deepseek/logs/trader.log | grep "Emulating LimitOrder"
echo ""
echo "=== LATEST PRICE UPDATE ==="
grep "Current Price:" /home/ubuntu/nautilus_deepseek/logs/trader.log | tail -n 1
