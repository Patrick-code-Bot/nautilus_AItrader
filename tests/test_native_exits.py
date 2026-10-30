"""
Tests for exchange-side exits, restart re-adoption and the worker-thread
analysis hand-off (all offline).
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from helpers import make_strategy_stub  # noqa: E402
from nautilus_trader.model.enums import OrderSide, OrderType, PositionSide  # noqa: E402

KEY = "BTCUSDT-PERP.BINANCE"


class _Clock:
    def utc_now(self):
        import pandas as pd
        return pd.Timestamp("2026-10-21 12:00:00", tz="UTC")


def _factory():
    factory = Mock()
    counter = {"n": 0}

    def _mk(**kwargs):
        counter["n"] += 1
        return SimpleNamespace(client_order_id=f"O-{counter['n']:03d}", **kwargs)

    factory.stop_market.side_effect = lambda **kw: _mk(order_type=OrderType.STOP_MARKET, **kw)
    factory.market_if_touched.side_effect = lambda **kw: _mk(order_type=OrderType.MARKET_IF_TOUCHED, **kw)
    factory.market.side_effect = lambda **kw: _mk(order_type=OrderType.MARKET, **kw)
    return factory


def _stub(**overrides):
    attrs = dict(
        order_factory=_factory(),
        clock=_Clock(),
        latest_technical_data={"support": 950.0, "resistance": 1050.0, "atr": 10.0},
        use_atr_exits=True,
        latest_signal_data={"signal": "BUY", "confidence": "HIGH"},
        latest_price_data={"price": 1000.0},
    )
    attrs.update(overrides)
    return make_strategy_stub(**attrs)


# ------------------------------------------------------------ entry + arming

def test_open_new_position_native_submits_market_entry_and_pending_context():
    strategy = _stub()
    strategy._open_new_position("long", 0.05)

    strategy.order_factory.market.assert_called_once()
    kw = strategy.order_factory.market.call_args.kwargs
    assert kw["order_side"] == OrderSide.BUY and kw["reduce_only"] is False
    strategy.submit_order.assert_called_once()
    strategy.submit_order_list.assert_not_called()  # no emulated bracket any more
    pending = strategy._pending_entry
    assert pending["side"] == "LONG" and pending["quantity"] == 0.05 and pending["confidence"] == "HIGH"
    assert pending["est_sl_price"] == 985.0 and pending["est_tp_price"] == 1030.0  # 1.5/3 x ATR


def test_open_new_position_legacy_bracket_when_native_disabled():
    strategy = _stub(native_exits=False, _submit_bracket_order=Mock())
    strategy._open_new_position("short", 0.02)
    strategy._submit_bracket_order.assert_called_once_with(side=OrderSide.SELL, quantity=0.02)
    assert strategy._pending_entry is None


def test_arm_native_exits_places_sl_and_tp_reduce_only_and_records_state():
    strategy = _stub()
    strategy._arm_native_exits("LONG", 0.05, 1002.0, "HIGH")

    sl_kw = strategy.order_factory.stop_market.call_args.kwargs
    tp_kw = strategy.order_factory.market_if_touched.call_args.kwargs
    assert sl_kw["order_side"] == OrderSide.SELL and sl_kw["reduce_only"] is True
    assert tp_kw["order_side"] == OrderSide.SELL and tp_kw["reduce_only"] is True
    assert sl_kw["trigger_price"] == 987.0 and tp_kw["trigger_price"] == 1032.0
    assert strategy.submit_order.call_count == 2

    state = strategy.trailing_stop_state[KEY]
    assert state["native"] is True and state["side"] == "LONG" and state["quantity"] == 0.05
    assert state["sl_order_id"] == "O-001" and state["tp_order_id"] == "O-002"
    assert state["current_sl_price"] == 987.0 and state["tp_price"] == 1032.0
    assert strategy.partial_tp_state == {}  # partial TP disabled in the stub
    strategy._save_position_state.assert_called()


def test_arm_native_exits_fixes_inconsistent_levels():
    strategy = _stub(latest_technical_data={"support": 1100.0, "resistance": 900.0, "atr": 0.0}, use_atr_exits=False)
    strategy._arm_native_exits("LONG", 0.01, 1000.0, "LOW")  # S/R fallback would put SL above entry
    sl_kw = strategy.order_factory.stop_market.call_args.kwargs
    tp_kw = strategy.order_factory.market_if_touched.call_args.kwargs
    assert sl_kw["trigger_price"] == 980.0 and tp_kw["trigger_price"] == 1040.0


def test_position_opened_arms_exits_from_actual_fill_price():
    strategy = _stub(_pending_entry={"side": "LONG", "quantity": 0.05, "confidence": "MEDIUM"},
                     _submit_disaster_stop=Mock())
    event = SimpleNamespace(side=PositionSide.LONG, quantity=0.05, avg_px_open=1004.0)
    strategy.on_position_opened(event)

    sl_kw = strategy.order_factory.stop_market.call_args.kwargs
    assert sl_kw["trigger_price"] == 989.0  # 1004 - 1.5*10 (actual fill, not the 1000 estimate)
    assert strategy._pending_entry is None
    strategy._submit_disaster_stop.assert_not_called()  # disabled in stub
    strategy._save_position_state.assert_called()


# ------------------------------------------------------------ trailing / partial

def _open_long_state(sl_id="SL-1", tp_id="TP-1", activated=True):
    return {KEY: {"entry_price": 1000.0, "highest_price": 1030.0, "lowest_price": None,
                  "current_sl_price": 990.0, "sl_order_id": sl_id, "tp_price": 1030.0,
                  "tp_order_id": tp_id, "activated": activated, "side": "LONG",
                  "quantity": 0.05, "atr": 10.0, "native": True}}


def test_native_trailing_replaces_stop_and_never_touches_tp():
    old_sl = SimpleNamespace(is_open=True, client_order_id="SL-1")
    cache = SimpleNamespace(order=lambda cid: old_sl if str(cid) == "SL-1" else None, bars=lambda bt: [],
                            positions_open=lambda **kw: [], orders_open=lambda **kw: [])
    strategy = _stub(enable_trailing_stop=True, trailing_use_atr=True, cache=cache,
                     trailing_stop_state=_open_long_state())

    strategy._update_trailing_stops(1040.0)  # new high -> new SL = 1040 - 1*ATR = 1030

    strategy.order_factory.stop_market.assert_called_once()
    assert strategy.order_factory.stop_market.call_args.kwargs["trigger_price"] == 1030.0
    strategy.submit_order.assert_called_once()
    strategy.cancel_order.assert_called_once_with(old_sl)
    strategy.modify_order.assert_not_called()
    state = strategy.trailing_stop_state[KEY]
    assert state["current_sl_price"] == 1030.0 and state["sl_order_id"] == "O-001"
    assert state["tp_order_id"] == "TP-1"  # untouched


def test_partial_tp_resizes_native_exits():
    opened = {"SL-1": SimpleNamespace(is_open=True, client_order_id="SL-1"),
              "TP-1": SimpleNamespace(is_open=True, client_order_id="TP-1")}
    cache = SimpleNamespace(order=lambda cid: opened.get(str(cid)), bars=lambda bt: [],
                            positions_open=lambda **kw: [], orders_open=lambda **kw: [])
    strategy = _stub(enable_partial_tp=True, cache=cache, _submit_order=Mock(),
                     trailing_stop_state=_open_long_state(activated=False),
                     partial_tp_state={KEY: {"entry_price": 1000.0, "sl_distance": 10.0, "side": "LONG",
                                             "original_quantity": 0.05, "levels_done": []}})

    strategy._check_partial_take_profits(1012.0)  # 1.2R reached -> close 50%

    strategy._submit_order.assert_called_once_with(side=OrderSide.SELL, quantity=0.025, reduce_only=True)
    # exits re-issued for the remaining 0.025 and the old ones cancelled
    assert strategy.order_factory.stop_market.call_args.kwargs["quantity"] == 0.025
    assert strategy.order_factory.market_if_touched.call_args.kwargs["quantity"] == 0.025
    assert strategy.cancel_order.call_count == 2
    assert strategy.trailing_stop_state[KEY]["quantity"] == 0.025
    assert strategy.partial_tp_state[KEY]["levels_done"] == [0]


def test_position_closed_cancels_exits_and_clears_state():
    opened = {"SL-1": SimpleNamespace(is_open=True, client_order_id="SL-1"),
              "TP-1": SimpleNamespace(is_open=True, client_order_id="TP-1")}
    cache = SimpleNamespace(order=lambda cid: opened.get(str(cid)), bars=lambda bt: [],
                            positions_open=lambda **kw: [], orders_open=lambda **kw: [])
    strategy = _stub(cache=cache, trailing_stop_state=_open_long_state(), max_consecutive_losses=5,
                     partial_tp_state={KEY: {"levels_done": []}})
    event = SimpleNamespace(side=PositionSide.FLAT, entry=OrderSide.BUY, realized_pnl=12.5,
                            avg_px_open=1000.0, peak_qty=0.05, quantity=0.0, avg_px_close=1010.0)
    strategy.on_position_closed(event)

    assert strategy.cancel_order.call_count == 2
    assert strategy.trailing_stop_state == {} and strategy.partial_tp_state == {}
    strategy._clear_position_state.assert_called_once()
    assert strategy.risk_state["consecutive_losses"] == 0


# ------------------------------------------------------------ re-adoption

def _position(side=PositionSide.LONG, qty=0.05, entry=1000.0):
    return SimpleNamespace(side=side, quantity=qty, avg_px_open=entry)


def _readopt_stub(open_orders, saved=None, mark=1005.0, **overrides):
    by_id = {str(o.client_order_id): o for o in open_orders}
    cache = SimpleNamespace(order=lambda cid: by_id.get(str(cid)), bars=lambda bt: [],
                            positions_open=lambda **kw: [_position()],
                            orders_open=lambda **kw: list(open_orders))
    im = SimpleNamespace(recent_bars=[SimpleNamespace(close=mark)],
                         get_technical_data=lambda p: {"support": 950.0, "resistance": 1050.0, "atr": 10.0})
    attrs = dict(cache=cache, indicator_manager=im, _load_position_state=Mock(return_value=saved),
                 _submit_disaster_stop=Mock(), disaster_stop_enabled=True, _submit_order=Mock(),
                 _cleanup_oco_orphans=Mock())
    attrs.update(overrides)
    return _stub(**attrs)


def test_readopt_without_state_rearms_everything():
    strategy = _readopt_stub(open_orders=[])
    strategy._readopt_open_position()

    # SL + TP armed from ATR around the venue's entry price, plus disaster stop
    assert strategy.order_factory.stop_market.call_count == 1
    assert strategy.order_factory.market_if_touched.call_count == 1
    assert strategy.order_factory.stop_market.call_args.kwargs["trigger_price"] == 985.0
    strategy._submit_disaster_stop.assert_called_once_with("long", 0.05, 1000.0)
    state = strategy.trailing_stop_state[KEY]
    assert state["side"] == "LONG" and state["native"] is True and state["quantity"] == 0.05
    assert strategy.log.contains("Re-adopting open LONG position")


def test_readopt_with_live_exits_adopts_them_without_duplicates():
    sl = SimpleNamespace(client_order_id="SL-9", is_open=True, is_reduce_only=True,
                         order_type=OrderType.STOP_MARKET, trigger_price=990.0)
    tp = SimpleNamespace(client_order_id="TP-9", is_open=True, is_reduce_only=True,
                         order_type=OrderType.MARKET_IF_TOUCHED, trigger_price=1030.0)
    dis = SimpleNamespace(client_order_id="DS-9", is_open=True, is_reduce_only=True,
                          order_type=OrderType.STOP_MARKET, trigger_price=985.0)
    saved = {"trailing_stop_state": _open_long_state(sl_id="SL-9", tp_id="TP-9"),
             "partial_tp_state": {}, "disaster_stop_state": {KEY: {"order_id": "DS-9", "price": 985.0}}}
    strategy = _readopt_stub(open_orders=[sl, tp, dis], saved=saved)
    strategy._readopt_open_position()

    strategy.order_factory.stop_market.assert_not_called()
    strategy.order_factory.market_if_touched.assert_not_called()
    strategy._submit_disaster_stop.assert_not_called()
    strategy.cancel_order.assert_not_called()
    assert strategy.trailing_stop_state[KEY]["activated"] is True  # trailing progress kept
    assert strategy.log.contains("already live")


def test_readopt_adopts_unknown_ids_by_scanning_open_orders():
    sl = SimpleNamespace(client_order_id="X-1", is_open=True, is_reduce_only=True,
                         order_type=OrderType.STOP_MARKET, trigger_price=992.0)
    dis = SimpleNamespace(client_order_id="X-2", is_open=True, is_reduce_only=True,
                          order_type=OrderType.STOP_MARKET, trigger_price=980.0)
    tp = SimpleNamespace(client_order_id="X-3", is_open=True, is_reduce_only=True,
                         order_type=OrderType.MARKET_IF_TOUCHED, trigger_price=1025.0)
    strategy = _readopt_stub(open_orders=[sl, tp, dis])  # no saved state at all
    strategy._readopt_open_position()

    state = strategy.trailing_stop_state[KEY]
    assert state["sl_order_id"] == "X-1" and state["current_sl_price"] == 992.0  # nearest stop = SL
    assert state["tp_order_id"] == "X-3" and state["tp_price"] == 1025.0
    assert strategy.disaster_stop_state[KEY]["order_id"] == "X-2"  # farthest stop = disaster
    strategy.order_factory.stop_market.assert_not_called()
    strategy._submit_disaster_stop.assert_not_called()


def test_readopt_rearms_when_only_tp_survived():
    tp = SimpleNamespace(client_order_id="TP-9", is_open=True, is_reduce_only=True,
                         order_type=OrderType.MARKET_IF_TOUCHED, trigger_price=1030.0)
    saved = {"trailing_stop_state": _open_long_state(sl_id="SL-9", tp_id="TP-9"),
             "partial_tp_state": {}, "disaster_stop_state": {}}
    strategy = _readopt_stub(open_orders=[tp], saved=saved)
    strategy._readopt_open_position()

    strategy.cancel_order.assert_called_once_with(tp)  # lone survivor cancelled, both re-armed
    assert strategy.order_factory.stop_market.call_args.kwargs["trigger_price"] == 990.0  # saved SL price kept
    assert strategy.order_factory.market_if_touched.call_args.kwargs["trigger_price"] == 1030.0
    strategy._submit_disaster_stop.assert_called_once()


def test_readopt_closes_position_breached_while_offline():
    saved = {"trailing_stop_state": _open_long_state(), "partial_tp_state": {}, "disaster_stop_state": {}}
    strategy = _readopt_stub(open_orders=[], saved=saved, mark=985.0)  # below saved SL 990
    strategy._readopt_open_position()

    strategy._submit_order.assert_called_once_with(side=OrderSide.SELL, quantity=0.05, reduce_only=True)
    strategy.order_factory.stop_market.assert_not_called()
    assert strategy.log.contains("breached while offline")


def test_readopt_flat_clears_stale_state_and_cleans_orphans():
    cache = SimpleNamespace(order=lambda cid: None, bars=lambda bt: [], positions_open=lambda **kw: [],
                            orders_open=lambda **kw: [])
    strategy = _stub(cache=cache, _load_position_state=Mock(return_value={"trailing_stop_state": _open_long_state()}),
                     _cleanup_oco_orphans=Mock())
    strategy._readopt_open_position()
    strategy._clear_position_state.assert_called_once()
    strategy._cleanup_oco_orphans.assert_called_once()


# ------------------------------------------------------------ worker hand-off

def test_run_analysis_and_completion_execute_trade_and_reset_inflight():
    strategy = _stub(_execute_trade=Mock(), _analysis_inflight=True,
                     llm=SimpleNamespace(signal_history=[], provider="anthropic", model="m",
                                         analyze=Mock(return_value={"signal": "BUY", "confidence": "HIGH",
                                                                    "reason": "r", "stop_loss": 1, "take_profit": 2})))
    ctx = {"price_data": {"price": 1000.0, "timestamp": "t"}, "technical_data": {"rsi": 50},
           "current_position": None, "forced_signal": None, "regime_needed": False}
    result = strategy._run_analysis(ctx)
    assert result["error"] is None and result["signal"]["signal"] == "BUY"

    strategy._on_analysis_complete(ctx, result)
    assert strategy._analysis_inflight is False
    strategy._execute_trade.assert_called_once()
    assert strategy.last_signal["signal"] == "BUY"


def test_completion_skips_execution_when_position_changed_during_analysis():
    strategy = _stub(_execute_trade=Mock(), _analysis_inflight=True,
                     _get_current_position_data=lambda: None)  # flat NOW
    ctx = {"price_data": {"price": 1000.0, "timestamp": "t"}, "technical_data": {},
           "current_position": {"side": "short", "quantity": 0.06}}  # was SHORT when analysis started
    strategy._on_analysis_complete(ctx, {"error": None, "elapsed": 1.0,
                                         "signal": {"signal": "SELL", "confidence": "MEDIUM", "reason": "r"}})
    strategy._execute_trade.assert_not_called()
    assert strategy.log.contains("Position changed during analysis")
    assert strategy._analysis_inflight is False


def test_completion_executes_with_fresh_position_when_unchanged():
    fresh = {"side": "long", "quantity": 0.05, "avg_px": 1000.0, "unrealized_pnl": 1.0}
    strategy = _stub(_execute_trade=Mock(), _get_current_position_data=lambda: fresh)
    ctx = {"price_data": {"price": 1000.0, "timestamp": "t"}, "technical_data": {},
           "current_position": {"side": "long", "quantity": 0.05}}
    strategy._on_analysis_complete(ctx, {"error": None, "elapsed": 1.0,
                                         "signal": {"signal": "HOLD", "confidence": "LOW", "reason": "r"}})
    strategy._execute_trade.assert_called_once()
    assert strategy._execute_trade.call_args.args[3] is fresh


def test_atr_trailing_uses_atr_step_threshold():
    old_sl = SimpleNamespace(is_open=True, client_order_id="SL-1")
    cache = SimpleNamespace(order=lambda cid: old_sl, bars=lambda bt: [], positions_open=lambda **kw: [],
                            orders_open=lambda **kw: [])
    state = _open_long_state()
    state[KEY].update({"current_sl_price": 1019.0, "highest_price": 1030.0})
    strategy = _stub(enable_trailing_stop=True, trailing_use_atr=True, cache=cache, trailing_stop_state=state)

    strategy._update_trailing_stops(1031.0)  # new SL would be 1021 = +2 < 0.25*ATR(10) -> no move
    strategy.order_factory.stop_market.assert_not_called()

    strategy._update_trailing_stops(1033.0)  # new SL 1023 = +4 >= 2.5 -> replace
    assert strategy.order_factory.stop_market.call_args.kwargs["trigger_price"] == 1023.0


def test_completion_with_error_does_not_trade():
    strategy = _stub(_execute_trade=Mock(), _analysis_inflight=True)
    ctx = {"price_data": {"price": 1000.0}, "technical_data": {}, "current_position": None}
    strategy._on_analysis_complete(ctx, {"error": RuntimeError("boom"), "signal": None})
    strategy._execute_trade.assert_not_called()
    assert strategy._analysis_inflight is False
    assert strategy.log.contains("LLM analysis failed")


def test_regime_from_worker_is_cached_on_completion():
    strategy = _stub(_execute_trade=Mock())
    ctx = {"price_data": {"price": 1000.0}, "technical_data": {}, "current_position": None}
    strategy._on_analysis_complete(ctx, {"error": None, "regime": "up", "elapsed": 1.0,
                                         "signal": {"signal": "HOLD", "confidence": "LOW", "reason": "r"}})
    assert strategy._regime_cache["value"] == "up"
    assert strategy._regime_cache_stale() is False


if __name__ == "__main__":
    failures = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print(f"✅ {name}")
            except AssertionError as e:
                failures += 1; print(f"❌ {name}: {e}")
    sys.exit(1 if failures else 0)
