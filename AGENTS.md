# Repository Guidelines

## Project Structure & Module Organization
`main_live.py` orchestrates Binance adapters, environment loading, and the Nautilus `TradingNode` that runs `DeepSeekAIStrategy`. Strategy logic sits in `strategy/deepseek_strategy.py`, indicator math in `indicators/technical_manager.py`, integrations (DeepSeek, sentiment, Telegram) in `utils/`, and durable configs in `configs/` (`strategy_config.yaml` for defaults, `.env` for secrets). Operational scripts (`start_trader.sh`, `restart_trader.sh`, `check_strategy_status.sh`, `run_quick_test.py`) live at the repo root, while runtime artifacts are written to `logs/` and can be tailed per session.

## Build, Test, and Development Commands
- `./start_trader.sh --setup` (or `uv venv --python 3.12 .venv && uv pip install -r requirements.txt`) – provision the interpreter; NautilusTrader ≥1.231 requires Python 3.12.
- `pip install -r requirements.txt` – install NautilusTrader, Binance adapters, and tooling; rerun when requirements change.
- `python main_live.py` – start using `.env` (BINANCE_ENV selects live/testnet/demo); monitor with `tail -f logs/trader*.log` and `logs/signal_log.jsonl`.
- `python run_quick_test.py` – launch the 1-minute quick test harness with reduced indicator periods for fast validation loops.
- `./start_trader.sh | ./restart_trader.sh | ./stop_trader.sh` – manage background sessions with PID bookkeeping instead of manual nohup handling.

## Coding Style & Naming Conventions
Use PEP 8, 4-space indentation, liberal type hints, and descriptive docstrings similar to `main_live.py`. Modules/functions stay `snake_case`, classes `PascalCase`, config keys `UPPER_SNAKE_CASE`, and YAML keys `lower_snake_case`. Keep shared helpers in `utils/` so imports remain aligned with `pyrightconfig.json`; run `pyright` (basic mode) before review to catch interface drift.

## Testing Guidelines
Exercise every behavior change in quick-test mode (`python quick_test_main.py` or `python run_quick_test.py`) and confirm logs show clean startup plus at least one signal cycle. Messaging work requires `python test_telegram.py <bot_token> <chat_id>` to validate send capability and `python test_command_listener.py` to prove inbound command handling. When editing risk sizing or indicator math, capture indicator dumps or equity deltas inside the PR so reviewers can gauge coverage.

## Commit & Pull Request Guidelines
Branch off `main` using `feature/<topic>` or `fix/<issue>` as documented in `GIT_WORKFLOW.md`. Commits follow `<type>: <summary>` (feat, fix, docs, refactor, etc.) and include a short body outlining rationale and `Testing: …`. PRs must summarize the change, list config/env deltas, attach representative log snippets, and link issues via `Fixes #id`. Avoid force pushes mid-review; instead add follow-up commits or coordinate with reviewers.

## Security & Configuration Tips
Never commit secrets—`.env` stays local with `chmod 600`. Document any new environment variable or YAML knob in README/QUICKSTART, and keep sanitized defaults under `configs/` so operators can reproduce your setup. Rotate Binance, DeepSeek, and Telegram credentials immediately if they leak through logs or screenshots.
