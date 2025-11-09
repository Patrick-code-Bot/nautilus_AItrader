#!/usr/bin/env python
"""
Telegram Command Handler Diagnostic Tool

This script helps diagnose why Telegram commands aren't responding.
It checks:
1. Telegram credentials configuration
2. Bot connectivity
3. Chat ID verification
4. Command handler setup
5. Actual command response

Usage:
    python diagnose_telegram.py
"""

import sys
import os
import asyncio
from pathlib import Path

# Add project directory to path
sys.path.insert(0, str(Path(__file__).parent))

def load_env():
    """Load environment variables from .env"""
    env_file = '.env'
    if not os.path.exists(env_file):
        print("❌ .env file not found!")
        print("💡 Create a .env file with your Telegram credentials:")
        print("   TELEGRAM_BOT_TOKEN=your_bot_token_here")
        print("   TELEGRAM_CHAT_ID=your_chat_id_here")
        return False

    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                # Remove inline comments
                if '#' in line:
                    line = line[:line.index('#')].strip()
                key, value = line.split('=', 1)
                value = value.strip().strip('"').strip("'")
                os.environ[key] = value
    return True

async def test_bot_connection(token: str) -> tuple:
    """Test basic bot connection."""
    try:
        from telegram import Bot
        bot = Bot(token=token)
        me = await bot.get_me()
        return True, me
    except Exception as e:
        return False, str(e)

async def get_updates(token: str) -> list:
    """Get recent updates to find the actual chat ID."""
    try:
        from telegram import Bot
        bot = Bot(token=token)
        updates = await bot.get_updates()
        return updates
    except Exception as e:
        print(f"❌ Error getting updates: {e}")
        return []

async def send_test_message(token: str, chat_id: str) -> tuple:
    """Send a test message."""
    try:
        from telegram import Bot
        bot = Bot(token=token)
        message = await bot.send_message(
            chat_id=chat_id,
            text="🧪 **Diagnostic Test**\n\nIf you see this message, the bot can send messages to this chat.",
            parse_mode='Markdown'
        )
        return True, "Message sent successfully"
    except Exception as e:
        return False, str(e)

async def test_command_handler(token: str, chat_id: str):
    """Test command handler initialization."""
    try:
        from utils.telegram_command_handler import TelegramCommandHandler

        # Create a simple callback
        def test_callback(command: str, args: dict) -> dict:
            return {
                'success': True,
                'message': f"✅ Command '{command}' received successfully!"
            }

        # Initialize handler
        handler = TelegramCommandHandler(
            token=token,
            allowed_chat_ids=[chat_id],
            strategy_callback=test_callback,
        )

        print("✅ Command handler initialized successfully")
        print("🔄 Starting command handler for 10 seconds...")
        print("   Please send /status command from your Telegram now!\n")

        # Start polling in background
        polling_task = asyncio.create_task(handler.start_polling())

        # Wait for 10 seconds to let user test commands
        try:
            await asyncio.sleep(10)
        except KeyboardInterrupt:
            print("\n⚠️  Interrupted by user")

        # Stop polling
        print("\n⏹️  Stopping command handler...")
        polling_task.cancel()

        if handler.is_running:
            try:
                await handler.stop_polling()
            except Exception:
                pass  # Ignore errors during cleanup

        try:
            await polling_task
        except asyncio.CancelledError:
            pass  # Expected when cancelling
        except Exception as e:
            # Ignore cleanup errors, just inform user
            pass

        print("✅ Command handler test completed")
        return True

    except ImportError as e:
        print(f"❌ Import error: {e}")
        print("💡 Make sure python-telegram-bot is installed:")
        print("   pip install python-telegram-bot")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

async def main():
    print("=" * 70)
    print("Telegram Command Handler Diagnostics")
    print("=" * 70)
    print()

    # Step 1: Check .env file
    print("Step 1: Checking .env file...")
    if not load_env():
        return
    print("✅ .env file found and loaded\n")

    # Step 2: Check credentials
    print("Step 2: Checking Telegram credentials...")
    token = os.getenv('TELEGRAM_BOT_TOKEN', '')
    chat_id = os.getenv('TELEGRAM_CHAT_ID', '')

    if not token:
        print("❌ TELEGRAM_BOT_TOKEN not found in .env")
        return
    print(f"✅ Bot Token: {token[:10]}...{token[-5:]}")

    if not chat_id:
        print("❌ TELEGRAM_CHAT_ID not found in .env")
        return
    print(f"✅ Chat ID: {chat_id}\n")

    # Step 3: Test bot connection
    print("Step 3: Testing bot connection...")
    success, result = await test_bot_connection(token)
    if not success:
        print(f"❌ Failed to connect to Telegram: {result}")
        return
    print(f"✅ Connected as @{result.username} ({result.first_name})\n")

    # Step 4: Verify Chat ID
    print("Step 4: Verifying chat ID...")
    print(f"   Configured chat ID: {chat_id}")
    print("   Getting recent updates to find actual chat ID...\n")

    updates = await get_updates(token)
    if updates:
        print(f"   Found {len(updates)} recent update(s):")
        seen_chat_ids = set()
        for update in updates[-5:]:  # Show last 5
            if update.message:
                actual_chat_id = str(update.message.chat.id)
                seen_chat_ids.add(actual_chat_id)
                chat_type = update.message.chat.type
                text = update.message.text[:30] if update.message.text else "N/A"
                print(f"   - Chat ID: {actual_chat_id} (type: {chat_type}, message: {text})")

        if chat_id not in seen_chat_ids and seen_chat_ids:
            print(f"\n⚠️  WARNING: Configured chat ID '{chat_id}' doesn't match recent messages!")
            print(f"   Recent chat IDs: {', '.join(seen_chat_ids)}")
            print(f"   This might be why commands aren't responding!\n")
        else:
            print(f"✅ Chat ID matches recent messages\n")
    else:
        print("   No recent updates found. Send a message to the bot first.\n")

    # Step 5: Test sending message
    print("Step 5: Testing message sending...")
    success, result = await send_test_message(token, chat_id)
    if success:
        print(f"✅ {result}\n")
    else:
        print(f"❌ Failed to send message: {result}\n")
        return

    # Step 6: Test command handler
    print("Step 6: Testing command handler...")
    await test_command_handler(token, chat_id)

    print("\n" + "=" * 70)
    print("Diagnostic Summary")
    print("=" * 70)
    print("\nIf commands still don't work, check:")
    print("1. Make sure the bot is not already running elsewhere")
    print("2. Verify the chat ID exactly matches (no spaces, correct sign)")
    print("3. Check if the strategy is actually starting the command handler")
    print("4. Look for error messages in the strategy logs")
    print("\nTo test commands manually:")
    print("  python test_telegram_commands.py status --send")
    print()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
