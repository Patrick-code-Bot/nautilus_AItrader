"""
DeepSeek AI Strategy for NautilusTrader

AI-powered cryptocurrency trading strategy using DeepSeek for decision making,
technical indicators for market analysis, and sentiment data for validation.
"""

import os
import asyncio
import threading
from decimal import Decimal
from typing import Dict, Any, Optional, List, Tuple

from nautilus_trader.config import StrategyConfig
from nautilus_trader.trading.strategy import Strategy
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide, TimeInForce, PositionSide, PriceType, TriggerType
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.model.position import Position
from nautilus_trader.model.orders import MarketOrder
from datetime import timedelta

import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from indicators.technical_manager import TechnicalIndicatorManager
from utils.deepseek_client import DeepSeekAnalyzer
from utils.sentiment_client import SentimentDataFetcher
from utils.oco_manager import OCOManager


class DeepSeekAIStrategyConfig(StrategyConfig, frozen=True):
    """Configuration for DeepSeek AI Strategy."""

    # Instrument
    instrument_id: str
    bar_type: str

    # Capital
    equity: float = 10000.0
    leverage: float = 10.0

    # Position sizing
    base_usdt_amount: float = 100.0
    high_confidence_multiplier: float = 1.5
    medium_confidence_multiplier: float = 1.0
    low_confidence_multiplier: float = 0.5
    max_position_ratio: float = 0.10
    trend_strength_multiplier: float = 1.2
    min_trade_amount: float = 0.001

    # Technical indicators
    sma_periods: Tuple[int, ...] = (5, 20, 50)
    rsi_period: int = 14
    macd_fast: int = 12
    macd_slow: int = 26
    bb_period: int = 20
    bb_std: float = 2.0

    # AI configuration
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-chat"
    deepseek_temperature: float = 0.1
    deepseek_max_retries: int = 2

    # Sentiment
    sentiment_enabled: bool = True
    sentiment_lookback_hours: int = 4
    sentiment_timeframe: str = "15m"  # Sentiment data timeframe (should match or be compatible with bar_type)

    # Risk management
    min_confidence_to_trade: str = "MEDIUM"
    allow_reversals: bool = True
    require_high_confidence_for_reversal: bool = False
    rsi_extreme_threshold_upper: float = 75.0
    rsi_extreme_threshold_lower: float = 25.0
    rsi_extreme_multiplier: float = 0.7
    
    # Stop Loss & Take Profit
    enable_auto_sl_tp: bool = True
    sl_use_support_resistance: bool = True
    sl_buffer_pct: float = 0.001
    tp_high_confidence_pct: float = 0.03
    tp_medium_confidence_pct: float = 0.02
    tp_low_confidence_pct: float = 0.01
    
    # OCO (One-Cancels-the-Other)
    enable_oco: bool = True
    oco_redis_host: str = "localhost"
    oco_redis_port: int = 6379
    oco_redis_db: int = 0
    oco_redis_password: Optional[str] = None
    oco_group_ttl_hours: int = 24
    
    # Trailing Stop Loss
    enable_trailing_stop: bool = True
    trailing_activation_pct: float = 0.01
    trailing_distance_pct: float = 0.005
    trailing_update_threshold_pct: float = 0.002
    
    # Partial Take Profit
    enable_partial_tp: bool = True
    partial_tp_levels: Tuple[Dict[str, float], ...] = (
        {"profit_pct": 0.02, "position_pct": 0.5},
        {"profit_pct": 0.04, "position_pct": 0.5},
    )
    
    # Telegram Notifications
    enable_telegram: bool = False
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_notify_signals: bool = True
    telegram_notify_fills: bool = True
    telegram_notify_positions: bool = True
    telegram_notify_errors: bool = True

    # Execution
    position_adjustment_threshold: float = 0.001

    # Timing
    timer_interval_sec: int = 900


