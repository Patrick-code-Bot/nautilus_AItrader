"""
Live Trading Entrypoint for DeepSeek AI Strategy

Runs the DeepSeek AI strategy on Binance Futures (BTCUSDT-PERP) with live market data.
"""

import os
import asyncio
import yaml
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv

from nautilus_trader.adapters.binance.common.enums import BinanceAccountType
from nautilus_trader.adapters.binance.config import BinanceDataClientConfig, BinanceExecClientConfig
from nautilus_trader.adapters.binance.factories import BinanceLiveDataClientFactory, BinanceLiveExecClientFactory
from nautilus_trader.config import InstrumentProviderConfig, LiveExecEngineConfig, LoggingConfig, TradingNodeConfig
from nautilus_trader.live.node import TradingNode
from nautilus_trader.model.identifiers import TraderId, InstrumentId
from nautilus_trader.trading.config import ImportableStrategyConfig

from strategy.deepseek_strategy import DeepSeekAIStrategy, DeepSeekAIStrategyConfig


# Load environment variables
load_dotenv()


def load_yaml_config() -> dict:
    """
    Load strategy configuration from YAML file.
    
    Returns
    -------
    dict
        Configuration dictionary from YAML
    """
    config_path = Path(__file__).parent / "configs" / "strategy_config.yaml"
    if config_path.exists():
        with open(config_path, 'r') as f:
            return yaml.safe_load(f)
    return {}


def get_env_float(key: str, default: str) -> float:
    """
    Safely get float environment variable, removing any inline comments.
    """
    value = os.getenv(key, default)
    # Remove inline comments (anything after #)
    if '#' in value:
        value = value.split('#')[0]
    # Strip whitespace
    value = value.strip()
    return float(value)


def get_env_str(key: str, default: str) -> str:
    """
    Safely get string environment variable, removing any inline comments.
    """
    value = os.getenv(key, default)
    # Remove inline comments (anything after #)
    if '#' in value:
        value = value.split('#')[0]
    # Strip whitespace
    return value.strip()


def get_env_int(key: str, default: str) -> int:
    """
    Safely get integer environment variable, removing any inline comments.
    """
    value = os.getenv(key, default)
    # Remove inline comments (anything after #)
    if '#' in value:
        value = value.split('#')[0]
    # Strip whitespace
    value = value.strip()
    return int(value)


