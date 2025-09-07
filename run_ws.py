#!/usr/bin/env python
"""Simple Wealthsimple API CLI.

Reads credentials from a .env file located beside this script. Expected keys:
  WS_USERNAME=...
  WS_PASSWORD=...
  WS_OTP=...            (optional; only if 2FA required this run)

Session is cached to session.json (OAuth refresh handled automatically).

Commands:
  accounts                        List accounts
  balances   [--account ID]       Show balances for an account (default: first)
  activities [--account ID] [--limit N]  Recent activities (default 20)
  search QUERY                    Search securities
  quotes --id SECURITY_ID [--range 1m|1d|1w|1m|3m|6m|1y|max]

Examples:
  python run_ws.py accounts
  python run_ws.py activities --limit 5
  python run_ws.py search XEQT
  python run_ws.py quotes --id sec-s-xeqt --range 1m
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ws_api import (
    ManualLoginRequired,
    OTPRequiredException,
    WealthsimpleAPI,
    WSAPISession,
)

ROOT = Path(__file__).parent
ENV_FILE = ROOT / ".env"
SESSION_FILE = ROOT / "session.json"


def load_env() -> dict[str, str]:
    data = {}
    if not ENV_FILE.exists():
        return data
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if '=' not in line:
            continue
        key, value = line.split('=', 1)
        raw = value.strip()
        # Remove surrounding quotes if present
        if (raw.startswith('"') and '"' in raw[1:]) or (raw.startswith("'") and "'" in raw[1:]):
            quote = raw[0]
            # find matching closing quote
            closing = raw.find(quote, 1)
            if closing != -1:
                core = raw[1:closing]
                trailing = raw[closing + 1 :].lstrip()
                # Ignore inline comment after closing quote
                if trailing.startswith('#'):
                    raw = core
                else:
                    raw = core + (' ' + trailing if trailing else '')
        # Strip inline comment if unquoted
        if '#' in raw:
            raw = raw.split('#', 1)[0].rstrip()
        data[key.strip()] = raw
    # Allow WS_EMAIL as an alias
    if 'WS_USERNAME' not in data and 'WS_EMAIL' in data:
        data['WS_USERNAME'] = data['WS_EMAIL']
    return data


def load_session() -> WSAPISession | None:
    if not SESSION_FILE.exists():
        return None
    try:
        return WSAPISession.from_json(SESSION_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_session(
    json_str: str,
    username: str | None = None,  # username ignored
):
    SESSION_FILE.write_text(json_str, encoding="utf-8")


def get_api(cli_otp: str | None = None) -> WealthsimpleAPI:
    env = load_env()
    sess = load_session()
    if sess:
        try:
            return WealthsimpleAPI.from_token(sess, persist_session_fct=save_session)
        except ManualLoginRequired:
            sess = None

    if not sess:
        user = env.get('WS_USERNAME')
        pwd = env.get('WS_PASSWORD')
        otp = cli_otp or env.get('WS_OTP')
        if not user or not pwd:
            print(
                "Credentials missing. Provide WS_USERNAME and WS_PASSWORD in " ".env file.",
                file=sys.stderr,
            )
            sys.exit(2)
        try:
            sess = WealthsimpleAPI.login(
                user, pwd, otp_answer=otp, persist_session_fct=save_session
            )
        except OTPRequiredException:
            # Interactive OTP flow (SMS / authenticator)
            attempts = 3
            for attempt in range(1, attempts + 1):
                if not otp:
                    try:
                        otp = input("Entrez le code OTP (SMS): ").strip()
                    except (EOFError, KeyboardInterrupt):
                        print("\nAbandon.")
                        sys.exit(3)
                try:
                    sess = WealthsimpleAPI.login(
                        user,
                        pwd,
                        otp_answer=otp,
                        persist_session_fct=save_session,
                    )
                    break
                except OTPRequiredException:
                    if attempt == attempts:
                        print(
                            "Code OTP invalide (3 tentatives).",
                            file=sys.stderr,
                        )
                        sys.exit(3)
                    print("Code invalide ou expiré. Réessayez.")
                    otp = None
    return WealthsimpleAPI.from_token(sess, persist_session_fct=save_session)


# ---- Command handlers ----


def cmd_accounts(api: WealthsimpleAPI, args):
    accounts = api.get_accounts(open_only=not args.all)
    for acc in accounts:
        print(
            json.dumps(
                {
                    'id': acc['id'],
                    'number': acc['number'],
                    'description': acc['description'],
                    'status': acc['status'],
                    'currency': acc['currency'],
                },
                ensure_ascii=False,
            )
        )


def resolve_account_id(api: WealthsimpleAPI, provided: str | None) -> str:
    if provided:
        return provided
    accounts = api.get_accounts()
    if not accounts:
        print("No accounts found", file=sys.stderr)
        sys.exit(4)
    return accounts[0]['id']


def cmd_balances(api: WealthsimpleAPI, args):
    account_id = resolve_account_id(api, args.account)
    balances = api.get_account_balances(account_id)
    print(json.dumps(balances, ensure_ascii=False, indent=2))


def cmd_activities(api: WealthsimpleAPI, args):
    account_id = resolve_account_id(api, args.account)
    acts = api.get_activities(account_id, how_many=args.limit)
    for act in acts:
        print(json.dumps(act, ensure_ascii=False))


def cmd_search(api: WealthsimpleAPI, args):
    res = api.search_security(args.query)
    for item in res:
        print(json.dumps(item, ensure_ascii=False))


def cmd_quotes(api: WealthsimpleAPI, args):
    quotes = api.get_security_historical_quotes(args.id, time_range=args.range)
    for q in quotes:
        print(json.dumps(q, ensure_ascii=False))


def build_parser():
    p = argparse.ArgumentParser(description="Wealthsimple API CLI")
    sub = p.add_subparsers(dest='command', required=True)

    pa = sub.add_parser('accounts', help='List accounts')
    pa.add_argument(
        '--all',
        action='store_true',
        help='Include closed accounts',
    )
    pa.set_defaults(func=cmd_accounts)

    pb = sub.add_parser('balances', help='Show balances for an account')
    pb.add_argument('--account', help='Account id (default: first)')
    pb.set_defaults(func=cmd_balances)

    pact = sub.add_parser('activities', help='Recent activities')
    pact.add_argument('--account', help='Account id (default: first)')
    pact.add_argument(
        '--limit',
        type=int,
        default=20,
        help='How many (default 20)',
    )
    pact.set_defaults(func=cmd_activities)

    ps = sub.add_parser('search', help='Search securities')
    ps.add_argument('query', help='Search query (symbol, name, etc.)')
    ps.set_defaults(func=cmd_search)

    pq = sub.add_parser('quotes', help='Historical quotes for a security')
    pq.add_argument('--id', required=True, help='Security id (eg sec-s-...)')
    pq.add_argument('--range', default='1m', help='Time range (default 1m)')
    pq.set_defaults(func=cmd_quotes)

    # Global optional OTP override
    p.add_argument('--otp', help='Code OTP (sinon demandé si requis)')
    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    api = get_api(cli_otp=args.otp)
    args.func(api, args)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
