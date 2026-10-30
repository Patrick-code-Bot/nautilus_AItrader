"""
Live Trading Entrypoint for the AI Strategy

Runs the LLM-powered strategy (Anthropic Claude by default) on Binance Futures
(BTCUSDT-PERP) with live market data.
"""

import os
import asyncio
import yaml
from decimal import Decimal
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from nautilus_trader.adapters.binance.common.enums import BinanceAccountType, BinanceEnvironment
from nautilus_trader.adapters.binance.common.symbol import BinanceSymbol
from nautilus_trader.adapters.binance.futures.enums import BinanceFuturesMarginType
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


def get_env_bool(key: str, default: bool = False) -> bool:
    """Parse a boolean environment variable (true/1/yes/on), ignoring inline comments."""
    raw = os.getenv(key)
    if raw is None:
        return default
    value = get_env_str(key, 'true' if default else 'false').lower()
    return value in ('1', 'true', 'yes', 'on')


def resolve_llm_settings(strategy_yaml: dict) -> dict:
    """
    Resolve the LLM decision-layer settings from environment / YAML.

    Precedence (highest first): LLM_* env vars, ANTHROPIC_API_KEY / legacy
    DEEPSEEK_* env vars, then `strategy.llm` in configs/strategy_config.yaml.

    Provider selection:
      * LLM_PROVIDER=anthropic|openai      explicit
      * LLM_PROVIDER=auto (default)        anthropic if ANTHROPIC_API_KEY is set
                                           (or the key looks like an Anthropic key /
                                           the model looks like a Claude model),
                                           otherwise OpenAI-compatible (DeepSeek/Kimi)
    """
    llm_yaml = strategy_yaml.get('llm', {}) or {}
    # Legacy YAML section name
    if not llm_yaml and strategy_yaml.get('deepseek'):
        llm_yaml = strategy_yaml.get('deepseek', {}) or {}

    provider = get_env_str('LLM_PROVIDER', str(llm_yaml.get('provider', 'auto'))).lower()

    anthropic_key = get_env_str('ANTHROPIC_API_KEY', '')
    generic_key = get_env_str('LLM_API_KEY', '')
    deepseek_key = get_env_str('DEEPSEEK_API_KEY', '')

    if provider in ('anthropic', 'claude'):
        provider = 'anthropic'
        api_key = anthropic_key or generic_key
    elif provider in ('openai', 'deepseek', 'kimi', 'moonshot', 'openai-compatible'):
        provider = 'openai'
        api_key = generic_key or deepseek_key
    else:
        # auto
        if anthropic_key:
            provider, api_key = 'anthropic', anthropic_key
        elif generic_key:
            api_key = generic_key
            provider = 'anthropic' if generic_key.startswith('sk-ant-') else 'openai'
        else:
            provider, api_key = 'openai', deepseek_key

    if not api_key:
        raise ValueError(
            "No LLM API key found. Set ANTHROPIC_API_KEY (Claude), or LLM_API_KEY / "
            "DEEPSEEK_API_KEY for an OpenAI-compatible provider."
        )

    model = get_env_str('LLM_MODEL', '') or get_env_str('DEEPSEEK_MODEL', '') or str(llm_yaml.get('model', '') or '')
    base_url = get_env_str('LLM_BASE_URL', '') or get_env_str('DEEPSEEK_BASE_URL', '') or str(llm_yaml.get('base_url', '') or '')

    # A Claude model name with LLM_PROVIDER=auto resolved from a generic key -> anthropic
    if provider == 'openai' and model.lower().startswith('claude') and not os.getenv('LLM_PROVIDER'):
        provider = 'anthropic'

    if provider == 'anthropic':
        # Never send an OpenAI-compatible base URL (e.g. DeepSeek/Moonshot) to the Anthropic SDK
        if base_url and 'anthropic' not in base_url.lower():
            print(f"[CONFIG] Ignoring base_url={base_url!r} for provider=anthropic")
            base_url = ''
        # A non-Claude model name (typically inherited from a legacy DeepSeek
        # config) would 404 against the Anthropic API -> use the provider default
        if model and not model.lower().startswith('claude'):
            print(f"[CONFIG] Ignoring model={model!r} for provider=anthropic (not a Claude model)")
            model = ''

    return {
        'provider': provider,
        'api_key': api_key,
        'model': model,
        'base_url': base_url,
        'temperature': get_env_float('LLM_TEMPERATURE', get_env_str('DEEPSEEK_TEMPERATURE', str(llm_yaml.get('temperature', 0.1)))),
        'effort': get_env_str('LLM_EFFORT', str(llm_yaml.get('effort', 'medium'))).lower(),
        'max_retries': get_env_int('LLM_MAX_RETRIES', str(llm_yaml.get('max_retries', 2))),
        'timeout_sec': get_env_float('LLM_TIMEOUT_SEC', str(llm_yaml.get('timeout_sec', 60))),
        'max_tokens': get_env_int('LLM_MAX_TOKENS', str(llm_yaml.get('max_tokens', 1024))),
        # Anthropic multi-workspace keys must send anthropic-workspace-id on every request
        'workspace_id': get_env_str('ANTHROPIC_WORKSPACE_ID', get_env_str('LLM_WORKSPACE_ID', str(llm_yaml.get('workspace_id', '') or ''))),
    }