def get_strategy_config() -> DeepSeekAIStrategyConfig:
    """
    Build strategy configuration from environment variables.

    Returns
    -------
    DeepSeekAIStrategyConfig
        Strategy configuration
    """
    # Get API keys
    deepseek_api_key = get_env_str('DEEPSEEK_API_KEY', '')
    if not deepseek_api_key:
        raise ValueError("DEEPSEEK_API_KEY not found in environment variables")

    # Load YAML config
    yaml_config = load_yaml_config()
    strategy_yaml = yaml_config.get('strategy', {})
    
    # Get strategy parameters from env or use defaults
    equity = get_env_float('EQUITY', str(strategy_yaml.get('equity', '400')))
    leverage = get_env_float('LEVERAGE', str(strategy_yaml.get('leverage', '10')))
    base_position = get_env_float('BASE_POSITION_USDT', str(strategy_yaml.get('position_management', {}).get('base_usdt_amount', '30')))
    timeframe = get_env_str('TIMEFRAME', '15m')  # Production: 15-minute timeframe
    
    # Debug output
    print(f"[CONFIG] Equity: {equity}")
    print(f"[CONFIG] Base Position: {base_position}")
    print(f"[CONFIG] Timeframe: {timeframe}")

    # Map timeframe to bar aggregation
    timeframe_map = {
        '1m': 'MINUTE',
        '5m': 'MINUTE',
        '15m': 'MINUTE',
        '1h': 'HOUR',
        '4h': 'HOUR',
        '1d': 'DAY',
    }

    # Parse timeframe
    print(f"DEBUG: timeframe = '{timeframe}'")  # Debug
    if timeframe == '1m':
        bar_spec = '1-MINUTE-LAST'
    elif timeframe == '5m':
        bar_spec = '5-MINUTE-LAST'
    elif timeframe == '15m':
        bar_spec = '15-MINUTE-LAST'
    elif timeframe == '1h':
        bar_spec = '1-HOUR-LAST'
    else:
        bar_spec = '15-MINUTE-LAST'  # Default
    
    print(f"DEBUG: bar_spec = '{bar_spec}'")  # Debug
    final_bar_type = f"BTCUSDT-PERP.BINANCE-{bar_spec}-EXTERNAL"
    print(f"DEBUG: final_bar_type = '{final_bar_type}'")  # Debug

    return DeepSeekAIStrategyConfig(
        instrument_id="BTCUSDT-PERP.BINANCE",
        bar_type=final_bar_type,

        # Capital
        equity=equity,
        leverage=leverage,

        # Position sizing
        base_usdt_amount=base_position,
        high_confidence_multiplier=get_env_float('HIGH_CONFIDENCE_MULTIPLIER', '1.5'),
        medium_confidence_multiplier=get_env_float('MEDIUM_CONFIDENCE_MULTIPLIER', '1.0'),
        low_confidence_multiplier=get_env_float('LOW_CONFIDENCE_MULTIPLIER', '0.5'),
        max_position_ratio=get_env_float('MAX_POSITION_RATIO', '0.10'),
        trend_strength_multiplier=get_env_float('TREND_STRENGTH_MULTIPLIER', '1.2'),
        min_trade_amount=0.001,  # Binance minimum

        # Technical indicators - Production mode (standard periods)
        # Use reduced periods only for 1m bars (for testing)
        sma_periods=[3, 7, 15] if timeframe == '1m' else [5, 20, 50],
        rsi_period=7 if timeframe == '1m' else 14,
        macd_fast=5 if timeframe == '1m' else 12,
        macd_slow=10 if timeframe == '1m' else 26,
        bb_period=10 if timeframe == '1m' else 20,
        bb_std=2.0,

        # AI
        deepseek_api_key=deepseek_api_key,
        deepseek_model="deepseek-chat",
        deepseek_temperature=0.1,
        deepseek_max_retries=2,

        # Sentiment
        sentiment_enabled=True,
        sentiment_lookback_hours=4,
        # Set sentiment timeframe based on bar timeframe (default to 15m)
        sentiment_timeframe="1m" if timeframe == "1m" else ("5m" if timeframe == "5m" else "15m"),

        # Risk
        min_confidence_to_trade=get_env_str('MIN_CONFIDENCE_TO_TRADE', 'MEDIUM'),
        allow_reversals=True,
        require_high_confidence_for_reversal=False,
        rsi_extreme_threshold_upper=75.0,
        rsi_extreme_threshold_lower=25.0,
        rsi_extreme_multiplier=0.7,

        # Execution
        position_adjustment_threshold=0.001,

        # Timing - Load from YAML config (default: 900 seconds = 15 minutes)
        timer_interval_sec=get_env_int('TIMER_INTERVAL_SEC', str(strategy_yaml.get('timer_interval_sec', 900))),
        
        # Telegram Notifications
        enable_telegram=strategy_yaml.get('telegram', {}).get('enabled', False),
        telegram_bot_token=get_env_str('TELEGRAM_BOT_TOKEN', ''),
        telegram_chat_id=get_env_str('TELEGRAM_CHAT_ID', ''),
        telegram_notify_signals=strategy_yaml.get('telegram', {}).get('notify_signals', True),
        telegram_notify_fills=strategy_yaml.get('telegram', {}).get('notify_fills', True),
        telegram_notify_positions=strategy_yaml.get('telegram', {}).get('notify_positions', True),
        telegram_notify_errors=strategy_yaml.get('telegram', {}).get('notify_errors', True),
    )


def get_binance_config() -> tuple:
    """
    Build Binance data and execution client configs.

    Returns
    -------
    tuple
        (data_config, exec_config)
    """
    # Get API credentials
    api_key = os.getenv('BINANCE_API_KEY')
    api_secret = os.getenv('BINANCE_API_SECRET')

    if not api_key or not api_secret:
        raise ValueError("BINANCE_API_KEY and BINANCE_API_SECRET required in .env")

    # Data client config
    data_config = BinanceDataClientConfig(
        api_key=api_key,
        api_secret=api_secret,
        account_type=BinanceAccountType.USDT_FUTURES,  # Binance Futures
        testnet=False,  # Set to True for testnet
        instrument_provider=InstrumentProviderConfig(load_all=True),
    )

    # Execution client config
    exec_config = BinanceExecClientConfig(
        api_key=api_key,
        api_secret=api_secret,
        account_type=BinanceAccountType.USDT_FUTURES,
        testnet=False,
        instrument_provider=InstrumentProviderConfig(load_all=True),
    )

    return data_config, exec_config


