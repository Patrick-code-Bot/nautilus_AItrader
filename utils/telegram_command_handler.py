"""
Telegram Command Handler for Trading Strategy

Handles incoming Telegram commands for remote control of the trading strategy.
"""

import asyncio
import logging
from typing import Optional, Callable, Dict, Any
from datetime import datetime

try:
    from telegram import Update
    from telegram.ext import Application, CommandHandler, ContextTypes
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    Application = None
    CommandHandler = None
    Update = None
    ContextTypes = None


class TelegramCommandHandler:
    """
    Handles Telegram commands for strategy control.
    
    Commands:
    - /status: Get strategy status
    - /position: Get current position info
    - /pause: Pause trading
    - /resume: Resume trading
    - /help: Show available commands
    """
    
    def __init__(
        self,
        token: str,
        allowed_chat_ids: list,
        strategy_callback: Callable,
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize command handler.
        
        Parameters
        ----------
        token : str
            Telegram Bot token
        allowed_chat_ids : list
            List of allowed chat IDs (for security)
        strategy_callback : callable
            Callback function to execute commands on strategy
            Signature: callback(command: str, args: dict) -> dict
        logger : logging.Logger, optional
            Logger instance
        """
        if not TELEGRAM_AVAILABLE:
            raise ImportError("python-telegram-bot not installed")
        
        self.token = token
        self.allowed_chat_ids = [str(cid) for cid in allowed_chat_ids]
        self.strategy_callback = strategy_callback
        self.logger = logger or logging.getLogger(__name__)
        
        self.application = None
        self.is_running = False
        self.start_time = datetime.utcnow()
    
    def _is_authorized(self, update: Update) -> bool:
        """Check if the user is authorized to send commands."""
        chat_id = str(update.effective_chat.id)
        return chat_id in self.allowed_chat_ids
    
    async def _send_response(self, update: Update, message: str):
        """Send response message."""
        try:
            await update.message.reply_text(
                message,
                parse_mode='Markdown'
            )
        except Exception as e:
            self.logger.error(f"Failed to send response: {e}")
    
    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command."""
        if not self._is_authorized(update):
            await self._send_response(update, "❌ Unauthorized")
            return
        
        try:
            # Call strategy callback to get status
            result = self.strategy_callback('status', {})
            
            if result.get('success'):
                await self._send_response(update, result.get('message', 'No status available'))
            else:
                await self._send_response(update, f"❌ Error: {result.get('error', 'Unknown')}")
        except Exception as e:
            self.logger.error(f"Error handling /status: {e}")
            await self._send_response(update, f"❌ Error: {str(e)}")
    
    async def cmd_position(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /position command."""
        if not self._is_authorized(update):
            await self._send_response(update, "❌ Unauthorized")
            return
        
        try:
            # Call strategy callback to get position
            result = self.strategy_callback('position', {})
            
            if result.get('success'):
                await self._send_response(update, result.get('message', 'No position info'))
            else:
                await self._send_response(update, f"❌ Error: {result.get('error', 'Unknown')}")
        except Exception as e:
            self.logger.error(f"Error handling /position: {e}")
            await self._send_response(update, f"❌ Error: {str(e)}")
    
    async def cmd_pause(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /pause command."""
        if not self._is_authorized(update):
            await self._send_response(update, "❌ Unauthorized")
            return
        
        try:
            # Call strategy callback to pause
            result = self.strategy_callback('pause', {})
            
            if result.get('success'):
                await self._send_response(update, result.get('message', '⏸️ Trading paused'))
            else:
                await self._send_response(update, f"❌ Error: {result.get('error', 'Unknown')}")
        except Exception as e:
            self.logger.error(f"Error handling /pause: {e}")
            await self._send_response(update, f"❌ Error: {str(e)}")
    
    async def cmd_resume(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /resume command."""
        if not self._is_authorized(update):
            await self._send_response(update, "❌ Unauthorized")
            return
        
        try:
            # Call strategy callback to resume
            result = self.strategy_callback('resume', {})
            
            if result.get('success'):
                await self._send_response(update, result.get('message', '▶️ Trading resumed'))
            else:
                await self._send_response(update, f"❌ Error: {result.get('error', 'Unknown')}")
        except Exception as e:
            self.logger.error(f"Error handling /resume: {e}")
            await self._send_response(update, f"❌ Error: {str(e)}")
    
    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command."""
        if not self._is_authorized(update):
            await self._send_response(update, "❌ Unauthorized")
            return
        
        help_msg = (
            "🤖 *Available Commands*\n\n"
            "*Query Commands*:\n"
            "• `/status` - View strategy status\n"
            "• `/position` - View current position\n"
            "• `/help` - Show this help message\n\n"
            "*Control Commands*:\n"
            "• `/pause` - Pause trading (no new orders)\n"
            "• `/resume` - Resume trading\n\n"
            "💡 _Commands are case-insensitive_\n"
        )
        await self._send_response(update, help_msg)
    
    async def start_polling(self):
        """Start the command handler polling loop."""
        if not TELEGRAM_AVAILABLE:
            self.logger.error("Telegram not available")
            return
        
        try:
            # Create application
            self.application = Application.builder().token(self.token).build()
            
            # Register command handlers
            self.application.add_handler(CommandHandler("status", self.cmd_status))
            self.application.add_handler(CommandHandler("position", self.cmd_position))
            self.application.add_handler(CommandHandler("pause", self.cmd_pause))
            self.application.add_handler(CommandHandler("resume", self.cmd_resume))
            self.application.add_handler(CommandHandler("help", self.cmd_help))
            self.application.add_handler(CommandHandler("start", self.cmd_help))  # Alias for help
            
            self.logger.info("🤖 Starting Telegram command handler...")
            
            # Start polling
            await self.application.initialize()
            await self.application.start()
            await self.application.updater.start_polling()
            
            self.is_running = True
            self.logger.info("✅ Telegram command handler started successfully")
            
            # Keep running (this will block until stopped)
            await self.application.updater.idle()
            
        except Exception as e:
            self.logger.error(f"❌ Failed to start command handler: {e}")
            self.is_running = False
    
    async def stop_polling(self):
        """Stop the command handler."""
        if self.application and self.is_running:
            try:
                self.logger.info("🛑 Stopping Telegram command handler...")
                await self.application.updater.stop()
                await self.application.stop()
                await self.application.shutdown()
                self.is_running = False
                self.logger.info("✅ Command handler stopped")
            except Exception as e:
                self.logger.error(f"Error stopping command handler: {e}")

