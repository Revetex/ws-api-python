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
        persist_session_fct = lambda sess: keyring.set_password(keyring_service_name, "session", sess)
        # The session contains tokens that can be used to empty your Wealthsimple account, so treat it with respect!
        # i.e. don't store it in a Git repository, or anywhere it can be accessed by others!
    
        # 2. If it's the first time you run this, create a new session using the username & password (and TOTP answer, if needed). Do NOT save those infos in your code!
        session = keyring.get_password(keyring_service_name, "session")
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
        ws = WealthsimpleAPI.from_token(session, persist_session_fct)
        # persist_session_fct is needed here too, because the session may be updated if the access token expired, and thus this function will be called to save the new session
        
        # 4. Use the API object to access your WS accounts
        accounts = ws.get_accounts()
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
                print("  Other positions:")
                for sec_id, bal in balances.items():
                    if sec_id in ['sec-c-cad', 'sec-c-usd']:
                        continue
                    stock = self.get_stock_info(ws, sec_id)
                    print(f"  - {stock['primaryExchange']}:{stock['symbol']} x {bal}")
    
            # Fetch activities (transactions)
            acts = ws.get_activities(account['id'])
            if acts:
                print("  Transactions:")
                acts.reverse()  # Activities are sorted by OCCURRED_AT_DESC by default

                for act in acts:
                    if act['status'] == 'FILLED' and (act['type'] == 'DIY_SELL' or act['type'] == 'DIY_BUY'):
                        stock = self.get_stock_info(ws, act['securityId'])
                        act['description'] = act['description'].replace(f"[{act['securityId']}]", f"{stock['primaryExchange']}:{stock['symbol']}")
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

    # This function is used to get a security (eg. stock) info, from a given security ID. This is useful to get a human-readable name for the security.
    # eg. sec-s-e7947deb977341ff9f0ddcf13703e9a6 => XEQT
    @staticmethod
    def get_stock_info(ws: WealthsimpleAPI, ws_security_id: str):
        # Instead of querying the WS API every time you need to find the symbol of a security ID, you should cache the results in a local storage (eg. database)
        # We'll just save JSON files in the temp directory in this example.
        temp_dir = tempfile.gettempdir()
        cache_file_path = os.path.join(temp_dir, f"ws-api-{ws_security_id}.json")
    
        # Try to read from cache
        if os.path.exists(cache_file_path):
            with open(cache_file_path, 'r') as file:
                market_data = json.load(file)
            return market_data['stock']
    
        # If not found in cache, make an API request
        market_data = ws.get_security_market_data(ws_security_id)
    
        # Cache the result for future use
        with open(cache_file_path, 'w') as file:
            # noinspection PyTypeChecker
            json.dump(market_data, file)
    
        return market_data['stock']

if __name__ == "__main__":
    WSApiTest().main()

```