class DeepSeekAIStrategy(Strategy):
    """
    DeepSeek AI-powered trading strategy.

    Combines AI decision making, technical analysis, and sentiment data
    for intelligent cryptocurrency trading on Binance Futures.
    """

    def __init__(self, config: DeepSeekAIStrategyConfig):
        """
        Initialize DeepSeek AI strategy.

        Parameters
        ----------
        config : DeepSeekAIStrategyConfig
            Strategy configuration
        """
        super().__init__(config)

        # Configuration
        self.instrument_id = InstrumentId.from_str(config.instrument_id)
        self.bar_type = BarType.from_str(config.bar_type)

        # Position sizing config
        self.equity = config.equity
        self.leverage = config.leverage
        self.base_usdt = config.base_usdt_amount
        self.position_config = {
            'high_confidence_multiplier': config.high_confidence_multiplier,
            'medium_confidence_multiplier': config.medium_confidence_multiplier,
            'low_confidence_multiplier': config.low_confidence_multiplier,
            'max_position_ratio': config.max_position_ratio,
            'trend_strength_multiplier': config.trend_strength_multiplier,
            'min_trade_amount': config.min_trade_amount,
            'adjustment_threshold': config.position_adjustment_threshold,
        }

        # Risk management
        self.min_confidence = config.min_confidence_to_trade
        self.allow_reversals = config.allow_reversals
        self.require_high_conf_reversal = config.require_high_confidence_for_reversal
        self.rsi_extreme_upper = config.rsi_extreme_threshold_upper
        self.rsi_extreme_lower = config.rsi_extreme_threshold_lower
        self.rsi_extreme_mult = config.rsi_extreme_multiplier
        
        # Stop Loss & Take Profit
        self.enable_auto_sl_tp = config.enable_auto_sl_tp
        self.sl_use_support_resistance = config.sl_use_support_resistance
        self.sl_buffer_pct = config.sl_buffer_pct
        self.tp_pct_config = {
            'HIGH': config.tp_high_confidence_pct,
            'MEDIUM': config.tp_medium_confidence_pct,
            'LOW': config.tp_low_confidence_pct,
        }
        
        # Store latest signal and technical data for SL/TP calculation
        self.latest_signal_data: Optional[Dict[str, Any]] = None
        self.latest_technical_data: Optional[Dict[str, Any]] = None
        
        # OCO (One-Cancels-the-Other) Manager
        self.enable_oco = config.enable_oco
        self.oco_manager: Optional[OCOManager] = None
        if self.enable_oco:
            try:
                self.oco_manager = OCOManager(
                    redis_host=config.oco_redis_host,
                    redis_port=config.oco_redis_port,
                    redis_db=config.oco_redis_db,
                    redis_password=config.oco_redis_password,
                    key_prefix="nautilus:deepseek:oco",
                    group_ttl_hours=config.oco_group_ttl_hours,
                    logger=self.log,
                )
                self.log.info(f"✅ OCO Manager initialized: {self.oco_manager}")
            except Exception as e:
                self.log.warning(f"⚠️ Failed to initialize OCO Manager: {e}")
                self.oco_manager = None
                self.enable_oco = False
        
        # Trailing Stop Loss
        self.enable_trailing_stop = config.enable_trailing_stop
        self.trailing_activation_pct = config.trailing_activation_pct
        self.trailing_distance_pct = config.trailing_distance_pct
        self.trailing_update_threshold_pct = config.trailing_update_threshold_pct
        
        # Track trailing stop state for each position
        self.trailing_stop_state: Dict[str, Dict[str, Any]] = {}
        # Format: {
        #   "instrument_id": {
        #       "entry_price": float,
        #       "highest_price": float (for LONG) or "lowest_price": float (for SHORT),
        #       "current_sl_price": float,
        #       "sl_order_id": str,
        #       "activated": bool,
        #       "side": str (LONG/SHORT)
        #   }
        # }

        # Technical indicators manager
        sma_periods = config.sma_periods if config.sma_periods else [5, 20, 50]
        self.indicator_manager = TechnicalIndicatorManager(
            sma_periods=sma_periods,
            ema_periods=[config.macd_fast, config.macd_slow],
            rsi_period=config.rsi_period,
            macd_fast=config.macd_fast,
            macd_slow=config.macd_slow,
            bb_period=config.bb_period,
            bb_std=config.bb_std,
        )

        # DeepSeek AI analyzer
        api_key = config.deepseek_api_key or os.getenv('DEEPSEEK_API_KEY')
        if not api_key:
            raise ValueError("DeepSeek API key not provided")

        self.deepseek = DeepSeekAnalyzer(
            api_key=api_key,
            model=config.deepseek_model,
            temperature=config.deepseek_temperature,
            max_retries=config.deepseek_max_retries,
        )
        
        # Telegram Bot
        self.telegram_bot = None
        self.enable_telegram = config.enable_telegram
        if self.enable_telegram:
            try:
                from utils.telegram_bot import TelegramBot
                
                bot_token = config.telegram_bot_token or os.getenv('TELEGRAM_BOT_TOKEN', '')
                chat_id = config.telegram_chat_id or os.getenv('TELEGRAM_CHAT_ID', '')
                
                if bot_token and chat_id:
                    self.telegram_bot = TelegramBot(
                        token=bot_token,
                        chat_id=chat_id,
                        logger=self.log,
                        enabled=True
                    )
                    # Store notification preferences
                    self.telegram_notify_signals = config.telegram_notify_signals
                    self.telegram_notify_fills = config.telegram_notify_fills
                    self.telegram_notify_positions = config.telegram_notify_positions
                    self.telegram_notify_errors = config.telegram_notify_errors
                    
                    self.log.info("✅ Telegram Bot initialized successfully")
                    
                    # Initialize command handler for remote control
                    try:
                        from utils.telegram_command_handler import TelegramCommandHandler
                        import threading
                        
                        # Create callback function for commands
                        def command_callback(command: str, args: Dict[str, Any]) -> Dict[str, Any]:
                            """Callback function for Telegram commands."""
                            return self.handle_telegram_command(command, args)
                        
                        # Initialize command handler
                        allowed_chat_ids = [chat_id]  # Only allow the configured chat ID
                        self.telegram_command_handler = TelegramCommandHandler(
                            token=bot_token,
                            allowed_chat_ids=allowed_chat_ids,
                            strategy_callback=command_callback,
                            logger=self.log
                        )
                        
                        # Start command handler in background thread
                        def run_command_handler():
                            """Run command handler in background thread."""
                            try:
                                loop = asyncio.new_event_loop()
                                asyncio.set_event_loop(loop)
                                # Start polling (this will run indefinitely via idle())
                                loop.run_until_complete(self.telegram_command_handler.start_polling())
                            except Exception as e:
                                self.log.error(f"❌ Command handler thread error: {e}")
                        
                        # Start background thread for command listening
                        command_thread = threading.Thread(
                            target=run_command_handler,
                            daemon=True,
                            name="TelegramCommandHandler"
                        )
                        command_thread.start()
                        self.log.info("✅ Telegram Command Handler started in background thread")
                        
                    except ImportError:
                        self.log.warning("⚠️ Telegram command handler not available")
                        self.telegram_command_handler = None
                    except Exception as e:
                        self.log.error(f"❌ Failed to initialize command handler: {e}")
                        self.telegram_command_handler = None
                    
                else:
                    self.log.warning("⚠️ Telegram enabled but token/chat_id not configured")
                    self.enable_telegram = False
            except ImportError:
                self.log.warning("⚠️ Telegram bot not available (python-telegram-bot not installed)")
                self.enable_telegram = False
            except Exception as e:
                self.log.error(f"❌ Failed to initialize Telegram Bot: {e}")
                self.enable_telegram = False
        
        # Strategy control state for remote commands
        self.is_trading_paused = False
        self.strategy_start_time = None

        # Sentiment data fetcher
        self.sentiment_enabled = config.sentiment_enabled
        if self.sentiment_enabled:
            # Use sentiment_timeframe from config, or derive from bar_type if not specified
            sentiment_tf = config.sentiment_timeframe
            if not sentiment_tf or sentiment_tf == "":
                # Extract timeframe from bar_type (e.g., "1-MINUTE" -> "1m")
                bar_str = str(self.bar_type)
                if "1-MINUTE" in bar_str:
                    sentiment_tf = "1m"
                elif "5-MINUTE" in bar_str:
                    sentiment_tf = "5m"
                elif "15-MINUTE" in bar_str:
                    sentiment_tf = "15m"
                elif "1-HOUR" in bar_str:
                    sentiment_tf = "1h"
                else:
                    sentiment_tf = "15m"  # Default fallback
            
            self.sentiment_fetcher = SentimentDataFetcher(
                lookback_hours=config.sentiment_lookback_hours,
                timeframe=sentiment_tf,
            )
            self.log.info(f"Sentiment fetcher initialized with timeframe: {sentiment_tf}")
        else:
            self.sentiment_fetcher = None

        # State tracking
        self.instrument: Optional[Instrument] = None
        self.last_signal: Optional[Dict[str, Any]] = None
        self.bars_received = 0

        self.log.info(f"DeepSeek AI Strategy initialized for {self.instrument_id}")

    def on_start(self):
        """Actions to be performed on strategy start."""
        self.log.info("Starting DeepSeek AI Strategy...")

        # Load instrument
        self.instrument = self.cache.instrument(self.instrument_id)
        if self.instrument is None:
            self.log.error(f"Could not find instrument {self.instrument_id}")
            self.stop()
            return

        self.log.info(f"Loaded instrument: {self.instrument.id}")

        # Subscribe to bars
        self.subscribe_bars(self.bar_type)
        self.log.info(f"Subscribed to {self.bar_type}")

        # Set up timer for periodic analysis
        self.clock.set_timer(
            name="analysis_timer",
            interval=timedelta(seconds=self.config.timer_interval_sec),
            callback=self.on_timer,
        )

        self.log.info("Strategy started successfully")
        
        # Record start time for uptime tracking
        from datetime import datetime
        self.strategy_start_time = datetime.utcnow()
        
        # Send Telegram startup notification
        if self.telegram_bot and self.enable_telegram:
            try:
                startup_msg = self.telegram_bot.format_startup_message(
                    instrument_id=str(self.instrument_id),
                    config={
                        'enable_auto_sl_tp': self.enable_auto_sl_tp,
                        'enable_oco': self.enable_oco,
                        'enable_trailing_stop': self.enable_trailing_stop,
                        'enable_partial_tp': hasattr(self, 'enable_partial_tp') and getattr(self, 'enable_partial_tp', False),
                    }
                )
                self.telegram_bot.send_message_sync(startup_msg)
                
                # Send command help message
                help_msg = self.telegram_bot.format_help_response()
                self.telegram_bot.send_message_sync(help_msg)
                
            except Exception as e:
                self.log.warning(f"Failed to send Telegram startup notification: {e}")

    def on_stop(self):
        """Actions to be performed on strategy stop."""
        self.log.info("Stopping DeepSeek AI Strategy...")

        # Cancel any pending orders
        self.cancel_all_orders(self.instrument_id)

        # Unsubscribe from data
        self.unsubscribe_bars(self.bar_type)

        self.log.info("Strategy stopped")

    def on_bar(self, bar: Bar):
        """
        Handle bar updates.

        Parameters
        ----------
        bar : Bar
            The bar received
        """
        self.bars_received += 1

        # Update technical indicators
        self.indicator_manager.update(bar)

        # Log bar data
        if self.bars_received % 10 == 0:
            self.log.info(
                f"Bar #{self.bars_received}: "
                f"O:{bar.open} H:{bar.high} L:{bar.low} C:{bar.close} V:{bar.volume}"
            )

    def on_timer(self, event):
        """
        Periodic analysis and trading logic.

        Called every timer_interval_sec seconds (default: 15 minutes).
        """
        self.log.info("=" * 60)
        self.log.info("Running periodic analysis...")

        # Check if indicators are ready
        if not self.indicator_manager.is_initialized():
            self.log.warning("Indicators not yet initialized, skipping analysis")
            return

        # Get current market data
        current_bar = self.indicator_manager.recent_bars[-1] if self.indicator_manager.recent_bars else None
        if not current_bar:
            self.log.warning("No bars available for analysis")
            return

        current_price = float(current_bar.close)

        # Get technical data
        try:
            technical_data = self.indicator_manager.get_technical_data(current_price)
            self.log.debug(f"Technical data retrieved: {len(technical_data)} indicators")
        except Exception as e:
            self.log.error(f"Failed to get technical data: {e}")
            return

        # Get K-line data
        kline_data = self.indicator_manager.get_kline_data(count=10)
        self.log.debug(f"Retrieved {len(kline_data)} K-lines for analysis")

        # Get sentiment data
        sentiment_data = None
        if self.sentiment_enabled and self.sentiment_fetcher:
            try:
                sentiment_data = self.sentiment_fetcher.fetch()
                if sentiment_data:
                    self.log.info(self.sentiment_fetcher.format_for_display(sentiment_data))
            except Exception as e:
                self.log.warning(f"Failed to fetch sentiment data: {e}")

        # Build price data for AI
        price_data = {
            'price': current_price,
            'timestamp': self.clock.utc_now().isoformat(),
            'high': float(current_bar.high),
            'low': float(current_bar.low),
            'volume': float(current_bar.volume),
            'price_change': self._calculate_price_change(),
            'kline_data': kline_data,
        }

        # Get current position
        current_position = self._get_current_position_data()

        # Log current state
        self.log.info(f"Current Price: ${current_price:,.2f}")
        self.log.info(f"Overall Trend: {technical_data.get('overall_trend', 'N/A')}")
        self.log.info(f"RSI: {technical_data.get('rsi', 0):.2f}")
        if current_position:
            self.log.info(
                f"Current Position: {current_position['side']} "
                f"{current_position['quantity']} @ ${current_position['avg_px']:.2f}"
            )

        # Analyze with DeepSeek AI
        try:
            self.log.info("Calling DeepSeek AI for analysis...")
            signal_data = self.deepseek.analyze(
                price_data=price_data,
                technical_data=technical_data,
                sentiment_data=sentiment_data,
                current_position=current_position,
            )
            self.log.info(
                f"🤖 Signal: {signal_data['signal']} | "
                f"Confidence: {signal_data['confidence']} | "
                f"Reason: {signal_data['reason']}"
            )
            
            # Send Telegram signal notification (only for actionable signals)
            if self.telegram_bot and self.enable_telegram and self.telegram_notify_signals:
                if signal_data['signal'] in ['BUY', 'SELL']:
                    try:
                        signal_notification = self.telegram_bot.format_trade_signal({
                            'signal': signal_data['signal'],
                            'confidence': signal_data['confidence'],
                            'price': price_data['price'],
                            'timestamp': price_data['timestamp'],
                            'rsi': technical_data.get('rsi', 0),
                            'macd': technical_data.get('macd', 0),
                            'support': technical_data.get('support', 0),
                            'resistance': technical_data.get('resistance', 0),
                            'reasoning': signal_data['reason'],
                        })
                        self.telegram_bot.send_message_sync(signal_notification)
                    except Exception as e:
                        self.log.warning(f"Failed to send Telegram signal notification: {e}")
                        
        except Exception as e:
            self.log.error(f"DeepSeek AI analysis failed: {e}", exc_info=True)
            
            # Send error notification
            if self.telegram_bot and self.enable_telegram and self.telegram_notify_errors:
                try:
                    error_msg = self.telegram_bot.format_error_alert({
                        'level': 'ERROR',
                        'message': f"AI Analysis Failed: {str(e)[:100]}",
                        'context': 'on_timer'
                    })
                    self.telegram_bot.send_message_sync(error_msg)
                except:
                    pass
            return

        # Store signal
        self.last_signal = signal_data

        # Execute trade
        self._execute_trade(signal_data, price_data, technical_data, current_position)
        
        # OCO maintenance: cleanup orphan orders and expired groups
        if self.enable_oco and self.oco_manager:
            self._cleanup_oco_orphans()
        
        # Trailing stop maintenance: check and update trailing stops
        if self.enable_trailing_stop:
            self._update_trailing_stops(price_data['price'])

    def _calculate_price_change(self) -> float:
        """Calculate price change percentage."""
        bars = self.indicator_manager.recent_bars
        if len(bars) < 2:
            return 0.0

        current = float(bars[-1].close)
        previous = float(bars[-2].close)

        return ((current - previous) / previous) * 100

    def _get_current_position_data(self) -> Optional[Dict[str, Any]]:
        """Get current position information."""
        # Get open positions for this instrument
        positions = self.cache.positions_open(instrument_id=self.instrument_id)
        
        if not positions:
            return None
        
        # Get the first open position (should only be one for netting OMS)
        position = positions[0]
        
        if position and position.is_open:
            # Get current price for PnL calculation
            # Use last bar close price as it's more reliable than cache.price()
            # cache.price() requires tick data which may not be available
            bars = self.indicator_manager.recent_bars
            if bars:
                current_price = bars[-1].close
            else:
                # Fallback: try cache.price() if bars not available
                try:
                    current_price = self.cache.price(self.instrument_id, PriceType.LAST)
                except (TypeError, AttributeError):
                    current_price = None
            
            return {
                'side': 'long' if position.side == PositionSide.LONG else 'short',
                'quantity': float(position.quantity),
                'avg_px': float(position.avg_px_open),
                'unrealized_pnl': float(position.unrealized_pnl(current_price)) if current_price else 0.0,
            }

        return None

    def _execute_trade(
        self,
        signal_data: Dict[str, Any],
        price_data: Dict[str, Any],
        technical_data: Dict[str, Any],
        current_position: Optional[Dict[str, Any]],
    ):
        """
        Execute trading logic based on signal.

        Parameters
        ----------
        signal_data : Dict
            AI-generated signal
        price_data : Dict
            Current price data
        technical_data : Dict
            Technical indicators
        current_position : Dict or None
            Current position info
        """
        # Check if trading is paused
        if self.is_trading_paused:
            self.log.info("⏸️ Trading is paused - skipping signal execution")
            return
        
        # Store signal and technical data for SL/TP calculation
        self.latest_signal_data = signal_data
        self.latest_technical_data = technical_data
        
        signal = signal_data['signal']
        confidence = signal_data['confidence']

        # Check minimum confidence
        confidence_levels = {'LOW': 0, 'MEDIUM': 1, 'HIGH': 2}
        min_conf_level = confidence_levels.get(self.min_confidence, 1)
        signal_conf_level = confidence_levels.get(confidence, 1)

        if signal_conf_level < min_conf_level:
            self.log.warning(
                f"⚠️ Signal confidence {confidence} below minimum {self.min_confidence}, skipping trade"
            )
            return

        # Handle HOLD signal
        if signal == 'HOLD':
            self.log.info("📊 Signal: HOLD - No action taken")
            return

        # Calculate target position size
        target_quantity = self._calculate_position_size(
            signal_data, price_data, technical_data, current_position
        )

        if target_quantity == 0:
            self.log.warning("⚠️ Calculated position size is 0, skipping trade")
            return

        # Determine order side
        target_side = 'long' if signal == 'BUY' else 'short'

        # Execute position management logic
        if current_position:
            self._manage_existing_position(
                current_position, target_side, target_quantity, confidence
            )
        else:
            self._open_new_position(target_side, target_quantity)

    def _calculate_position_size(
        self,
        signal_data: Dict[str, Any],
        price_data: Dict[str, Any],
        technical_data: Dict[str, Any],
        current_position: Optional[Dict[str, Any]],
    ) -> float:
        """
        Calculate intelligent position size.

        Returns BTC quantity based on confidence, trend, and RSI.
        """
        # Base USDT amount
        base_usdt = self.base_usdt

        # Confidence multiplier
        conf_mult = self.position_config.get(
            f"{signal_data['confidence'].lower()}_confidence_multiplier",
            1.0
        )

        # Trend multiplier
        trend = technical_data.get('overall_trend', '震荡整理')
        trend_mult = (
            self.position_config['trend_strength_multiplier']
            if trend in ['强势上涨', '强势下跌']
            else 1.0
        )

        # RSI multiplier (reduce size in extreme RSI)
        rsi = technical_data.get('rsi', 50)
        rsi_mult = (
            self.rsi_extreme_mult
            if rsi > self.rsi_extreme_upper or rsi < self.rsi_extreme_lower
            else 1.0
        )

        # Calculate suggested USDT
        suggested_usdt = base_usdt * conf_mult * trend_mult * rsi_mult

        # Apply max position ratio limit
        max_usdt = self.equity * self.position_config['max_position_ratio']
        final_usdt = min(suggested_usdt, max_usdt)

        # Convert to BTC quantity
        current_price = price_data['price']
        btc_quantity = final_usdt / current_price

        # Apply minimum trade amount
        if btc_quantity < self.position_config['min_trade_amount']:
            btc_quantity = self.position_config['min_trade_amount']

        # Round to instrument precision
        btc_quantity = round(btc_quantity, 3)  # Binance BTC precision

        self.log.info(
            f"📊 Position Sizing: "
            f"Base:{base_usdt} × Conf:{conf_mult} × Trend:{trend_mult} × RSI:{rsi_mult} "
            f"= ${final_usdt:.2f} = {btc_quantity:.3f} BTC"
        )

        return btc_quantity

    def _manage_existing_position(
        self,
        current_position: Dict[str, Any],
        target_side: str,
        target_quantity: float,
        confidence: str,
    ):
        """Manage existing position (add, reduce, or reverse)."""
        current_side = current_position['side']
        current_qty = current_position['quantity']

        # Same direction - adjust position
        if target_side == current_side:
            size_diff = target_quantity - current_qty
            threshold = self.position_config['adjustment_threshold']

            if abs(size_diff) < threshold:
                self.log.info(
                    f"✅ Position size appropriate ({current_qty:.3f} BTC), no adjustment needed"
                )
                return

            if size_diff > 0:
                # Add to position
                self._submit_order(
                    side=OrderSide.BUY if target_side == 'long' else OrderSide.SELL,
                    quantity=abs(size_diff),
                    reduce_only=False,
                )
                self.log.info(
                    f"📈 Adding to {target_side} position: {abs(size_diff):.3f} BTC "
                    f"({current_qty:.3f} → {target_quantity:.3f})"
                )
            else:
                # Reduce position
                self._submit_order(
                    side=OrderSide.SELL if target_side == 'long' else OrderSide.BUY,
                    quantity=abs(size_diff),
                    reduce_only=True,
                )
                self.log.info(
                    f"📉 Reducing {target_side} position: {abs(size_diff):.3f} BTC "
                    f"({current_qty:.3f} → {target_quantity:.3f})"
                )

        # Opposite direction - reverse position
        elif self.allow_reversals:
            # Check if high confidence required for reversal
            if self.require_high_conf_reversal and confidence != 'HIGH':
                self.log.warning(
                    f"🔒 Reversal requires HIGH confidence, got {confidence}. "
                    f"Keeping {current_side} position."
                )
                return

            self.log.info(f"🔄 Reversing position: {current_side} → {target_side}")

            # Close current position
            self._submit_order(
                side=OrderSide.SELL if current_side == 'long' else OrderSide.BUY,
                quantity=current_qty,
                reduce_only=True,
            )

            # Open opposite position
            self._submit_order(
                side=OrderSide.BUY if target_side == 'long' else OrderSide.SELL,
                quantity=target_quantity,
                reduce_only=False,
            )

        else:
            self.log.warning(
                f"⚠️ Signal suggests {target_side} but have {current_side} position. "
                f"Reversals disabled."
            )

    def _open_new_position(self, side: str, quantity: float):
        """Open new position."""
        order_side = OrderSide.BUY if side == 'long' else OrderSide.SELL

        self._submit_order(
            side=order_side,
            quantity=quantity,
            reduce_only=False,
        )

        self.log.info(f"🚀 Opening {side} position: {quantity:.3f} BTC")

    def _submit_order(
        self,
        side: OrderSide,
        quantity: float,
        reduce_only: bool = False,
    ):
        """Submit market order to exchange."""
        if quantity < self.position_config['min_trade_amount']:
            self.log.warning(
                f"⚠️ Order quantity {quantity:.3f} below minimum "
                f"{self.position_config['min_trade_amount']:.3f}, skipping"
            )
            return

        # Create market order
        order = self.order_factory.market(
            instrument_id=self.instrument_id,
            order_side=side,
            quantity=self.instrument.make_qty(quantity),
            time_in_force=TimeInForce.GTC,
            reduce_only=reduce_only,
        )

        # Submit order
        self.submit_order(order)

        self.log.info(
            f"📤 Submitted {side.name} market order: {quantity:.3f} BTC "
            f"(reduce_only={reduce_only})"
        )
    
    def _submit_sl_tp_orders(
        self,
        entry_side: OrderSide,
        entry_price: float,
        quantity: float,
    ):
        """
        Submit Stop Loss and Take Profit orders after position is opened.
        
        Parameters
        ----------
        entry_side : OrderSide
            Side of the entry order (BUY or SELL)
        entry_price : float
            Entry price of the position
        quantity : float
            Quantity of the position
        """
        if not self.enable_auto_sl_tp:
            self.log.debug("Auto SL/TP is disabled, skipping")
            return
        
        if not self.latest_signal_data or not self.latest_technical_data:
            self.log.warning("⚠️ No signal/technical data available for SL/TP calculation")
            return
        
        # Get confidence and technical data
        confidence = self.latest_signal_data.get('confidence', 'MEDIUM')
        support = self.latest_technical_data.get('support', 0.0)
        resistance = self.latest_technical_data.get('resistance', 0.0)
        
        # Determine exit side (opposite of entry)
        exit_side = OrderSide.SELL if entry_side == OrderSide.BUY else OrderSide.BUY
        
        # Calculate Stop Loss price
        if entry_side == OrderSide.BUY:
            # BUY: Stop loss below support
            if self.sl_use_support_resistance and support > 0:
                stop_loss_price = support * (1 - self.sl_buffer_pct)
                self.log.info(f"📍 Using support level for SL: ${support:,.2f} → ${stop_loss_price:,.2f}")
            else:
                stop_loss_price = entry_price * 0.98  # Default 2% below entry
                self.log.info(f"📍 Using default 2% SL: ${stop_loss_price:,.2f}")
        else:
            # SELL: Stop loss above resistance
            if self.sl_use_support_resistance and resistance > 0:
                stop_loss_price = resistance * (1 + self.sl_buffer_pct)
                self.log.info(f"📍 Using resistance level for SL: ${resistance:,.2f} → ${stop_loss_price:,.2f}")
            else:
                stop_loss_price = entry_price * 1.02  # Default 2% above entry
                self.log.info(f"📍 Using default 2% SL: ${stop_loss_price:,.2f}")
        
        # Prepare Take Profit levels
        tp_orders_info = []
        
        if self.enable_partial_tp and len(self.partial_tp_levels) > 0:
            # Use partial take profit levels
            self.log.info(f"📊 Using Partial Take Profit with {len(self.partial_tp_levels)} levels")
            
            remaining_qty = quantity
            for i, level in enumerate(self.partial_tp_levels):
                profit_pct = level["profit_pct"]
                position_pct = level["position_pct"]
                
                # Calculate price for this level
                if entry_side == OrderSide.BUY:
                    tp_price = entry_price * (1 + profit_pct)
                else:
                    tp_price = entry_price * (1 - profit_pct)
                
                # Calculate quantity for this level
                level_qty = quantity * position_pct
                
                tp_orders_info.append({
                    "price": tp_price,
                    "quantity": level_qty,
                    "profit_pct": profit_pct,
                    "position_pct": position_pct,
                    "level": i + 1
                })
                
                remaining_qty -= level_qty
            
            # Log partial TP plan
            self.log.info("📋 Partial Take Profit Plan:")
            for info in tp_orders_info:
                self.log.info(
                    f"   Level {info['level']}: {info['position_pct']*100:.0f}% @ "
                    f"${info['price']:,.2f} (+{info['profit_pct']*100:.1f}%)"
                )
        else:
            # Use single take profit based on confidence
            tp_pct = self.tp_pct_config.get(confidence, 0.02)
            if entry_side == OrderSide.BUY:
                tp_price = entry_price * (1 + tp_pct)
            else:
                tp_price = entry_price * (1 - tp_pct)
            
            tp_orders_info.append({
                "price": tp_price,
                "quantity": quantity,
                "profit_pct": tp_pct,
                "position_pct": 1.0,
                "level": 1
            })
        
        # Log SL/TP summary
        self.log.info(
            f"🎯 Calculated SL/TP for {entry_side.name} position:\n"
            f"   Entry: ${entry_price:,.2f}\n"
            f"   Stop Loss: ${stop_loss_price:,.2f} ({((stop_loss_price/entry_price - 1) * 100):.2f}%)\n"
            f"   Take Profit Levels: {len(tp_orders_info)}\n"
            f"   Confidence: {confidence}"
        )
        
        try:
            # Submit Stop Loss order (STOP_MARKET)
            sl_order = self.order_factory.stop_market(
                instrument_id=self.instrument_id,
                order_side=exit_side,
                quantity=self.instrument.make_qty(quantity),
                trigger_price=self.instrument.make_price(stop_loss_price),
                trigger_type=TriggerType.LAST_TRADE,
                reduce_only=True,
            )
            self.submit_order(sl_order)
            self.log.info(f"🛡️ Submitted Stop Loss order @ ${stop_loss_price:,.2f}")
            
            # Submit Take Profit orders (LIMIT)
            tp_order_ids = []
            for tp_info in tp_orders_info:
                tp_order = self.order_factory.limit(
                    instrument_id=self.instrument_id,
                    order_side=exit_side,
                    quantity=self.instrument.make_qty(tp_info["quantity"]),
                    price=self.instrument.make_price(tp_info["price"]),
                    time_in_force=TimeInForce.GTC,
                    reduce_only=True,
                )
                self.submit_order(tp_order)
                tp_order_ids.append(str(tp_order.client_order_id))
                
                self.log.info(
                    f"🎯 Submitted TP Level {tp_info['level']}: "
                    f"{tp_info['position_pct']*100:.0f}% @ ${tp_info['price']:,.2f}"
                )
            
            # Save SL order ID for trailing stop
            if self.enable_trailing_stop:
                instrument_key = str(self.instrument_id)
                if instrument_key in self.trailing_stop_state:
                    self.trailing_stop_state[instrument_key]["sl_order_id"] = str(sl_order.client_order_id)
                    self.trailing_stop_state[instrument_key]["current_sl_price"] = stop_loss_price
                    self.log.debug(
                        f"📌 Saved SL order ID for trailing stop: {str(sl_order.client_order_id)[:8]}..."
                    )
            
            # Register OCO group if enabled (with multiple TP orders)
            if self.enable_oco and self.oco_manager:
                import time
                group_id = f"{entry_side.name}_{self.instrument_id}_{int(time.time())}"
                
                # Store multiple TP order IDs
                tp_order_id_str = ",".join(tp_order_ids)  # Join multiple IDs with comma
                
                self.oco_manager.create_oco_group(
                    group_id=group_id,
                    sl_order_id=str(sl_order.client_order_id),
                    tp_order_id=tp_order_id_str,  # Can contain multiple IDs
                    instrument_id=str(self.instrument_id),
                    entry_side=entry_side.name,
                    entry_price=entry_price,
                    quantity=quantity,
                    sl_price=stop_loss_price,
                    tp_price=tp_orders_info[0]["price"],  # First TP level for reference
                    metadata={
                        "confidence": confidence,
                        "support": self.latest_technical_data.get('support', 0.0) if self.latest_technical_data else 0.0,
                        "resistance": self.latest_technical_data.get('resistance', 0.0) if self.latest_technical_data else 0.0,
                        "partial_tp": self.enable_partial_tp,
                        "tp_levels": len(tp_orders_info),
                        "tp_order_ids": tp_order_ids,  # Store as list in metadata
                    }
                )
                
                self.log.debug(f"🔗 Registered OCO group: {group_id} (1 SL + {len(tp_order_ids)} TP orders)")
            
        except Exception as e:
            self.log.error(f"❌ Failed to submit SL/TP orders: {e}")

    def on_order_filled(self, event):
        """
        Handle order filled events.
        
        Implements OCO logic: when one order fills, automatically cancel the peer order.
        """
        filled_order_id = str(event.client_order_id)
        
        self.log.info(
            f"✅ Order filled: {event.order_side.name} "
            f"{event.last_qty} @ {event.last_px} "
            f"(ID: {filled_order_id[:8]}...)"
        )
        
        # Send Telegram order fill notification
        if self.telegram_bot and self.enable_telegram and self.telegram_notify_fills:
            try:
                fill_msg = self.telegram_bot.format_order_fill({
                    'side': event.order_side.name,
                    'quantity': float(event.last_qty),
                    'price': float(event.last_px),
                    'order_type': 'MARKET',  # Could extract from order if needed
                })
                self.telegram_bot.send_message_sync(fill_msg)
            except Exception as e:
                self.log.warning(f"Failed to send Telegram fill notification: {e}")
        
        # Check if this order belongs to an OCO group
        if self.enable_oco and self.oco_manager:
            group_id = self.oco_manager.find_group_by_order(filled_order_id)
            
            if group_id:
                # This order is part of an OCO group
                self.log.info(f"🔗 Order belongs to OCO group: {group_id}")
                
                # Mark as filled
                self.oco_manager.mark_filled(group_id, filled_order_id)
                
                # Get the group data to find all related orders
                group_data = self.oco_manager.get_group(group_id)
                
                if group_data:
                    # Collect all order IDs in this group
                    all_order_ids = []
                    
                    # Add SL order
                    sl_order_id = group_data.get("sl_order_id")
                    if sl_order_id:
                        all_order_ids.append(sl_order_id)
                    
                    # Add TP order(s) - can be single ID or comma-separated IDs
                    tp_order_id_str = group_data.get("tp_order_id", "")
                    if tp_order_id_str:
                        if "," in tp_order_id_str:
                            # Multiple TP orders
                            all_order_ids.extend(tp_order_id_str.split(","))
                        else:
                            # Single TP order
                            all_order_ids.append(tp_order_id_str)
                    
                    # Also check metadata for tp_order_ids list
                    metadata = group_data.get("metadata", {})
                    if isinstance(metadata, dict):
                        tp_order_ids_list = metadata.get("tp_order_ids", [])
                        if tp_order_ids_list:
                            all_order_ids.extend(tp_order_ids_list)
                    
                    # Remove duplicates and the filled order itself
                    orders_to_cancel = list(set(all_order_ids))
                    orders_to_cancel = [oid for oid in orders_to_cancel if oid != filled_order_id]
                    
                    # Cancel all peer orders
                    if orders_to_cancel:
                        self.log.info(f"🔴 OCO: Cancelling {len(orders_to_cancel)} peer orders")
                        for peer_order_id in orders_to_cancel:
                            self._cancel_oco_peer_order(peer_order_id, group_id)
                    
                # Clean up OCO group
                self.oco_manager.remove_group(group_id)
    
    def _cancel_oco_peer_order(self, peer_order_id: str, group_id: str):
        """
        Cancel the peer order in an OCO group.
        
        Parameters
        ----------
        peer_order_id : str
            Order ID to cancel
        group_id : str
            OCO group ID for logging
        """
        try:
            # Find the order in cache
            from nautilus_trader.model.identifiers import ClientOrderId
            order_id_obj = ClientOrderId(peer_order_id)
            order = self.cache.order(order_id_obj)
            
            if order:
                if order.is_open:
                    # Order is open, cancel it
                    self.cancel_order(order)
                    self.log.info(
                        f"🔴 OCO: Auto-cancelled peer order {peer_order_id[:8]}... "
                        f"from group [{group_id}]"
                    )
                elif order.is_canceled:
                    self.log.debug(f"ℹ️ Peer order already cancelled: {peer_order_id[:8]}...")
                elif order.is_closed:
                    self.log.warning(
                        f"⚠️ Peer order already closed: {peer_order_id[:8]}... "
                        f"(status: {order.status.name})"
                    )
                else:
                    self.log.debug(f"ℹ️ Peer order status: {order.status.name}")
            else:
                self.log.warning(f"⚠️ Peer order not found in cache: {peer_order_id[:8]}...")
                
        except Exception as e:
            self.log.error(
                f"❌ Failed to cancel OCO peer order {peer_order_id[:8]}...: {e}"
            )

    def on_order_rejected(self, event):
        """Handle order rejected events."""
        self.log.error(f"❌ Order rejected: {event.reason}")

    def on_position_opened(self, event):
        """Handle position opened events."""
        # PositionOpened event contains position data directly
        self.log.info(
            f"🟢 Position opened: {event.side.name} "
            f"{event.quantity} @ {event.avg_px_open}"
        )
        
        # Submit Stop Loss and Take Profit orders
        entry_side = OrderSide.BUY if event.side == PositionSide.LONG else OrderSide.SELL
        self._submit_sl_tp_orders(
            entry_side=entry_side,
            entry_price=float(event.avg_px_open),
            quantity=float(event.quantity),
        )
        
        # Initialize trailing stop state if enabled
        if self.enable_trailing_stop:
            instrument_key = str(self.instrument_id)
            entry_price = float(event.avg_px_open)
            
            self.trailing_stop_state[instrument_key] = {
                "entry_price": entry_price,
                "highest_price": entry_price if event.side == PositionSide.LONG else None,
                "lowest_price": entry_price if event.side == PositionSide.SHORT else None,
                "current_sl_price": None,  # Will be set after SL order is submitted
                "sl_order_id": None,  # Will be set after SL order is submitted
                "activated": False,
                "side": event.side.name,
                "quantity": float(event.quantity),
            }
            self.log.info(
                f"📊 Trailing stop initialized for {event.side.name} position @ ${entry_price:,.2f}"
            )
        
        # Send Telegram position opened notification
        if self.telegram_bot and self.enable_telegram and self.telegram_notify_positions:
            try:
                position_msg = self.telegram_bot.format_position_update({
                    'action': 'OPENED',
                    'side': event.side.name,
                    'quantity': float(event.quantity),
                    'entry_price': float(event.avg_px_open),
                    'current_price': float(event.avg_px_open),
                    'pnl': 0.0,
                    'pnl_pct': 0.0,
                })
                self.telegram_bot.send_message_sync(position_msg)
            except Exception as e:
                self.log.warning(f"Failed to send Telegram position opened notification: {e}")

    def on_position_closed(self, event):
        """Handle position closed events."""
        # PositionOpened event contains position data directly
        self.log.info(
            f"🔴 Position closed: {event.side.name} "
            f"P&L: {event.realized_pnl:.2f} USDT"
        )
        
        # Clear trailing stop state
        instrument_key = str(self.instrument_id)
        if instrument_key in self.trailing_stop_state:
            del self.trailing_stop_state[instrument_key]
            self.log.debug(f"🗑️ Cleared trailing stop state for {instrument_key}")
        
        # Send Telegram position closed notification
        if self.telegram_bot and self.enable_telegram and self.telegram_notify_positions:
            try:
                # Calculate P&L percentage (approximate)
                pnl = float(event.realized_pnl)
                # Get rough position size estimate for percentage
                # Note: This is approximate, actual calculation would require more data
                pnl_pct = (pnl / 100.0) * 100 if pnl != 0 else 0.0  # Rough estimate
                
                position_msg = self.telegram_bot.format_position_update({
                    'action': 'CLOSED',
                    'side': event.side.name,
                    'quantity': float(event.quantity) if hasattr(event, 'quantity') else 0.0,
                    'entry_price': float(event.avg_px_open) if hasattr(event, 'avg_px_open') else 0.0,
                    'current_price': float(event.avg_px_close) if hasattr(event, 'avg_px_close') else 0.0,
                    'pnl': pnl,
                    'pnl_pct': pnl_pct,
                })
                self.telegram_bot.send_message_sync(position_msg)
            except Exception as e:
                self.log.warning(f"Failed to send Telegram position closed notification: {e}")
    
    def _cleanup_oco_orphans(self):
        """
        Clean up orphan orders and expired OCO groups.
        
        This is a safety mechanism that runs periodically to:
        1. Cancel orphan reduce-only orders when no position exists
        2. Clean up expired OCO groups (older than TTL)
        3. Log OCO statistics
        """
        try:
            # Get current positions
            positions = self.cache.positions_open(instrument_id=self.instrument_id)
            has_position = len(positions) > 0
            
            if not has_position:
                # No position but check for orphan orders
                open_orders = self.cache.orders_open(instrument_id=self.instrument_id)
                
                if open_orders:
                    orphan_count = 0
                    for order in open_orders:
                        if order.is_reduce_only:
                            # This is a reduce-only order without a position - orphan!
                            try:
                                self.cancel_order(order)
                                orphan_count += 1
                                self.log.info(
                                    f"🗑️ Cancelled orphan reduce-only order: "
                                    f"{str(order.client_order_id)[:8]}..."
                                )
                            except Exception as e:
                                self.log.error(
                                    f"Failed to cancel orphan order: {e}"
                                )
                    
                    if orphan_count > 0:
                        self.log.warning(
                            f"⚠️ Cleaned up {orphan_count} orphan orders"
                        )
            
            # Clean up expired OCO groups
            expired_count = self.oco_manager.cleanup_expired_groups()
            
            # Log OCO statistics periodically
            stats = self.oco_manager.get_statistics()
            if stats['total_groups'] > 0:
                self.log.debug(
                    f"📊 OCO Stats: Total={stats['total_groups']}, "
                    f"Active={stats['active_groups']}, "
                    f"Redis={'✅' if stats['redis_enabled'] else '❌'}"
                )
                
        except Exception as e:
            self.log.error(f"❌ OCO cleanup failed: {e}")
    
    def _update_trailing_stops(self, current_price: float):
        """
        Update trailing stop loss orders based on current price.
        
        Logic:
        1. Check if position is profitable enough to activate trailing stop
        2. Track highest price (LONG) or lowest price (SHORT)
        3. Update stop loss when price moves favorably beyond threshold
        4. Stop loss only moves in favorable direction, never backwards
        
        Parameters
        ----------
        current_price : float
            Current market price
        """
        try:
            instrument_key = str(self.instrument_id)
            
            # Check if we have trailing stop state for this instrument
            if instrument_key not in self.trailing_stop_state:
                return
            
            state = self.trailing_stop_state[instrument_key]
            entry_price = state["entry_price"]
            side = state["side"]
            activated = state["activated"]
            
            # Calculate profit percentage
            if side == "LONG":
                profit_pct = (current_price - entry_price) / entry_price
                
                # Update highest price
                if state["highest_price"] is None or current_price > state["highest_price"]:
                    state["highest_price"] = current_price
                
                highest_price = state["highest_price"]
                
                # Check if we should activate trailing stop
                if not activated and profit_pct >= self.trailing_activation_pct:
                    state["activated"] = True
                    self.log.info(
                        f"🎯 Trailing stop ACTIVATED for LONG @ ${current_price:,.2f} "
                        f"(Profit: {profit_pct*100:.2f}%)"
                    )
                    activated = True
                
                # If activated, check if we should update stop loss
                if activated:
                    # Calculate new stop loss based on highest price
                    new_sl_price = highest_price * (1 - self.trailing_distance_pct)
                    current_sl_price = state["current_sl_price"]
                    
                    # Only update if new SL is significantly higher than current
                    if current_sl_price is None:
                        should_update = True
                    else:
                        price_move_pct = (new_sl_price - current_sl_price) / current_sl_price
                        should_update = price_move_pct >= self.trailing_update_threshold_pct
                    
                    if should_update and new_sl_price > current_sl_price:
                        self._execute_trailing_stop_update(
                            instrument_key=instrument_key,
                            new_sl_price=new_sl_price,
                            current_price=current_price,
                            side="LONG"
                        )
            
            elif side == "SHORT":
                profit_pct = (entry_price - current_price) / entry_price
                
                # Update lowest price
                if state["lowest_price"] is None or current_price < state["lowest_price"]:
                    state["lowest_price"] = current_price
                
                lowest_price = state["lowest_price"]
                
                # Check if we should activate trailing stop
                if not activated and profit_pct >= self.trailing_activation_pct:
                    state["activated"] = True
                    self.log.info(
                        f"🎯 Trailing stop ACTIVATED for SHORT @ ${current_price:,.2f} "
                        f"(Profit: {profit_pct*100:.2f}%)"
                    )
                    activated = True
                
                # If activated, check if we should update stop loss
                if activated:
                    # Calculate new stop loss based on lowest price
                    new_sl_price = lowest_price * (1 + self.trailing_distance_pct)
                    current_sl_price = state["current_sl_price"]
                    
                    # Only update if new SL is significantly lower than current
                    if current_sl_price is None:
                        should_update = True
                    else:
                        price_move_pct = (current_sl_price - new_sl_price) / current_sl_price
                        should_update = price_move_pct >= self.trailing_update_threshold_pct
                    
                    if should_update and new_sl_price < current_sl_price:
                        self._execute_trailing_stop_update(
                            instrument_key=instrument_key,
                            new_sl_price=new_sl_price,
                            current_price=current_price,
                            side="SHORT"
                        )
                        
        except Exception as e:
            self.log.error(f"❌ Trailing stop update failed: {e}")
    
    def _execute_trailing_stop_update(
        self,
        instrument_key: str,
        new_sl_price: float,
        current_price: float,
        side: str
    ):
        """
        Execute the actual update of trailing stop loss order.
        
        Parameters
        ----------
        instrument_key : str
            Instrument identifier
        new_sl_price : float
            New stop loss price
        current_price : float
            Current market price
        side : str
            Position side (LONG/SHORT)
        """
        try:
            state = self.trailing_stop_state[instrument_key]
            old_sl_price = state["current_sl_price"]
            old_sl_order_id = state["sl_order_id"]
            quantity = state["quantity"]
            
            # Log the update
            if old_sl_price:
                move_pct = ((new_sl_price - old_sl_price) / old_sl_price) * 100
                self.log.info(
                    f"⬆️ Trailing Stop Update ({side}):\n"
                    f"   Current Price: ${current_price:,.2f}\n"
                    f"   Old SL: ${old_sl_price:,.2f}\n"
                    f"   New SL: ${new_sl_price:,.2f} ({move_pct:+.2f}%)\n"
                    f"   Distance: {abs((new_sl_price - current_price) / current_price * 100):.2f}%"
                )
            else:
                self.log.info(
                    f"📍 Initial Trailing Stop ({side}):\n"
                    f"   Current Price: ${current_price:,.2f}\n"
                    f"   SL Price: ${new_sl_price:,.2f}\n"
                    f"   Distance: {abs((new_sl_price - current_price) / current_price * 100):.2f}%"
                )
            
            # Cancel old stop loss order if it exists
            if old_sl_order_id:
                try:
                    from nautilus_trader.model.identifiers import ClientOrderId
                    old_order_id_obj = ClientOrderId(old_sl_order_id)
                    old_order = self.cache.order(old_order_id_obj)
                    
                    if old_order and old_order.is_open:
                        self.cancel_order(old_order)
                        self.log.debug(f"🔴 Cancelled old SL order: {old_sl_order_id[:8]}...")
                except Exception as e:
                    self.log.warning(f"⚠️ Failed to cancel old SL order: {e}")
            
            # Submit new stop loss order
            exit_side = OrderSide.SELL if side == "LONG" else OrderSide.BUY
            
            new_sl_order = self.order_factory.stop_market(
                instrument_id=self.instrument_id,
                order_side=exit_side,
                quantity=self.instrument.make_qty(quantity),
                trigger_price=self.instrument.make_price(new_sl_price),
                trigger_type=TriggerType.LAST_TRADE,
                reduce_only=True,
            )
            self.submit_order(new_sl_order)
            
            # Update state
            state["current_sl_price"] = new_sl_price
            state["sl_order_id"] = str(new_sl_order.client_order_id)
            
            self.log.info(f"✅ New trailing SL order submitted @ ${new_sl_price:,.2f}")
            
            # Update OCO group if enabled
            if self.enable_oco and self.oco_manager and old_sl_order_id:
                # Find and update OCO group
                group_id = self.oco_manager.find_group_by_order(old_sl_order_id)
                if group_id:
                    group_data = self.oco_manager.get_group(group_id)
                    if group_data:
                        # Update SL order ID in OCO group
                        self.oco_manager.oco_groups[group_id]["sl_order_id"] = str(new_sl_order.client_order_id)
                        self.oco_manager.oco_groups[group_id]["sl_price"] = new_sl_price
                        self.log.debug(f"🔄 Updated OCO group [{group_id}] with new SL order")
                        
        except Exception as e:
            self.log.error(f"❌ Failed to execute trailing stop update: {e}")
    
    # ===== Remote Control Methods (for Telegram commands) =====
    
    def handle_telegram_command(self, command: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle Telegram commands.
        
        Parameters
        ----------
        command : str
            Command name (status, position, pause, resume)
        args : dict
            Command arguments
        
        Returns
        -------
        dict
            Response with 'success', 'message', and optional 'error'
        """
        try:
            if command == 'status':
                return self._cmd_status()
            elif command == 'position':
                return self._cmd_position()
            elif command == 'pause':
                return self._cmd_pause()
            elif command == 'resume':
                return self._cmd_resume()
            else:
                return {
                    'success': False,
                    'error': f"Unknown command: {command}"
                }
        except Exception as e:
            self.log.error(f"Error handling command '{command}': {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def _cmd_status(self) -> Dict[str, Any]:
        """Handle /status command."""
        try:
            from datetime import datetime
            
            # Get current price
            current_price = 0
            bars = self.indicator_manager.recent_bars if hasattr(self, 'indicator_manager') else []
            if bars:
                current_price = float(bars[-1].close)
            
            # Get unrealized PnL
            unrealized_pnl = 0
            positions = self.cache.positions_open(instrument_id=self.instrument_id)
            if positions:
                position = positions[0]
                if current_price > 0:
                    unrealized_pnl = float(position.unrealized_pnl(current_price))
            
            # Calculate uptime
            uptime_str = "N/A"
            if self.strategy_start_time:
                uptime_delta = datetime.utcnow() - self.strategy_start_time
                hours = uptime_delta.total_seconds() // 3600
                minutes = (uptime_delta.total_seconds() % 3600) // 60
                uptime_str = f"{int(hours)}h {int(minutes)}m"
            
            # Get last signal
            last_signal = "N/A"
            last_signal_time = "N/A"
            if hasattr(self, 'last_signal') and self.last_signal:
                last_signal = f"{self.last_signal.get('signal', 'N/A')} ({self.last_signal.get('confidence', 'N/A')})"
                # You could store timestamp if needed
            
            status_info = {
                'is_running': True,  # If this method is called, strategy is running
                'is_paused': self.is_trading_paused,
                'instrument_id': str(self.instrument_id),
                'current_price': current_price,
                'equity': self.equity,
                'unrealized_pnl': unrealized_pnl,
                'last_signal': last_signal,
                'last_signal_time': last_signal_time,
                'uptime': uptime_str,
            }
            
            message = self.telegram_bot.format_status_response(status_info) if self.telegram_bot else "Status unavailable"
            
            return {
                'success': True,
                'message': message
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def _cmd_position(self) -> Dict[str, Any]:
        """Handle /position command."""
        try:
            # Get current position
            current_position = self._get_current_position_data()
            
            position_info = {
                'has_position': current_position is not None,
            }
            
            if current_position:
                bars = self.indicator_manager.recent_bars if hasattr(self, 'indicator_manager') else []
                current_price = float(bars[-1].close) if bars else current_position['avg_px']
                
                entry_price = current_position['avg_px']
                pnl = current_position['unrealized_pnl']
                pnl_pct = (pnl / (entry_price * current_position['quantity'])) * 100 if entry_price > 0 else 0
                
                position_info.update({
                    'side': current_position['side'].upper(),
                    'quantity': current_position['quantity'],
                    'entry_price': entry_price,
                    'current_price': current_price,
                    'unrealized_pnl': pnl,
                    'pnl_pct': pnl_pct,
                    # SL/TP prices would need to be tracked separately if needed
                })
            
            message = self.telegram_bot.format_position_response(position_info) if self.telegram_bot else "Position unavailable"
            
            return {
                'success': True,
                'message': message
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def _cmd_pause(self) -> Dict[str, Any]:
        """Handle /pause command."""
        try:
            if self.is_trading_paused:
                message = self.telegram_bot.format_pause_response(False, "Trading is already paused") if self.telegram_bot else "Already paused"
            else:
                self.is_trading_paused = True
                self.log.info("⏸️ Trading paused by Telegram command")
                message = self.telegram_bot.format_pause_response(True) if self.telegram_bot else "Trading paused"
            
            return {
                'success': True,
                'message': message
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def _cmd_resume(self) -> Dict[str, Any]:
        """Handle /resume command."""
        try:
            if not self.is_trading_paused:
                message = self.telegram_bot.format_resume_response(False, "Trading is not paused") if self.telegram_bot else "Not paused"
            else:
                self.is_trading_paused = False
                self.log.info("▶️ Trading resumed by Telegram command")
                message = self.telegram_bot.format_resume_response(True) if self.telegram_bot else "Trading resumed"
            
            return {
                'success': True,
                'message': message
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
