#!/usr/bin/env python
"""
Telegram Bot Connection Test Script

Usage:
    python test_telegram.py <bot_token> <chat_id>
    
Or with environment variables:
    python test_telegram.py

This script tests the Telegram bot connection and sends a test message.
"""

import sys
import os
import asyncio
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from utils.telegram_bot import TelegramBot, test_telegram_bot


async def main():
    """Main test function"""
    
    # Get credentials from arguments or environment
    if len(sys.argv) >= 3:
        token = sys.argv[1]
        chat_id = sys.argv[2]
        print(f"📱 Using credentials from command line arguments")
    else:
        # Try to load from .env
        token = os.getenv('TELEGRAM_BOT_TOKEN', '')
        chat_id = os.getenv('TELEGRAM_CHAT_ID', '')
        
        if not token or not chat_id:
            # Try to load from .env file
            env_file = project_root / '.env'
            if env_file.exists():
                print(f"📂 Loading credentials from .env file...")
                from dotenv import load_dotenv
                load_dotenv(env_file)
                token = os.getenv('TELEGRAM_BOT_TOKEN', '')
                chat_id = os.getenv('TELEGRAM_CHAT_ID', '')
    
    # Validate credentials
    if not token or not chat_id:
        print("❌ Error: Bot token or chat ID not provided")
        print("\nUsage:")
        print("  1. Command line: python test_telegram.py <bot_token> <chat_id>")
        print("  2. Environment variables: Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID")
        print("  3. .env file: Add credentials to .env file")
        print("\nHow to get credentials:")
        print("  • Bot Token: Search @BotFather on Telegram, send /newbot")
        print("  • Chat ID: Search @userinfobot on Telegram, send any message")
        sys.exit(1)
    
    print(f"\n🧪 Testing Telegram Bot Connection")
    print(f"{'='*50}")
    print(f"Bot Token: {token[:10]}...{token[-4:]}")
    print(f"Chat ID: {chat_id}")
    print(f"{'='*50}\n")
    
    # Run test
    try:
        result = await test_telegram_bot(token, chat_id)
        
        if result:
            print("\n" + "="*50)
            print("✅ TEST SUCCESSFUL!")
            print("="*50)
            print("\nYour Telegram bot is working correctly!")
            print("You should have received a test message on Telegram.")
            print("\nNext steps:")
            print("1. Update .env file with your credentials")
            print("2. Set TELEGRAM_ENABLED=true in .env")
            print("3. Set telegram.enabled: true in configs/telegram_config.yaml")
            print("4. Restart the trading strategy")
            return 0
        else:
            print("\n" + "="*50)
            print("❌ TEST FAILED")
            print("="*50)
            print("\nPlease check:")
            print("• Bot token is correct")
            print("• Chat ID is correct")
            print("• You have started a conversation with the bot")
            print("  (Send /start to your bot first)")
            print("• Internet connection is working")
            return 1
            
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)

