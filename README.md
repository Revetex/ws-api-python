Unofficial Wealthsimple API Library for Python
==============================================

This library allows you to access your own account using the Wealthsimple (GraphQL) API using Python.

Installation
------------

```bash
pip install ws-api
```

Usage
-----

Note: You'll need the keyring package to run the code below. Install with: `pip install keyring`

```python
from datetime import datetime
import json
import keyring
import os
import tempfile
from ws_api import WealthsimpleAPI, OTPRequiredException, LoginFailedException, WSAPISession

class WSApiTest:
    def main(self):
        # 1. Define a function that will be called when the session is created or updated. Persist the session to a safe place, like in the keyring
        keyring_service_name = "foo.bar"
        persist_session_fct = lambda sess, uname: keyring.set_password(f"{keyring_service_name}.{uname}", "session", sess)
        # The session contains tokens that can be used to empty your Wealthsimple account, so treat it with respect!
        # i.e. don't store it in a Git repository, or anywhere it can be accessed by others!

        # If you want, you can set a custom User-Agent for the requests to the WealthSimple API:
        WealthsimpleAPI.set_user_agent("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36")

        # 2. If it's the first time you run this, create a new session using the username & password (and TOTP answer, if needed). Do NOT save those infos in your code!
        username = input("Wealthsimple username (email): ")
        session = keyring.get_password(f"{keyring_service_name}.{username}", "session")
        if session:
            session = WSAPISession.from_json(session)
        if not session:
            username = None
            password = None
            otp_answer = None
            while True:
                try:
                    if not username:
                        username = input("Wealthsimple username (email): ")
                        session = keyring.get_password(f"{keyring_service_name}.{username}", "session")
                        if session:
                            session = WSAPISession.from_json(session)
                            break
                    if not password:
                        password = input("Password: ")
                    WealthsimpleAPI.login(username, password, otp_answer, persist_session_fct=persist_session_fct)
                    # The above will throw exceptions if login failed
                    # So we break (out of the login "while True" loop) on success:
                    session = WSAPISession.from_json(keyring.get_password(keyring_service_name, "session"))
                    break
                except OTPRequiredException:
                    otp_answer = input("TOTP code: ")
                except LoginFailedException:
                    print("Login failed. Try again.")
                    username = None
                    password = None

        # 3. Use the session object to instantiate the API object
        ws = WealthsimpleAPI.from_token(session, persist_session_fct, username)
        # persist_session_fct is needed here too, because the session may be updated if the access token expired, and thus this function will be called to save the new session

        # Optionally define functions to cache market data, if you want transactions' descriptions and accounts balances to show the security's symbol instead of its ID
        # eg. sec-s-e7947deb977341ff9f0ddcf13703e9a6 => TSX:XEQT
        def sec_info_getter_fn(ws_security_id: str):
            cache_file_path = os.path.join(tempfile.gettempdir(), f"ws-api-{ws_security_id}.json")
            if os.path.exists(cache_file_path):
                return json.load(open(cache_file_path, 'r'))
            return None
        def sec_info_setter_fn(ws_security_id: str, market_data: object):
            cache_file_path = os.path.join(tempfile.gettempdir(), f"ws-api-{ws_security_id}.json")
            # noinspection PyTypeChecker
            json.dump(market_data, open(cache_file_path, 'w'))
            return market_data
        ws.set_security_market_data_cache(sec_info_getter_fn, sec_info_setter_fn)

        # 4. Use the API object to access your WS accounts
        accounts = ws.get_accounts()

        print("All Accounts Historical Value & Gains:")
        historical_fins = ws.get_identity_historical_financials([a['id'] for a in accounts])
        for hf in historical_fins:
            value = float(hf['netLiquidationValueV2']['amount'])
            deposits = float(hf['netDepositsV2']['amount'])
            gains = value - deposits
            print(f"  - {hf['date']} = ${value:,.0f} - {deposits:,.0f} (deposits) = {gains:,.0f} (gains)")

        for account in accounts:
            print(f"Account: {account['description']} ({account['number']})")
            if account['description'] == account['unifiedAccountType']:
                # This is an "unknown" account, for which description is generic; please open an issue on https://github.com/gboudreau/ws-api-python/issues and include the following:
                print(f"    Unknown account: {account}")

            if account['currency'] == 'CAD':
                value = account['financials']['currentCombined']['netLiquidationValue']['amount']
                print(f"  Net worth: {value} {account['currency']}")
            # Note: For USD accounts, value is the CAD value converted to USD
            # For USD accounts, only the balance & positions are relevant

            # Cash and positions balances
            balances = ws.get_account_balances(account['id'])
            cash_balance_key = 'sec-c-usd' if account['currency'] == 'USD' else 'sec-c-cad'
            cash_balance = float(balances.get(cash_balance_key, 0))
            print(f"  Available (cash) balance: {cash_balance} {account['currency']}")

            if len(balances) > 1:
                print("  Assets:")
                for security, bal in balances.items():
                    if security in ['sec-c-cad', 'sec-c-usd']:
                        continue
                    print(f"  - {security} x {bal}")

            print("  Historical Value & Gains:")
            historical_fins = ws.get_account_historical_financials(account['id'], account['currency'])
            for hf in historical_fins:
                value = hf['netLiquidationValueV2']['cents'] / 100
                deposits = hf['netDepositsV2']['cents'] / 100
                gains = value - deposits
                print(f"  - {hf['date']} = ${value:,.0f} - {deposits:,.0f} (deposits) = {gains:,.0f} (gains)")

            # Fetch activities (transactions)
            acts = ws.get_activities(account['id'])
            if acts:
                print("  Transactions:")
                acts.reverse()  # Activities are sorted by OCCURRED_AT_DESC by default

                for act in acts:
                    if act['type'] == 'DIY_BUY':
                        act['amountSign'] = 'negative'

                    # Print transaction details
                    print(
                        f"  - [{datetime.strptime(act['occurredAt'].replace(':', ''), '%Y-%m-%dT%H%M%S.%f%z')}] [{act['canonicalId']}] {act['description']} "
                        f"{'+' if act['amountSign'] == 'positive' else '-'}{act['amount']} {act['currency']}")

                    if act['description'] == f"{act['type']}: {act['subType']}":
                        # This is an "unknown" transaction, for which description is generic; please open an issue on https://github.com/gboudreau/ws-api-python/issues and include the following:
                        print(f"    Unknown activity: {act}")

            print()

if __name__ == "__main__":
    WSApiTest().main()

```

