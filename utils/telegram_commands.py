"""Stateless parser for Telegram trade commands.

Supported forms:
- /buy SYM [qty N|$N] [mkt|limit P|stop P|stoplimit S L] [tif day|gtc]
- /sell SYM [qty N|$N] [mkt|limit P|stop P|stoplimit S L] [tif day|gtc]

Returns a dict with keys: side, symbol, qty, notional, order_type, limit_price,
stop_price, time_in_force. Values may be None when omitted.
"""

from __future__ import annotations

from typing import Any


def _parse_float(tok: str) -> float | None:
    try:
        return float(tok.replace(',', ''))
    except Exception:
        return None


def parse_trade_command(text: str) -> dict[str, Any]:
    """Parse a Telegram trade command into normalized order parameters.

    Raises ValueError on invalid/missing mandatory parts.
    """
    if not text or not isinstance(text, str):
        raise ValueError("empty command")

    raw = text.strip()
    if not raw:
        raise ValueError("empty command")

    parts = raw.split()
    if not parts:
        raise ValueError("empty command")

    first = parts[0].lstrip('/')
    first_l = first.lower()
    if first_l not in ("buy", "sell"):
        raise ValueError("unsupported command; expected /buy or /sell")
    side = "buy" if first_l == "buy" else "sell"

    if len(parts) < 2:
        raise ValueError("symbol required")
    symbol = parts[1].upper()
    if not symbol.isalnum():  # basic sanity; still allow dots like "BRK.B"
        # keep simple: allow common special chars
        sym = symbol.replace(".", "").replace("-", "")
        if not sym:
            raise ValueError("invalid symbol")

    # Defaults
    qty = None
    notional = None
    order_type = "market"
    limit_price = None
    stop_price = None
    time_in_force = "day"

    i = 2
    n = len(parts)
    while i < n:
        tok = parts[i]
        low = tok.lower()

        # qty N
        if low == "qty" and i + 1 < n:
            q = _parse_float(parts[i + 1])
            if q is not None:
                qty = q
            i += 2
            continue

        # $N or "$" N
        if low.startswith("$"):
            v = _parse_float(low[1:])
            if v is not None:
                notional = v
            i += 1
            continue
        if low == "$" and i + 1 < n:
            v = _parse_float(parts[i + 1])
            if v is not None:
                notional = v
            i += 2
            continue

        # type shortcuts
        if low in ("mkt", "market"):
            order_type = "market"
            i += 1
            continue
        if low == "limit" and i + 1 < n:
            order_type = "limit"
            lp = _parse_float(parts[i + 1])
            if lp is not None:
                limit_price = lp
            i += 2
            continue
        if low == "stop" and i + 1 < n:
            order_type = "stop"
            sp = _parse_float(parts[i + 1])
            if sp is not None:
                stop_price = sp
            i += 2
            continue
        if low in ("stoplimit", "stop_limit") and i + 2 < n:
            order_type = "stop_limit"
            sp = _parse_float(parts[i + 1])
            lp = _parse_float(parts[i + 2])
            if sp is not None:
                stop_price = sp
            if lp is not None:
                limit_price = lp
            i += 3
            continue

        # time-in-force
        if low in ("tif", "time_in_force") and i + 1 < n:
            tif = parts[i + 1].lower()
            if tif in ("day", "gtc"):
                time_in_force = tif
            i += 2
            continue

        # bare number -> qty fallback if not set yet
        val = _parse_float(tok)
        if val is not None and qty is None:
            qty = val
            i += 1
            continue

        # Unknown token; skip gracefully
        i += 1

    return {
        "side": side,
        "symbol": symbol,
        "qty": qty,
        "notional": notional,
        "order_type": order_type,
        "limit_price": limit_price,
        "stop_price": stop_price,
        "time_in_force": time_in_force,
    }
