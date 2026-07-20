"""
DeepSeek AI Strategy for NautilusTrader

AI-powered cryptocurrency trading strategy using DeepSeek for decision making,
technical indicators for market analysis, and sentiment data for validation.
"""

import os
import json
import math
import asyncio
import threading
from decimal import Decimal
from typing import Dict, Any, Optional, List, Tuple

from nautilus_trader.config import StrategyConfig
from nautilus_trader.trading.strategy import Strategy
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide, TimeInForce, PositionSide, PriceType, TriggerType, OrderType
from nautilus_trader.model.identifiers import InstrumentId, ClientOrderId
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.model.position import Position
from nautilus_trader.model.orders import MarketOrder
from nautilus_trader.model.currencies import USDT
from datetime import datetime, timedelta

import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from indicators.technical_manager import TechnicalIndicatorManager
from utils.deepseek_client import DeepSeekAnalyzer
from utils.sentiment_client import SentimentDataFetcher
# OCOManager no longer needed - using NautilusTrader's built-in bracket orders


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
    deepseek_model: str = "deepseek-v4-pro"
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
    # Levels in R multiples (R = entry-to-stop distance). When reached, a
    # reduce-only market order closes position_pct of the ORIGINAL quantity.
    partial_tp_levels: Tuple[Dict[str, float], ...] = (
        {"r_multiple": 1.0, "position_pct": 0.5},
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

    # Phase 0 safety: risk-based sizing & kill-switches
    risk_per_trade_pct: float = 0.01  # Fraction of live equity risked per trade (SL distance based)
    max_position_leverage: float = 2.0  # Max position notional as multiple of live equity
    min_notional_usdt: float = 100.0  # Binance minimum notional; trades below this are SKIPPED, never upsized
    daily_loss_limit_pct: float = 0.03  # Halt new trades for the day beyond this daily loss
    max_consecutive_losses: int = 5  # Pause trading after this many consecutive losing closes
    loss_pause_hours: float = 24.0  # Pause duration after kill-switch triggers
    max_consecutive_same_signal: int = 5  # Block churn after this many identical consecutive signals
    disaster_stop_enabled: bool = True  # Native exchange-side catastrophic stop (survives restarts)
    disaster_stop_min_pct: float = 0.015  # Minimum distance of the disaster stop from entry
    risk_state_file: str = "logs/risk_state.json"  # Persisted kill-switch state (survives restarts)

    # Phase 1: ATR-based exits (fix reward:risk asymmetry)
    atr_period: int = 14
    use_atr_exits: bool = True  # ATR-based SL/TP; falls back to S/R then 2% when ATR unavailable
    sl_atr_multiplier: float = 1.5  # Stop loss = 1.5 x ATR from entry
    tp_atr_multiplier: float = 3.0  # Take profit = 3 x ATR from entry (2:1 payoff)
    trailing_use_atr: bool = True  # ATR-based trailing; falls back to pct when ATR unavailable
    trailing_activation_atr: float = 1.0  # Activate trailing at +1 x ATR profit (1R)
    trailing_distance_atr: float = 1.0  # Trail 1 x ATR behind the extreme price

    # Phase 2: signal measurement (shadow mode) & higher-timeframe regime filter
    signal_only_mode: bool = False  # Log every evaluated signal WITHOUT executing (calibration dataset)
    signal_log_file: str = "logs/signal_log.jsonl"  # JSONL signal records for tools/score_signals.py
    regime_filter_enabled: bool = True  # Only trade with the higher-timeframe trend; sit out chop
    regime_timeframe: str = "4h"  # Binance kline interval used for regime classification
    regime_ema_fast: int = 20
    regime_ema_slow: int = 50
    regime_flat_threshold_pct: float = 0.002  # |EMA_fast-EMA_slow|/price below this = flat/chop
    regime_cache_ttl_sec: int = 1800  # How long a regime classification stays cached

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
        
        # Store latest signal, technical, and price data for SL/TP calculation
        self.latest_signal_data: Optional[Dict[str, Any]] = None
        self.latest_technical_data: Optional[Dict[str, Any]] = None
        self.latest_price_data: Optional[Dict[str, Any]] = None

        # OCO (One-Cancels-the-Other) - Now handled by NautilusTrader's bracket orders
        # No need for manual OCO manager anymore
        self.enable_oco = config.enable_oco  # Keep for config compatibility
        self.oco_manager = None  # Deprecated: bracket orders handle OCO automatically
        
        # Trailing Stop Loss
        self.enable_trailing_stop = config.enable_trailing_stop
        self.trailing_activation_pct = config.trailing_activation_pct
        self.trailing_distance_pct = config.trailing_distance_pct
        self.trailing_update_threshold_pct = config.trailing_update_threshold_pct

        # Phase 1: ATR-based exits & trailing
        self.use_atr_exits = config.use_atr_exits
        self.sl_atr_multiplier = config.sl_atr_multiplier
        self.tp_atr_multiplier = config.tp_atr_multiplier
        self.trailing_use_atr = config.trailing_use_atr
        self.trailing_activation_atr = config.trailing_activation_atr
        self.trailing_distance_atr = config.trailing_distance_atr

        # Partial Take Profit (implemented in Phase 1, R-multiple based)
        self.enable_partial_tp = config.enable_partial_tp
        self.partial_tp_levels = config.partial_tp_levels
        # Format: {instrument_id: {"entry_price": float, "sl_distance": float,
        #   "side": str (LONG/SHORT), "original_quantity": float, "levels_done": [int]}}
        self.partial_tp_state: Dict[str, Dict[str, Any]] = {}

        # Phase 2: signal measurement & regime filter
        self.signal_only_mode = config.signal_only_mode
        self.signal_log_file = config.signal_log_file
        self.regime_filter_enabled = config.regime_filter_enabled
        self.regime_timeframe = config.regime_timeframe
        self.regime_ema_fast = config.regime_ema_fast
        self.regime_ema_slow = config.regime_ema_slow
        self.regime_flat_threshold_pct = config.regime_flat_threshold_pct
        self.regime_cache_ttl_sec = config.regime_cache_ttl_sec
        self._regime_cache: Dict[str, Any] = {"value": None, "ts": 0.0}
        
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

        # Phase 0 safety: risk-based sizing & kill-switches
        self.risk_per_trade_pct = config.risk_per_trade_pct
        self.max_position_leverage = config.max_position_leverage
        self.min_notional_usdt = config.min_notional_usdt
        self.daily_loss_limit_pct = config.daily_loss_limit_pct
        self.max_consecutive_losses = config.max_consecutive_losses
        self.loss_pause_hours = config.loss_pause_hours
        self.max_consecutive_same_signal = config.max_consecutive_same_signal
        self.disaster_stop_enabled = config.disaster_stop_enabled
        self.disaster_stop_min_pct = config.disaster_stop_min_pct
        self.risk_state_file = config.risk_state_file

        # Kill-switch state (persisted to risk_state_file, survives restarts)
        self.risk_state: Dict[str, Any] = {
            "consecutive_losses": 0,
            "paused_until": None,      # ISO timestamp (UTC) while paused
            "day_date": None,          # UTC date of current daily baseline
            "day_start_equity": None,  # Equity at start of UTC day
        }

        # Native disaster-stop orders (exchange-side, survive process restarts)
        # Format: {instrument_id: {"order_id": str, "price": float}}
        self.disaster_stop_state: Dict[str, Dict[str, Any]] = {}

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
            atr_period=config.atr_period,
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
            nautilus_logger=self.log,
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

        # Pre-fetch historical bars before subscribing to live data
        self._prefetch_historical_bars(limit=200)

        # Subscribe to bars (live data)
        self.subscribe_bars(self.bar_type)
        self.log.info(f"Subscribed to {self.bar_type}")

        # Set up timer for periodic analysis
        self.clock.set_timer(
            name="analysis_timer",
            interval=timedelta(seconds=self.config.timer_interval_sec),
            callback=self.on_timer,
        )

        self.log.info("Strategy started successfully")

        # Restore persisted kill-switch state (daily baseline, loss streaks, pauses)
        self._load_risk_state()

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

    def _prefetch_historical_bars(self, limit: int = 200):
        """
        Pre-fetch historical bars from Binance API on startup.

        This eliminates the waiting period for indicators to initialize by loading
        historical data directly from Binance exchange on strategy startup.

        Parameters
        ----------
        limit : int
            Number of historical bars to fetch (default: 200)
        """
        try:
            import requests
            from nautilus_trader.core.datetime import millis_to_nanos

            # Extract symbol from instrument_id
            # Example: BTCUSDT-PERP.BINANCE -> BTCUSDT
            symbol_str = str(self.instrument_id)
            symbol = symbol_str.split('-')[0]

            # Convert bar type to Binance interval
            # NOTE: check longer timeframes first - "15-MINUTE" contains "5-MINUTE"
            bar_type_str = str(self.bar_type)
            if '15-MINUTE' in bar_type_str:
                interval = '15m'
            elif '30-MINUTE' in bar_type_str:
                interval = '30m'
            elif '5-MINUTE' in bar_type_str:
                interval = '5m'
            elif '1-MINUTE' in bar_type_str:
                interval = '1m'
            elif '1-HOUR' in bar_type_str:
                interval = '1h'
            elif '4-HOUR' in bar_type_str:
                interval = '4h'
            elif '1-DAY' in bar_type_str:
                interval = '1d'
            else:
                interval = '5m'  # Default fallback

            self.log.info(
                f"📡 Pre-fetching {limit} historical bars from Binance "
                f"(symbol={symbol}, interval={interval})..."
            )

            # Binance Futures API endpoint
            url = "https://fapi.binance.com/fapi/v1/klines"
            params = {
                'symbol': symbol,
                'interval': interval,
                'limit': min(limit, 1500),  # Binance max
            }

            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            klines = response.json()

            if not klines:
                self.log.warning("⚠️ No bars received from Binance API")
                return

            self.log.info(f"📊 Received {len(klines)} bars from Binance")

            # Convert to NautilusTrader bars and feed to indicators
            bars_fed = 0
            for kline in klines:
                try:
                    # Create Bar object
                    bar = Bar(
                        bar_type=self.bar_type,
                        open=self.instrument.make_price(float(kline[1])),
                        high=self.instrument.make_price(float(kline[2])),
                        low=self.instrument.make_price(float(kline[3])),
                        close=self.instrument.make_price(float(kline[4])),
                        volume=self.instrument.make_qty(float(kline[5])),
                        ts_event=millis_to_nanos(kline[0]),
                        ts_init=millis_to_nanos(kline[0]),
                    )

                    # Feed to indicator manager
                    self.indicator_manager.update(bar)
                    bars_fed += 1

                except Exception as e:
                    self.log.warning(f"Failed to convert kline to bar: {e}")
                    continue

            self.log.info(
                f"✅ Pre-fetched {bars_fed} bars successfully! "
                f"Indicators ready: {self.indicator_manager.is_initialized()}"
            )

        except Exception as e:
            self.log.error(f"❌ Failed to pre-fetch bars from Binance: {e}")
            self.log.warning("Continuing with live bars only...")

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
            import time as _time
            self.log.info("Calling DeepSeek AI for analysis...")
            _t0 = _time.monotonic()
            signal_data = self.deepseek.analyze(
                price_data=price_data,
                technical_data=technical_data,
                sentiment_data=sentiment_data,
                current_position=current_position,
            )
            _elapsed = _time.monotonic() - _t0
            self.log.info(
                f"🤖 Signal: {signal_data['signal']} | "
                f"Confidence: {signal_data['confidence']} | "
                f"API time: {_elapsed:.1f}s | "
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

        # Partial take-profit maintenance: execute R-multiple levels
        if self.enable_partial_tp:
            self._check_partial_take_profits(price_data['price'])

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

    # ===== Phase 0 safety helpers =====

    def _get_account_equity(self) -> float:
        """
        Get live USDT wallet balance from the portfolio.

        Falls back to the configured equity if the live balance
        is unavailable (e.g. account not yet loaded).
        """
        try:
            account = self.portfolio.account(self.instrument_id.venue)
            if account is not None:
                balance = account.balance_total(USDT)
                if balance is not None:
                    equity = float(balance)
                    if equity > 0:
                        return equity
        except Exception as e:
            self.log.warning(f"⚠️ Could not read live account balance: {e}")
        return float(self.equity)

    def _get_current_atr(self) -> float:
        """Current ATR value from the latest technical data (0 if unavailable)."""
        technical = self.latest_technical_data or {}
        return float(technical.get('atr', 0.0) or 0.0)

    def _calculate_stop_loss_price(self, side: str, entry_price: float) -> float:
        """
        Calculate stop-loss price for a position side ('long'/'short').

        Priority: ATR-based (sl_atr_multiplier x ATR) when use_atr_exits and
        ATR is available, then support/resistance, then a default 2% stop.
        """
        atr = self._get_current_atr()
        if self.use_atr_exits and atr > 0:
            if side == 'long':
                return entry_price - self.sl_atr_multiplier * atr
            return entry_price + self.sl_atr_multiplier * atr

        technical = self.latest_technical_data or {}
        support = technical.get('support', 0.0)
        resistance = technical.get('resistance', 0.0)

        if side == 'long':
            if self.sl_use_support_resistance and support > 0:
                return support * (1 - self.sl_buffer_pct)
            return entry_price * 0.98
        else:
            if self.sl_use_support_resistance and resistance > 0:
                return resistance * (1 + self.sl_buffer_pct)
            return entry_price * 1.02

    def _calculate_take_profit_price(self, side: str, entry_price: float, confidence: str) -> float:
        """
        Calculate take-profit price for a position side ('long'/'short').

        ATR-based (tp_atr_multiplier x ATR) when use_atr_exits and ATR is
        available — with the default 3.0/1.5 multipliers this gives a 2:1
        reward:risk. Falls back to the confidence-based percentage target.
        """
        atr = self._get_current_atr()
        if self.use_atr_exits and atr > 0:
            if side == 'long':
                return entry_price + self.tp_atr_multiplier * atr
            return entry_price - self.tp_atr_multiplier * atr

        tp_pct = self.tp_pct_config.get(confidence, 0.02)
        if side == 'long':
            return entry_price * (1 + tp_pct)
        return entry_price * (1 - tp_pct)

    def _same_signal_run_length(self) -> int:
        """Count trailing consecutive identical AI signals (including latest)."""
        history = getattr(self.deepseek, 'signal_history', [])
        if not history:
            return 0
        last = history[-1].get('signal')
        run = 0
        for s in reversed(history):
            if s.get('signal') == last:
                run += 1
            else:
                break
        return run

    def _load_risk_state(self) -> None:
        """Load persisted kill-switch state (survives restarts)."""
        try:
            if os.path.exists(self.risk_state_file):
                with open(self.risk_state_file, 'r') as f:
                    saved = json.load(f)
                if isinstance(saved, dict):
                    for key in self.risk_state:
                        if key in saved:
                            self.risk_state[key] = saved[key]
                self.log.info(f"🛡️ Risk state loaded: {self.risk_state}")
        except Exception as e:
            self.log.warning(f"⚠️ Could not load risk state file: {e}")

    def _save_risk_state(self) -> None:
        """Persist kill-switch state to disk."""
        try:
            directory = os.path.dirname(self.risk_state_file)
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(self.risk_state_file, 'w') as f:
                json.dump(self.risk_state, f)
        except Exception as e:
            self.log.warning(f"⚠️ Could not save risk state file: {e}")

    def _trigger_pause(self, reason: str) -> None:
        """Pause new trading for loss_pause_hours and notify."""
        paused_until = self.clock.utc_now().to_pydatetime() + timedelta(hours=self.loss_pause_hours)
        self.risk_state["paused_until"] = paused_until.isoformat()
        self._save_risk_state()
        self.log.error(
            f"🛡️ TRADING PAUSED for {self.loss_pause_hours:.0f}h: {reason}"
        )
        if self.telegram_bot and self.enable_telegram and self.telegram_notify_errors:
            try:
                alert = self.telegram_bot.format_error_alert({
                    'level': 'RISK',
                    'message': f"Trading paused {self.loss_pause_hours:.0f}h: {reason}"[:200],
                    'context': 'risk_guard',
                })
                self.telegram_bot.send_message_sync(alert)
            except Exception:
                pass

    def _check_risk_guards(self) -> bool:
        """
        Evaluate kill-switches before any trade execution.

        Returns True if trading is allowed, False if blocked.
        """
        now = self.clock.utc_now().to_pydatetime()
        today = now.strftime('%Y-%m-%d')

        # (1) UTC day rollover: reset the daily equity baseline
        if self.risk_state.get("day_date") != today:
            self.risk_state["day_date"] = today
            self.risk_state["day_start_equity"] = self._get_account_equity()
            self._save_risk_state()

        # (2) Active pause?
        paused_until_str = self.risk_state.get("paused_until")
        if paused_until_str:
            try:
                paused_until = datetime.fromisoformat(paused_until_str)
                if now < paused_until:
                    self.log.warning(
                        f"🛡️ Risk guard: trading paused until {paused_until_str} (UTC)"
                    )
                    return False
                # Pause expired: clear and reset the loss streak
                self.risk_state["paused_until"] = None
                self.risk_state["consecutive_losses"] = 0
                self._save_risk_state()
                self.log.info("🛡️ Risk guard: pause expired, trading resumed")
            except ValueError:
                self.risk_state["paused_until"] = None

        # (3) Daily loss limit vs live equity
        start_equity = self.risk_state.get("day_start_equity")
        if start_equity and start_equity > 0:
            equity_now = self._get_account_equity()
            daily_pnl_pct = (equity_now - start_equity) / start_equity
            if daily_pnl_pct <= -self.daily_loss_limit_pct:
                self._trigger_pause(
                    f"Daily loss limit hit: {daily_pnl_pct:+.2%} "
                    f"(limit -{self.daily_loss_limit_pct:.2%})"
                )
                return False

        # (4) Anti-churn: block after too many consecutive identical signals
        run = self._same_signal_run_length()
        if run > self.max_consecutive_same_signal:
            self.log.warning(
                f"🛡️ Risk guard: {run} consecutive identical signals "
                f"(max {self.max_consecutive_same_signal}) - blocking churn"
            )
            return False

        return True

    def _submit_disaster_stop(self, side: str, quantity: float, entry_price: float) -> None:
        """
        Submit a native exchange-side catastrophic stop-loss.

        Unlike emulated stops (which die with the process), this STOP_MARKET
        order lives on Binance and protects the position even if the bot
        crashes or restarts. It is placed at 2x the normal SL distance
        (minimum disaster_stop_min_pct) so the regular emulated SL and
        trailing stop trigger first under normal operation.
        """
        try:
            sl_price = self._calculate_stop_loss_price(side, entry_price)
            sl_dist_pct = abs(entry_price - sl_price) / entry_price
            disaster_dist_pct = max(2.0 * sl_dist_pct, self.disaster_stop_min_pct)

            if side == 'long':
                stop_price = entry_price * (1 - disaster_dist_pct)
                exit_side = OrderSide.SELL
            else:
                stop_price = entry_price * (1 + disaster_dist_pct)
                exit_side = OrderSide.BUY

            order = self.order_factory.stop_market(
                instrument_id=self.instrument_id,
                order_side=exit_side,
                quantity=self.instrument.make_qty(quantity),
                trigger_price=self.instrument.make_price(stop_price),
                trigger_type=TriggerType.LAST_PRICE,
                time_in_force=TimeInForce.GTC,
                reduce_only=True,
            )
            self.submit_order(order)

            self.disaster_stop_state[str(self.instrument_id)] = {
                "order_id": str(order.client_order_id),
                "price": stop_price,
            }
            self.log.info(
                f"🛡️ Native disaster stop submitted @ ${stop_price:,.2f} "
                f"({disaster_dist_pct:.2%} from entry, qty {quantity})"
            )
        except Exception as e:
            self.log.error(f"❌ Failed to submit disaster stop: {e}")

    def _cancel_disaster_stop(self) -> None:
        """Cancel the native disaster stop if one is open."""
        state = self.disaster_stop_state.pop(str(self.instrument_id), None)
        if not state:
            return
        try:
            order = self.cache.order(ClientOrderId(state["order_id"]))
            if order and order.is_open:
                self.cancel_order(order)
                self.log.info(
                    f"🗑️ Cancelled disaster stop {state['order_id'][:8]}..."
                )
        except Exception as e:
            self.log.warning(f"⚠️ Failed to cancel disaster stop: {e}")

    # ===== Phase 2: signal measurement & regime filter =====

    def _log_signal_record(
        self,
        signal_data: Dict[str, Any],
        price_data: Dict[str, Any],
        technical_data: Dict[str, Any],
        current_position: Optional[Dict[str, Any]],
    ) -> None:
        """
        Append one JSONL record per evaluated signal.

        This is the calibration dataset consumed by tools/score_signals.py:
        every cycle's signal is recorded with the exact SL/TP the strategy
        would have used, so signal quality can be measured offline against
        realized price paths — including cycles where no trade was taken.
        """
        try:
            price = float(price_data['price'])
            signal = signal_data.get('signal', 'HOLD')
            if signal in ('BUY', 'SELL'):
                side = 'long' if signal == 'BUY' else 'short'
                sl_price = self._calculate_stop_loss_price(side, price)
                tp_price = self._calculate_take_profit_price(
                    side, price, signal_data.get('confidence', 'MEDIUM')
                )
            else:
                sl_price = None
                tp_price = None

            record = {
                "ts": self.clock.utc_now().isoformat(),
                "signal": signal,
                "confidence": signal_data.get('confidence', 'LOW'),
                "price": price,
                "atr": self._get_current_atr(),
                "sl_price": sl_price,
                "tp_price": tp_price,
                "regime": self._get_regime(),
                "rsi": technical_data.get('rsi'),
                "overall_trend": technical_data.get('overall_trend'),
                "macd_histogram": technical_data.get('macd_histogram'),
                "bb_position": technical_data.get('bb_position'),
                "volume_ratio": technical_data.get('volume_ratio'),
                "has_position": current_position is not None,
                "position_side": current_position.get('side') if current_position else None,
                "signal_only": self.signal_only_mode,
                "reason": str(signal_data.get('reason', ''))[:300],
            }

            directory = os.path.dirname(self.signal_log_file)
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(self.signal_log_file, 'a') as f:
                f.write(json.dumps(record) + "\n")
        except Exception as e:
            self.log.warning(f"⚠️ Failed to write signal record: {e}")

    def _get_regime(self) -> str:
        """Cached higher-timeframe regime: 'up', 'down', 'flat' or 'unknown'."""
        import time
        now = time.monotonic()
        if (
            self._regime_cache["value"] is not None
            and now - self._regime_cache["ts"] < self.regime_cache_ttl_sec
        ):
            return self._regime_cache["value"]
        regime = self._fetch_regime()
        self._regime_cache = {"value": regime, "ts": now}
        return regime

    def _fetch_regime(self) -> str:
        """Classify the higher-timeframe trend from Binance klines (EMA cross)."""
        try:
            import requests
            symbol = str(self.instrument_id).split('-')[0]
            response = requests.get(
                "https://fapi.binance.com/fapi/v1/klines",
                params={
                    "symbol": symbol,
                    "interval": self.regime_timeframe,
                    "limit": 60,
                },
                timeout=10,
            )
            response.raise_for_status()
            closes = [float(k[4]) for k in response.json()]
            if len(closes) < self.regime_ema_slow + 1:
                return "unknown"

            ema_fast = self._ema(closes, self.regime_ema_fast)
            ema_slow = self._ema(closes, self.regime_ema_slow)
            spread_pct = (ema_fast - ema_slow) / closes[-1]

            if abs(spread_pct) < self.regime_flat_threshold_pct:
                return "flat"
            return "up" if spread_pct > 0 else "down"
        except Exception as e:
            self.log.warning(f"⚠️ Regime fetch failed: {e}")
            return "unknown"

    @staticmethod
    def _ema(values: List[float], period: int) -> float:
        """Exponential moving average over a price series."""
        k = 2.0 / (period + 1)
        ema = values[0]
        for value in values[1:]:
            ema = value * k + ema * (1 - k)
        return ema

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
        self.latest_price_data = price_data

        # Phase 2: record every evaluated signal for offline calibration
        self._log_signal_record(signal_data, price_data, technical_data, current_position)

        # Phase 2: shadow mode - measure signal quality without executing
        if self.signal_only_mode:
            self.log.info("📝 Signal-only mode: signal recorded, execution disabled")
            return

        # Phase 0 kill-switches (daily loss limit, loss streaks, anti-churn)
        if not self._check_risk_guards():
            return

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

        # Phase 2: higher-timeframe regime gate (trade with the trend, sit out chop)
        if self.regime_filter_enabled:
            regime = self._get_regime()
            if regime == "flat":
                self.log.info("🧭 Regime filter: higher timeframe is flat/choppy - no trades")
                return
            if regime == "up" and signal == 'SELL':
                self.log.info("🧭 Regime filter: 4h uptrend - SELL blocked")
                return
            if regime == "down" and signal == 'BUY':
                self.log.info("🧭 Regime filter: 4h downtrend - BUY blocked")
                return
            # "unknown" -> fail-open so data issues never block trading

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
        Calculate risk-based position size (Phase 0).

        Size is derived from LIVE account equity and the stop-loss distance:
        quantity = risk_usdt / (sl_distance_pct * price), where risk_usdt is
        equity * risk_per_trade_pct scaled by confidence/trend/RSI modifiers.
        Notional is capped at max_position_leverage * equity. If the result
        is below the exchange minimum notional, the trade is SKIPPED (never
        upsized to meet the minimum).

        Returns BTC quantity, or 0.0 when the trade is not allowed.
        """
        entry_price = price_data['price']
        side = 'long' if signal_data['signal'] == 'BUY' else 'short'

        # Live equity (falls back to configured equity if unavailable)
        equity = self._get_account_equity()

        # Stop-loss distance drives the size
        sl_price = self._calculate_stop_loss_price(side, entry_price)
        sl_distance_pct = abs(entry_price - sl_price) / entry_price

        # Floor the distance to avoid degenerate huge sizes when S/R == entry
        MIN_SL_DISTANCE_PCT = 0.002  # 0.2%
        if sl_distance_pct < MIN_SL_DISTANCE_PCT:
            sl_distance_pct = MIN_SL_DISTANCE_PCT

        # Confidence / trend / RSI modifiers scale RISK, not notional
        conf_mult = self.position_config.get(
            f"{signal_data['confidence'].lower()}_confidence_multiplier",
            1.0
        )
        trend = technical_data.get('overall_trend', '震荡整理')
        trend_mult = (
            self.position_config['trend_strength_multiplier']
            if trend in ['强势上涨', '强势下跌']
            else 1.0
        )
        rsi = technical_data.get('rsi', 50)
        rsi_mult = (
            self.rsi_extreme_mult
            if rsi > self.rsi_extreme_upper or rsi < self.rsi_extreme_lower
            else 1.0
        )

        risk_usdt = equity * self.risk_per_trade_pct * conf_mult * trend_mult * rsi_mult
        quantity = risk_usdt / (sl_distance_pct * entry_price)

        # Notional cap: max_position_leverage * live equity
        max_notional = equity * self.max_position_leverage
        if quantity * entry_price > max_notional:
            quantity = max_notional / entry_price

        # Round DOWN to instrument precision (never round up beyond risk)
        quantity = math.floor(quantity * 1000) / 1000

        # Minimum notional: skip the trade instead of inflating size
        notional = quantity * entry_price
        if quantity < self.position_config['min_trade_amount'] or notional < self.min_notional_usdt:
            self.log.warning(
                f"🛡️ Trade skipped: sized {quantity:.3f} BTC (${notional:.2f}) is below "
                f"minimum (${self.min_notional_usdt:.0f} notional) at current equity "
                f"${equity:.2f}. Risk limits not violated - no trade."
            )
            return 0.0

        self.log.info(
            f"📊 Position Sizing: equity ${equity:.2f} | "
            f"risk ${risk_usdt:.2f} ({self.risk_per_trade_pct:.2%} × Conf:{conf_mult} "
            f"× Trend:{trend_mult} × RSI:{rsi_mult}) | "
            f"SL dist {sl_distance_pct:.2%} → {quantity:.3f} BTC (notional: ${notional:.2f})"
        )

        return quantity

    def _manage_existing_position(
        self,
        current_position: Dict[str, Any],
        target_side: str,
        target_quantity: float,
        confidence: str,
    ):
        """Manage existing position (reduce or close only; adds/re-entries blocked)."""
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
                # Phase 0: pyramiding disabled. Adds are not covered by the
                # bracket SL/TP and previously allowed uncapped position growth.
                self.log.info(
                    f"🛡️ Add to {target_side} position blocked (pyramiding disabled): "
                    f"keeping {current_qty:.3f} BTC"
                )
                return
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

        # Opposite direction - close only, do NOT re-open
        elif self.allow_reversals:
            # Check if high confidence required for reversal
            if self.require_high_conf_reversal and confidence != 'HIGH':
                self.log.warning(
                    f"🔒 Reversal requires HIGH confidence, got {confidence}. "
                    f"Keeping {current_side} position."
                )
                return

            # Phase 0: close-only reversal. The old logic re-opened via a plain
            # market order, leaving the new position with NO SL/TP and no
            # trailing stop state. Now we only close; if the signal persists,
            # the next cycle opens a fresh position through _open_new_position
            # with full bracket SL/TP protection.
            self.log.info(
                f"🔄 Reversal signal ({current_side} → {target_side}): closing position "
                f"only; a protected {target_side} entry will be evaluated next cycle"
            )

            # Close current position
            self._submit_order(
                side=OrderSide.SELL if current_side == 'long' else OrderSide.BUY,
                quantity=current_qty,
                reduce_only=True,
            )

        else:
            self.log.warning(
                f"⚠️ Signal suggests {target_side} but have {current_side} position. "
                f"Reversals disabled."
            )

    def _open_new_position(self, side: str, quantity: float):
        """
        Open new position using bracket order (entry + SL + TP).

        This method submits a bracket order which automatically includes:
        - Entry order (MARKET)
        - Stop Loss order (STOP_MARKET)
        - Take Profit order(s) (LIMIT)

        The SL and TP orders are linked with OCO, so when one fills, the others cancel.
        """
        order_side = OrderSide.BUY if side == 'long' else OrderSide.SELL

        # Submit bracket order with SL/TP
        self._submit_bracket_order(
            side=order_side,
            quantity=quantity,
        )

        self.log.info(f"🚀 Opening {side} position: {quantity:.3f} BTC (with bracket SL/TP)")

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
    
    def _submit_bracket_order(
        self,
        side: OrderSide,
        quantity: float,
    ):
        """
        Submit a bracket order with entry, stop loss, and take profit using NautilusTrader's built-in bracket orders.

        This uses the OrderFactory.bracket() method which automatically creates:
        - Entry order (MARKET)
        - Stop Loss order (STOP_MARKET) linked with OTO (One-Triggers-Other)
        - Take Profit order (LIMIT) linked with OTO and OCO with SL

        The OCO linkage is handled automatically by NautilusTrader.

        Parameters
        ----------
        side : OrderSide
            Side of the entry order (BUY or SELL)
        quantity : float
            Quantity to trade
        """
        if quantity < self.position_config['min_trade_amount']:
            self.log.warning(
                f"⚠️ Order quantity {quantity:.3f} below minimum "
                f"{self.position_config['min_trade_amount']:.3f}, skipping"
            )
            return

        if not self.enable_auto_sl_tp:
            self.log.warning("⚠️ Auto SL/TP is disabled - submitting simple market order instead")
            self._submit_order(side=side, quantity=quantity, reduce_only=False)
            return

        if not self.latest_signal_data or not self.latest_technical_data:
            # Phase 0: never open an unprotected position as a fallback
            self.log.error("❌ No signal/technical data available for SL/TP - skipping entry")
            return

        # Determine latest price for entry estimation
        entry_price: Optional[float] = None

        if self.latest_price_data and self.latest_price_data.get('price'):
            entry_price = float(self.latest_price_data['price'])

        if entry_price is None and hasattr(self.indicator_manager, "recent_bars"):
            recent_bars = self.indicator_manager.recent_bars
            if recent_bars:
                entry_price = float(recent_bars[-1].close)

        if entry_price is None:
            cache_bars = self.cache.bars(self.bar_type)
            if cache_bars:
                entry_price = float(cache_bars[-1].close)

        if entry_price is None or entry_price <= 0:
            # Phase 0: never open an unprotected position as a fallback
            self.log.error("❌ Unable to determine entry price for bracket order - skipping entry")
            return

        # Get confidence for TP calculation
        confidence = self.latest_signal_data.get('confidence', 'MEDIUM')

        # Calculate Stop Loss price (shared with risk-based position sizing)
        side_str = 'long' if side == OrderSide.BUY else 'short'
        stop_loss_price = self._calculate_stop_loss_price(side_str, entry_price)
        if side == OrderSide.BUY:
            self.log.info(f"📍 Stop loss for LONG: ${stop_loss_price:,.2f}")
        else:
            self.log.info(f"📍 Stop loss for SHORT: ${stop_loss_price:,.2f}")

        # Calculate Take Profit price (ATR-based when enabled, else confidence %)
        tp_price = self._calculate_take_profit_price(side_str, entry_price, confidence)

        # Log SL/TP summary
        self.log.info(
            f"🎯 Creating bracket order for {side.name}:\n"
            f"   Entry: ~${entry_price:,.2f} (MARKET)\n"
            f"   Stop Loss: ${stop_loss_price:,.2f} ({((stop_loss_price/entry_price - 1) * 100):.2f}%)\n"
            f"   Take Profit: ${tp_price:,.2f} ({((tp_price/entry_price - 1) * 100):.2f}%)\n"
            f"   Quantity: {quantity:.3f}\n"
            f"   Confidence: {confidence}"
        )

        try:
            # Create bracket order using OrderFactory
            # This automatically creates entry + SL + TP with OTO/OCO linkage
            # IMPORTANT: Use emulation_trigger to enable order emulation for Binance compatibility
            # Binance doesn't support native OCO+OTO orders, so NautilusTrader will emulate them
            bracket_order_list = self.order_factory.bracket(
                instrument_id=self.instrument_id,
                order_side=side,
                quantity=self.instrument.make_qty(quantity),
                sl_trigger_price=self.instrument.make_price(stop_loss_price),
                tp_price=self.instrument.make_price(tp_price),
                time_in_force=TimeInForce.GTC,
                emulation_trigger=TriggerType.DEFAULT,  # Enable order emulation
            )

            # Submit the bracket order list
            self.submit_order_list(bracket_order_list)

            self.log.info(
                f"✅ Submitted bracket order: {side.name} {quantity:.3f} BTC with SL/TP\n"
                f"   OrderList ID: {bracket_order_list.id}"
            )

            # Save bracket order info for trailing stop
            if self.enable_trailing_stop:
                instrument_key = str(self.instrument_id)

                # Extract SL order from bracket (it's typically the second order in the list)
                sl_order = None
                for order in bracket_order_list.orders:
                    if order.order_type == OrderType.STOP_MARKET:
                        sl_order = order
                        break

                if sl_order:
                    self.trailing_stop_state[instrument_key] = {
                        "entry_price": entry_price,
                        "highest_price": entry_price if side == OrderSide.BUY else None,
                        "lowest_price": entry_price if side == OrderSide.SELL else None,
                        "current_sl_price": stop_loss_price,
                        "sl_order_id": str(sl_order.client_order_id),
                        "activated": False,
                        "side": "LONG" if side == OrderSide.BUY else "SHORT",
                        "quantity": quantity,
                        "atr": self._get_current_atr(),
                    }
                    self.log.debug(
                        f"📌 Saved SL order ID for trailing stop: {str(sl_order.client_order_id)[:8]}..."
                    )

            # Phase 1: initialize partial take-profit tracking (R-multiple based)
            if self.enable_partial_tp and self.partial_tp_levels:
                self.partial_tp_state[instrument_key] = {
                    "entry_price": entry_price,
                    "sl_distance": abs(entry_price - stop_loss_price),
                    "side": "LONG" if side == OrderSide.BUY else "SHORT",
                    "original_quantity": quantity,
                    "levels_done": [],
                }

        except Exception as e:
            # Phase 0: never fall back to an unprotected naked entry
            self.log.error(f"❌ Failed to submit bracket order: {e} - entry skipped (no unprotected positions)")

    def on_order_filled(self, event):
        """
        Handle order filled events.

        Note: OCO logic is now handled automatically by NautilusTrader's bracket orders.
        We no longer need to manually cancel peer orders.
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
    

    def on_order_rejected(self, event):
        """Handle order rejected events."""
        self.log.error(f"❌ Order rejected: {event.reason}")

    def on_position_opened(self, event):
        """
        Handle position opened events.

        Note: With bracket orders, SL/TP orders are automatically submitted as part of the bracket.
        We no longer need to manually submit them here.
        """
        # PositionOpened event contains position data directly
        self.log.info(
            f"🟢 Position opened: {event.side.name} "
            f"{event.quantity} @ {event.avg_px_open}"
        )

        # Update trailing stop state with actual entry price if it exists
        # (bracket order already initialized it with estimated price)
        if self.enable_trailing_stop:
            instrument_key = str(self.instrument_id)
            entry_price = float(event.avg_px_open)

            if instrument_key in self.trailing_stop_state:
                # Update with actual entry price
                self.trailing_stop_state[instrument_key]["entry_price"] = entry_price
                if event.side == PositionSide.LONG:
                    self.trailing_stop_state[instrument_key]["highest_price"] = entry_price
                else:
                    self.trailing_stop_state[instrument_key]["lowest_price"] = entry_price

                self.log.debug(
                    f"📊 Updated trailing stop state with actual entry price: ${entry_price:,.2f}"
                )
            else:
                # Fallback: initialize if not already set (shouldn't happen with bracket orders)
                self.trailing_stop_state[instrument_key] = {
                    "entry_price": entry_price,
                    "highest_price": entry_price if event.side == PositionSide.LONG else None,
                    "lowest_price": entry_price if event.side == PositionSide.SHORT else None,
                    "current_sl_price": None,
                    "sl_order_id": None,
                    "activated": False,
                    "side": event.side.name,
                    "quantity": float(event.quantity),
                    "atr": self._get_current_atr(),
                }
                self.log.info(
                    f"📊 Trailing stop initialized for {event.side.name} position @ ${entry_price:,.2f}"
                )

        # Phase 0: native exchange-side catastrophic stop, independent of the
        # (emulated) bracket SL. Protects the position if this process dies.
        if self.disaster_stop_enabled:
            side_str = 'long' if event.side == PositionSide.LONG else 'short'
            self._submit_disaster_stop(
                side=side_str,
                quantity=float(event.quantity),
                entry_price=float(event.avg_px_open),
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
            f"P&L: {float(event.realized_pnl):.2f} USDT"
        )

        # Phase 0: consecutive-loss kill-switch
        realized_pnl = float(event.realized_pnl)
        if realized_pnl < 0:
            self.risk_state["consecutive_losses"] = int(self.risk_state.get("consecutive_losses", 0)) + 1
        else:
            self.risk_state["consecutive_losses"] = 0
        if self.risk_state["consecutive_losses"] >= self.max_consecutive_losses:
            self._trigger_pause(
                f"{self.risk_state['consecutive_losses']} consecutive losing trades "
                f"(max {self.max_consecutive_losses})"
            )
        self._save_risk_state()

        # Cancel the native disaster stop (position is flat now)
        self._cancel_disaster_stop()

        # Clear trailing stop state
        instrument_key = str(self.instrument_id)
        if instrument_key in self.trailing_stop_state:
            del self.trailing_stop_state[instrument_key]
            self.log.debug(f"🗑️ Cleared trailing stop state for {instrument_key}")

        # Clear partial take-profit state
        if instrument_key in self.partial_tp_state:
            del self.partial_tp_state[instrument_key]
            self.log.debug(f"🗑️ Cleared partial TP state for {instrument_key}")
        
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
        Clean up orphan orders.

        This is a safety mechanism that runs periodically to:
        1. Cancel orphan reduce-only orders when no position exists

        Note: OCO group management is no longer needed as NautilusTrader handles it automatically.
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

        except Exception as e:
            self.log.error(f"❌ Orphan order cleanup failed: {e}")
    
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

            # Phase 1: ATR-based activation/distance when available
            atr = float(state.get("atr") or 0.0)
            use_atr = self.trailing_use_atr and atr > 0
            activation_distance = (
                self.trailing_activation_atr * atr
                if use_atr else self.trailing_activation_pct * entry_price
            )
            
            # Calculate profit percentage
            if side == "LONG":
                profit_distance = current_price - entry_price
                profit_pct = profit_distance / entry_price
                
                # Update highest price
                if state["highest_price"] is None or current_price > state["highest_price"]:
                    state["highest_price"] = current_price
                
                highest_price = state["highest_price"]
                
                # Check if we should activate trailing stop
                if not activated and profit_distance >= activation_distance:
                    state["activated"] = True
                    self.log.info(
                        f"🎯 Trailing stop ACTIVATED for LONG @ ${current_price:,.2f} "
                        f"(Profit: {profit_pct*100:.2f}%)"
                    )
                    activated = True
                
                # If activated, check if we should update stop loss
                if activated:
                    # Calculate new stop loss based on highest price
                    new_sl_price = (
                        highest_price - self.trailing_distance_atr * atr
                        if use_atr else highest_price * (1 - self.trailing_distance_pct)
                    )
                    current_sl_price = state["current_sl_price"]
                    
                    # Only update if new SL is significantly higher than current
                    if current_sl_price is None:
                        should_update = True
                    else:
                        price_move_pct = (new_sl_price - current_sl_price) / current_sl_price
                        should_update = price_move_pct >= self.trailing_update_threshold_pct
                    
                    if should_update and (current_sl_price is None or new_sl_price > current_sl_price):
                        self._execute_trailing_stop_update(
                            instrument_key=instrument_key,
                            new_sl_price=new_sl_price,
                            current_price=current_price,
                            side="LONG"
                        )
            
            elif side == "SHORT":
                profit_distance = entry_price - current_price
                profit_pct = profit_distance / entry_price
                
                # Update lowest price
                if state["lowest_price"] is None or current_price < state["lowest_price"]:
                    state["lowest_price"] = current_price
                
                lowest_price = state["lowest_price"]
                
                # Check if we should activate trailing stop
                if not activated and profit_distance >= activation_distance:
                    state["activated"] = True
                    self.log.info(
                        f"🎯 Trailing stop ACTIVATED for SHORT @ ${current_price:,.2f} "
                        f"(Profit: {profit_pct*100:.2f}%)"
                    )
                    activated = True
                
                # If activated, check if we should update stop loss
                if activated:
                    # Calculate new stop loss based on lowest price
                    new_sl_price = (
                        lowest_price + self.trailing_distance_atr * atr
                        if use_atr else lowest_price * (1 + self.trailing_distance_pct)
                    )
                    current_sl_price = state["current_sl_price"]
                    
                    # Only update if new SL is significantly lower than current
                    if current_sl_price is None:
                        should_update = True
                    else:
                        price_move_pct = (current_sl_price - new_sl_price) / current_sl_price
                        should_update = price_move_pct >= self.trailing_update_threshold_pct
                    
                    if should_update and (current_sl_price is None or new_sl_price < current_sl_price):
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
                trigger_type=TriggerType.LAST_PRICE,
                # Phase 0: native Binance STOP_MARKET (no emulation) so the stop
                # lives on the exchange and survives process restarts
                reduce_only=True,
            )
            self.submit_order(new_sl_order)
            
            # Update state
            state["current_sl_price"] = new_sl_price
            state["sl_order_id"] = str(new_sl_order.client_order_id)

            self.log.info(f"✅ New trailing SL order submitted @ ${new_sl_price:,.2f}")

            # Note: OCO relationship is handled automatically by NautilusTrader
            # When the new SL is submitted, it will be linked to the existing TP orders

        except Exception as e:
            self.log.error(f"❌ Failed to execute trailing stop update: {e}")

    def _check_partial_take_profits(self, current_price: float):
        """
        Execute configured partial take-profit levels (in R multiples).

        R is the entry-to-stop distance captured at entry. When price reaches
        r_multiple x R in profit, a reduce-only market order closes
        position_pct of the ORIGINAL quantity. Each level fires at most once.
        """
        try:
            instrument_key = str(self.instrument_id)
            state = self.partial_tp_state.get(instrument_key)
            if not state:
                return

            entry_price = state["entry_price"]
            sl_distance = state["sl_distance"]
            if sl_distance <= 0:
                return

            if state["side"] == "LONG":
                r_now = (current_price - entry_price) / sl_distance
            else:
                r_now = (entry_price - current_price) / sl_distance

            for idx, level in enumerate(self.partial_tp_levels):
                if idx in state["levels_done"]:
                    continue
                if r_now < level.get("r_multiple", 1.0):
                    continue

                qty = math.floor(
                    state["original_quantity"] * level.get("position_pct", 0.5) * 1000
                ) / 1000
                state["levels_done"].append(idx)

                if qty < self.position_config['min_trade_amount']:
                    self.log.warning(
                        f"⚠️ Partial TP level {idx + 1} reached ({r_now:.2f}R) but "
                        f"quantity {qty:.3f} below minimum - skipping"
                    )
                    continue

                exit_side = OrderSide.SELL if state["side"] == "LONG" else OrderSide.BUY
                self._submit_order(side=exit_side, quantity=qty, reduce_only=True)

                # Keep tracked trailing-stop quantity in sync with reduced position
                if instrument_key in self.trailing_stop_state:
                    remaining = self.trailing_stop_state[instrument_key]["quantity"] - qty
                    self.trailing_stop_state[instrument_key]["quantity"] = max(0.0, remaining)

                self.log.info(
                    f"💰 Partial TP level {idx + 1} hit at {r_now:.2f}R: "
                    f"closed {qty:.3f} BTC ({level.get('position_pct', 0.5):.0%} of original)"
                )

                # Telegram notification
                if self.telegram_bot and self.enable_telegram and self.telegram_notify_positions:
                    try:
                        tp_msg = self.telegram_bot.format_partial_tp_notification({
                            'level': idx + 1,
                            'quantity': qty,
                            'price': current_price,
                            'profit_pct': (current_price - entry_price) / entry_price
                                if state["side"] == "LONG"
                                else (entry_price - current_price) / entry_price,
                            'remaining_quantity': max(0.0, state["original_quantity"] - qty),
                        })
                        self.telegram_bot.send_message_sync(tp_msg)
                    except Exception:
                        pass

        except Exception as e:
            self.log.error(f"❌ Partial take-profit check failed: {e}")

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
