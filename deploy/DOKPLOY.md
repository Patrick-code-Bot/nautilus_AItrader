# Deploying with Dokploy (Debian 12)

The bot is a single long-running container with **no inbound ports** (Telegram is
the operator channel) and **one persistent volume** (`/app/logs`: kill-switch
state, position state, signal log, heartbeat). Dokploy only needs to build the
`Dockerfile`, inject environment variables and mount that volume.

## 0. Host preparation (once, as root on the Debian 12 server)

```bash
# Accurate clock - Binance rejects signed requests with > 1 s drift
apt-get install -y systemd-timesyncd && timedatectl set-ntp true && timedatectl   # "System clock synchronized: yes"

# Dokploy should already be running
docker ps --format '{{.Names}}' | grep -i dokploy

# Public IP of this server -> whitelist it on the Binance API key
curl -s https://api.ipify.org; echo
```

Containers use the host clock, so NTP on the host is what matters.

## 1. Create the service in Dokploy (recommended: Application / Dockerfile)

1. **Projects → Create Project** `nautilus` → **Create Service → Application**.
2. **Provider**: *GitHub* (if you connected your GitHub account) or *Git* with
   `https://github.com/suhrabahdi775-cpu/nautilus_AItrader.git` (public, no key needed).
   Branch: `feature/claude-llm-provider-and-bugfixes` (or `main` after you merge).
3. **Build Type**: *Dockerfile* — Dockerfile path `Dockerfile`, build context `.`.
4. **Environment** tab → paste the block below (edit values). Dokploy injects
   these into the container; the image has no `.env` file by design.
5. **Volumes** tab → *Add → Volume Mount*: name `trader-logs`, mount path `/app/logs`.
6. **Domains**: none. Leave **Auto Deploy** OFF (a push would restart the bot
   mid-position; restarts are safe but you want to choose the moment).
7. **Deploy**.

```env
# --- venue: rehearse on testnet FIRST, then switch to live ---
BINANCE_ENV=testnet
BINANCE_API_KEY=
BINANCE_API_SECRET=
BINANCE_LEVERAGE=5
BINANCE_MARGIN_TYPE=isolated
LIVE_TRADING_ACK=false

# --- AI (A: Claude; B: an OpenAI-compatible provider that serves your region,
#         e.g. DeepSeek - Anthropic returns 403 "Request not allowed" from unsupported countries) ---
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=
ANTHROPIC_WORKSPACE_ID=
LLM_MODEL=claude-opus-5-5
LLM_EFFORT=medium
# B) instead of the four lines above:
# LLM_PROVIDER=openai
# LLM_API_KEY=<deepseek key>
# LLM_MODEL=deepseek-v4-pro
# LLM_BASE_URL=https://api.deepseek.com
# LLM_TEMPERATURE=0.1
LLM_TIMEOUT_SEC=60
LLM_MAX_TOKENS=1024
LLM_ASYNC=true

# --- strategy ---
TIMEFRAME=15m
TIMER_INTERVAL_SEC=900
MIN_CONFIDENCE_TO_TRADE=MEDIUM
REGIME_FILTER_ENABLED=true
NATIVE_EXITS=true

# --- risk (first-month defaults) ---
RISK_PER_TRADE_PCT=0.005
MAX_POSITION_LEVERAGE=1.5
DAILY_LOSS_LIMIT_PCT=0.03
MAX_CONSECUTIVE_LOSSES=4
LOSS_PAUSE_HOURS=24
MAX_TOTAL_DRAWDOWN_PCT=0.10

# --- safety flags ---
TEST_MODE=false
DRY_RUN=false
SIGNAL_ONLY_MODE=false
AUTO_CONFIRM=true

# --- alerts ---
ENABLE_TELEGRAM=true
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
LOG_LEVEL=INFO
```

### What happens on start
The entrypoint runs `tools/preflight_live.py` first. On **NO-GO** it prints the
checklist, waits 120 s and exits 1 (Dokploy restarts it; the loop is slow and
readable in *Logs*). On **GO** it `exec`s `main_live.py`. Expect, within ~30 s:
`ExecClient-BINANCE: Connected`, `leverage 5x ... margin ISOLATED`,
`Pre-fetched 199 bars`, `Subscribed to ...15-MINUTE...`, `LLM analysis runs on a
worker thread`, and a Telegram startup message. The image healthcheck turns
*unhealthy* if the heartbeat (every bar / cycle) is older than 40 min.

## 2. Dress rehearsal on testnet (recommended, 1–2 days)
With the block above (testnet keys, `BINANCE_ENV=testnet`) the preflight passes
with warnings and the bot trades paper money on your server exactly as it will
live. Check *Logs* for one full cycle (`🤖 Signal:`) and that `/app/logs`
persists across a **Redeploy** (`risk_state.json`, `heartbeat`).

## 3. Switch to live
1. Create the **live** Binance key (Enable Futures, **no withdrawals**, IP-restricted
   to the server IP from step 0; One-way position mode) and fund the USDⓈ-M wallet.
2. In Dokploy *Environment*: `BINANCE_ENV=live`, the live key/secret, keep
   `LIVE_TRADING_ACK=false` → **Redeploy** → the preflight prints the live
   checklist (key permissions, balance, drift…) and stops at the ack. Read it.
3. Set `LIVE_TRADING_ACK=true` → **Redeploy**. Persisted testnet state is
   discarded automatically (state files are venue-tagged).

## 4. Operate
| Task | How |
|---|---|
| Status / position | Telegram `/status`, `/position`; Dokploy *Logs* |
| Pause new entries (exits stay) | Telegram `/pause` / `/resume` |
| Stop the bot | Dokploy **Stop** — exchange-side SL/TP/disaster orders keep protecting any open position |
| Restart / update code | **Redeploy** — the open position is re-adopted and its exits verified |
| Run the preflight manually | Dokploy *Terminal* → `python tools/preflight_live.py` |
| Score the calibration log | *Terminal* → `python tools/score_signals.py --file logs/signal_log.jsonl` |
| After a circuit-breaker halt | add `RESET_RISK_STATE=true`, Redeploy once, then remove it |
| Back up state | `docker run --rm -v trader-logs:/data -v $PWD:/b alpine tar czf /b/trader-logs.tgz /data` |

## Alternative: Compose mode
Create *Service → Compose*, same repository, compose path `docker-compose.yml`.
Dokploy writes the *Environment* tab to a `.env` next to the compose file, which
the `env_file` entry passes into the container; the named volume `trader_logs`
is declared in the compose file.

## Resources & notes
- ~400 MB RAM, < 0.2 vCPU idle; the image is ~700 MB (nautilus_trader wheel).
- Use a *named* volume (as above). With a bind mount, `chown 1000:1000` the host
  directory — the container runs as uid 1000 and silently loses state writes otherwise.
- Dokploy Applications run as Docker Swarm services with a 10 s stop grace
  period; the node shuts down in ~2 s, exits stay on the exchange regardless.
- Latency: the server's location only affects fill timing by tens of ms;
  Binance's matching engine is in AWS Tokyo.
