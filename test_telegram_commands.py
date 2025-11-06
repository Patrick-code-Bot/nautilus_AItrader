#!/usr/bin/env python
"""
Manual test script for Telegram commands.

This script allows you to manually test command responses without running
the full command handler (which would require threading/async setup).

Usage:
    python test_telegram_commands.py <command>
    
Commands:
    status   - Test /status command response
    position - Test /position command response
    pause    - Test /pause command response
    resume   - Test /resume command response
    help     - Test /help command response
"""

import sys
import os

# Add project directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def load_env():
    """Load environment variables from .env"""
    env_file = '.env'
    if os.path.exists(env_file):
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

def test_command_formatters(command: str):
    """Test command response formatters."""
    from utils.telegram_bot import TelegramBot
    
    # Load credentials
    load_env()
    token = os.getenv('TELEGRAM_BOT_TOKEN', '')
    chat_id = os.getenv('TELEGRAM_CHAT_ID', '')
    
    if not token or not chat_id:
        print("❌ TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set in .env")
        return
    
    # Create bot instance
    bot = TelegramBot(token=token, chat_id=chat_id)
    
    print("=" * 70)
    print(f"Testing Command: /{command}")
    print("=" * 70)
    print()
    
    if command == 'status':
        # Mock status data
        status_info = {
            'is_running': True,
            'is_paused': False,
            'instrument_id': 'BTCUSDT-PERP.BINANCE',
            'current_price': 70000.50,
            'equity': 400.0,
            'unrealized_pnl': 15.25,
            'last_signal': 'HOLD (MEDIUM)',
            'last_signal_time': '2025-11-06 18:30:00 UTC',
            'uptime': '2h 15m',
        }
        message = bot.format_status_response(status_info)
        
    elif command == 'position':
        # Mock position data
        position_info = {
            'has_position': True,
            'side': 'LONG',
            'quantity': 0.001,
            'entry_price': 69500.00,
            'current_price': 70000.50,
            'unrealized_pnl': 0.50,
            'pnl_pct': 0.72,
            'sl_price': 68500.00,
            'tp_price': 71500.00,
        }
        message = bot.format_position_response(position_info)
        
    elif command == 'pause':
        message = bot.format_pause_response(True)
        
    elif command == 'resume':
        message = bot.format_resume_response(True)
        
    elif command == 'help':
        message = bot.format_help_response()
        
    else:
        print(f"Unknown command: {command}")
        print()
        print("Available commands: status, position, pause, resume, help")
        return
    
    print("Formatted Message:")
    print("-" * 70)
    print(message)
    print("-" * 70)
    print()
    
    # Check if we should send automatically
    auto_send = '--send' in sys.argv
    no_send = '--no-send' in sys.argv
    
    if no_send:
        print("ℹ️  Message not sent (--no-send flag)")
        return
    
    if auto_send:
        # Auto-send mode
        print("📤 Sending message to Telegram...")
        success = bot.send_message_sync(message)
        if success:
            print("✅ Message sent successfully!")
        else:
            print("❌ Failed to send message")
    else:
        # Interactive mode (if possible)
        try:
            response = input("Send this message to Telegram? (y/n): ")
            if response.lower() == 'y':
                success = bot.send_message_sync(message)
                if success:
                    print("✅ Message sent successfully!")
                else:
                    print("❌ Failed to send message")
            else:
                print("Message not sent.")
        except (EOFError, KeyboardInterrupt):
            # Non-interactive environment
            print("ℹ️  Non-interactive mode - message not sent")
            print("💡 Use --send to automatically send, or --no-send to skip")

def main():
    if len(sys.argv) < 2:
        print("Usage: python test_telegram_commands.py <command> [--send|--no-send]")
        print()
        print("Commands:")
        print("  status   - Test /status command response")
        print("  position - Test /position command response")
        print("  pause    - Test /pause command response")
        print("  resume   - Test /resume command response")
        print("  help     - Test /help command response")
        print()
        print("Options:")
        print("  --send    - Automatically send message to Telegram")
        print("  --no-send - Only display message, don't send")
        print()
        print("Examples:")
        print("  python test_telegram_commands.py status")
        print("  python test_telegram_commands.py status --send")
        print("  python test_telegram_commands.py position --no-send")
        sys.exit(1)
    
    command = sys.argv[1].lower()
    test_command_formatters(command)

if __name__ == '__main__':
    main()

