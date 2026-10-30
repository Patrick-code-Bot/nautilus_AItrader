# Going live — runbook

This is the exact sequence to move the bot from Binance Futures Testnet to a
real account. Every step is reversible except funding; nothing below places
an order until `systemctl start`.

> Honest status (2026-10-23): the code paths are verified on testnet
> (entries, exchange-side exits, restart re-adoption, manual-close handling,
> kill-switches). The **strategy's profitability is not demonstrated**: the
> 7-day replay with real Claude decisions returned −0.33% on 8 trades. Trade
> only money you can lose in full, and keep the first-month risk settings in
> `.env.live.example`.

> Running Dokploy or plain Docker? Use **[deploy/DOKPLOY.md](deploy/DOKPLOY.md)** instead of sections 1 and 5–6; everything else here still applies.

## 0. What you need
- A Linux VPS near Binance's matching engine (AWS **ap-northeast-1 Tokyo** or
  **ap-southeast-1 Singapore**; 1 vCPU / 2 GB RAM is plenty). A laptop is not
  acceptable: trailing stops and partial take-profits only move while the
  process is alive, and Wi-Fi/sleep interruptions mean orphaned state.
- Binance Futures account with USDT transferred to the **USDⓈ-M Futures wallet**.
  Sizing needs roughly **≥ $300**; the 2× notional cap must clear the $100
  minimum notional and tick slippage matters below that.
- Anthropic API key (workspace-scoped, or set `ANTHROPIC_WORKSPACE_ID`),
  prepaid credits (~$2/day on Opus 5.5, ~$1/day on Sonnet 5.5 at 15-min cadence).
- Telegram bot token + your chat id (fills, closes, pauses and the circuit
  breaker are pushed to your phone).

## 1. Provision the server (10 min)
```bash
ssh ubuntu@<vps-ip>
curl -fsSL https://raw.githubusercontent.com/suhrabahdi775-cpu/nautilus_AItrader/feature/claude-llm-provider-and-bugfixes/deploy/setup_vps.sh | bash
```
The script installs `uv`, Python 3.12, clones the branch into `~/nautilus_AItrader`,
builds `.venv`, copies `.env.live.example` → `.env` (chmod 600), installs and
enables the `nautilus-trader` systemd unit (not started), and enables NTP
(signed Binance requests fail with > 1 s clock drift).

## 2. Create the LIVE Binance API key (5 min)
Binance → Profile → **API Management** → Create API → *System generated*:
- ✅ Enable Reading
- ✅ Enable Futures
- ❌ Enable Withdrawals (never)
- ❌ Enable Spot & Margin Trading (not needed)
- **Restrict access to trusted IPs only** → add the VPS IP (`curl -s https://api.ipify.org` on the VPS).
  Unrestricted keys are auto-expired by Binance after 90 days and expose the
  account if the secret leaks.
- Futures → Preferences: **One-way mode** (the bot uses netting), and leave
  margin/leverage alone — the bot sets BTCUSDT to `BINANCE_LEVERAGE` /
  `BINANCE_MARGIN_TYPE` at startup when flat.

Your current keys are **testnet** keys; they are rejected by live Binance.

## 3. Fill in `.env`
```bash
nano ~/nautilus_AItrader/.env
```
Set `BINANCE_API_KEY`, `BINANCE_API_SECRET`, `ANTHROPIC_API_KEY`
(+ `ANTHROPIC_WORKSPACE_ID` if needed), `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.
Leave `LIVE_TRADING_ACK=false` for now. Review the risk block — defaults are
half the testnet settings:

| Setting | First month | Meaning |
|---|---|---|
| `RISK_PER_TRADE_PCT` | 0.005 | 0.5% of live equity lost if the stop is hit |
| `MAX_POSITION_LEVERAGE` | 1.5 | position notional ≤ 1.5× equity |
| `BINANCE_LEVERAGE` / `BINANCE_MARGIN_TYPE` | 5 / isolated | exchange-side; isolated caps a liquidation at the position margin |
| `DAILY_LOSS_LIMIT_PCT` | 0.03 | −3% in a UTC day → 24 h pause |
| `MAX_CONSECUTIVE_LOSSES` | 4 | 4 losing closes → 24 h pause |
| `MAX_TOTAL_DRAWDOWN_PCT` | 0.10 | −10% from equity peak → **halt** until you reset |
| `MIN_CONFIDENCE_TO_TRADE` | MEDIUM | HIGH would mean ~no trades with Opus 5.5 |

With $500: a typical trade is ~0.009 BTC (≈ $750 notional), risks ≈ $2.5–3,
targets ≈ $5–6, and costs ≈ $0.75 in taker fees round-trip.

## 4. Preflight (must print GO)
```bash
cd ~/nautilus_AItrader && .venv/bin/python tools/preflight_live.py
```
Checks: venue, ack flag, safety flags, key permissions (futures on,
withdrawals off, IP restricted), USDT balance, open positions/orders, clock
drift, Python/deps, Anthropic model access, Telegram bot. Fix every ❌; read
every ⚠️. The systemd unit runs this automatically before each start and
refuses to start on a failure.

## 5. Arm and start
```bash
sed -i 's/^LIVE_TRADING_ACK=.*/LIVE_TRADING_ACK=true/' ~/nautilus_AItrader/.env
sudo systemctl start nautilus-trader
journalctl -u nautilus-trader -f          # or: tail -f ~/nautilus_AItrader/logs/trader.log
```
Within ~30 s you should see `ExecClient-BINANCE: Connected`, `leverage 5x ... margin ISOLATED`,
`Pre-fetched 199 bars`, `Subscribed to ...15-MINUTE...`, and a Telegram startup
message. The first decision comes after `TIMER_INTERVAL_SEC` (15 min).

## 6. Operate
| Task | Command |
|---|---|
| Status | `systemctl status nautilus-trader` · Telegram `/status`, `/position` |
| Pause new entries (keeps exits) | Telegram `/pause` · resume with `/resume` |
| Stop the bot (exits stay on the exchange) | `sudo systemctl stop nautilus-trader` |
| Restart (position is re-adopted) | `sudo systemctl restart nautilus-trader` |
| Flatten manually | Close in the Binance app — the bot sees the fill and cancels its exits |
| After a circuit-breaker halt | Investigate, then `RESET_RISK_STATE=true` for one start (or delete `logs/risk_state.json`) |
| Calibration data | `logs/signal_log.jsonl` → `python tools/score_signals.py` weekly |
| Update code | `git pull --ff-only && sudo systemctl restart nautilus-trader` |

## 7. Rollback
`sudo systemctl stop nautilus-trader` stops new entries immediately; exchange-side
SL/TP/disaster orders keep protecting any open position. To go fully flat:
close the position in the Binance app (reduce-only algo orders are then
cancelled by the bot if running, or by the orphan sweep at next start — or
cancel them under Futures → Open Orders → Conditional).

## What this does NOT solve
- **Edge.** Run `tools/replay_week.py` over 4 weeks and keep scoring
  `signal_log.jsonl`. If expectancy after fees stays ≤ 0, stop.
- **Fees.** At 15-min holding periods commissions were ~1.5% of equity per
  week in the replay; a 1-hour cadence or wider targets would need re-testing.
- **Model drift.** Claude is non-deterministic and the prompt is the strategy;
  do not change the prompt on a live account without a replay first.