def get_strategy_config(binance_env: str = 'live') -> DeepSeekAIStrategyConfig:
    """
    Build strategy configuration from environment variables.

    Parameters
    ----------
    binance_env : str
        'live' | 'testnet' | 'demo' - selects the REST endpoint the strategy
        uses for historical klines so indicators match the trading venue.

    Returns
    -------
    DeepSeekAIStrategyConfig
        Strategy configuration
    """
    # Load YAML config
    yaml_config = load_yaml_config()
    strategy_yaml = yaml_config.get('strategy', {})

    # LLM decision layer (Claude by default)
    llm = resolve_llm_settings(strategy_yaml)

    # Forced test signal: ONLY on paper venues. Never let a synthetic signal reach a real account.
    force_signal = get_env_str('FORCE_SIGNAL', '').upper()
    if force_signal and force_signal not in ('BUY', 'SELL'):
        raise ValueError(f"FORCE_SIGNAL={force_signal!r} must be BUY or SELL")
    if force_signal and binance_env == 'live':
        raise ValueError("FORCE_SIGNAL is only allowed with BINANCE_ENV=testnet or demo")
    if force_signal:
        print(f"[CONFIG] 🧪 FORCE_SIGNAL={force_signal} (paper venue {binance_env}) - LLM bypassed for the first cycle(s)")
    print(f"[CONFIG] LLM provider: {llm['provider']} | model: {llm['model'] or '(provider default)'}")

    # Live gate: a real account is never traded by accident (copied template, wrong
    # BINANCE_ENV, ...). The operator must set LIVE_TRADING_ACK=true explicitly.
    if binance_env == 'live' and not get_env_bool('LIVE_TRADING_ACK', False):
        raise ValueError(
            "BINANCE_ENV=live but LIVE_TRADING_ACK is not true. Run `python tools/preflight_live.py`, "
            "read DEPLOY_LIVE.md, then set LIVE_TRADING_ACK=true in .env to trade a real account."
        )

    # Operator-requested reset of the persisted kill-switch state (after a circuit-breaker halt)
    if get_env_bool('RESET_RISK_STATE', False):
        risk_file = Path(get_env_str('RISK_STATE_FILE', 'logs/risk_state.json'))
        if risk_file.exists():
            risk_file.unlink()
            print(f"[CONFIG] ⚠️ RESET_RISK_STATE=true -> removed {risk_file} (kill-switch state cleared)")

    # Safety: TEST_MODE / DRY_RUN run the full pipeline but never execute orders
    # (maps onto the strategy's signal-only shadow mode). Previously these flags
    # only printed a banner while real orders were still placed.
    dry_run = get_env_bool('TEST_MODE', False) or get_env_bool('DRY_RUN', False)
    signal_only_mode = get_env_bool('SIGNAL_ONLY_MODE', False) or dry_run
    if dry_run:
        print("[CONFIG] TEST_MODE/DRY_RUN enabled -> signal-only mode (no orders will be placed)")

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
        binance_rest_base_url=BINANCE_REST_BASE_URLS[binance_env],
        # Claim external orders/fills on our instrument (e.g. a manual close in the
        # Binance app) so on_position_closed fires and protective exits are cancelled
        # immediately instead of lingering until the next orphan sweep.
        external_order_claims=["BTCUSDT-PERP.BINANCE"],

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

        # AI decision layer (Anthropic Claude by default; DeepSeek/Kimi via OpenAI-compatible API)
        llm_provider=llm['provider'],
        llm_api_key=llm['api_key'],
        llm_model=llm['model'],
        llm_base_url=llm['base_url'],
        llm_temperature=llm['temperature'],
        llm_effort=llm['effort'],
        llm_max_retries=llm['max_retries'],
        llm_timeout_sec=llm['timeout_sec'],
        llm_max_tokens=llm['max_tokens'],
        llm_workspace_id=llm['workspace_id'],

        # Sentiment
        sentiment_enabled=True,
        sentiment_lookback_hours=4,
        # Set sentiment timeframe based on bar timeframe (default to 15m)
        sentiment_timeframe="1m" if timeframe == "1m" else ("5m" if timeframe == "5m" else "15m"),

        # Risk
        min_confidence_to_trade=get_env_str(
            'MIN_CONFIDENCE_TO_TRADE',
            strategy_yaml.get('risk', {}).get('min_confidence_to_trade', 'MEDIUM'),
        ),
        allow_reversals=True,
        require_high_confidence_for_reversal=False,
        rsi_extreme_threshold_upper=75.0,
        rsi_extreme_threshold_lower=25.0,
        rsi_extreme_multiplier=0.7,

        # Phase 0 safety: risk-based sizing & kill-switches
        risk_per_trade_pct=get_env_float('RISK_PER_TRADE_PCT', '0.01'),
        max_position_leverage=get_env_float('MAX_POSITION_LEVERAGE', '2.0'),
        daily_loss_limit_pct=get_env_float('DAILY_LOSS_LIMIT_PCT', '0.03'),
        max_consecutive_losses=get_env_int('MAX_CONSECUTIVE_LOSSES', '5'),
        loss_pause_hours=get_env_float('LOSS_PAUSE_HOURS', '24'),
        max_total_drawdown_pct=get_env_float('MAX_TOTAL_DRAWDOWN_PCT', '0.10'),
        risk_state_file=get_env_str('RISK_STATE_FILE', 'logs/risk_state.json'),
        max_consecutive_same_signal=get_env_int('MAX_CONSECUTIVE_SAME_SIGNAL', '5'),

        # Phase 1: ATR-based exits & trailing
        atr_period=get_env_int('ATR_PERIOD', '14'),
        use_atr_exits=get_env_str('USE_ATR_EXITS', 'true').lower() == 'true',
        sl_atr_multiplier=get_env_float('SL_ATR_MULTIPLIER', '1.5'),
        tp_atr_multiplier=get_env_float('TP_ATR_MULTIPLIER', '3.0'),
        trailing_use_atr=get_env_str('TRAILING_USE_ATR', 'true').lower() == 'true',
        trailing_activation_atr=get_env_float('TRAILING_ACTIVATION_ATR', '1.0'),
        trailing_distance_atr=get_env_float('TRAILING_DISTANCE_ATR', '1.0'),
        trailing_update_threshold_atr=get_env_float('TRAILING_UPDATE_THRESHOLD_ATR', '0.25'),

        # Phase 2: signal measurement & regime filter (also forced on by TEST_MODE/DRY_RUN)
        signal_only_mode=signal_only_mode,
        regime_filter_enabled=get_env_str('REGIME_FILTER_ENABLED', 'true').lower() == 'true',
        regime_timeframe=get_env_str('REGIME_TIMEFRAME', '4h'),
        regime_ema_fast=get_env_int('REGIME_EMA_FAST', '20'),
        regime_ema_slow=get_env_int('REGIME_EMA_SLOW', '50'),
        regime_flat_threshold_pct=get_env_float('REGIME_FLAT_THRESHOLD_PCT', '0.002'),

        # Execution
        position_adjustment_threshold=0.001,

        # Testing aid (paper venues only, validated above)
        force_signal=force_signal,
        force_signal_cycles=get_env_int('FORCE_SIGNAL_CYCLES', '1'),

        # Exit management & resilience
        native_exits=get_env_bool('NATIVE_EXITS', True),      # exchange-side SL/TP that survive restarts
        llm_async=get_env_bool('LLM_ASYNC', True),            # LLM/sentiment/regime calls off the event loop
        position_state_file=get_env_str('POSITION_STATE_FILE', 'logs/position_state.json'),
        heartbeat_file=get_env_str('HEARTBEAT_FILE', 'logs/heartbeat'),

        # Timing - Load from YAML config (default: 900 seconds = 15 minutes)
        timer_interval_sec=get_env_int('TIMER_INTERVAL_SEC', str(strategy_yaml.get('timer_interval_sec', 900))),
        
        # Telegram Notifications (ENABLE_TELEGRAM env overrides the YAML flag;
        # previously the env var documented in .env.template had no effect)
        enable_telegram=get_env_bool(
            'ENABLE_TELEGRAM',
            bool(strategy_yaml.get('telegram', {}).get('enabled', False)),
        ),
        telegram_bot_token=get_env_str('TELEGRAM_BOT_TOKEN', ''),
        telegram_chat_id=get_env_str('TELEGRAM_CHAT_ID', ''),
        telegram_notify_signals=strategy_yaml.get('telegram', {}).get('notify_signals', True),
        telegram_notify_fills=strategy_yaml.get('telegram', {}).get('notify_fills', True),
        telegram_notify_positions=strategy_yaml.get('telegram', {}).get('notify_positions', True),
        telegram_notify_errors=strategy_yaml.get('telegram', {}).get('notify_errors', True),
    )