Development & Tests
-------------------

To run the local test suite (requires `pytest`):

```bash
pip install -U pytest
pytest -q
```

The lightweight tests currently cover news sentiment robustness in `symbol_analyzer`. More tests can be added under `tests/` for API behaviors and signal generation.

Persistent cache (SQLite)
-------------------------

This project includes a lightweight persistent cache to reduce API calls and provide a degraded offline mode. By default it creates `cache.sqlite3` at the project root. You can override the path and TTLs via environment variables:

- `WSAPP_CACHE_DB` or `CACHE_DB_PATH`: full path to the SQLite file
- `CACHE_TTL_QUOTE_SEC` (default 60): quote freshness window
- `CACHE_TTL_SERIES_SEC` (default 300): time series freshness window
- `CACHE_TTL_NEWS_SEC` (default 600): news freshness window

The cache is read-through in `APIManager.get_quote`, `APIManager.get_time_series`, and News API calls. On successful fetches, results are written back to the cache.

GUI app (wsapp_gui)
--------------------

If you use the optional Tkinter GUI under `wsapp_gui/`, a few UX features and Telegram preferences are available:

- Insights badge: The header shows a compact insights badge. Click it to open a popup with the full text and a copy button.
- Telegram tab:
    - Include technical alerts: When enabled, INFO-level `TECH_*` alerts (e.g., SMA crosses) are routed to Telegram.
    - TECH_* format: Choose how `TECH_*` alerts are formatted in Telegram: `plain` or `emoji-rich`.

Enhanced AI Advisor (optional)
--------------------------------

