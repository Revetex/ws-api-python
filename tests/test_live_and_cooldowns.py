from __future__ import annotations

import math
from unittest.mock import patch

from wsapp_gui.trade_executor import TradeExecutor


class DummyAPI:
    def __init__(self, price_map):
        self.price_map = dict(price_map)

    def get_quote(self, symbol):
        p = self.price_map.get(symbol)
        if p is None:
            return None
        return {"05. price": p}


def test_place_order_live_delegates_and_no_mutation():
    # No ledger load side-effects
    with patch("wsapp_gui.trade_executor.TradeExecutor._load_ledger"):
        api = DummyAPI({"AAA": 100.0})
        ex = TradeExecutor(api)
        ex.configure(enabled=True, mode="live", base_size=1000.0)

        calls: list[tuple] = []

        def fake_live(symbol, side, qty, price, meta):
            calls.append((symbol, side, qty, price, meta))

        ex.set_live_executor(fake_live)

        # Place a market buy without explicit qty -> executor computes from base_size
        order = ex.place_order(symbol="AAA", side="buy", order_type="market")

        # In live mode, orders are submitted (open) and not filled in paper state
        assert order["status"] == "open"
        assert order["filled_qty"] == 0.0
        assert order["avg_fill_price"] is None

        # Portfolio snapshot in live mode returns placeholders, proving no paper mutation
        snap = ex.portfolio_snapshot()
        assert snap["mode"] == "live"
        assert snap["cash"] is None
        assert snap["equity"] is None
        assert len(snap["positions"]) == 0

        # Live executor was invoked with computed qty and current price
        assert len(calls) == 1
        sym, side, qty, price, meta = calls[0]
        assert sym == "AAA" and side == "buy"
        assert math.isclose(qty, 1000.0 / 100.0, rel_tol=1e-6)
        assert math.isclose(price, 100.0, rel_tol=1e-6)
        assert meta.get("order_type") == "market"


def test_on_signal_global_cooldown_enforced(monkeypatch):
    # Ensures min_trade_interval_sec blocks rapid consecutive signals
    with patch("wsapp_gui.trade_executor.TradeExecutor._load_ledger"):
        api = DummyAPI({"AAA": 50.0})
        ex = TradeExecutor(api)
        ex.configure(
            enabled=True,
            mode="paper",
            base_size=100.0,
            paper_starting_cash=1000.0,
            min_trade_interval_sec=10.0,
        )

        class Sig:
            def __init__(self, kind, index):
                self.kind = kind
                self.index = index

        t0 = 1_000_000.0
        # Monkeypatch global time.time so the executor's __import__('time').time() sees it
        import time as _time

        monkeypatch.setattr(_time, "time", lambda: t0)
        ex.on_signal("AAA", Sig("buy", index=1))

        # Within cooldown window -> blocked
        monkeypatch.setattr(_time, "time", lambda: t0 + 5.0)
        ex.on_signal("AAA", Sig("buy", index=2))

        # After cooldown -> allowed
        monkeypatch.setattr(_time, "time", lambda: t0 + 11.0)
        ex.on_signal("AAA", Sig("buy", index=3))

        snap = ex.portfolio_snapshot()
        # price=50, base_size=100 -> qty=2 per executed trade; 2 trades executed
        assert len(snap["positions"]) == 1
        assert math.isclose(snap["positions"][0]["qty"], 4.0, rel_tol=1e-6)


def test_on_signal_symbol_cooldown_enforced(monkeypatch):
    # Ensures symbol_cooldown_sec only blocks repeated trades on same symbol
    with patch("wsapp_gui.trade_executor.TradeExecutor._load_ledger"):
        api = DummyAPI({"AAA": 100.0, "BBB": 100.0})
        ex = TradeExecutor(api)
        ex.configure(
            enabled=True,
            mode="paper",
            base_size=100.0,
            paper_starting_cash=1000.0,
            symbol_cooldown_sec=30.0,
            min_trade_interval_sec=0.0,
        )

        class Sig:
            def __init__(self, kind, index):
                self.kind = kind
                self.index = index

        import time as _time

        t0 = 2_000_000.0
        monkeypatch.setattr(_time, "time", lambda: t0)
        ex.on_signal("AAA", Sig("buy", index=1))  # allowed

        # Same symbol within cooldown -> blocked
        monkeypatch.setattr(_time, "time", lambda: t0 + 5.0)
        ex.on_signal("AAA", Sig("buy", index=2))

        # Different symbol at same time -> allowed
        ex.on_signal("BBB", Sig("buy", index=3))

        snap = ex.portfolio_snapshot()
        # Two positions: AAA (1 trade) and BBB (1 trade)
        symbols = {p["symbol"]: p for p in snap["positions"]}
        assert set(symbols.keys()) == {"AAA", "BBB"}
        assert math.isclose(symbols["AAA"]["qty"], 1.0, rel_tol=1e-6)  # 100/100 = 1
        assert math.isclose(symbols["BBB"]["qty"], 1.0, rel_tol=1e-6)


def test_place_order_ignores_daily_limit_and_cooldowns():
    """
    By design, direct place_order bypasses max_trades_per_day and cooldown checks.
    This test documents that behavior: multiple direct orders still fill.
    """
    with patch("wsapp_gui.trade_executor.TradeExecutor._load_ledger"):
        api = DummyAPI({"AAA": 100.0})
        ex = TradeExecutor(api)
        ex.configure(
            enabled=True,
            mode="paper",
            base_size=1000.0,
            paper_starting_cash=10000.0,
            max_trades_per_day=1,
            min_trade_interval_sec=999.0,
            symbol_cooldown_sec=999.0,
        )

        o1 = ex.place_order(symbol="AAA", side="buy", order_type="market")
        o2 = ex.place_order(symbol="AAA", side="buy", order_type="market")

        assert o1["status"] == "filled"
        assert o2["status"] == "filled"

        snap = ex.portfolio_snapshot()
        # Two fills of 10 shares each (1000/100)
        assert len(snap["positions"]) == 1
        assert math.isclose(snap["positions"][0]["qty"], 20.0, rel_tol=1e-6)
