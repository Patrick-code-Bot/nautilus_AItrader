#!/bin/bash

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo "╔════════════════════════════════════════════════════════════════════╗"
echo "║           EMULATED ORDERS REAL-TIME DASHBOARD                     ║"
echo "╚════════════════════════════════════════════════════════════════════╝"
echo ""

# Get current price
CURRENT_PRICE=$(grep "Current Price:" /home/ubuntu/nautilus_deepseek/logs/trader.log | tail -n 1 | sed 's/.*Current Price: \$\([0-9,]*\.[0-9]*\).*/\1/' | tr -d ',')
echo -e "${BLUE}📊 Current BTC Price: \$${CURRENT_PRICE}${NC}"
echo ""

# Stop Loss Details
SL_PRICE="90915.40"
echo -e "${RED}🛑 STOP LOSS (Emulated)${NC}"
echo "   Order ID: O-20251119-145638-001-000-2"
echo "   Type: STOP_MARKET"
echo "   Trigger Price: \$$SL_PRICE"
echo "   Quantity: 0.002 BTC"
echo "   Status: EMULATED ✓"
echo "   Distance: $(echo "scale=2; ($CURRENT_PRICE - $SL_PRICE)" | bc) points below"
echo ""

# Take Profit Details
TP_PRICE="94335.70"
echo -e "${GREEN}🎯 TAKE PROFIT (Emulated)${NC}"
echo "   Order ID: O-20251119-145638-001-000-3"
echo "   Type: LIMIT"
echo "   Target Price: \$$TP_PRICE"
echo "   Quantity: 0.002 BTC"
echo "   Status: EMULATED ✓"
echo "   Distance: $(echo "scale=2; ($TP_PRICE - $CURRENT_PRICE)" | bc) points above"
echo ""

# Position Details
echo -e "${YELLOW}📈 CURRENT POSITION${NC}"
ENTRY_PRICE="91480.50"
echo "   Entry: \$$ENTRY_PRICE"
echo "   Current: \$$CURRENT_PRICE"
UNREALIZED_PNL=$(echo "scale=2; (($CURRENT_PRICE - $ENTRY_PRICE) * 0.002)" | bc)
echo "   Unrealized P&L: \$$UNREALIZED_PNL"
echo ""

# Emulator Status
echo -e "${BLUE}⚙️  ORDER EMULATOR STATUS${NC}"
EMULATOR_STATUS=$(grep "OrderEmulator: RUNNING" /home/ubuntu/nautilus_deepseek/logs/trader.log | tail -n 1)
if [ -n "$EMULATOR_STATUS" ]; then
    echo "   Status: RUNNING ✓"
    echo "   Monitoring: Order Book + Quote Ticks"
else
    echo "   Status: UNKNOWN"
fi
echo ""

# Latest Activity
echo -e "${YELLOW}📝 LATEST ACTIVITY (Last 5 events)${NC}"
grep -E "(OrderEmulator|Position|Signal:)" /home/ubuntu/nautilus_deepseek/logs/trader.log | tail -n 5 | sed 's/\[1m//g' | sed 's/\[0m//g' | cut -c 1-100
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "To monitor in real-time: tail -f /home/ubuntu/nautilus_deepseek/logs/trader.log | grep --line-buffered OrderEmulator"
