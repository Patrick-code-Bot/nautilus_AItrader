#!/usr/bin/env python3
"""
Quick Test Runner - Sets environment variables before starting
"""
import os
import sys

# Set quick test environment variables
os.environ['TIMEFRAME'] = '1m'
os.environ['BASE_POSITION_USDT'] = '30'
os.environ['EQUITY'] = '400'
os.environ['TIMER_INTERVAL_SEC'] = '60'

print("=" * 60)
print("QUICK TEST MODE")
print("=" * 60)
print("Timeframe: 1 minute")
print("Position Size: 30 USDT")
print("Analysis Interval: 60 seconds")
print("Indicators need: ~15 bars (15 minutes)")
print("=" * 60)
print()

# Import and run main
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from main_live import main

if __name__ == "__main__":
    main()  # main() is synchronous (node.run() blocks); asyncio.run() raised ValueError
