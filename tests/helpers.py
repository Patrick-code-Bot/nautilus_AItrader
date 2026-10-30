"""
Shared test helpers.

`DeepSeekAIStrategy` extends NautilusTrader's Cython `Strategy`, whose core
attributes (`cache`, `log`, `clock`, `portfolio`, ...) are read-only. To unit
test the pure-Python strategy methods in isolation we bind them onto a plain
Python object where every attribute can be stubbed.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import FunctionType, SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class DummyLogger:
    def __init__(self) -> None:
        self.messages: List[str] = []

    def _record(self, level: str, msg: str, *args: Any, **kwargs: Any) -> None:
        self.messages.append(f"{level}: {msg}")

    def info(self, msg: str, *a: Any, **k: Any) -> None:
        self._record("INFO", msg)

    def warning(self, msg: str, *a: Any, **k: Any) -> None:
        self._record("WARNING", msg)

    def error(self, msg: str, *a: Any, **k: Any) -> None:
        self._record("ERROR", msg)

    def debug(self, msg: str, *a: Any, **k: Any) -> None:
        self._record("DEBUG", msg)

    def contains(self, needle: str) -> bool:
        return any(needle in m for m in self.messages)


class DummyInstrument:
    """Minimal instrument double returning plain floats for prices/quantities."""

    def make_qty(self, quantity: float) -> float:
        return round(float(quantity), 3)

    def make_price(self, price: float) -> float:
        return round(float(price), 2)


def make_strategy_stub(**attrs: Any):
    """
    Build an object carrying every Python-level method of DeepSeekAIStrategy
    (but none of the Cython base-class machinery), pre-populated with sane
    defaults that tests can override via keyword arguments.
    """
    from strategy.deepseek_strategy import DeepSeekAIStrategy

    methods: Dict[str, Any] = {
        name: fn
        for name, fn in vars(DeepSeekAIStrategy).items()
        if isinstance(fn, (FunctionType, staticmethod, classmethod))
        and not name.startswith("__")
    }
    cls = type("StrategyStub", (object,), methods)
    stub = cls()

    defaults: Dict[str, Any] = {
        "log": DummyLogger(),
        "instrument": DummyInstrument(),
        "instrument_id": "BTCUSDT-PERP.BINANCE",
        "bar_type": "BTCUSDT-PERP.BINANCE-15-MINUTE-LAST-EXTERNAL",
        "equity": 400.0,
        "position_config": {
            "high_confidence_multiplier": 1.5,
            "medium_confidence_multiplier": 1.0,
            "low_confidence_multiplier": 0.5,
            "max_position_ratio": 0.10,
            "trend_strength_multiplier": 1.2,
            "min_trade_amount": 0.001,
            "adjustment_threshold": 0.001,
        },
        "rsi_extreme_upper": 75.0,
        "rsi_extreme_lower": 25.0,
        "rsi_extreme_mult": 0.7,
        "risk_per_trade_pct": 0.01,
        "max_position_leverage": 2.0,
        "min_notional_usdt": 100.0,
        "use_atr_exits": False,
        "sl_atr_multiplier": 1.5,
        "tp_atr_multiplier": 3.0,
        "sl_use_support_resistance": True,
        "sl_buffer_pct": 0.001,
        "tp_pct_config": {"HIGH": 0.03, "MEDIUM": 0.02, "LOW": 0.01},
        "enable_auto_sl_tp": True,
        "enable_trailing_stop": False,
        "enable_partial_tp": False,
        "partial_tp_levels": ({"r_multiple": 1.0, "position_pct": 0.5},),
        "trailing_stop_state": {},
        "partial_tp_state": {},
        "disaster_stop_state": {},
        "trailing_use_atr": False,
        "trailing_activation_atr": 1.0,
        "trailing_distance_atr": 1.0,
        "trailing_activation_pct": 0.01,
        "trailing_distance_pct": 0.005,
        "trailing_update_threshold_pct": 0.002,
        "trailing_update_threshold_atr": 0.25,
        "latest_signal_data": {"confidence": "HIGH", "signal": "BUY"},
        "latest_technical_data": {"support": 950.0, "resistance": 1050.0, "atr": 0.0},
        "latest_price_data": {"price": 1000.0},
        "indicator_manager": SimpleNamespace(recent_bars=[]),
        "cache": SimpleNamespace(
            bars=lambda bar_type: [],
            order=lambda cid: None,
            positions_open=lambda **kw: [],
            orders_open=lambda **kw: [],
        ),
        "order_factory": Mock(),
        "submit_order": Mock(),
        "submit_order_list": Mock(),
        "modify_order": Mock(),
        "cancel_order": Mock(),
        "telegram_bot": None,
        "enable_telegram": False,
        "telegram_notify_positions": False,
        "telegram_notify_errors": False,
        "max_consecutive_same_signal": 5,
        "daily_loss_limit_pct": 0.03,
        "loss_pause_hours": 24.0,
        "risk_state": {
            "consecutive_losses": 0,
            "paused_until": None,
            "day_date": None,
            "day_start_equity": None,
            "equity_peak": None,
            "halted_reason": None,
        },
        "max_total_drawdown_pct": 0.10,
        "risk_state_file": "",
        "_save_risk_state": Mock(),  # no disk persistence in unit tests
        "llm": SimpleNamespace(signal_history=[], provider="test", model="stub"),
        # Exit management & resilience
        "native_exits": True,
        "position_state_file": "",
        "heartbeat_file": "",
        "_save_position_state": Mock(),
        "_clear_position_state": Mock(),
        "_load_position_state": Mock(return_value=None),
        "disaster_stop_enabled": False,
        "disaster_stop_min_pct": 0.015,
        "_pending_entry": None,
        "llm_async": False,
        "_loop": None,
        "_llm_executor": None,
        "_analysis_inflight": False,
        "_force_signal_remaining": 0,
        "force_signal": "",
        "regime_filter_enabled": False,
        "regime_cache_ttl_sec": 1800,
        "_regime_cache": {"value": None, "ts": 0.0},
        "sentiment_enabled": False,
        "sentiment_fetcher": None,
        "signal_only_mode": False,
        "is_trading_paused": False,
        "min_confidence": "MEDIUM",
        "allow_reversals": True,
        "require_high_conf_reversal": False,
        "enable_oco": False,
        "last_signal": None,
        "latest_signal_data_": None,
        "_log_signal_record": Mock(),
        "telegram_notify_signals": False,
        "telegram_notify_fills": False,
    }
    defaults.update(attrs)
    for key, value in defaults.items():
        setattr(stub, key, value)
    stub.deepseek = stub.llm  # legacy alias
    return stub
