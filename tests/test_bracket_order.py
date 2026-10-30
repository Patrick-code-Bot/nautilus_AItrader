"""Unit tests for bracket-order submission and the trailing-stop update path."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from helpers import make_strategy_stub  # noqa: E402

from nautilus_trader.model.enums import OrderSide, OrderType  # noqa: E402


class DummyOrderList:
    def __init__(self) -> None:
        self.orders = [
            SimpleNamespace(order_type=OrderType.MARKET, client_order_id="ENTRY-order"),
            SimpleNamespace(order_type=OrderType.STOP_MARKET, client_order_id="SL-order"),
            SimpleNamespace(order_type=OrderType.LIMIT, client_order_id="TP-order"),
        ]
        self.id = "order-list-001"


class DummyOrderFactory:
    def __init__(self) -> None:
        self.kwargs: Dict[str, Any] | None = None

    def bracket(self, **kwargs: Any) -> DummyOrderList:
        self.kwargs = kwargs
        return DummyOrderList()


def _bracket_stub(**overrides: Any):
    attrs: Dict[str, Any] = {
        "order_factory": DummyOrderFactory(),
        "_submit_order": Mock(),
        "_get_current_atr": lambda: 0.0,
    }
    attrs.update(overrides)
    return make_strategy_stub(**attrs)


def test_submit_bracket_order_uses_latest_price_and_support_resistance() -> None:
    strategy = _bracket_stub()

    strategy._submit_bracket_order(OrderSide.BUY, 0.01)

    kwargs = strategy.order_factory.kwargs
    assert kwargs is not None, "Bracket call should occur"
    # TP: HIGH confidence -> +3% ; SL: support 950 * (1 - 0.001) = 949.05
    assert kwargs["tp_price"] == 1030.0
    assert kwargs["sl_trigger_price"] == 949.05
    assert kwargs["quantity"] == 0.01
    strategy.submit_order_list.assert_called_once()
    strategy._submit_order.assert_not_called()


def test_submit_bracket_order_uses_atr_exits_when_available() -> None:
    strategy = _bracket_stub(use_atr_exits=True, _get_current_atr=lambda: 10.0)

    strategy._submit_bracket_order(OrderSide.SELL, 0.02)

    kwargs = strategy.order_factory.kwargs
    # SHORT: SL = entry + 1.5*ATR, TP = entry - 3*ATR  (2:1 reward:risk)
    assert kwargs["sl_trigger_price"] == 1015.0
    assert kwargs["tp_price"] == 970.0


def test_submit_bracket_order_skips_entry_when_price_missing() -> None:
    """Phase 0 rule: never open an unprotected position as a fallback."""
    strategy = _bracket_stub(latest_price_data={})
    strategy.indicator_manager.recent_bars = []

    strategy._submit_bracket_order(OrderSide.SELL, 0.02)

    strategy._submit_order.assert_not_called()
    strategy.submit_order_list.assert_not_called()
    assert strategy.order_factory.kwargs is None
    assert strategy.log.contains("Unable to determine entry price")


def test_submit_bracket_order_initialises_partial_tp_without_trailing() -> None:
    """Regression: `instrument_key` was undefined when trailing was disabled."""
    strategy = _bracket_stub(enable_trailing_stop=False, enable_partial_tp=True)

    strategy._submit_bracket_order(OrderSide.BUY, 0.01)

    assert not strategy.log.contains("Failed to submit bracket order")
    state = strategy.partial_tp_state["BTCUSDT-PERP.BINANCE"]
    assert state["side"] == "LONG"
    assert state["original_quantity"] == 0.01
    assert abs(state["sl_distance"] - (1000.0 - 949.05)) < 1e-9
    assert strategy.trailing_stop_state == {}


def test_submit_bracket_order_records_trailing_state() -> None:
    strategy = _bracket_stub(enable_trailing_stop=True)

    strategy._submit_bracket_order(OrderSide.BUY, 0.01)

    state = strategy.trailing_stop_state["BTCUSDT-PERP.BINANCE"]
    assert state["sl_order_id"] == "SL-order"
    assert state["side"] == "LONG"
    assert state["current_sl_price"] == 949.05
    assert state["activated"] is False


def test_trailing_update_modifies_sl_in_place_and_keeps_tp() -> None:
    """
    Regression: bracket SL/TP are OUO-linked, so cancelling the SL cancelled the
    TP as well. The update must MODIFY the existing SL trigger, not cancel it.
    """
    open_sl_order = SimpleNamespace(is_open=True, client_order_id="SL-order")
    strategy = make_strategy_stub(
        enable_trailing_stop=True,
        cache=SimpleNamespace(order=lambda cid: open_sl_order, bars=lambda bt: []),
        trailing_stop_state={
            "BTCUSDT-PERP.BINANCE": {
                "entry_price": 1000.0,
                "highest_price": 1000.0,
                "lowest_price": None,
                "current_sl_price": 949.05,
                "sl_order_id": "SL-order",
                "activated": False,
                "side": "LONG",
                "quantity": 0.01,
                "atr": 0.0,
            }
        },
    )

    # Price rallies +2% -> activation (1%) reached; new SL = high * (1 - 0.5%)
    strategy._update_trailing_stops(1020.0)

    state = strategy.trailing_stop_state["BTCUSDT-PERP.BINANCE"]
    assert state["activated"] is True
    strategy.modify_order.assert_called_once()
    called_order, = strategy.modify_order.call_args.args
    assert called_order is open_sl_order
    assert strategy.modify_order.call_args.kwargs["trigger_price"] == 1014.9
    strategy.cancel_order.assert_not_called()
    strategy.submit_order.assert_not_called()
    assert state["current_sl_price"] == 1014.9
    assert state["sl_order_id"] == "SL-order"


def test_trailing_update_submits_native_stop_when_sl_order_unknown() -> None:
    """After a restart the bracket SL is gone -> a fresh reduce-only stop is placed."""
    new_order = SimpleNamespace(client_order_id="NEW-SL")
    factory = Mock()
    factory.stop_market.return_value = new_order
    strategy = make_strategy_stub(
        enable_trailing_stop=True,
        order_factory=factory,
        cache=SimpleNamespace(order=lambda cid: None, bars=lambda bt: []),
        trailing_stop_state={
            "BTCUSDT-PERP.BINANCE": {
                "entry_price": 1000.0,
                "highest_price": None,
                "lowest_price": 1000.0,
                "current_sl_price": None,
                "sl_order_id": None,
                "activated": False,
                "side": "SHORT",
                "quantity": 0.01,
                "atr": 0.0,
            }
        },
    )

    strategy._update_trailing_stops(980.0)  # -2% for a SHORT -> activated

    factory.stop_market.assert_called_once()
    kwargs = factory.stop_market.call_args.kwargs
    assert kwargs["order_side"] == OrderSide.BUY
    assert kwargs["reduce_only"] is True
    assert kwargs["trigger_price"] == 984.9  # 980 * 1.005
    strategy.submit_order.assert_called_once_with(new_order)
    strategy.modify_order.assert_not_called()
    assert strategy.trailing_stop_state["BTCUSDT-PERP.BINANCE"]["sl_order_id"] == "NEW-SL"


def test_trailing_stop_never_moves_backwards() -> None:
    open_sl_order = SimpleNamespace(is_open=True, client_order_id="SL-order")
    strategy = make_strategy_stub(
        enable_trailing_stop=True,
        cache=SimpleNamespace(order=lambda cid: open_sl_order, bars=lambda bt: []),
        trailing_stop_state={
            "BTCUSDT-PERP.BINANCE": {
                "entry_price": 1000.0,
                "highest_price": 1030.0,
                "lowest_price": None,
                "current_sl_price": 1024.85,
                "sl_order_id": "SL-order",
                "activated": True,
                "side": "LONG",
                "quantity": 0.01,
                "atr": 0.0,
            }
        },
    )

    strategy._update_trailing_stops(1010.0)  # pullback: SL must stay

    strategy.modify_order.assert_not_called()
    assert strategy.trailing_stop_state["BTCUSDT-PERP.BINANCE"]["current_sl_price"] == 1024.85


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"✅ {name}")
    print("✅ bracket order tests passed")
