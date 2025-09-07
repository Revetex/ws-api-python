import math

from wsapp_gui.trade_executor import TradeExecutor


class FakeAPI:
    def __init__(self, price_map=None, default=100.0):
        self.default = float(default)
        self.price_map = dict(price_map or {})

    def get_quote(self, symbol: str):
        price = self.price_map.get(symbol, self.default)
        # mimic alpha-like shape
        return {"05. price": price}


def test_market_order_fill():
    api = FakeAPI(default=100.0)
    ex = TradeExecutor(api)
    ex.configure_simple(enabled=True, mode="paper", base_size=1000.0)
    o = ex.place_order(symbol="AAPL", side="buy", order_type="market")
    assert o["status"] == "filled"
    assert math.isclose(o["filled_qty"], 10.0, rel_tol=1e-6)
    assert math.isclose(o["avg_fill_price"], 100.0, rel_tol=1e-6)


def test_limit_order_fill_and_open():
    api = FakeAPI(default=100.0)
    ex = TradeExecutor(api)
    ex.configure_simple(enabled=True, mode="paper", base_size=1000.0)
    # Buy limit at or above last -> should fill
    o1 = ex.place_order(symbol="MSFT", side="buy", order_type="limit", limit_price=100.0)
    assert o1["status"] == "filled"
    # Sell limit at or below last -> should fill
    o2 = ex.place_order(symbol="MSFT", side="sell", order_type="limit", limit_price=100.0, qty=1.0)
    assert o2["status"] == "filled"
    # Buy limit below last -> open
    o3 = ex.place_order(symbol="MSFT", side="buy", order_type="limit", limit_price=90.0)
    assert o3["status"] == "open"


def test_stop_and_stop_limit_trigger_logic():
    api = FakeAPI(default=100.0)
    ex = TradeExecutor(api)
    ex.configure_simple(enabled=True, mode="paper", base_size=1000.0)
    # Stop (becomes market when triggered)
    o1 = ex.place_order(symbol="NVDA", side="buy", order_type="stop", stop_price=95.0)
    assert o1["status"] == "filled"  # price_now >= stop for buy
    o2 = ex.place_order(symbol="NVDA", side="sell", order_type="stop", stop_price=105.0, qty=1.0)
    assert o2["status"] == "filled"  # price_now <= stop for sell
    # Non-triggered stop -> open
    o3 = ex.place_order(symbol="NVDA", side="buy", order_type="stop", stop_price=105.0)
    assert o3["status"] == "open"

    # Stop-limit: trigger + limit check
    # Triggered and limit allows fill (buy: last <= limit)
    o4 = ex.place_order(
        symbol="AMZN",
        side="buy",
        order_type="stop_limit",
        stop_price=95.0,
        limit_price=100.0,
    )
    assert o4["status"] == "filled"
    # Triggered but limit prevents fill -> open
    o5 = ex.place_order(
        symbol="AMZN",
        side="buy",
        order_type="stop_limit",
        stop_price=95.0,
        limit_price=90.0,
    )
    assert o5["status"] == "open"
