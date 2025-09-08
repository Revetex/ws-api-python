import pytest

from utils.telegram_commands import parse_trade_command


def test_parse_buy_market_minimal():
    cmd = "/buy AAPL"
    p = parse_trade_command(cmd)
    assert p["side"] == "buy"
    assert p["symbol"] == "AAPL"
    assert p["order_type"] == "market"
    assert p["qty"] is None and p["notional"] is None


def test_parse_sell_with_qty_and_limit():
    cmd = "/sell msft qty 10 limit 450.5 tif gtc"
    p = parse_trade_command(cmd)
    assert p["side"] == "sell"
    assert p["symbol"] == "MSFT"
    assert p["order_type"] == "limit"
    assert p["qty"] == 10
    assert p["limit_price"] == 450.5
    assert p["time_in_force"] == "gtc"


def test_parse_buy_stop():
    p = parse_trade_command("/buy TSLA stop 300")
    assert p["order_type"] == "stop"
    assert p["stop_price"] == 300


def test_parse_buy_stop_limit_with_notional():
    p = parse_trade_command("/buy NVDA $1000 stoplimit 850 840")
    assert p["notional"] == 1000
    assert p["order_type"] == "stop_limit"
    assert p["stop_price"] == 850
    assert p["limit_price"] == 840


def test_parse_accepts_bare_qty_number():
    p = parse_trade_command("/buy SHOP 12 mkt")
    assert p["qty"] == 12
    assert p["order_type"] == "market"


def test_parse_rejects_invalid_command():
    with pytest.raises(ValueError):
        parse_trade_command("/foo AAPL")


def test_parse_requires_symbol():
    with pytest.raises(ValueError):
        parse_trade_command("/buy")