- What it is: An on-device helper that summarizes portfolio metrics and suggests conservative, safety-aware actions (no live orders).
- How to enable:
    - In the app: Preferences > Intelligence Artificielle > "Activer le Conseiller (Enhanced AI)".
    - Or via environment variable before launching the app:

    - Windows PowerShell:

        ```powershell
        $env:AI_ENHANCED = "1"; python .\\gui.py
        ```

    - macOS/Linux bash:

        ```bash
        AI_ENHANCED=1 python gui.py
        ```
- Where to use: Strategy tab > "Conseiller (AI)" section. Click "Analyser maintenant" to generate insights.
- Notes: Feature-flagged; safe by default. PII is lightly masked in outputs.
Configuration keys (auto-persisted to `ws_app_config.json` when changed in the UI):

- `integrations.telegram.include_technical` (bool, default: true)
- `integrations.telegram.tech_format` ("plain" | "emoji-rich", default: "plain")

Note: The notifier reads `tech_format` at send time, so changes take effect immediately; no restart required.

Telegram bot commands (optional)
--------------------------------

If you set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`, you can enable a simple bot that responds to:

- `/summary` or `/insights` – Portfolio insights
- `/positions` – Top positions
- `/signals` – Recent signals + quick SMA snapshot
- `/quote SYM` – Quick market quote (price and change%)
- `/signal SYM` – Technical SMA(5/20) signal for a symbol

To start the polling handler in your app code:

```python
from external_apis import APIManager

api = APIManager()
api.start_telegram_commands(agent, allowed_chat_id="123456789")
# Or pass a list with allowed_chat_ids=["123456789","987654321"]
```

Telegram configuration behavior
-------------------------------

- By default, `TelegramNotifier()` reads `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` from the environment.
- If you explicitly pass `None` for `bot_token` and/or `chat_id` when creating `TelegramNotifier`, it will treat those as unconfigured and will not fall back to environment variables. This is useful for tests or when you want to disable Telegram programmatically.
- Passing actual values (non-None) will override any environment values.

Windows quick start
-------------------

1) Copy `.env.example` to `.env` and fill credentials (don’t commit secrets).

1) Launch the GUI:

```powershell
./run_gui.bat
```

1) Optional: enable Enhanced AI for this session:

```powershell
./run_gui_enhanced.bat
```

1) CLI helper (wraps `run_ws.py`):

```powershell
./run_ws_cli.bat accounts
```

VS Code tips
------------

- Tasks: Run GUI, CLI accounts, Lint, and Tests are preconfigured under `.vscode/tasks.json`.
- Debug: Launch configs for the GUI, CLI, and per-file tests are in `.vscode/launch.json`.
- Dev tools: If needed, install dev dependencies:

```powershell
pip install -r requirements-dev.txt
```

Continuous Integration (CI)
---------------------------

- GitHub Actions workflow runs pytest on pushes and PRs against main (see `.github/workflows/ci.yml`).

Pre-commit hooks
----------------

Install and enable hooks locally:

```powershell
pip install pre-commit
pre-commit install
```

Includes: basic whitespace fixes, ruff (lint + format), black, and flake8.

Silent GUI launcher (Windows)
-----------------------------

Use `run_gui_silent.bat` to start the GUI without an attached console window. It prefers pythonw from `.venv`/`venv`, otherwise falls back to a VBScript shim.

Offline and log-noise tips
--------------------------

When working offline or behind restrictive networks, you can reduce console noise and prefer offline-friendly providers:

- Prefer Yahoo as market data provider (no API key required):

        - Windows PowerShell:

            ```powershell
            $env:MARKET_DATA_PROVIDER = "yahoo"; python .\\gui.py
            ```

        - macOS/Linux bash:

            ```bash
            MARKET_DATA_PROVIDER=yahoo python ./gui.py
            ```

- Silence external API error logs unless debugging:

    - Alpha Vantage: set `ALPHA_LOG_ERRORS=0` (default 0; set 1 to enable)
    - News API: set `NEWS_LOG_ERRORS=0` (default 0; set 1 to enable)
    - Yahoo: set `YAHOO_LOG_ERRORS=0` (default 0; set 1 to enable)

- Keep compatibility with legacy requests session (default): `WSAPP_HTTPCLIENT_ONLY=0`

Caching notes:

- Quotes/series/news are cached on success; if a provider fails, the app serves stale data (when available) instead of erroring.