# Binance USDT-M Futures REST endpoints per environment (used by the strategy's
# kline prefetch and regime fetch so indicator history matches the trading venue)
BINANCE_REST_BASE_URLS = {
    'live': 'https://fapi.binance.com',
    'testnet': 'https://testnet.binancefuture.com',
    'demo': 'https://demo-fapi.binance.com',
}


def resolve_binance_environment() -> str:
    """
    Resolve BINANCE_ENV -> 'live' | 'testnet' | 'demo' (default: live).

    Testnet/demo keys are issued separately (testnet.binancefuture.com /
    Binance demo trading) and are rejected by live Binance with -2015/-2008.
    """
    env = get_env_str('BINANCE_ENV', 'live').lower()
    aliases = {'prod': 'live', 'production': 'live', 'mainnet': 'live', 'paper': 'demo', 'test': 'testnet'}
    env = aliases.get(env, env)
    if env not in BINANCE_REST_BASE_URLS:
        raise ValueError(f"BINANCE_ENV={env!r} is not one of live|testnet|demo")
    return env


def query_binance_symbol_settings(environment: str, api_key: str, api_secret: str, symbol: str = 'BTCUSDT') -> Optional[dict]:
    """
    Read the account's current leverage / margin type / position for `symbol`
    (signed GET /fapi/v2/positionRisk). Returns None if the query fails.

    Used to make startup idempotent: Binance rejects a margin-type change while
    a position is open (-4048) and the Nautilus exec client treats that as a
    failed connect, which would leave an open position unmanaged after a restart.
    """
    import hmac
    import hashlib
    import time as _time
    import requests

    base = BINANCE_REST_BASE_URLS[environment]
    try:
        query = f"symbol={symbol}&timestamp={int(_time.time() * 1000)}&recvWindow=10000"
        signature = hmac.new(api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        response = requests.get(
            f"{base}/fapi/v2/positionRisk?{query}&signature={signature}",
            headers={"X-MBX-APIKEY": api_key},
            timeout=10,
        )
        response.raise_for_status()
        rows = [r for r in response.json() if r.get('symbol') == symbol]
        if not rows:
            return None
        row = rows[0]
        return {
            'leverage': int(float(row.get('leverage', 0) or 0)),
            'margin_type': str(row.get('marginType', '')).lower(),  # 'isolated' | 'cross'
            'position_amt': float(row.get('positionAmt', 0) or 0),
        }
    except Exception as e:  # noqa: BLE001
        print(f"[CONFIG] ⚠️ Could not read current Binance symbol settings: {e}")
        return None


def get_binance_config(environment: str = 'live') -> tuple:
    """
    Build Binance data and execution client configs.

    Parameters
    ----------
    environment : str
        'live' | 'testnet' | 'demo' (see `resolve_binance_environment`).

    Returns
    -------
    tuple
        (data_config, exec_config)
    """
    # Get API credentials
    api_key = get_env_str('BINANCE_API_KEY', '')
    api_secret = get_env_str('BINANCE_API_SECRET', '')

    if not api_key or not api_secret:
        raise ValueError("BINANCE_API_KEY and BINANCE_API_SECRET required in .env")

    binance_env = {
        'live': BinanceEnvironment.LIVE,
        'testnet': BinanceEnvironment.TESTNET,
        'demo': BinanceEnvironment.DEMO,
    }[environment]

    # Exchange-side leverage & margin mode for the traded symbol. Previously the
    # bot never set these, so the account default (often 20x cross) applied.
    # Position notional is independently capped at max_position_leverage x equity.
    leverage = get_env_int('BINANCE_LEVERAGE', get_env_str('LEVERAGE', '5'))
    leverage = max(1, min(leverage, 125))
    margin_type_str = get_env_str('BINANCE_MARGIN_TYPE', 'isolated').lower()
    margin_type = BinanceFuturesMarginType.CROSS if margin_type_str in ('cross', 'crossed') else BinanceFuturesMarginType.ISOLATED
    symbol = BinanceSymbol('BTCUSDT')

    # Only send what can actually change: an impossible change (margin type with
    # an open position) would fail the exec client connect.
    futures_leverages = {symbol: leverage}
    futures_margin_types = {symbol: margin_type}
    current = query_binance_symbol_settings(environment, api_key, api_secret, str(symbol))
    if current is None:
        print("[CONFIG] ⚠️ Current symbol settings unknown - not touching leverage/margin at startup")
        futures_leverages, futures_margin_types = None, None
    else:
        if current['leverage'] == leverage:
            futures_leverages = None
        if current['margin_type'] == margin_type.name.lower():
            futures_margin_types = None
        elif current['position_amt'] != 0:
            print(
                f"[CONFIG] ⚠️ Margin type is {current['margin_type']} but {margin_type.name.lower()} requested; "
                f"cannot change while a position ({current['position_amt']}) is open - keeping current"
            )
            futures_margin_types = None
    print(
        f"[CONFIG] Binance {environment} {symbol}: leverage {leverage}x "
        f"({'set at startup' if futures_leverages else 'already set'}), margin {margin_type.name} "
        f"({'set at startup' if futures_margin_types else 'unchanged'})"
    )

    # Data client config
    data_config = BinanceDataClientConfig(
        api_key=api_key,
        api_secret=api_secret,
        account_type=BinanceAccountType.USDT_FUTURES,  # Binance Futures
        environment=binance_env,
        instrument_provider=InstrumentProviderConfig(load_all=True),
    )

    # Execution client config
    exec_config = BinanceExecClientConfig(
        api_key=api_key,
        api_secret=api_secret,
        account_type=BinanceAccountType.USDT_FUTURES,
        environment=binance_env,
        instrument_provider=InstrumentProviderConfig(load_all=True),
        futures_leverages=futures_leverages,
        futures_margin_types=futures_margin_types,
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
    binance_env = resolve_binance_environment()
    strategy_config = get_strategy_config(binance_env)
    data_config, exec_config = get_binance_config(binance_env)

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
        log_directory="logs",
        log_file_name="deepseek_trader",
        log_file_format="json",
        log_colors=True,
        bypass_logging=False,
        log_file_max_size=10_485_760,  # 10MB in bytes (10 * 1024 * 1024)
        log_file_max_backup_count=3,   # Keep 3 backup files (total: 40MB max)
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
    print("AI Trading Strategy - Live Trading Mode")
    print("=" * 70)
    print(f"Exchange: Binance Futures (USDT-M)")
    print(f"Instrument: BTCUSDT-PERP")
    print(f"Strategy: LLM-powered (Claude by default; LLM_PROVIDER selects DeepSeek/Kimi)")
    print("=" * 70)

    # Safety check
    test_mode = get_env_bool('TEST_MODE', False) or get_env_bool('DRY_RUN', False)
    auto_confirm = get_env_bool('AUTO_CONFIRM', False)
    binance_env = resolve_binance_environment()
    if binance_env != 'live':
        print(f"🧪 BINANCE_ENV={binance_env} - paper trading venue ({BINANCE_REST_BASE_URLS[binance_env]}), no real funds")
        auto_confirm = True  # nothing real at stake -> no interactive prompt needed
    else:
        print("🏦 BINANCE_ENV=live - REAL Binance Futures account")

    if test_mode:
        print("⚠️  TEST_MODE/DRY_RUN=true - signal-only mode: signals are logged, NO orders are placed")
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
    print(f"✅ Strategy configured with LLM decision layer")
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
