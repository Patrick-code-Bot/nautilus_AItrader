#!/bin/bash
# One-shot VPS setup (Ubuntu 22.04/24.04, Debian 12). Run as the user that will own the bot:
#
#   curl -fsSL https://raw.githubusercontent.com/suhrabahdi775-cpu/nautilus_AItrader/feature/claude-llm-provider-and-bugfixes/deploy/setup_vps.sh | bash -s -- [repo_url] [branch]
#
# Then: edit $HOME/nautilus_AItrader/.env, run the preflight, and `sudo systemctl start nautilus-trader`.
set -euo pipefail

REPO_URL="${1:-https://github.com/suhrabahdi775-cpu/nautilus_AItrader.git}"
BRANCH="${2:-feature/claude-llm-provider-and-bugfixes}"
REPO_DIR="$HOME/nautilus_AItrader"

echo "== packages =="
sudo apt-get update -qq
sudo apt-get install -y -qq git curl chrony ca-certificates >/dev/null
sudo systemctl enable --now chrony >/dev/null 2>&1 || true   # accurate clock: Binance signed requests need < 1 s drift

echo "== uv (Python manager) =="
if ! command -v uv >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

echo "== repository =="
if [ -d "$REPO_DIR/.git" ]; then
    git -C "$REPO_DIR" fetch -q origin && git -C "$REPO_DIR" checkout -q "$BRANCH" && git -C "$REPO_DIR" pull -q --ff-only
else
    git clone -q --branch "$BRANCH" "$REPO_URL" "$REPO_DIR"
fi
cd "$REPO_DIR"

echo "== python 3.12 venv + requirements =="
uv python install 3.12 >/dev/null
uv venv --python 3.12 .venv >/dev/null
UV_CONCURRENT_DOWNLOADS=2 uv pip install --python .venv/bin/python -q -r requirements.txt
mkdir -p logs

echo "== .env =="
if [ ! -f .env ]; then
    cp .env.live.example .env
    chmod 600 .env
    echo "   created .env from .env.live.example - FILL IN the keys before starting"
else
    chmod 600 .env
    echo "   existing .env kept"
fi

echo "== systemd unit =="
sed -e "s#__USER__#$(whoami)#g" -e "s#__REPO_DIR__#$REPO_DIR#g" deploy/nautilus-trader.service | sudo tee /etc/systemd/system/nautilus-trader.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable nautilus-trader >/dev/null

echo
echo "✅ Setup complete. Next:"
echo "   1) nano $REPO_DIR/.env            # live Binance keys, ANTHROPIC_API_KEY, Telegram"
echo "   2) curl -s https://api.ipify.org  # whitelist this IP on the Binance API key"
echo "   3) $REPO_DIR/.venv/bin/python $REPO_DIR/tools/preflight_live.py"
echo "   4) set LIVE_TRADING_ACK=true in .env, then: sudo systemctl start nautilus-trader"
echo "   5) journalctl -u nautilus-trader -f   |   tail -f $REPO_DIR/logs/trader.log"
