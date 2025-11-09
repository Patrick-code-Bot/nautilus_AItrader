#!/usr/bin/env python
"""
Simple Command Listener Test

Tests if the Telegram bot can receive and respond to commands.
Run this script and send /status from your Telegram app.
"""

import os
import sys
import asyncio
from pathlib import Path

# Add project directory to path
sys.path.insert(0, str(Path(__file__).parent))

from utils.telegram_command_handler import TelegramCommandHandler

def load_env():
    """Load environment variables from .env"""
    env_file = '.env'
    if not os.path.exists(env_file):
        print("❌ .env file not found!")
        return False

    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                if '#' in line:
                    line = line[:line.index('#')].strip()
                key, value = line.split('=', 1)
                value = value.strip().strip('"').strip("'")
                os.environ[key] = value
    return True

async def main():
    print("=" * 70)
    print("Telegram Command Listener Test")
    print("=" * 70)
    print()

    # Load credentials
    if not load_env():
        return

    token = os.getenv('TELEGRAM_BOT_TOKEN', '')
    chat_id = os.getenv('TELEGRAM_CHAT_ID', '')

    if not token or not chat_id:
        print("❌ TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set")
        return

    print(f"✅ Bot Token: {token[:10]}...{token[-5:]}")
    print(f"✅ Chat ID: {chat_id}")
    print()

    # Create simple callback that prints received commands
    def command_callback(command: str, args: dict) -> dict:
        print(f"\n🎯 COMMAND RECEIVED: /{command}")
        print(f"   Args: {args}")
        print(f"   Time: {asyncio.get_event_loop().time()}")

        # Return a success response
        return {
            'success': True,
            'message': f"✅ Command '/{command}' received and processed successfully!\n\n"
                      f"This confirms the command handler is working."
        }

    # Initialize handler
    handler = TelegramCommandHandler(
        token=token,
        allowed_chat_ids=[chat_id],
        strategy_callback=command_callback,
    )

    print("🤖 Starting command listener...")
    print("📱 Send /status, /help, or /position from your Telegram app now!")
    print("⏹️  Press Ctrl+C to stop\n")

    try:
        # Start polling (this will run until interrupted)
        await handler.start_polling()
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Cleanup
        print("\n🛑 Stopping command handler...")
        if handler.is_running:
            try:
                await handler.stop_polling()
            except Exception:
                pass
        print("✅ Stopped")

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n✅ Stopped")
