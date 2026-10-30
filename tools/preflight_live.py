#!/usr/bin/env python3
"""
Live-trading preflight: a go/no-go checklist run BEFORE starting the bot on a
real Binance Futures account.

    python tools/preflight_live.py            # checks the .env in the repo root
    python tools/preflight_live.py --strict   # warnings also fail

Exit code 0 = all hard checks passed. Nothing here places orders or changes
account settings; it only reads.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import stat
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import requests  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

RESULTS: list[tuple[str, str, str]] = []  # (status, check, detail)  status: PASS | WARN | FAIL


def env(key: str, default: str = "") -> str:
    return (os.getenv(key) or default).split("#")[0].strip()


def env_bool(key: str, default: bool = False) -> bool:
    raw = env(key)
    return default if raw == "" else raw.lower() in ("1", "true", "yes", "on")


def record(status: str, check: str, detail: str = "") -> None:
    RESULTS.append((status, check, detail))


def signed_get(base: str, path: str, key: str, secret: str, **params):
    params.update(timestamp=int(time.time() * 1000), recvWindow=10000)
    query = "&".join(f"{k}={v}" for k, v in params.items())
    sig = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    r = requests.get(f"{base}{path}?{query}&signature={sig}", headers={"X-MBX-APIKEY": key}, timeout=15)
    try:
        return r.status_code, r.json()
    except Exception:  # noqa: BLE001
        return r.status_code, r.text[:200]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true", help="treat warnings as failures")
    args = ap.parse_args()

    # ------------------------------------------------------------- config sanity
    binance_env = env("BINANCE_ENV", "live").lower()
    is_live = binance_env == "live"
    if is_live:
        record("PASS", "BINANCE_ENV", "live - REAL MONEY")
    elif binance_env in ("testnet", "demo"):
        record("WARN", "BINANCE_ENV", f"{binance_env} - paper venue, not real trading (set BINANCE_ENV=live + live keys to go live)")
    else:
        record("FAIL", "BINANCE_ENV", f"{binance_env!r} is not live|testnet|demo")

    if not is_live:
        record("PASS", "LIVE_TRADING_ACK", "not required on a paper venue")
    elif env_bool("LIVE_TRADING_ACK"):
        record("PASS", "LIVE_TRADING_ACK", "true")
    else:
        record("FAIL", "LIVE_TRADING_ACK", "must be true to start on a live account (set it only after this preflight passes)")

    for flag in ("TEST_MODE", "DRY_RUN", "SIGNAL_ONLY_MODE"):
        if env_bool(flag):
            record("FAIL", flag, "true -> the bot would NOT place orders; set false for live")
        else:
            record("PASS", flag, "false")
    if env("FORCE_SIGNAL"):
        record("FAIL", "FORCE_SIGNAL", "must be unset (main_live refuses it on live anyway)")
    else:
        record("PASS", "FORCE_SIGNAL", "unset")

    min_conf = env("MIN_CONFIDENCE_TO_TRADE", "MEDIUM").upper()
    record("PASS" if min_conf in ("MEDIUM", "HIGH") else "WARN", "MIN_CONFIDENCE_TO_TRADE",
           f"{min_conf} (replay 2026-10-15..22: Opus 5.5 never issued HIGH -> HIGH means ~no trades)")

    risk = float(env("RISK_PER_TRADE_PCT", "0.01") or 0.01)
    record("PASS" if risk <= 0.01 else "WARN", "RISK_PER_TRADE_PCT", f"{risk:.2%} per trade" + (" (>1% is aggressive)" if risk > 0.01 else ""))
    lev_cap = float(env("MAX_POSITION_LEVERAGE", "2.0") or 2.0)
    record("PASS" if lev_cap <= 2.0 else "WARN", "MAX_POSITION_LEVERAGE", f"notional cap {lev_cap:.1f}x equity")
    ex_lev = int(float(env("BINANCE_LEVERAGE", env("LEVERAGE", "5")) or 5))
    record("PASS" if ex_lev <= 10 else "WARN", "BINANCE_LEVERAGE", f"{ex_lev}x exchange leverage" + (" (>10x: liquidation margin thin)" if ex_lev > 10 else ""))
    record("PASS" if env("BINANCE_MARGIN_TYPE", "isolated").lower().startswith("iso") else "WARN", "BINANCE_MARGIN_TYPE",
           env("BINANCE_MARGIN_TYPE", "isolated") + ("" if env("BINANCE_MARGIN_TYPE", "isolated").lower().startswith("iso") else " (isolated recommended: losses capped at position margin)"))
    dd = float(env("MAX_TOTAL_DRAWDOWN_PCT", "0.10") or 0.10)
    record("PASS" if 0 < dd <= 0.25 else "WARN", "MAX_TOTAL_DRAWDOWN_PCT", f"circuit breaker at {dd:.0%} drawdown from equity peak")
    record("PASS" if env_bool("NATIVE_EXITS", True) else "FAIL", "NATIVE_EXITS", "exchange-side SL/TP" if env_bool("NATIVE_EXITS", True) else "false -> emulated exits die with the process; use true for live")
    record("PASS" if env_bool("LLM_ASYNC", True) else "WARN", "LLM_ASYNC", "worker thread" if env_bool("LLM_ASYNC", True) else "false -> LLM call blocks the event loop")

    # ------------------------------------------------------------- files / env
    env_path = ROOT / ".env"
    if env_path.exists():
        mode = stat.S_IMODE(env_path.stat().st_mode)
        record("PASS" if mode & 0o077 == 0 else "WARN", ".env permissions", f"{oct(mode)}" + ("" if mode & 0o077 == 0 else " -> chmod 600 .env"))
    elif env("BINANCE_API_KEY"):
        record("PASS", ".env", "not used - configuration injected via environment variables (container)")
    else:
        record("FAIL", ".env", "missing and no environment variables set")
    hb = ROOT / env("HEARTBEAT_FILE", "logs/heartbeat")
    record("PASS", "heartbeat file", f"{hb} (healthcheck: tools/healthcheck.py)")
    for f in ("logs/position_state.json",):
        record("WARN" if (ROOT / f).exists() else "PASS", f, "exists - stale state from a previous run will be reconciled on start" if (ROOT / f).exists() else "clean")
    rs = ROOT / "logs" / "risk_state.json"
    if rs.exists():
        try:
            data = json.loads(rs.read_text())
            if data.get("halted_reason"):
                record("FAIL", "risk_state", f"circuit breaker halted: {data['halted_reason']} (RESET_RISK_STATE=true to clear)")
            elif data.get("paused_until"):
                record("WARN", "risk_state", f"paused_until {data['paused_until']}")
            else:
                record("PASS", "risk_state", f"consecutive_losses={data.get('consecutive_losses')} peak={data.get('equity_peak')}")
        except Exception as e:  # noqa: BLE001
            record("WARN", "risk_state", f"unreadable: {e}")
    else:
        record("PASS", "risk_state", "none (fresh)")

    record("PASS" if sys.version_info >= (3, 12) else "FAIL", "python", sys.version.split()[0] + ("" if sys.version_info >= (3, 12) else " (nautilus_trader needs >= 3.12)"))
    try:
        import nautilus_trader  # noqa: F401
        import anthropic  # noqa: F401
        record("PASS", "dependencies", f"nautilus_trader {nautilus_trader.__version__}, anthropic {anthropic.__version__}")
    except Exception as e:  # noqa: BLE001
        record("FAIL", "dependencies", str(e))

    # ------------------------------------------------------------- Binance (read-only)
    key, secret = env("BINANCE_API_KEY"), env("BINANCE_API_SECRET")
    base = {"live": "https://fapi.binance.com", "testnet": "https://testnet.binancefuture.com", "demo": "https://demo-fapi.binance.com"}.get(binance_env, "https://fapi.binance.com")
    if not key or not secret:
        record("FAIL", "binance keys", "BINANCE_API_KEY / BINANCE_API_SECRET missing")
    else:
        try:
            srv = requests.get(f"{base}/fapi/v1/time", timeout=10).json()["serverTime"]
            drift = abs(int(time.time() * 1000) - srv)
            record("PASS" if drift < 1000 else "FAIL", "clock drift", f"{drift} ms vs Binance" + ("" if drift < 1000 else " -> enable NTP; signed requests fail beyond recvWindow"))
        except Exception as e:  # noqa: BLE001
            record("FAIL", "binance reachability", f"{base}: {e}")

        sc, bal = signed_get(base, "/fapi/v2/balance", key, secret)
        if sc == 200 and isinstance(bal, list):
            usdt = next((float(b["balance"]) for b in bal if b["asset"] == "USDT"), 0.0)
            avail = next((float(b["availableBalance"]) for b in bal if b["asset"] == "USDT"), 0.0)
            record("PASS", "binance auth", f"futures account reachable on {binance_env}")
            # 2x-equity notional cap must clear Binance's $100 minimum -> equity >= $50; realistic floor higher
            if usdt < 100:
                record("FAIL", "USDT balance", f"{usdt:.2f} (available {avail:.2f}) - below $100: most trades skipped by min-notional rule")
            elif usdt < 300:
                record("WARN", "USDT balance", f"{usdt:.2f} (available {avail:.2f}) - thin; one-tick slippage matters at this size")
            else:
                record("PASS", "USDT balance", f"{usdt:.2f} (available {avail:.2f})")
        else:
            record("FAIL", "binance auth", f"{sc} {bal} - wrong venue for these keys, IP not whitelisted, or futures not enabled")

        sc, pos = signed_get(base, "/fapi/v2/positionRisk", key, secret, symbol="BTCUSDT")
        if sc == 200 and isinstance(pos, list):
            p = next((p for p in pos if p["symbol"] == "BTCUSDT"), {})
            amt = float(p.get("positionAmt", 0) or 0)
            record("PASS" if amt == 0 else "WARN", "open position", "flat" if amt == 0 else f"{amt} BTC @ {p.get('entryPrice')} - will be re-adopted and protected on start")
            record("PASS", "symbol settings", f"leverage {p.get('leverage')}x, margin {p.get('marginType')}")
        sc, algos = signed_get(base, "/fapi/v1/openAlgoOrders", key, secret, symbol="BTCUSDT")
        if sc == 200 and isinstance(algos, list):
            record("PASS" if not algos else "WARN", "open algo orders", f"{len(algos)}" + ("" if not algos else " - orphan sweep / re-adoption will reconcile them"))
        sc, oo = signed_get(base, "/fapi/v1/openOrders", key, secret, symbol="BTCUSDT")
        if sc == 200 and isinstance(oo, list):
            record("PASS" if not oo else "WARN", "open orders", str(len(oo)))

        if binance_env == "live":
            sc, restr = signed_get("https://api.binance.com", "/sapi/v1/account/apiRestrictions", key, secret)
            if sc == 200 and isinstance(restr, dict) and "enableFutures" in restr:
                record("PASS" if restr.get("enableFutures") else "FAIL", "key: futures enabled", str(restr.get("enableFutures")))
                record("PASS" if not restr.get("enableWithdrawals") else "FAIL", "key: withdrawals", "disabled" if not restr.get("enableWithdrawals") else "ENABLED - create a key without withdrawal permission")
                record("PASS" if restr.get("ipRestrict") else "WARN", "key: IP restriction", "restricted" if restr.get("ipRestrict") else "unrestricted - whitelist the server IP (Binance also expires unrestricted keys after 90 days)")
                record("PASS" if not restr.get("enableSpotAndMarginTrading") else "WARN", "key: spot/margin", "disabled" if not restr.get("enableSpotAndMarginTrading") else "enabled (not needed by the bot)")
            else:
                record("WARN", "key restrictions", f"could not read apiRestrictions: {sc} {restr}")

    # ------------------------------------------------------------- LLM provider (the one actually configured)
    try:
        import main_live
        cfg = main_live.resolve_llm_settings(main_live.load_yaml_config().get("strategy", {}))
        record("PASS", "LLM config", f"{cfg['provider']} / {cfg['model'] or '(default)'} "
               + (f"effort={cfg['effort']}" if cfg["provider"] == "anthropic" else f"temperature={cfg['temperature']} base_url={cfg['base_url'] or 'https://api.deepseek.com'}")
               + f" timeout={cfg['timeout_sec']}s")
        if cfg["provider"] == "anthropic":
            import anthropic
            kw = {"api_key": cfg["api_key"], "timeout": 20}
            if cfg.get("workspace_id"):
                kw["default_headers"] = {"anthropic-workspace-id": cfg["workspace_id"]}
            try:
                ids = [m.id for m in anthropic.Anthropic(**kw).models.list().data]
                model = cfg["model"] or "claude-sonnet-5-5"
                record("PASS" if model in ids else "FAIL", "Anthropic API",
                       f"models visible: {len(ids)}; {model} {'available' if model in ids else 'NOT available'}")
            except Exception as e:  # noqa: BLE001
                msg = str(e)
                if "Request not allowed" in msg or "forbidden" in msg.lower():
                    record("FAIL", "Anthropic API",
                           "403 'Request not allowed' - this server's region is not supported by Anthropic "
                           "(anthropic.com/supported-countries). Use LLM_PROVIDER=openai with a provider that serves "
                           "this region, or host where the service is offered. Do NOT proxy/VPN - it violates the usage policy.")
                else:
                    record("FAIL", "Anthropic API", msg[:160])
        else:
            # OpenAI-compatible provider (DeepSeek, Kimi/Moonshot, ...): list models with the configured key
            base = (cfg["base_url"] or "https://api.deepseek.com").rstrip("/")
            model = cfg["model"] or "deepseek-v4-pro"
            try:
                r = requests.get(f"{base}/models", headers={"Authorization": f"Bearer {cfg['api_key']}"}, timeout=20)
                if r.status_code == 200:
                    ids = [m.get("id") for m in r.json().get("data", [])]
                    record("PASS" if (not ids or model in ids) else "WARN", f"{cfg['provider']} API ({base})",
                           f"reachable, auth OK; models: {len(ids)}; {model} {'listed' if model in ids else 'not in list (provider may still accept it)'}")
                elif r.status_code in (401, 403):
                    record("FAIL", f"{cfg['provider']} API ({base})", f"HTTP {r.status_code}: key rejected ({r.text[:100]})")
                else:
                    record("WARN", f"{cfg['provider']} API ({base})", f"HTTP {r.status_code}: {r.text[:100]}")
            except Exception as e:  # noqa: BLE001
                record("FAIL", f"{cfg['provider']} API ({base})", f"unreachable: {str(e)[:120]}")
    except Exception as e:  # noqa: BLE001
        record("FAIL", "LLM config", str(e)[:160])

    # ------------------------------------------------------------- Telegram
    if env_bool("ENABLE_TELEGRAM"):
        tok, chat = env("TELEGRAM_BOT_TOKEN"), env("TELEGRAM_CHAT_ID")
        try:
            me = requests.get(f"https://api.telegram.org/bot{tok}/getMe", timeout=10).json()
            record("PASS" if me.get("ok") else "FAIL", "Telegram", f"bot @{me.get('result', {}).get('username')} chat {chat}" if me.get("ok") else str(me)[:120])
        except Exception as e:  # noqa: BLE001
            record("FAIL", "Telegram", str(e)[:120])
    else:
        record("WARN", "Telegram", "disabled - no alerts for fills, pauses or the circuit breaker")

    # ------------------------------------------------------------- report
    width = max(len(c) for _, c, _ in RESULTS)
    icons = {"PASS": "✅", "WARN": "⚠️ ", "FAIL": "❌"}
    print("\nLIVE PREFLIGHT")
    print("=" * 72)
    for status, check, detail in RESULTS:
        print(f"{icons[status]} {status:4s} {check:<{width}}  {detail}")
    fails = sum(1 for s, _, _ in RESULTS if s == "FAIL")
    warns = sum(1 for s, _, _ in RESULTS if s == "WARN")
    print("=" * 72)
    verdict_fail = fails > 0 or (args.strict and warns > 0)
    print(f"{'NO-GO' if verdict_fail else 'GO'}: {fails} failed, {warns} warnings, {len(RESULTS) - fails - warns} passed")
    return 1 if verdict_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