def setup_trading_node() -> TradingNodeConfig:
    """
    Configure the NautilusTrader trading node.

    Returns
    -------
    TradingNodeConfig
        Trading node configuration
    """
    # Get configurations
    strategy_config = get_strategy_config()
    data_config, exec_config = get_binance_config()

    # Wrap strategy config in ImportableStrategyConfig
    importable_config = ImportableStrategyConfig(
        strategy_path="strategy.deepseek_strategy:DeepSeekAIStrategy",
        config_path="strategy.deepseek_strategy:DeepSeekAIStrategyConfig",
        config=strategy_config.dict(),
    )

    # Logging configuration
    log_level = get_env_str('LOG_LEVEL', 'INFO')

    logging_config = LoggingConfig(
        log_level=log_level,
        log_level_file=log_level,
        log_file_format="json",
    )

    # Trading node config
    config = TradingNodeConfig(
        trader_id=TraderId("DeepSeekTrader-001"),
        logging=logging_config,
        exec_engine=LiveExecEngineConfig(
            reconciliation=True,  # Enable position reconciliation
            inflight_check_interval_ms=5000,  # Check in-flight orders every 5s
        ),
        # Data clients
        data_clients={
            "BINANCE": data_config,
        },
        # Execution clients
        exec_clients={
            "BINANCE": exec_config,
        },
        # Strategy configs
        strategies=[importable_config],
    )

    return config


def main():
    """
    Main entry point for live trading.
    """
    print("=" * 70)
    print("DeepSeek AI Trading Strategy - Live Trading Mode")
    print("=" * 70)
    print(f"Exchange: Binance Futures (USDT-M)")
    print(f"Instrument: BTCUSDT-PERP")
    print(f"Strategy: AI-powered with DeepSeek")
    print("=" * 70)

    # Safety check
    test_mode = os.getenv('TEST_MODE', 'false').strip().lower() == 'true'
    auto_confirm = os.getenv('AUTO_CONFIRM', 'false').strip().lower() == 'true'
    
    if test_mode:
        print("⚠️  TEST_MODE=true - This is a simulation, no real orders will be placed")
    else:
        print("🚨 LIVE TRADING MODE - Real orders will be placed!")
        if auto_confirm:
            print("⚠️  AUTO_CONFIRM=true - Skipping user confirmation")
        else:
            response = input("Are you sure you want to continue? (yes/no): ")
            if response.lower() != 'yes':
                print("Exiting...")
                return

    # Build configuration
    print("\n📋 Building configuration...")
    config = setup_trading_node()

    print(f"✅ Trader ID: {config.trader_id}")
    print(f"✅ Strategy configured with DeepSeek AI")
    print(f"✅ Binance Futures adapter configured")

    # Create and start trading node
    print("\n🚀 Starting trading node...")
    node = TradingNode(config=config)
    
    # Register Binance factories
    node.add_data_client_factory("BINANCE", BinanceLiveDataClientFactory)
    node.add_exec_client_factory("BINANCE", BinanceLiveExecClientFactory)
    print("✅ Binance factories registered")

    try:
        # Build the node (connects to exchange, loads instruments)
        node.build()
        print("✅ Trading node built successfully")

        # Run the node (this starts strategies and begins event processing)
        print("✅ Starting trading node...")
        print("\n🟢 Strategy is now running. Press Ctrl+C to stop.\n")
        
        # Run the node - this is a blocking call that processes all events
        node.run()

    except KeyboardInterrupt:
        print("\n\n⚠️  Keyboard interrupt received...")

    except Exception as e:
        print(f"\n❌ Error occurred: {e}")
        import traceback
        traceback.print_exc()

    finally:
        # Dispose the node to clean up resources
        print("\n🛑 Cleaning up resources...")
        node.dispose()
        print("✅ Resources cleaned up")

        print("\n" + "=" * 70)
        print("Trading session ended")
        print("=" * 70)


if __name__ == "__main__":
    # Check Python path
    import sys
    project_root = Path(__file__).parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    # Run the trading bot
    try:
        main()
    except KeyboardInterrupt:
        print("\n✅ Program terminated by user")
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
