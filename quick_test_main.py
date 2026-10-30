"""
Quick Test Mode - 1 Minute Bars for Rapid Testing
Force 1m configuration without environment variables
"""
import os
import sys
from pathlib import Path

# Set working directory
os.chdir(Path(__file__).parent)

# Force quick test parameters BEFORE any imports
os.environ['TIMEFRAME'] = '1m'
os.environ['BASE_POSITION_USDT'] = '30'
os.environ['EQUITY'] = '400'
os.environ['TIMER_INTERVAL_SEC'] = '60'

print("=" * 70)
print(" QUICK TEST MODE - 1 MINUTE BARS")
print("=" * 70)
print(f" Timeframe: 1 minute")
print(f" Position Size: 30 USDT")  
print(f" Analysis Interval: 60 seconds")
print(f" Indicators Initialize: ~15 minutes (15 bars)")
print("=" * 70)
print()

# Now import main_live module
from main_live import main

if __name__ == "__main__":
    try:
        main()  # main() is synchronous (node.run() blocks); asyncio.run() raised ValueError
    except KeyboardInterrupt:
        print("\n\n🛑 Quick test stopped by user")
    except Exception as e:
        print(f"\n\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
