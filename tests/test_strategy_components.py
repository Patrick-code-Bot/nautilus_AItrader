"""
Unit tests for strategy components: position sizing, SL/TP, risk guards and
the LLM response contract. No network access, no NautilusTrader node.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from helpers import make_strategy_stub  # noqa: E402


PRICE = 90_000.0


def _sizing_stub(**overrides):
    defaults = dict(
        _get_account_equity=lambda: 10_000.0,
        _get_live_equity=lambda: 10_000.0,
        latest_technical_data={"support": PRICE * 0.99, "resistance": PRICE * 1.01, "atr": 0.0},
        latest_price_data={"price": PRICE},
    )
    defaults.update(overrides)
    return make_strategy_stub(**defaults)


def _size(strategy, confidence="MEDIUM", signal="BUY", trend="震荡整理", rsi=50.0):
    return strategy._calculate_position_size(
        signal_data={"signal": signal, "confidence": confidence},
        price_data={"price": PRICE},
        technical_data={"overall_trend": trend, "rsi": rsi, "support": PRICE * 0.99,
                        "resistance": PRICE * 1.01},
        current_position=None,
    )


def test_position_size_is_risk_based():
    """quantity = (equity * risk%) / (sl_distance% * price), floored to 0.001."""
    strategy = _sizing_stub()
    qty = _size(strategy)

    # SL = support * (1 - 0.001) -> distance ≈ 1.099%; risk = 1% of 10,000 = $100
    sl_price = PRICE * 0.99 * (1 - 0.001)
    sl_dist = (PRICE - sl_price) / PRICE
    expected = int((100.0 / (sl_dist * PRICE)) * 1000) / 1000
    assert qty == expected, f"{qty} != {expected}"
    assert qty * PRICE >= 100.0


def test_position_size_scales_with_confidence():
    strategy = _sizing_stub(_get_account_equity=lambda: 50_000.0)
    sizes = {c: _size(strategy, confidence=c) for c in ("LOW", "MEDIUM", "HIGH")}
    assert sizes["LOW"] < sizes["MEDIUM"] < sizes["HIGH"], sizes


def test_position_size_respects_leverage_cap():
    strategy = _sizing_stub(_get_account_equity=lambda: 1_000.0, max_position_leverage=2.0,
                            risk_per_trade_pct=0.50)  # absurd risk -> cap must bite
    qty = _size(strategy)
    assert qty * PRICE <= 2.0 * 1_000.0 + 1e-6


def test_position_size_skips_below_min_notional_instead_of_upsizing():
    # $100 equity * 1% risk = $1 of risk over a ~1.1% stop -> 0.001 BTC = $90 notional (< $100)
    strategy = _sizing_stub(_get_account_equity=lambda: 100.0)
    qty = _size(strategy)
    assert qty == 0.0
    assert strategy.log.contains("Trade skipped")

    # Just above the threshold the trade goes through (never inflated to meet the minimum)
    strategy = _sizing_stub(_get_account_equity=lambda: 400.0)
    qty = _size(strategy)
    assert qty > 0 and qty * PRICE >= 100.0


def test_rsi_extreme_reduces_risk():
    strategy = _sizing_stub(_get_account_equity=lambda: 50_000.0)
    normal = _size(strategy, rsi=50.0)
    extreme = _size(strategy, rsi=80.0)
    assert extreme < normal


def test_stop_loss_uses_support_resistance_then_default():
    strategy = make_strategy_stub(
        latest_technical_data={"support": 950.0, "resistance": 1050.0, "atr": 0.0},
    )
    assert strategy._calculate_stop_loss_price("long", 1000.0) == 950.0 * (1 - 0.001)
    assert strategy._calculate_stop_loss_price("short", 1000.0) == 1050.0 * (1 + 0.001)

    strategy.latest_technical_data = {"support": 0.0, "resistance": 0.0, "atr": 0.0}
    assert strategy._calculate_stop_loss_price("long", 1000.0) == 980.0
    assert strategy._calculate_stop_loss_price("short", 1000.0) == 1020.0


def test_atr_exits_have_two_to_one_reward_risk():
    strategy = make_strategy_stub(
        use_atr_exits=True,
        latest_technical_data={"support": 950.0, "resistance": 1050.0, "atr": 20.0},
    )
    sl = strategy._calculate_stop_loss_price("long", 1000.0)
    tp = strategy._calculate_take_profit_price("long", 1000.0, "LOW")
    assert sl == 970.0 and tp == 1060.0
    assert (tp - 1000.0) / (1000.0 - sl) == 2.0


def test_take_profit_scales_with_confidence_without_atr():
    strategy = make_strategy_stub(
        latest_technical_data={"support": 950.0, "resistance": 1050.0, "atr": 0.0},
    )
    tps = [strategy._calculate_take_profit_price("long", 1000.0, c) for c in ("LOW", "MEDIUM", "HIGH")]
    assert tps == [1010.0, 1020.0, 1030.0]


# ----------------------------------------------------------------- risk guards

class _Clock:
    def __init__(self, ts):
        self._ts = ts

    def utc_now(self):
        import pandas as pd
        return pd.Timestamp(self._ts, tz="UTC")


def _guard_stub(**overrides):
    defaults = dict(clock=_Clock("2026-10-20 10:00:00"))
    defaults.update(overrides)
    return make_strategy_stub(**defaults)


def test_daily_loss_guard_triggers_pause_on_live_drawdown():
    strategy = _guard_stub(
        _get_live_equity=lambda: 9_600.0,
        risk_state={"consecutive_losses": 0, "paused_until": None,
                    "day_date": "2026-10-20", "day_start_equity": 10_000.0},
    )
    assert strategy._check_risk_guards() is False
    assert strategy.risk_state["paused_until"] is not None
    assert strategy.log.contains("Daily loss limit hit")


def test_daily_loss_guard_ignores_unavailable_live_balance():
    """
    Regression: a transient balance-read failure used to fall back to the
    static configured equity and could trigger a false 24h pause.
    """
    strategy = _guard_stub(
        equity=400.0,  # configured equity far below the live baseline
        _get_live_equity=lambda: None,
        risk_state={"consecutive_losses": 0, "paused_until": None,
                    "day_date": "2026-10-20", "day_start_equity": 10_000.0},
    )
    assert strategy._check_risk_guards() is True
    assert strategy.risk_state["paused_until"] is None


def test_day_rollover_resets_baseline_with_live_equity_only():
    strategy = _guard_stub(_get_live_equity=lambda: None,
                           risk_state={"consecutive_losses": 0, "paused_until": None,
                                       "day_date": "2026-10-19", "day_start_equity": 9_000.0})
    assert strategy._check_risk_guards() is True
    assert strategy.risk_state["day_date"] == "2026-10-20"
    assert strategy.risk_state["day_start_equity"] is None  # never seeded with static equity

    strategy._get_live_equity = lambda: 10_500.0
    assert strategy._check_risk_guards() is True
    assert strategy.risk_state["day_start_equity"] == 10_500.0


def test_active_pause_blocks_and_expired_pause_resets_streak():
    strategy = _guard_stub(
        _get_live_equity=lambda: 10_000.0,
        risk_state={"consecutive_losses": 5, "paused_until": "2026-10-20T12:00:00+00:00",
                    "day_date": "2026-10-20", "day_start_equity": 10_000.0},
    )
    assert strategy._check_risk_guards() is False

    strategy.risk_state["paused_until"] = "2026-10-20T09:00:00"  # legacy naive timestamp, expired
    assert strategy._check_risk_guards() is True
    assert strategy.risk_state["paused_until"] is None
    assert strategy.risk_state["consecutive_losses"] == 0


def test_circuit_breaker_halts_on_total_drawdown_and_requires_manual_reset():
    strategy = _guard_stub(_get_live_equity=lambda: 1000.0,
                           risk_state={"consecutive_losses": 0, "paused_until": None, "day_date": "2026-10-20",
                                       "day_start_equity": 1000.0, "equity_peak": None, "halted_reason": None})
    assert strategy._check_risk_guards() is True
    assert strategy.risk_state["equity_peak"] == 1000.0

    strategy._get_live_equity = lambda: 1100.0  # new high-water mark
    strategy.risk_state["day_start_equity"] = 1100.0
    assert strategy._check_risk_guards() is True and strategy.risk_state["equity_peak"] == 1100.0

    strategy._get_live_equity = lambda: 985.0  # -10.5% from peak -> halt (daily -10.5% would also pause, but halt wins)
    strategy.risk_state["day_start_equity"] = 985.0
    assert strategy._check_risk_guards() is False
    assert "below peak" in strategy.risk_state["halted_reason"]
    assert strategy.log.contains("CIRCUIT BREAKER")

    strategy._get_live_equity = lambda: 1200.0  # recovery does NOT un-halt
    strategy.risk_state["day_start_equity"] = 1200.0
    assert strategy._check_risk_guards() is False

    strategy.risk_state.update({"halted_reason": None, "paused_until": None})  # manual reset
    assert strategy._check_risk_guards() is True


def test_live_gate_requires_explicit_ack(monkeypatch):
    import main_live
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.delenv("LIVE_TRADING_ACK", raising=False)
    try:
        main_live.get_strategy_config("live")
        assert False, "live without ack must be refused"
    except ValueError as e:
        assert "LIVE_TRADING_ACK" in str(e)
    monkeypatch.setenv("LIVE_TRADING_ACK", "true")
    assert main_live.get_strategy_config("live").max_total_drawdown_pct == 0.10
    monkeypatch.delenv("LIVE_TRADING_ACK")
    main_live.get_strategy_config("testnet")  # paper venues need no ack


def test_anti_churn_ignores_hold_runs_but_blocks_actionable_runs():
    strategy = _guard_stub(_get_live_equity=lambda: 10_000.0,
                           risk_state={"consecutive_losses": 0, "paused_until": None,
                                       "day_date": "2026-10-20", "day_start_equity": 10_000.0})
    strategy.llm.signal_history = [{"signal": "HOLD"}] * 8
    assert strategy._check_risk_guards() is True  # HOLD never trades -> never "churn"

    strategy.llm.signal_history = [{"signal": "BUY"}] * 6
    assert strategy._check_risk_guards() is False
    assert strategy.log.contains("blocking churn")

    strategy.log.messages.clear()
    strategy.llm.signal_history = [{"signal": "BUY"}] * 5
    assert strategy._check_risk_guards() is True


# ------------------------------------------------------ position management

def test_reversal_closes_only_and_never_reopens():
    strategy = make_strategy_stub(allow_reversals=True, require_high_conf_reversal=False,
                                  _submit_order=Mock())
    from nautilus_trader.model.enums import OrderSide

    strategy._manage_existing_position(
        {"side": "long", "quantity": 0.02}, target_side="short", target_quantity=0.03,
        confidence="MEDIUM",
    )
    strategy._submit_order.assert_called_once_with(side=OrderSide.SELL, quantity=0.02, reduce_only=True)


def test_pyramiding_is_blocked():
    strategy = make_strategy_stub(_submit_order=Mock())
    strategy._manage_existing_position(
        {"side": "long", "quantity": 0.02}, target_side="long", target_quantity=0.05,
        confidence="HIGH",
    )
    strategy._submit_order.assert_not_called()
    assert strategy.log.contains("pyramiding disabled")


if __name__ == "__main__":
    failures = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"✅ {name}")
            except AssertionError as e:
                failures += 1
                print(f"❌ {name}: {e}")
    sys.exit(1 if failures else 0)


# ------------------------------------------------------------ binance env

def test_binance_environment_resolution(monkeypatch):
    import main_live
    for raw, expected in [("live", "live"), ("TESTNET", "testnet"), ("demo", "demo"),
                          ("paper", "demo"), ("prod", "live"), ("testnet   # paper", "testnet")]:
        monkeypatch.setenv("BINANCE_ENV", raw)
        assert main_live.resolve_binance_environment() == expected, raw
    monkeypatch.delenv("BINANCE_ENV", raising=False)
    assert main_live.resolve_binance_environment() == "live"
    monkeypatch.setenv("BINANCE_ENV", "staging")
    try:
        main_live.resolve_binance_environment()
        assert False, "invalid env must raise"
    except ValueError:
        pass


def test_binance_configs_carry_environment_and_rest_url(monkeypatch):
    import main_live
    from nautilus_trader.adapters.binance.common.enums import BinanceEnvironment
    monkeypatch.setenv("BINANCE_API_KEY", "k")
    monkeypatch.setenv("BINANCE_API_SECRET", "s")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("LIVE_TRADING_ACK", "true")  # the live config below needs the gate
    monkeypatch.setattr(main_live, "query_binance_symbol_settings", lambda *a, **k: None)
    data_cfg, exec_cfg = main_live.get_binance_config("testnet")
    assert data_cfg.environment == BinanceEnvironment.TESTNET
    assert exec_cfg.environment == BinanceEnvironment.TESTNET
    cfg = main_live.get_strategy_config("testnet")
    assert cfg.binance_rest_base_url == "https://testnet.binancefuture.com"
    assert cfg.external_order_claims == ["BTCUSDT-PERP.BINANCE"]
    assert main_live.get_strategy_config("live").binance_rest_base_url == "https://fapi.binance.com"


def test_force_signal_refused_on_live_and_allowed_on_paper(monkeypatch):
    import main_live
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("FORCE_SIGNAL", "BUY")
    try:
        main_live.get_strategy_config("live")
        assert False, "FORCE_SIGNAL must be refused on the live venue"
    except ValueError as e:
        assert "testnet" in str(e)
    cfg = main_live.get_strategy_config("testnet")
    assert cfg.force_signal == "BUY" and cfg.force_signal_cycles == 1
    monkeypatch.setenv("FORCE_SIGNAL", "HOLD")
    try:
        main_live.get_strategy_config("testnet")
        assert False
    except ValueError:
        pass


def test_forced_signal_is_well_formed():
    strategy = make_strategy_stub(force_signal="SELL", clock=_Clock("2026-10-20 10:00:00"))
    sig = strategy._build_forced_signal({"price": 1000.0})
    assert sig["signal"] == "SELL" and sig["confidence"] == "HIGH" and sig["forced"] is True
    assert sig["take_profit"] < 1000.0 < sig["stop_loss"]


def test_binance_exec_config_pins_leverage_and_margin(monkeypatch):
    import main_live
    from nautilus_trader.adapters.binance.common.symbol import BinanceSymbol
    from nautilus_trader.adapters.binance.futures.enums import BinanceFuturesMarginType
    sym = BinanceSymbol("BTCUSDT")
    monkeypatch.setenv("BINANCE_API_KEY", "k"); monkeypatch.setenv("BINANCE_API_SECRET", "s")
    monkeypatch.setenv("BINANCE_LEVERAGE", "7"); monkeypatch.setenv("BINANCE_MARGIN_TYPE", "isolated")

    # Account currently 20x cross and flat -> both get set
    monkeypatch.setattr(main_live, "query_binance_symbol_settings",
                        lambda *a, **k: {"leverage": 20, "margin_type": "cross", "position_amt": 0.0})
    _, exec_cfg = main_live.get_binance_config("testnet")
    assert exec_cfg.futures_leverages == {sym: 7}
    assert exec_cfg.futures_margin_types == {sym: BinanceFuturesMarginType.ISOLATED}

    # Already as requested -> nothing sent (idempotent restart)
    monkeypatch.setattr(main_live, "query_binance_symbol_settings",
                        lambda *a, **k: {"leverage": 7, "margin_type": "isolated", "position_amt": 0.118})
    _, exec_cfg = main_live.get_binance_config("testnet")
    assert exec_cfg.futures_leverages is None and exec_cfg.futures_margin_types is None

    # Margin differs but a position is open -> leverage set, margin left alone (Binance -4048)
    monkeypatch.setattr(main_live, "query_binance_symbol_settings",
                        lambda *a, **k: {"leverage": 20, "margin_type": "cross", "position_amt": 0.118})
    _, exec_cfg = main_live.get_binance_config("testnet")
    assert exec_cfg.futures_leverages == {sym: 7} and exec_cfg.futures_margin_types is None

    # Query failed -> touch nothing
    monkeypatch.setattr(main_live, "query_binance_symbol_settings", lambda *a, **k: None)
    _, exec_cfg = main_live.get_binance_config("testnet")
    assert exec_cfg.futures_leverages is None and exec_cfg.futures_margin_types is None

    # LEVERAGE fallback with inline comment, cross margin
    monkeypatch.delenv("BINANCE_LEVERAGE"); monkeypatch.setenv("LEVERAGE", "10 # comment")
    monkeypatch.setenv("BINANCE_MARGIN_TYPE", "cross")
    monkeypatch.setattr(main_live, "query_binance_symbol_settings",
                        lambda *a, **k: {"leverage": 5, "margin_type": "isolated", "position_amt": 0.0})
    _, exec_cfg = main_live.get_binance_config("live")
    assert exec_cfg.futures_leverages == {sym: 10}
    assert exec_cfg.futures_margin_types == {sym: BinanceFuturesMarginType.CROSS}


def test_persisted_state_from_another_venue_is_discarded(tmp_path):
    import json
    rs = tmp_path / "risk_state.json"
    rs.write_text(json.dumps({"consecutive_losses": 4, "paused_until": None, "day_date": "2026-10-23",
                              "day_start_equity": 4955.0, "equity_peak": 4955.0, "halted_reason": None,
                              "venue": "https://testnet.binancefuture.com"}))
    strategy = make_strategy_stub(risk_state_file=str(rs), binance_rest_base_url="https://fapi.binance.com")
    from strategy.deepseek_strategy import DeepSeekAIStrategy
    strategy._save_risk_state = DeepSeekAIStrategy._save_risk_state.__get__(strategy)  # real writer for this test
    strategy._load_risk_state()
    assert strategy.risk_state["equity_peak"] is None and strategy.risk_state["consecutive_losses"] == 0
    assert strategy.log.contains("another venue")
    assert json.loads(rs.read_text())["venue"] == "https://fapi.binance.com"  # rewritten for the live venue

    # same venue -> loaded
    rs.write_text(json.dumps({"consecutive_losses": 2, "paused_until": None, "day_date": "2026-10-23",
                              "day_start_equity": 500.0, "equity_peak": 520.0, "halted_reason": None,
                              "venue": "https://fapi.binance.com"}))
    strategy._load_risk_state()
    assert strategy.risk_state["equity_peak"] == 520.0 and strategy.risk_state["consecutive_losses"] == 2

    ps = tmp_path / "position_state.json"
    ps.write_text(json.dumps({"venue": "https://testnet.binancefuture.com", "trailing_stop_state": {"x": 1}}))
    strategy.position_state_file = str(ps)
    strategy._load_position_state = DeepSeekAIStrategy._load_position_state.__get__(strategy)
    assert strategy._load_position_state() is None
