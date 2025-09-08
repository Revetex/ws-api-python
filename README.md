Wealthsimple Portfolio Toolkit (GUI + Trading + Library)
=======================================================

This repository combines:

- A Tkinter desktop app to browse accounts, charts, news, screeners, and control trading.
- A paper/live-safe trading engine with full order types and guardrails.
- A Python library (`ws_api`) to call the Wealthsimple GraphQL API.
- Utilities: caching, circuit breakers, Telegram notifier, and basic analytics/backtests.

Quick start (Windows PowerShell)
--------------------------------

1. Create and activate a virtual environment, then install dev deps:

```powershell
python -m venv .venv; . .\.venv\Scripts\Activate.ps1; pip install -r requirements-dev.txt
```

1. Launch the GUI:

```powershell
python .\gui.py
```

1. Optional toggles for this session:

```powershell
# Prefer Yahoo for quotes (offline-friendly)
$env:MARKET_DATA_PROVIDER = "yahoo"
# Enable enhanced AI advisor (local, safe)
$env:AI_ENHANCED = "1"
python .\gui.py
```

Features at a glance
--------------------

- Trading engine (paper/live-safe):
  - Market, limit, stop, stop-limit orders; convenience helpers (buy/sell variants).
  - Guardrails: per-day trade cap, global and per-symbol cooldowns, per-symbol qty/notional limits.
  - Paper portfolio snapshot (cash, equity, positions) and activity log.
  - Live mode is safe by default (no-ops) unless a `live_executor` is explicitly wired.
- GUI (Tkinter + Matplotlib):
  - Accounts/positions/activities tables, charting with SMA and export, screener, news.
  - Strategy runner and “Derniers signaux”; manual order panel filtered by type.
  - Telegram tab with preferences (auto start, tech alerts, format).
  - Theming, font scale, logos, status and insights badge.
- Data layer and resilience:
  - API manager with Alpha Vantage primary and Yahoo fallback; News API integration.
  - SQLite persistent cache with TTLs; circuit breakers; low-noise logging by default.
- AI helpers (optional):
  - Local advisor summaries; simple technical signals (SMA/RSI) and backtests.

Run modes and safety
--------------------

- Paper: Default. Orders affect only an in-memory portfolio with starting cash (configurable).
- Live: Safe stub. No real orders are placed unless you set `TradeExecutor.set_live_executor(...)`.
- Cooldowns and limits apply when trading via signals; direct `place_order` bypasses them by design.

Trading API (high level)
------------------------

From `wsapp_gui.trade_executor.TradeExecutor`:

- place_order(symbol, side, order_type, qty=None, notional=None, limit_price=None, stop_price=None, time_in_force='day', meta=None) -> dict
- buy_market/sell_market/... convenience wrappers.
- on_signal(symbol, signal): applies daily limits, cooldowns, idempotency ledger, then executes.
- set_live_executor(callable): wire a live delegate safely.

Backtesting and analytics
-------------------------

- `analytics/` includes simple indicators and backtest runners.
- StrategyRunner in the GUI can generate signals and drive one-click paper trades.

Configuration and persistence
-----------------------------

App preferences are auto-saved to `ws_app_config.json`. Useful keys:

- theme, ui.font.*, ui.tabs.*, integrations.telegram.*, strategy_runner.*, autotrade.*
- autotrade.ledger keeps idempotency for signals.

Environment variables:

- Data providers: `MARKET_DATA_PROVIDER=yahoo|alpha`; `ALPHA_VANTAGE_KEY` (for Alpha).
- Cache: `WSAPP_CACHE_DB`, `CACHE_DB_PATH`, `CACHE_TTL_QUOTE_SEC`, `CACHE_TTL_SERIES_SEC`, `CACHE_TTL_NEWS_SEC`.
- Circuit breakers/logging: `ALPHA_LOG_ERRORS`, `NEWS_LOG_ERRORS`, `YAHOO_LOG_ERRORS`, and `*_CB_*` knobs.
- AI: `AI_ENHANCED=1`.

Telegram integration (optional)
-------------------------------

Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` to enable notifications and the Telegram tab.
You can set bot commands via `external_apis.TelegramNotifier.set_bot_commands()`.

Library: `ws_api` (GraphQL client)
----------------------------------

You can use the embedded library directly from Python to access WS accounts. Example login/session code and account reads are similar to earlier versions; see `ws_api/wealthsimple_api.py` and `ws_api/session.py` for APIs. If you publish the library separately, install via pip; otherwise, import from the source tree.

Development
-----------

Install tools and run tests:

```powershell
pip install -r requirements-dev.txt
python -m pytest -q
```

Pre-commit hooks (recommended):

```powershell
pip install pre-commit; pre-commit install; pre-commit run --all-files
```

Quality gates
-------------

- Lint/format: Ruff (lint + ruff-format), Black, flake8 configured in `pyproject.toml`.
- Tests: Pytest suite covers charts, trading engine (order types, guardrails, live delegation), and more.
- Headless CI: GUI tests are skipped when DISPLAY is unavailable.

Troubleshooting
---------------

- No quotes / offline: set `MARKET_DATA_PROVIDER=yahoo` and ensure cache TTLs are generous.
- Excess logs: set `*_LOG_ERRORS=0` (default) and avoid DEBUG unless needed.
- Tk crashes in CI: ensure tests skip when headless (already handled).

Repository layout
-----------------

- `wsapp_gui/`: GUI app (app, panels, trade executor, strategy runner, telegram UI)
- `ws_api/`: Wealthsimple GraphQL client and exceptions
- `utils/`: env loading, logging, http client, sqlite cache, performance tools
- `analytics/`: indicators, strategies, backtests
- `external_apis.py`: Alpha Vantage, Yahoo fallback, News, Telegram
- `run_ws.py`: CLI helpers; `gui.py`: app launcher
- `tests/`: pytest suite

Security
--------

Treat WS sessions and tokens as secrets. Don’t commit them. The app keeps settings in `ws_app_config.json`; review before sharing logs or configs.
