"""
AI Strategy for NautilusTrader

AI-powered cryptocurrency trading strategy using an LLM (Anthropic Claude by
default; DeepSeek / Kimi / any OpenAI-compatible API as alternatives) for
decision making, technical indicators for market analysis, and sentiment data
for validation.

Class names keep the historical ``DeepSeek`` prefix for backwards compatibility
with existing configs, service files and imports.
"""

import os
import json
import math
import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor
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
from utils.llm_client import LLMAnalyzer, resolve_provider
from utils.sentiment_client import SentimentDataFetcher
# OCOManager no longer needed - using NautilusTrader's built-in bracket orders


class DeepSeekAIStrategyConfig(StrategyConfig, frozen=True):
    """Configuration for DeepSeek AI Strategy."""

    # Instrument
    instrument_id: str
    bar_type: str
    # Binance USDT-M REST endpoint for historical klines (prefetch + regime filter).
    # Must match the venue the data/exec clients connect to (live/testnet/demo).
    binance_rest_base_url: str = "https://fapi.binance.com"

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

    # AI configuration (LLM decision layer)
    # provider: "anthropic" (Claude, default) | "openai" (DeepSeek/Kimi/any OpenAI-compatible) | "auto"
    llm_provider: str = "auto"
    llm_api_key: str = ""
    llm_model: str = ""  # empty -> provider default (claude-sonnet-5-5 / deepseek-v4-pro)
    llm_base_url: str = ""  # empty -> provider default
    llm_temperature: float = 0.1  # OpenAI-compatible providers only
    llm_effort: str = "medium"  # Anthropic only: low | medium | high | xhigh | max
    llm_max_retries: int = 2
    llm_timeout_sec: float = 60.0  # bounded: the call blocks the trading event loop
    llm_max_tokens: int = 1024
    llm_workspace_id: str = ""  # Anthropic only: wrkspc_... (required for multi-workspace keys)

    # Legacy DeepSeek-era names (still honoured when the llm_* fields are empty)
    deepseek_api_key: str = ""
    deepseek_model: str = ""
    deepseek_temperature: float = 0.1
    deepseek_max_retries: int = 2
    deepseek_base_url: str = ""

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
    max_total_drawdown_pct: float = 0.10  # Circuit breaker: halt (until manual reset) once live equity is this far below its peak
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
    trailing_update_threshold_atr: float = 0.25  # Move the stop only when it improves by >= this x ATR

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

    # Testing aid (paper venues ONLY - main_live.py refuses it on BINANCE_ENV=live):
    # bypass the LLM for the first `force_signal_cycles` analysis cycles and push
    # this signal through the real risk guards / sizing / bracket-order path.
    force_signal: str = ""  # "" | BUY | SELL
    force_signal_cycles: int = 1

    # Exit management & resilience
    native_exits: bool = True  # exchange-side SL (STOP_MARKET) + TP (TAKE_PROFIT_MARKET) that survive restarts;
                               # False = legacy emulated bracket legs (die with the process)
    position_state_file: str = "logs/position_state.json"  # persisted exit/trailing/partial-TP state
    heartbeat_file: str = "logs/heartbeat"  # touched on every bar/cycle; container healthchecks read its age
    llm_async: bool = True  # run LLM + sentiment + regime network calls on a worker thread (keeps the event loop free)


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
        self.binance_rest_base_url = (config.binance_rest_base_url or "https://fapi.binance.com").rstrip('/')

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
        self.trailing_update_threshold_atr = config.trailing_update_threshold_atr

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
        self.max_total_drawdown_pct = config.max_total_drawdown_pct
        self.max_consecutive_same_signal = config.max_consecutive_same_signal
        self.disaster_stop_enabled = config.disaster_stop_enabled
        self.disaster_stop_min_pct = config.disaster_stop_min_pct
        self.risk_state_file = config.risk_state_file

        # Exit management & resilience
        self.native_exits = config.native_exits
        self.position_state_file = config.position_state_file
        self.heartbeat_file = config.heartbeat_file
        self.llm_async = config.llm_async
        self._pending_entry: Optional[Dict[str, Any]] = None  # context for the fill that arms native exits
        self._loop = None  # asyncio loop captured in on_start (live mode)
        self._llm_executor: Optional[ThreadPoolExecutor] = None
        self._analysis_inflight = False

        # Kill-switch state (persisted to risk_state_file, survives restarts)
        self.risk_state: Dict[str, Any] = {
            "consecutive_losses": 0,
            "paused_until": None,      # ISO timestamp (UTC) while paused
            "day_date": None,          # UTC date of current daily baseline
            "day_start_equity": None,  # Equity at start of UTC day
            "equity_peak": None,       # High-water mark of live equity (circuit breaker reference)
            "halted_reason": None,     # Set when the circuit breaker trips; cleared only by a manual reset
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

        # LLM decision layer (Claude by default; DeepSeek/Kimi via OpenAI-compatible API)
        api_key = (
            config.llm_api_key
            or config.deepseek_api_key
            or os.getenv('ANTHROPIC_API_KEY')
            or os.getenv('LLM_API_KEY')
            or os.getenv('DEEPSEEK_API_KEY')
            or ''
        )
        if not api_key:
            raise ValueError(
                "LLM API key not provided (set ANTHROPIC_API_KEY, LLM_API_KEY or DEEPSEEK_API_KEY)"
            )

        llm_model = config.llm_model or config.deepseek_model or None
        llm_base_url = config.llm_base_url or config.deepseek_base_url or None
        provider = resolve_provider(config.llm_provider, api_key, llm_model, llm_base_url)

        self.deepseek = LLMAnalyzer(
            api_key=api_key,
            model=llm_model,
            temperature=config.llm_temperature,  # OpenAI-compatible providers only
            base_url=llm_base_url,
            max_retries=config.llm_max_retries or config.deepseek_max_retries,
            provider=provider,
            effort=config.llm_effort,
            timeout_sec=config.llm_timeout_sec,
            max_tokens=config.llm_max_tokens,
            workspace_id=config.llm_workspace_id or os.getenv('ANTHROPIC_WORKSPACE_ID', ''),
            nautilus_logger=self.log,
        )
        # Readable alias; `self.deepseek` is kept for backwards compatibility
        self.llm = self.deepseek
        
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

        # Forced test signal (paper venues only)
        self.force_signal = (config.force_signal or "").strip().upper()
        self._force_signal_remaining = int(config.force_signal_cycles) if self.force_signal in ("BUY", "SELL") else 0
        if self._force_signal_remaining:
            self.log.warning(
                f"🧪 FORCE_SIGNAL={self.force_signal} active for {self._force_signal_remaining} cycle(s) - "
                f"the LLM is bypassed and a synthetic signal is executed (paper venues only)"
            )

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

        # Worker thread for network-bound analysis (LLM, sentiment, regime)
        if self.llm_async:
            try:
                self._loop = asyncio.get_running_loop()
            except RuntimeError:
                self._loop = None
            if self._loop is not None:
                self._llm_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="llm-analysis")
                self.log.info("🧵 LLM analysis runs on a worker thread (event loop stays free)")
            else:
                self.log.warning("⚠️ No running event loop - LLM analysis will run synchronously")

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
        self._touch_heartbeat("start")

        # Restore persisted kill-switch state (daily baseline, loss streaks, pauses)
        self._load_risk_state()

        # Re-adopt a position left open by a previous process (restart/crash) and
        # make sure it is protected by exchange-side exits
        try:
            self._readopt_open_position()
        except Exception as e:
            self.log.error(f"❌ Failed to re-adopt open position: {e}", exc_info=True)

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
        self.log.info("Stopping AI Strategy...")

        if self._llm_executor is not None:
            self._llm_executor.shutdown(wait=False, cancel_futures=True)
            self._llm_executor = None

        # Cancel pending ENTRY orders only. Reduce-only protective orders (the
        # native disaster stop / trailing stop) must stay on the exchange while
        # a position is open - cancelling them here would leave the position
        # unprotected across a restart, defeating the purpose of the native stop.
        try:
            has_position = bool(self.cache.positions_open(instrument_id=self.instrument_id))
            if not has_position:
                self.cancel_all_orders(self.instrument_id)
            else:
                kept = 0
                for order in self.cache.orders_open(instrument_id=self.instrument_id):
                    if order.is_reduce_only:
                        kept += 1
                        continue
                    self.cancel_order(order)
                self.log.warning(
                    f"🛡️ Position still open on stop - keeping {kept} reduce-only "
                    f"protective order(s) on the exchange"
                )
        except Exception as e:
            self.log.error(f"❌ Error while cancelling orders on stop: {e}")
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
                f"📡 Pre-fetching {limit} historical bars from {self.binance_rest_base_url} "
                f"(symbol={symbol}, interval={interval})..."
            )

            # Binance Futures API endpoint
            url = f"{self.binance_rest_base_url}/fapi/v1/klines"
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

            # The last kline returned by Binance is the CURRENT, still-forming
            # candle (close time in the future). Feeding it as a closed bar would
            # double-count the period once the live bar arrives on close.
            now_ms = int(self.clock.timestamp_ms())
            closed_klines = [k for k in klines if int(k[6]) <= now_ms]
            if len(closed_klines) < len(klines):
                self.log.info(
                    f"📊 Received {len(klines)} klines from Binance "
                    f"(dropped {len(klines) - len(closed_klines)} unfinished candle)"
                )
            else:
                self.log.info(f"📊 Received {len(klines)} bars from Binance")
            klines = closed_klines

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
        self._touch_heartbeat("bar")

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

        Network-bound work (sentiment fetch, higher-timeframe regime, the LLM
        call) runs on a worker thread so the trading event loop - which also
        processes fills, position events and emulated orders - is never blocked
        for the 5-60 s an LLM round trip can take. The result is handed back to
        the event loop via `call_soon_threadsafe` and acted on in
        `_on_analysis_complete`.
        """
        self.log.info("=" * 60)
        self.log.info("Running periodic analysis...")
        self._touch_heartbeat("timer")

        if self._analysis_inflight:
            self.log.warning("⏳ Previous analysis still in flight (slow LLM?) - skipping this cycle")
            return

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

        # Forced test signal (paper venues only) is built on the event-loop thread
        forced_signal = None
        if self._force_signal_remaining > 0:
            self._force_signal_remaining -= 1
            forced_signal = self._build_forced_signal(price_data)

        ctx = {
            'price_data': price_data,
            'technical_data': technical_data,
            'current_position': current_position,
            'forced_signal': forced_signal,
            'regime_needed': self.regime_filter_enabled and self._regime_cache_stale(),
        }

        if self._llm_executor is not None and self._loop is not None:
            self._analysis_inflight = True
            self.log.info(
                f"Calling LLM ({self.llm.provider}/{self.llm.model}) on worker thread..."
                if forced_signal is None else "🧪 Forced signal - skipping LLM call"
            )
            self._llm_executor.submit(self._analysis_worker, ctx)
        else:
            self.log.info(f"Calling LLM ({self.llm.provider}/{self.llm.model}) for analysis...")
            self._on_analysis_complete(ctx, self._run_analysis(ctx))

    def _run_analysis(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        """
        Network-bound part of a cycle: sentiment, regime and the LLM decision.

        Safe to run on a worker thread: touches no NautilusTrader state other
        than logging. Never raises - errors are returned in the result.
        """
        result: Dict[str, Any] = {'sentiment': None, 'regime': None, 'signal': None, 'error': None, 'elapsed': 0.0}
        try:
            if self.sentiment_enabled and self.sentiment_fetcher:
                try:
                    result['sentiment'] = self.sentiment_fetcher.fetch()
                except Exception as e:
                    self.log.warning(f"Failed to fetch sentiment data: {e}")

            if ctx.get('regime_needed'):
                result['regime'] = self._fetch_regime()

            t0 = time.monotonic()
            if ctx.get('forced_signal') is not None:
                result['signal'] = ctx['forced_signal']
            else:
                result['signal'] = self.llm.analyze(
                    price_data=ctx['price_data'],
                    technical_data=ctx['technical_data'],
                    sentiment_data=result['sentiment'],
                    current_position=ctx['current_position'],
                )
            result['elapsed'] = time.monotonic() - t0
        except Exception as e:  # noqa: BLE001 - never let the worker die silently
            result['error'] = e
        return result

    def _analysis_worker(self, ctx: Dict[str, Any]) -> None:
        """Worker-thread entry point: run the analysis, hand the result to the event loop."""
        result = self._run_analysis(ctx)
        try:
            self._loop.call_soon_threadsafe(self._on_analysis_complete, ctx, result)
        except RuntimeError as e:  # loop closed during shutdown
            self._analysis_inflight = False
            self.log.warning(f"⚠️ Could not deliver analysis result to event loop: {e}")

    def _on_analysis_complete(self, ctx: Dict[str, Any], result: Dict[str, Any]) -> None:
        """Event-loop side of a cycle: log, notify, execute and run maintenance."""
        self._analysis_inflight = False
        price_data = ctx['price_data']
        technical_data = ctx['technical_data']
        current_position = ctx['current_position']

        if result.get('regime') is not None:
            self._regime_cache = {"value": result['regime'], "ts": time.monotonic()}

        if result.get('sentiment'):
            try:
                self.log.info(self.sentiment_fetcher.format_for_display(result['sentiment']))
            except Exception:
                pass

        error = result.get('error')
        if error is not None or result.get('signal') is None:
            self.log.error(f"LLM analysis failed: {error}")
            if self.telegram_bot and self.enable_telegram and self.telegram_notify_errors:
                try:
                    error_msg = self.telegram_bot.format_error_alert({
                        'level': 'ERROR',
                        'message': f"AI Analysis Failed: {str(error)[:100]}",
                        'context': 'on_timer',
                    })
                    self.telegram_bot.send_message_sync(error_msg)
                except Exception:
                    pass
            return

        signal_data = result['signal']
        if signal_data.get('forced'):
            self.log.warning(
                f"🧪 Using FORCED test signal {signal_data['signal']} "
                f"({self._force_signal_remaining} forced cycle(s) left) - LLM bypassed"
            )
        self.log.info(
            f"🤖 Signal: {signal_data['signal']} | "
            f"Confidence: {signal_data['confidence']} | "
            f"API time: {result.get('elapsed', 0.0):.1f}s"
            + (" | FALLBACK" if signal_data.get('is_fallback') else "")
            + f" | Reason: {signal_data['reason']}"
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

        # Store signal
        self.last_signal = signal_data

        # The analysis ran for several seconds; the position may have changed in
        # the meantime (e.g. an exchange-side stop filled). Never act on a stale
        # snapshot: re-read the position and, if it differs from what the LLM
        # was shown, skip execution for this cycle.
        fresh_position = self._get_current_position_data()
        if self._position_snapshot(fresh_position) != self._position_snapshot(current_position):
            self.log.warning(
                f"⚠️ Position changed during analysis "
                f"({self._position_snapshot(current_position)} → {self._position_snapshot(fresh_position)}) "
                f"- skipping execution this cycle"
            )
            self._log_signal_record(signal_data, price_data, technical_data, fresh_position)
        else:
            try:
                self._execute_trade(signal_data, price_data, technical_data, fresh_position)
            except Exception as e:
                self.log.error(f"❌ Trade execution failed: {e}", exc_info=True)

        # Safety maintenance: cancel orphan reduce-only orders left behind when flat.
        if self.enable_oco:
            self._cleanup_oco_orphans()

        # Trailing stop maintenance: check and update trailing stops
        if self.enable_trailing_stop:
            self._update_trailing_stops(price_data['price'])

        # Partial take-profit maintenance: execute R-multiple levels
        if self.enable_partial_tp:
            self._check_partial_take_profits(price_data['price'])

    def _build_forced_signal(self, price_data: Dict[str, Any]) -> Dict[str, Any]:
        """Synthetic HIGH-confidence signal used by FORCE_SIGNAL (paper venues only)."""
        price = float(price_data['price'])
        is_buy = self.force_signal == 'BUY'
        return {
            "signal": self.force_signal,
            "confidence": "HIGH",
            "reason": "FORCED TEST SIGNAL (FORCE_SIGNAL) - not an AI decision; exercising the order path",
            "stop_loss": price * (0.98 if is_buy else 1.02),
            "take_profit": price * (1.02 if is_buy else 0.98),
            "trend_strength": "MODERATE",
            "risk_assessment": "MEDIUM",
            "timestamp": self.clock.utc_now().strftime("%Y-%m-%d %H:%M:%S"),
            "forced": True,
        }

    @staticmethod
    def _position_snapshot(position: Optional[Dict[str, Any]]) -> str:
        """Compact, comparable description of a position dict ('flat' when None)."""
        if not position:
            return "flat"
        return f"{position.get('side', '?')} {float(position.get('quantity', 0.0)):.3f}"

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

    def _get_live_equity(self) -> Optional[float]:
        """Live USDT wallet balance from the portfolio, or None if unavailable."""
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
        return None

    def _get_account_equity(self) -> float:
        """
        Get live USDT wallet balance from the portfolio.

        Falls back to the configured equity if the live balance
        is unavailable (e.g. account not yet loaded). Use only for sizing -
        the daily-loss guard must compare live values against live values
        (see `_check_risk_guards`).
        """
        live = self._get_live_equity()
        return live if live is not None else float(self.equity)

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
        history = getattr(self.llm, 'signal_history', [])
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

    def _state_venue_tag(self) -> str:
        """Identifies the venue a persisted state file belongs to (REST base = live/testnet/demo)."""
        return self.binance_rest_base_url

    def _load_risk_state(self) -> None:
        """
        Load persisted kill-switch state (survives restarts).

        State written on another venue (e.g. a testnet rehearsal before going
        live) is discarded: its equity peak / baselines would be meaningless
        here and could trip the circuit breaker immediately.
        """
        try:
            if os.path.exists(self.risk_state_file):
                with open(self.risk_state_file, 'r') as f:
                    saved = json.load(f)
                if isinstance(saved, dict):
                    saved_venue = saved.get("venue")
                    if saved_venue and saved_venue != self._state_venue_tag():
                        self.log.warning(
                            f"⚠️ Risk state file belongs to another venue ({saved_venue}); "
                            f"starting with fresh kill-switch state for {self._state_venue_tag()}"
                        )
                        self._save_risk_state()
                        return
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
                json.dump({**self.risk_state, "venue": self._state_venue_tag()}, f)
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

    def _trigger_halt(self, reason: str) -> None:
        """
        Circuit breaker: stop opening new positions until an operator resets the
        risk state (delete logs/risk_state.json or start with RESET_RISK_STATE=true).
        Open positions keep their exchange-side exits.
        """
        far_future = self.clock.utc_now().to_pydatetime() + timedelta(days=3650)
        self.risk_state["paused_until"] = far_future.isoformat()
        self.risk_state["halted_reason"] = reason
        self._save_risk_state()
        self.log.error(f"🛑 CIRCUIT BREAKER - TRADING HALTED: {reason} (manual reset required)")
        if self.telegram_bot and self.enable_telegram and self.telegram_notify_errors:
            try:
                alert = self.telegram_bot.format_error_alert({
                    'level': 'HALT',
                    'message': f"Circuit breaker - trading halted: {reason}"[:200],
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

        live_equity = self._get_live_equity()

        # (1) UTC day rollover: reset the daily equity baseline (live values only -
        # never seed the baseline with the static configured equity)
        if self.risk_state.get("day_date") != today:
            self.risk_state["day_date"] = today
            self.risk_state["day_start_equity"] = live_equity
            self._save_risk_state()
        elif self.risk_state.get("day_start_equity") is None and live_equity is not None:
            # Baseline was unavailable earlier today; capture it now
            self.risk_state["day_start_equity"] = live_equity
            self._save_risk_state()

        # (2) Active pause?
        paused_until_str = self.risk_state.get("paused_until")
        if paused_until_str:
            try:
                paused_until = datetime.fromisoformat(paused_until_str)
                if paused_until.tzinfo is None:
                    # Legacy naive timestamps were written as UTC
                    paused_until = paused_until.replace(tzinfo=now.tzinfo)
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
            except (ValueError, TypeError):
                self.risk_state["paused_until"] = None
                self._save_risk_state()

        # (2b) Circuit breaker: total drawdown from the live-equity high-water mark.
        # Unlike the daily/streak pauses this does NOT expire on its own.
        if self.risk_state.get("halted_reason"):
            self.log.warning(f"🛑 Trading halted by circuit breaker: {self.risk_state['halted_reason']}")
            return False
        if live_equity is not None and self.max_total_drawdown_pct > 0:
            peak = self.risk_state.get("equity_peak")
            if not peak or live_equity > peak:
                self.risk_state["equity_peak"] = live_equity
                self._save_risk_state()
                peak = live_equity
            drawdown = (peak - live_equity) / peak if peak else 0.0
            if drawdown >= self.max_total_drawdown_pct:
                self._trigger_halt(
                    f"Equity ${live_equity:,.2f} is {drawdown:.1%} below peak ${peak:,.2f} "
                    f"(limit {self.max_total_drawdown_pct:.0%})"
                )
                return False

        # (3) Daily loss limit: live equity vs live baseline only. Comparing a
        # fallback (configured) equity against a live baseline could trigger a
        # false 24h pause after a transient balance-read failure.
        start_equity = self.risk_state.get("day_start_equity")
        if start_equity and start_equity > 0 and live_equity is not None:
            daily_pnl_pct = (live_equity - start_equity) / start_equity
            if daily_pnl_pct <= -self.daily_loss_limit_pct:
                self._trigger_pause(
                    f"Daily loss limit hit: {daily_pnl_pct:+.2%} "
                    f"(limit -{self.daily_loss_limit_pct:.2%})"
                )
                return False

        # (4) Anti-churn: block after too many consecutive identical actionable
        # signals (HOLD never trades, so a long HOLD run must not block anything)
        history = getattr(self.llm, 'signal_history', [])
        latest_signal = history[-1].get('signal') if history else None
        if latest_signal in ('BUY', 'SELL'):
            run = self._same_signal_run_length()
            if run > self.max_consecutive_same_signal:
                self.log.warning(
                    f"🛡️ Risk guard: {run} consecutive identical {latest_signal} signals "
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
            self._save_position_state()
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
                "forced": bool(signal_data.get('forced', False)),
                "provider": signal_data.get('provider'),
                "model": signal_data.get('model'),
                "reason": str(signal_data.get('reason', ''))[:300],
            }

            directory = os.path.dirname(self.signal_log_file)
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(self.signal_log_file, 'a') as f:
                f.write(json.dumps(record) + "\n")
        except Exception as e:
            self.log.warning(f"⚠️ Failed to write signal record: {e}")

    def _regime_cache_stale(self) -> bool:
        """True when the cached regime is missing or older than regime_cache_ttl_sec."""
        return (
            self._regime_cache["value"] is None
            or time.monotonic() - self._regime_cache["ts"] >= self.regime_cache_ttl_sec
        )

    def _get_regime(self) -> str:
        """
        Cached higher-timeframe regime: 'up', 'down', 'flat' or 'unknown'.

        The cache is normally refreshed by the analysis worker thread; fetching
        here only happens if that refresh did not run (keeps the loop safe).
        """
        if not self._regime_cache_stale():
            return self._regime_cache["value"]
        regime = self._fetch_regime()
        self._regime_cache = {"value": regime, "ts": time.monotonic()}
        return regime

    def _fetch_regime(self) -> str:
        """Classify the higher-timeframe trend from Binance klines (EMA cross)."""
        try:
            import requests
            symbol = str(self.instrument_id).split('-')[0]
            response = requests.get(
                f"{self.binance_rest_base_url}/fapi/v1/klines",
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
        Open a new, protected position.

        native_exits=True (default): MARKET entry; on the fill `on_position_opened`
        arms exchange-side STOP_MARKET (SL) and TAKE_PROFIT_MARKET (TP) reduce-only
        algo orders plus the disaster stop. These live on Binance and survive a
        process crash/restart, and they trigger on the venue - not on this
        process' event loop.

        native_exits=False: legacy emulated bracket (entry + SL + TP managed by
        the NautilusTrader OrderEmulator inside this process).
        """
        order_side = OrderSide.BUY if side == 'long' else OrderSide.SELL

        if not self.native_exits:
            self._submit_bracket_order(side=order_side, quantity=quantity)
            self.log.info(f"🚀 Opening {side} position: {quantity:.3f} BTC (with emulated bracket SL/TP)")
            return

        if not self.latest_signal_data or not self.latest_technical_data:
            self.log.error("❌ No signal/technical data available for SL/TP - skipping entry")
            return

        entry_estimate = float((self.latest_price_data or {}).get('price') or 0.0)
        if entry_estimate <= 0 and self.indicator_manager.recent_bars:
            entry_estimate = float(self.indicator_manager.recent_bars[-1].close)
        if entry_estimate <= 0:
            self.log.error("❌ Unable to determine entry price estimate - skipping entry")
            return

        confidence = self.latest_signal_data.get('confidence', 'MEDIUM')
        sl_estimate = self._calculate_stop_loss_price(side, entry_estimate)
        tp_estimate = self._calculate_take_profit_price(side, entry_estimate, confidence)

        # Context consumed by on_position_opened when the entry fills
        self._pending_entry = {
            'side': 'LONG' if side == 'long' else 'SHORT',
            'quantity': quantity,
            'confidence': confidence,
            'atr': self._get_current_atr(),
            'est_entry_price': entry_estimate,
            'est_sl_price': sl_estimate,
            'est_tp_price': tp_estimate,
            'ts': self.clock.utc_now().isoformat(),
        }

        self.log.info(
            f"🚀 Opening {side} position: {quantity:.3f} BTC (MARKET) - "
            f"exchange-side SL ~${sl_estimate:,.2f} / TP ~${tp_estimate:,.2f} armed on fill"
        )
        self._submit_order(side=order_side, quantity=quantity, reduce_only=False)

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

            # `instrument_key` is needed by BOTH the trailing-stop and partial-TP
            # blocks below (previously only defined inside the trailing block ->
            # NameError when trailing was disabled but partial TP enabled).
            instrument_key = str(self.instrument_id)

            # Save bracket order info for trailing stop
            if self.enable_trailing_stop:
                # Extract SL order from bracket (STOP_MARKET leg)
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
                        "native": False,
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
            self._save_position_state()

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

        if self.native_exits:
            # Arm exchange-side SL/TP from the ACTUAL fill price
            pending = self._pending_entry or {}
            self._pending_entry = None
            side_name = 'LONG' if event.side == PositionSide.LONG else 'SHORT'
            confidence = pending.get('confidence') or (self.latest_signal_data or {}).get('confidence', 'MEDIUM')
            if pending and pending.get('side') != side_name:
                self.log.warning(
                    f"⚠️ Pending entry side {pending.get('side')} != opened {side_name}; "
                    f"arming exits from current indicators"
                )
            try:
                self._arm_native_exits(
                    side=side_name,
                    quantity=float(event.quantity),
                    entry_price=float(event.avg_px_open),
                    confidence=confidence,
                )
            except Exception as e:
                self.log.error(f"❌ Failed to arm exchange-side exits: {e}", exc_info=True)

        # Legacy emulated-bracket bookkeeping: update trailing stop state with the
        # actual entry price (bracket initialised it with the estimate)
        if not self.native_exits and self.enable_trailing_stop:
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
        # regular SL (defense in depth; placed at 2x the SL distance, min 1.5%).
        if self.disaster_stop_enabled:
            side_str = 'long' if event.side == PositionSide.LONG else 'short'
            self._submit_disaster_stop(
                side=side_str,
                quantity=float(event.quantity),
                entry_price=float(event.avg_px_open),
            )

        self._save_position_state()

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
        # PositionClosed.side is FLAT - report the direction that was closed
        entry_side = getattr(event, 'entry', None)
        direction = (
            'LONG' if entry_side == OrderSide.BUY
            else 'SHORT' if entry_side == OrderSide.SELL
            else event.side.name
        )
        self.log.info(
            f"🔴 Position closed: {direction} "
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

        # Cancel remaining exchange-side exit orders (Binance also auto-cancels
        # reduce-only orders when flat; this is belt-and-braces and immediate)
        self._cancel_native_exit_orders()
        self._cancel_disaster_stop()
        self._pending_entry = None

        # Clear trailing stop state
        instrument_key = str(self.instrument_id)
        if instrument_key in self.trailing_stop_state:
            del self.trailing_stop_state[instrument_key]
            self.log.debug(f"🗑️ Cleared trailing stop state for {instrument_key}")

        # Clear partial take-profit state
        if instrument_key in self.partial_tp_state:
            del self.partial_tp_state[instrument_key]
            self.log.debug(f"🗑️ Cleared partial TP state for {instrument_key}")

        self._clear_position_state()
        
        # Send Telegram position closed notification
        if self.telegram_bot and self.enable_telegram and self.telegram_notify_positions:
            try:
                # P&L percentage relative to the notional that was closed
                pnl = float(event.realized_pnl)
                entry_px = float(getattr(event, 'avg_px_open', 0.0) or 0.0)
                closed_qty = float(getattr(event, 'peak_qty', 0.0) or getattr(event, 'quantity', 0.0) or 0.0)
                notional = entry_px * closed_qty
                pnl_pct = (pnl / notional) * 100 if notional > 0 else 0.0

                # PositionClosed.side is FLAT; derive the direction from the entry order side
                entry_side = getattr(event, 'entry', None)
                closed_side = (
                    'LONG' if entry_side == OrderSide.BUY
                    else 'SHORT' if entry_side == OrderSide.SELL
                    else event.side.name
                )

                position_msg = self.telegram_bot.format_position_update({
                    'action': 'CLOSED',
                    'side': closed_side,
                    'quantity': closed_qty,
                    'entry_price': entry_px,
                    'current_price': float(getattr(event, 'avg_px_close', 0.0) or 0.0),
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
                    # (ATR-based minimum step when trailing by ATR; the percentage
                    # threshold is far too coarse relative to an ATR distance)
                    if current_sl_price is None:
                        should_update = True
                    elif use_atr:
                        should_update = (new_sl_price - current_sl_price) >= self.trailing_update_threshold_atr * atr
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
                    elif use_atr:
                        should_update = (current_sl_price - new_sl_price) >= self.trailing_update_threshold_atr * atr
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
            
            # Preferred path: MODIFY the existing stop-loss trigger in place.
            #
            # The bracket's SL and TP legs are linked with ContingencyType.OUO.
            # Cancelling the SL (the previous implementation) makes Nautilus'
            # OrderManager cancel the linked TP as well - the position was left
            # with no take-profit after the first trailing update. Modifying
            # the trigger price keeps the bracket (and the TP) intact.
            old_order = None
            if old_sl_order_id:
                try:
                    old_order = self.cache.order(ClientOrderId(old_sl_order_id))
                except Exception as e:
                    self.log.warning(f"⚠️ Could not look up SL order {old_sl_order_id[:8]}...: {e}")

            if state.get("native"):
                # Exchange-side STOP_MARKET orders cannot be modified on Binance:
                # submit the replacement FIRST (no unprotected window), then cancel
                # the old stop. The TP is an independent native order - untouched.
                exit_side = OrderSide.SELL if side == "LONG" else OrderSide.BUY
                new_sl_order = self.order_factory.stop_market(
                    instrument_id=self.instrument_id,
                    order_side=exit_side,
                    quantity=self.instrument.make_qty(quantity),
                    trigger_price=self.instrument.make_price(new_sl_price),
                    trigger_type=TriggerType.LAST_PRICE,
                    time_in_force=TimeInForce.GTC,
                    reduce_only=True,
                )
                self.submit_order(new_sl_order)
                if old_order is not None and old_order.is_open:
                    self.cancel_order(old_order)
                state["current_sl_price"] = new_sl_price
                state["sl_order_id"] = str(new_sl_order.client_order_id)
                self._save_position_state()
                self.log.info(
                    f"✅ Trailing SL replaced on exchange @ ${new_sl_price:,.2f} "
                    f"(new {state['sl_order_id'][:8]}..., TP untouched)"
                )
                return

            if old_order is not None and old_order.is_open:
                self.modify_order(
                    old_order,
                    trigger_price=self.instrument.make_price(new_sl_price),
                )
                state["current_sl_price"] = new_sl_price
                self._save_position_state()
                self.log.info(
                    f"✅ Trailing SL trigger modified in place @ ${new_sl_price:,.2f} "
                    f"(order {old_sl_order_id[:8]}..., TP leg preserved)"
                )
                return

            # Fallback (no open SL order known, e.g. after a restart): submit a
            # fresh native reduce-only STOP_MARKET so the position is protected.
            exit_side = OrderSide.SELL if side == "LONG" else OrderSide.BUY

            new_sl_order = self.order_factory.stop_market(
                instrument_id=self.instrument_id,
                order_side=exit_side,
                quantity=self.instrument.make_qty(quantity),
                trigger_price=self.instrument.make_price(new_sl_price),
                trigger_type=TriggerType.LAST_PRICE,
                # Native Binance STOP_MARKET (no emulation) so the stop lives on
                # the exchange and survives process restarts
                reduce_only=True,
            )
            self.submit_order(new_sl_order)

            # Update state
            state["current_sl_price"] = new_sl_price
            state["sl_order_id"] = str(new_sl_order.client_order_id)
            state["native"] = True
            self._save_position_state()

            self.log.info(f"✅ New trailing SL order submitted @ ${new_sl_price:,.2f}")

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
                    remaining = max(0.0, math.floor(remaining * 1000) / 1000)
                    self.trailing_stop_state[instrument_key]["quantity"] = remaining
                    # Exchange-side exits are sized for the original quantity: resize them
                    if self.trailing_stop_state[instrument_key].get("native") and remaining > 0:
                        self._replace_native_exits(remaining)
                self._save_position_state()

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

    # ===== Exchange-side exits, persistence & restart re-adoption =====

    def _order_is_open(self, order_id: Optional[str]) -> bool:
        """True if the order with this client order id is known to the cache and open."""
        if not order_id:
            return False
        try:
            order = self.cache.order(ClientOrderId(order_id))
            return order is not None and order.is_open
        except Exception:
            return False

    def _arm_native_exits(
        self,
        side: str,
        quantity: float,
        entry_price: float,
        confidence: str,
        sl_price: Optional[float] = None,
        tp_price: Optional[float] = None,
    ) -> None:
        """
        Place exchange-side reduce-only exits for an open position:
        STOP_MARKET (stop loss) + TAKE_PROFIT_MARKET (take profit).

        Both are Binance conditional (algo) orders: they trigger on the venue,
        survive restarts, and Binance auto-cancels the survivor when the
        position is flat (reduce-only). Also initialises trailing / partial-TP
        bookkeeping (keyed by instrument) and persists it.
        """
        side = side.upper()
        side_lc = 'long' if side == 'LONG' else 'short'
        if sl_price is None:
            sl_price = self._calculate_stop_loss_price(side_lc, entry_price)
        if tp_price is None:
            tp_price = self._calculate_take_profit_price(side_lc, entry_price, confidence)

        # Sanity: a stop on the wrong side of the entry would trigger instantly
        # (Binance -2021). Fall back to a plain 2% / 4% structure.
        if side == 'LONG' and not (sl_price < entry_price < tp_price):
            self.log.warning(f"⚠️ Inconsistent LONG exits SL {sl_price:.2f} / entry {entry_price:.2f} / TP {tp_price:.2f} - using 2%/4%")
            sl_price, tp_price = entry_price * 0.98, entry_price * 1.04
        if side == 'SHORT' and not (tp_price < entry_price < sl_price):
            self.log.warning(f"⚠️ Inconsistent SHORT exits TP {tp_price:.2f} / entry {entry_price:.2f} / SL {sl_price:.2f} - using 2%/4%")
            sl_price, tp_price = entry_price * 1.02, entry_price * 0.96

        exit_side = OrderSide.SELL if side == 'LONG' else OrderSide.BUY
        qty = self.instrument.make_qty(quantity)

        sl_order = self.order_factory.stop_market(
            instrument_id=self.instrument_id,
            order_side=exit_side,
            quantity=qty,
            trigger_price=self.instrument.make_price(sl_price),
            trigger_type=TriggerType.LAST_PRICE,
            time_in_force=TimeInForce.GTC,
            reduce_only=True,
        )
        tp_order = self.order_factory.market_if_touched(
            instrument_id=self.instrument_id,
            order_side=exit_side,
            quantity=qty,
            trigger_price=self.instrument.make_price(tp_price),
            trigger_type=TriggerType.LAST_PRICE,
            time_in_force=TimeInForce.GTC,
            reduce_only=True,
        )
        self.submit_order(sl_order)
        self.submit_order(tp_order)

        key = str(self.instrument_id)
        previous = self.trailing_stop_state.get(key) or {}
        self.trailing_stop_state[key] = {
            "entry_price": entry_price,
            "highest_price": previous.get("highest_price") if side == 'LONG' else None,
            "lowest_price": previous.get("lowest_price") if side == 'SHORT' else None,
            "current_sl_price": sl_price,
            "sl_order_id": str(sl_order.client_order_id),
            "tp_price": tp_price,
            "tp_order_id": str(tp_order.client_order_id),
            "activated": bool(previous.get("activated", False)),
            "side": side,
            "quantity": quantity,
            "atr": previous.get("atr") or self._get_current_atr(),
            "native": True,
        }
        if self.trailing_stop_state[key]["highest_price"] is None and side == 'LONG':
            self.trailing_stop_state[key]["highest_price"] = entry_price
        if self.trailing_stop_state[key]["lowest_price"] is None and side == 'SHORT':
            self.trailing_stop_state[key]["lowest_price"] = entry_price

        if self.enable_partial_tp and self.partial_tp_levels and key not in self.partial_tp_state:
            self.partial_tp_state[key] = {
                "entry_price": entry_price,
                "sl_distance": abs(entry_price - sl_price),
                "side": side,
                "original_quantity": quantity,
                "levels_done": [],
            }

        self._save_position_state()
        self.log.info(
            f"🛡️ Exchange-side exits armed for {side} {quantity:.3f} BTC @ ${entry_price:,.2f}: "
            f"SL ${sl_price:,.2f} ({(sl_price / entry_price - 1) * 100:+.2f}%) | "
            f"TP ${tp_price:,.2f} ({(tp_price / entry_price - 1) * 100:+.2f}%)"
        )

    def _replace_native_exits(self, new_quantity: float) -> None:
        """Re-issue the exchange-side SL/TP for a smaller quantity (after a partial close)."""
        key = str(self.instrument_id)
        state = self.trailing_stop_state.get(key)
        if not state or not state.get("native"):
            return
        if new_quantity < self.position_config['min_trade_amount']:
            return
        old_sl, old_tp = state.get("sl_order_id"), state.get("tp_order_id")
        side = state["side"]
        exit_side = OrderSide.SELL if side == 'LONG' else OrderSide.BUY
        qty = self.instrument.make_qty(new_quantity)

        sl_order = self.order_factory.stop_market(
            instrument_id=self.instrument_id, order_side=exit_side, quantity=qty,
            trigger_price=self.instrument.make_price(state["current_sl_price"]),
            trigger_type=TriggerType.LAST_PRICE, time_in_force=TimeInForce.GTC, reduce_only=True,
        )
        tp_order = self.order_factory.market_if_touched(
            instrument_id=self.instrument_id, order_side=exit_side, quantity=qty,
            trigger_price=self.instrument.make_price(state["tp_price"]),
            trigger_type=TriggerType.LAST_PRICE, time_in_force=TimeInForce.GTC, reduce_only=True,
        )
        self.submit_order(sl_order)
        self.submit_order(tp_order)
        for old_id in (old_sl, old_tp):
            if self._order_is_open(old_id):
                self.cancel_order(self.cache.order(ClientOrderId(old_id)))
        state["sl_order_id"] = str(sl_order.client_order_id)
        state["tp_order_id"] = str(tp_order.client_order_id)
        state["quantity"] = new_quantity
        self._save_position_state()
        self.log.info(f"🔁 Exchange-side exits resized to {new_quantity:.3f} BTC")

    def _cancel_native_exit_orders(self) -> None:
        """Cancel the tracked exchange-side SL/TP orders if they are still open."""
        state = self.trailing_stop_state.get(str(self.instrument_id)) or {}
        for label in ("sl_order_id", "tp_order_id"):
            order_id = state.get(label)
            if self._order_is_open(order_id):
                try:
                    self.cancel_order(self.cache.order(ClientOrderId(order_id)))
                    self.log.info(f"🗑️ Cancelled {label.split('_')[0].upper()} exit order {order_id[:8]}...")
                except Exception as e:
                    self.log.warning(f"⚠️ Failed to cancel {label}: {e}")

    def _touch_heartbeat(self, source: str) -> None:
        """Write a liveness marker (ISO time + source). Read by tools/healthcheck.py."""
        if not self.heartbeat_file:
            return
        try:
            directory = os.path.dirname(self.heartbeat_file)
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(self.heartbeat_file, 'w') as f:
                f.write(f"{self.clock.utc_now().isoformat()} {source}\n")
        except Exception:
            pass

    def _save_position_state(self) -> None:
        """Persist exit/trailing/partial-TP bookkeeping so a restart can re-adopt the position."""
        if not self.position_state_file:
            return
        try:
            directory = os.path.dirname(self.position_state_file)
            if directory:
                os.makedirs(directory, exist_ok=True)
            payload = {
                "instrument_id": str(self.instrument_id),
                "venue": self._state_venue_tag(),
                "saved_at": self.clock.utc_now().isoformat(),
                "trailing_stop_state": self.trailing_stop_state,
                "partial_tp_state": self.partial_tp_state,
                "disaster_stop_state": self.disaster_stop_state,
            }
            tmp = f"{self.position_state_file}.tmp"
            with open(tmp, 'w') as f:
                json.dump(payload, f, indent=1, default=str)
            os.replace(tmp, self.position_state_file)
        except Exception as e:
            self.log.warning(f"⚠️ Could not save position state: {e}")

    def _load_position_state(self) -> Optional[Dict[str, Any]]:
        if not self.position_state_file or not os.path.exists(self.position_state_file):
            return None
        try:
            with open(self.position_state_file, 'r') as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return None
            if data.get("venue") and data["venue"] != self._state_venue_tag():
                self.log.warning(
                    f"⚠️ Position state file belongs to another venue ({data['venue']}) - ignoring it"
                )
                return None
            return data
        except Exception as e:
            self.log.warning(f"⚠️ Could not load position state: {e}")
            return None

    def _clear_position_state(self) -> None:
        if not self.position_state_file:
            return
        try:
            if os.path.exists(self.position_state_file):
                os.remove(self.position_state_file)
        except Exception as e:
            self.log.warning(f"⚠️ Could not clear position state file: {e}")

    def _readopt_open_position(self) -> None:
        """
        On start: take ownership of a position left open by a previous process.

        * No open position -> drop stale persisted state, cancel orphan
          reduce-only orders.
        * Open position -> restore trailing / partial-TP / disaster bookkeeping
          from disk when it matches, verify each protective order still exists
          on the venue (by id, else by scanning open reduce-only orders) and
          re-arm whatever is missing. If the stop or target was breached while
          offline, close at market immediately.
        """
        key = str(self.instrument_id)
        saved = self._load_position_state()
        positions = self.cache.positions_open(instrument_id=self.instrument_id)

        if not positions:
            if saved:
                self.log.info("ℹ️ Persisted position state found but no open position (closed while offline) - clearing")
                self._clear_position_state()
            self._cleanup_oco_orphans()
            return

        position = positions[0]
        side = 'LONG' if position.side == PositionSide.LONG else 'SHORT'
        qty = float(position.quantity)
        entry = float(position.avg_px_open)
        bars = self.indicator_manager.recent_bars
        price = float(bars[-1].close) if bars else entry

        # ATR-based exit maths needs technical data (none yet right after start)
        try:
            self.latest_technical_data = self.indicator_manager.get_technical_data(price)
        except Exception as e:
            self.log.warning(f"⚠️ Technical data unavailable during re-adoption: {e}")

        restored = False
        if saved and (saved.get("trailing_stop_state") or {}).get(key, {}).get("side") == side:
            self.trailing_stop_state = saved.get("trailing_stop_state") or {}
            self.partial_tp_state = saved.get("partial_tp_state") or {}
            self.disaster_stop_state = saved.get("disaster_stop_state") or {}
            self.trailing_stop_state[key]["quantity"] = qty  # the venue is the truth
            restored = True

        self.log.warning(
            f"♻️ Re-adopting open {side} position {qty:.3f} BTC @ ${entry:,.2f} "
            f"(mark ${price:,.2f}, persisted state {'restored' if restored else 'not available'})"
        )

        state = self.trailing_stop_state.get(key) or {}
        confidence = (self.latest_signal_data or {}).get('confidence', 'MEDIUM')
        side_lc = side.lower()
        sl_price = state.get("current_sl_price") or self._calculate_stop_loss_price(side_lc, entry)
        tp_price = state.get("tp_price") or self._calculate_take_profit_price(side_lc, entry, confidence)

        # Breached while offline? Then the position should already be closed - do it now.
        exit_side = OrderSide.SELL if side == 'LONG' else OrderSide.BUY
        if (side == 'LONG' and price <= sl_price) or (side == 'SHORT' and price >= sl_price):
            self.log.error(f"🛑 Stop ${sl_price:,.2f} breached while offline (mark ${price:,.2f}) - closing at market")
            self._submit_order(side=exit_side, quantity=qty, reduce_only=True)
            return
        if (side == 'LONG' and price >= tp_price) or (side == 'SHORT' and price <= tp_price):
            self.log.info(f"🎯 Target ${tp_price:,.2f} reached while offline (mark ${price:,.2f}) - closing at market")
            self._submit_order(side=exit_side, quantity=qty, reduce_only=True)
            return

        # Which protective orders are still live on the venue?
        open_ro = [o for o in self.cache.orders_open(instrument_id=self.instrument_id) if o.is_reduce_only]
        sl_ok = self._order_is_open(state.get("sl_order_id"))
        tp_ok = self._order_is_open(state.get("tp_order_id"))
        disaster = self.disaster_stop_state.get(key) or {}
        disaster_ok = self._order_is_open(disaster.get("order_id"))

        if not (sl_ok and tp_ok and disaster_ok):
            # Adopt by scanning (ids may differ after reconciliation)
            known = {state.get("sl_order_id"), state.get("tp_order_id"), disaster.get("order_id")}
            stops = sorted(
                [o for o in open_ro if o.order_type == OrderType.STOP_MARKET and str(o.client_order_id) not in known],
                key=lambda o: abs(float(o.trigger_price) - entry),
            )
            mits = [o for o in open_ro if o.order_type == OrderType.MARKET_IF_TOUCHED and str(o.client_order_id) not in known]
            if not sl_ok and stops:
                o = stops.pop(0)
                state["sl_order_id"], state["current_sl_price"], sl_ok = str(o.client_order_id), float(o.trigger_price), True
                sl_price = state["current_sl_price"]
            if not disaster_ok and stops:
                o = stops.pop(-1)
                self.disaster_stop_state[key] = {"order_id": str(o.client_order_id), "price": float(o.trigger_price)}
                disaster_ok = True
            if not tp_ok and mits:
                o = mits.pop(0)
                state["tp_order_id"], state["tp_price"], tp_ok = str(o.client_order_id), float(o.trigger_price), True
                tp_price = state["tp_price"]

        if sl_ok and tp_ok:
            if key not in self.trailing_stop_state:
                self.trailing_stop_state[key] = state
            state.update({"side": side, "quantity": qty, "entry_price": state.get("entry_price", entry), "native": True})
            state.setdefault("activated", False)
            state.setdefault("atr", self._get_current_atr())
            state.setdefault("highest_price", entry if side == 'LONG' else None)
            state.setdefault("lowest_price", entry if side == 'SHORT' else None)
            self.log.info(f"✅ Exchange-side exits already live: SL ${sl_price:,.2f} | TP ${tp_price:,.2f}")
        else:
            # Re-arm both at the saved prices; cancel any lone survivor first to avoid duplicates
            for order_id in (state.get("sl_order_id") if sl_ok else None, state.get("tp_order_id") if tp_ok else None):
                if order_id and self._order_is_open(order_id):
                    self.cancel_order(self.cache.order(ClientOrderId(order_id)))
            self.log.warning("🛡️ Protective exits missing after restart - re-arming on the exchange")
            self._arm_native_exits(side, qty, entry, confidence, sl_price=sl_price, tp_price=tp_price)

        if key not in self.partial_tp_state and self.enable_partial_tp and self.partial_tp_levels:
            self.partial_tp_state[key] = {
                "entry_price": entry, "sl_distance": abs(entry - sl_price), "side": side,
                "original_quantity": qty, "levels_done": [],
            }

        if not disaster_ok:
            self.disaster_stop_state.pop(key, None)
            if self.disaster_stop_enabled:
                self._submit_disaster_stop(side_lc, qty, entry)

        self._save_position_state()

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
                'equity': self._get_account_equity(),  # live balance when available
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
