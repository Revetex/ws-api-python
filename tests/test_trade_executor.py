import pytest
from datetime import date
from unittest.mock import patch

from wsapp_gui.trade_executor import TradeExecutor


class DummyAPI:
    def __init__(self, price_map):
        self.price_map = price_map
    
    def get_quote(self, symbol):
        p = self.price_map.get(symbol)
        if p is None:
            return None
        return {'05. price': p}


class Sig:
    def __init__(self, kind, index=0, reason=None, confidence=None):
        self.kind = kind
        self.index = index
        self.reason = reason
        self.confidence = confidence


def test_sizing_and_cash_reduction():
    with patch('wsapp_gui.trade_executor.TradeExecutor._load_ledger'):
        api = DummyAPI({'AAA': 100.0})
        ex = TradeExecutor(api)
        ex.configure(enabled=True, mode='paper', base_size=1000.0, paper_starting_cash=10000.0)
        ex.on_signal('AAA', Sig('buy', index=1))
        # 1000 / 100 = 10 shares
        snap = ex.portfolio_snapshot()
        assert pytest.approx(snap['cash'], rel=1e-3) == 10000.0 - 1000.0
        assert len(snap['positions']) == 1
        assert snap['positions'][0]['symbol'] == 'AAA'
        assert pytest.approx(snap['positions'][0]['qty'], rel=1e-6) == 10.0


def test_max_trades_per_day_enforced():
    with patch('wsapp_gui.trade_executor.TradeExecutor._load_ledger'):
        api = DummyAPI({'AAA': 50.0})
        ex = TradeExecutor(api)
        ex.configure(enabled=True, mode='paper', base_size=1000.0, paper_starting_cash=10000.0, max_trades_per_day=1)
        ex.on_signal('AAA', Sig('buy', index=1))
        ex.on_signal('AAA', Sig('buy', index=2))
        snap = ex.portfolio_snapshot()
        # Only one trade executed
        assert len(snap['positions']) == 1
        assert pytest.approx(snap['positions'][0]['qty'], rel=1e-6) == 20.0


def test_per_symbol_max_notional():
    with patch('wsapp_gui.trade_executor.TradeExecutor._load_ledger'):
        api = DummyAPI({'AAA': 100.0})
        ex = TradeExecutor(api)
        ex.configure(enabled=True, mode='paper', base_size=400.0, paper_starting_cash=10000.0, max_position_notional_per_symbol=500.0)
        # First buy -> 4 shares (400 notional)
        ex.on_signal('AAA', Sig('buy', index=1))
        # Second buy would attempt +4 shares (another 400) but capped to remaining 100 notional -> 1 share
        ex.on_signal('AAA', Sig('buy', index=2))
        snap = ex.portfolio_snapshot()
        qty = snap['positions'][0]['qty']
        assert pytest.approx(qty, rel=1e-6) == 5.0


def test_idempotency_ledger():
    with patch('wsapp_gui.trade_executor.TradeExecutor._load_ledger'):
        api = DummyAPI({'AAA': 10.0})
        ex = TradeExecutor(api)
        ex.configure(enabled=True, mode='paper', base_size=100.0, paper_starting_cash=1000.0)
        sig = Sig('buy', index=123)
        ex.on_signal('AAA', sig)
        ex.on_signal('AAA', sig)  # same index
        snap = ex.portfolio_snapshot()
        assert len(snap['positions']) == 1
        assert pytest.approx(snap['positions'][0]['qty'], rel=1e-6) == 10.0


def test_daily_rollover():
    """Test that trade counter resets on new day."""
    with patch('wsapp_gui.trade_executor.TradeExecutor._load_ledger'):
        api = DummyAPI({'AAA': 100.0})
        ex = TradeExecutor(api)
        ex.configure(enabled=True, mode='paper', base_size=1000.0, max_trades_per_day=1)
        
        # Set up initial state - day 1 with max trades reached
        ex._last_trade_day = date(2024, 1, 1)
        ex._trade_count_today = 1
        
        # Mock datetime to return day 2
        with patch('wsapp_gui.trade_executor.datetime') as mock_dt:
            mock_dt.now.return_value.date.return_value = date(2024, 1, 2)
            ex.on_signal('AAA', Sig('buy', index=1))
            # Counter should reset and trade should execute
            assert ex._trade_count_today == 1
            assert ex._last_trade_day == date(2024, 1, 2)
            snap = ex.portfolio_snapshot()
            assert len(snap['positions']) == 1


def test_per_symbol_max_quantity():
    """Test quantity-based position limits."""
    with patch('wsapp_gui.trade_executor.TradeExecutor._load_ledger'):
        api = DummyAPI({'AAA': 50.0})
        ex = TradeExecutor(api)
        ex.configure(enabled=True, mode='paper', base_size=1000.0, max_position_qty_per_symbol=30.0)
        
        # First buy: 1000/50 = 20 shares
        ex.on_signal('AAA', Sig('buy', index=1))
        # Second buy: would be +20 shares but capped to 10 more (max 30 total)
        ex.on_signal('AAA', Sig('buy', index=2))
        
        snap = ex.portfolio_snapshot()
        assert len(snap['positions']) == 1
        assert pytest.approx(snap['positions'][0]['qty'], rel=1e-6) == 30.0


def test_ledger_persistence():
    """Test that ledger entries are saved and loaded."""
    # Mock config for persistence
    mock_config = {}
    
    def mock_get(key, default=None):
        return mock_config.get(key, default)
    
    def mock_set(key, value):
        mock_config[key] = value
    
    # Test saving to ledger
    with patch('wsapp_gui.config.app_config') as mock_app_config:
        mock_app_config.get = mock_get
        mock_app_config.set = mock_set
        
        api = DummyAPI({'AAA': 100.0})
        ex = TradeExecutor(api)
        ex.configure(enabled=True, mode='paper', base_size=1000.0)
        ex.on_signal('AAA', Sig('buy', index=123))
        
        # Verify ledger was saved
        assert 'autotrade.ledger' in mock_config
        ledger_data = mock_config['autotrade.ledger']
        assert len(ledger_data) == 1
        assert ledger_data[0]['symbol'] == 'AAA'
        assert ledger_data[0]['kind'] == 'buy'
        assert ledger_data[0]['index'] == 123
    
    # Test loading from ledger
    with patch('wsapp_gui.config.app_config') as mock_app_config:
        mock_app_config.get = mock_get
        mock_app_config.set = mock_set
        
        # Create new executor - should load existing ledger
        api2 = DummyAPI({'AAA': 100.0})
        ex2 = TradeExecutor(api2)
        ex2.configure(enabled=True, mode='paper', base_size=1000.0)
        
        # Try to execute same signal - should be blocked by idempotency
        ex2.on_signal('AAA', Sig('buy', index=123))
        snap = ex2.portfolio_snapshot()
        assert len(snap['positions']) == 0  # No trade executed due to idempotency


def test_portfolio_snapshot_with_quotes():
    """Test portfolio snapshot with quote fetching and PnL calculation."""
    with patch('wsapp_gui.trade_executor.TradeExecutor._load_ledger'):
        api = DummyAPI({'AAA': 100.0, 'BBB': 50.0})
        ex = TradeExecutor(api)
        ex.configure(enabled=True, mode='paper', base_size=1000.0, paper_starting_cash=10000.0)
        
        # Buy some positions
        ex.on_signal('AAA', Sig('buy', index=1))  # 10 shares at 100
        ex.on_signal('BBB', Sig('buy', index=2))  # 20 shares at 50
        
        # Test with include_quotes=True
        snap = ex.portfolio_snapshot(include_quotes=True)
        
        assert 'quotes' in snap
        assert 'AAA' in snap['quotes'] or 'BBB' in snap['quotes']  # At least one should have quotes
        
        # Test with manual quotes (simulating price changes)
        snap_with_changes = ex.portfolio_snapshot(quotes={'AAA': 110.0, 'BBB': 45.0})
        
        # Cash should be 10000 - 2000 = 8000
        assert pytest.approx(snap_with_changes['cash'], rel=1e-3) == 8000.0
        
        # Equity should reflect new prices: 8000 + (10*110) + (20*45) = 8000 + 1100 + 900 = 10000
        assert pytest.approx(snap_with_changes['equity'], rel=1e-3) == 10000.0


# ===== ROBUST TEST CASES =====

def test_edge_case_zero_price():
    """Test handling of zero or negative prices."""
    with patch('wsapp_gui.trade_executor.TradeExecutor._load_ledger'):
        api = DummyAPI({'AAA': 0.0, 'BBB': -5.0})
        ex = TradeExecutor(api)
        ex.configure(enabled=True, mode='paper', base_size=1000.0, paper_starting_cash=10000.0)
        
        # Should skip trades with zero/negative prices
        ex.on_signal('AAA', Sig('buy', index=1))
        ex.on_signal('BBB', Sig('buy', index=2))
        
        snap = ex.portfolio_snapshot()
        assert len(snap['positions']) == 0
        assert snap['cash'] == 10000.0  # No cash used


def test_insufficient_cash_handling():
    """Test behavior when insufficient cash for full trade size."""
    with patch('wsapp_gui.trade_executor.TradeExecutor._load_ledger'):
        api = DummyAPI({'AAA': 100.0})
        ex = TradeExecutor(api)
        ex.configure(enabled=True, mode='paper', base_size=5000.0, paper_starting_cash=1000.0)
        
        # Should scale down to available cash: 1000/100 = 10 shares
        ex.on_signal('AAA', Sig('buy', index=1))
        
        snap = ex.portfolio_snapshot()
        assert len(snap['positions']) == 1
        assert pytest.approx(snap['positions'][0]['qty'], rel=1e-6) == 10.0
        assert pytest.approx(snap['cash'], rel=1e-3) == 0.0


def test_sell_signal_execution():
    """Test sell signal processing and cash return."""
    with patch('wsapp_gui.trade_executor.TradeExecutor._load_ledger'):
        api = DummyAPI({'AAA': 100.0})
        ex = TradeExecutor(api)
        ex.configure(enabled=True, mode='paper', base_size=1000.0, paper_starting_cash=10000.0)
        
        # Buy first
        ex.on_signal('AAA', Sig('buy', index=1))
        snap_after_buy = ex.portfolio_snapshot()
        assert pytest.approx(snap_after_buy['cash'], rel=1e-3) == 9000.0
        
        # Then sell
        ex.on_signal('AAA', Sig('sell', index=2))
        snap_after_sell = ex.portfolio_snapshot()
        
        # Should return all cash (assuming same price)
        assert pytest.approx(snap_after_sell['cash'], rel=1e-3) == 10000.0
        assert len(snap_after_sell['positions']) == 0


def test_partial_sell_handling():
    """Test selling when position exists but with partial quantity."""
    with patch('wsapp_gui.trade_executor.TradeExecutor._load_ledger'):
        api = DummyAPI({'AAA': 100.0})
        ex = TradeExecutor(api)
        ex.configure(enabled=True, mode='paper', base_size=1000.0, paper_starting_cash=10000.0)
        
        # Buy 10 shares
        ex.on_signal('AAA', Sig('buy', index=1))
        
        # Sell with smaller base_size (5 shares worth)
        ex.configure(base_size=500.0)
        ex.on_signal('AAA', Sig('sell', index=2))
        
        snap = ex.portfolio_snapshot()
        assert len(snap['positions']) == 1
        assert pytest.approx(snap['positions'][0]['qty'], rel=1e-6) == 5.0
        assert pytest.approx(snap['cash'], rel=1e-3) == 9500.0


def test_sell_empty_position():
    """Test sell signal when no position exists."""
    with patch('wsapp_gui.trade_executor.TradeExecutor._load_ledger'):
        api = DummyAPI({'AAA': 100.0})
        ex = TradeExecutor(api)
        ex.configure(enabled=True, mode='paper', base_size=1000.0, paper_starting_cash=10000.0)
        
        # Try to sell without position
        ex.on_signal('AAA', Sig('sell', index=1))
        
        snap = ex.portfolio_snapshot()
        assert len(snap['positions']) == 0
        assert snap['cash'] == 10000.0  # No change


def test_mixed_guardrails_enforcement():
    """Test both quantity and notional guardrails working together."""
    with patch('wsapp_gui.trade_executor.TradeExecutor._load_ledger'):
        api = DummyAPI({'AAA': 100.0})
        ex = TradeExecutor(api)
        ex.configure(
            enabled=True, mode='paper', base_size=2000.0, paper_starting_cash=10000.0,
            max_position_notional_per_symbol=1500.0,  # 15 shares max by notional
            max_position_qty_per_symbol=12.0          # 12 shares max by quantity
        )
        
        # First trade: 2000/100 = 20 shares, but capped to 12 by quantity limit
        ex.on_signal('AAA', Sig('buy', index=1))
        
        snap = ex.portfolio_snapshot()
        assert len(snap['positions']) == 1
        assert pytest.approx(snap['positions'][0]['qty'], rel=1e-6) == 12.0
        assert pytest.approx(snap['cash'], rel=1e-3) == 8800.0  # 10000 - 1200


def test_guardrails_with_existing_position():
    """Test guardrails considering existing positions."""
    with patch('wsapp_gui.trade_executor.TradeExecutor._load_ledger'):
        api = DummyAPI({'AAA': 50.0})
        ex = TradeExecutor(api)
        ex.configure(
            enabled=True, mode='paper', base_size=1000.0, paper_starting_cash=10000.0,
            max_position_qty_per_symbol=30.0
        )
        
        # First trade: 1000/50 = 20 shares
        ex.on_signal('AAA', Sig('buy', index=1))
        
        # Second trade: would be +20 but capped to +10 (total 30)
        ex.on_signal('AAA', Sig('buy', index=2))
        
        snap = ex.portfolio_snapshot()
        assert pytest.approx(snap['positions'][0]['qty'], rel=1e-6) == 30.0


def test_notional_guardrail_with_price_changes():
    """Test notional guardrail with different entry prices."""
    with patch('wsapp_gui.trade_executor.TradeExecutor._load_ledger'):
        # Start with price of 100
        api = DummyAPI({'AAA': 100.0})
        ex = TradeExecutor(api)
        ex.configure(
            enabled=True, mode='paper', base_size=1000.0, paper_starting_cash=10000.0,
            max_position_notional_per_symbol=1500.0
        )
        
        # First trade: 10 shares at $100 = $1000 notional
        ex.on_signal('AAA', Sig('buy', index=1))
        
        # Change price to $50
        api.price_map['AAA'] = 50.0
        
        # Second trade: would add 20 shares at $50, but limited by notional
        # Current position: 10 shares * $100 avg = $1000 notional
        # Remaining allowed: $1500 - $1000 = $500
        # At $50/share: can buy 10 more shares
        ex.on_signal('AAA', Sig('buy', index=2))
        
        snap = ex.portfolio_snapshot()
        assert pytest.approx(snap['positions'][0]['qty'], rel=1e-6) == 20.0


def test_disabled_executor():
    """Test that disabled executor doesn't execute trades."""
    with patch('wsapp_gui.trade_executor.TradeExecutor._load_ledger'):
        api = DummyAPI({'AAA': 100.0})
        ex = TradeExecutor(api)
        ex.configure(enabled=False, mode='paper', base_size=1000.0, paper_starting_cash=10000.0)
        
        ex.on_signal('AAA', Sig('buy', index=1))
        
        snap = ex.portfolio_snapshot()
        assert len(snap['positions']) == 0
        assert snap['cash'] == 10000.0


def test_live_mode_stub():
    """Test that live mode doesn't affect paper portfolio."""
    with patch('wsapp_gui.trade_executor.TradeExecutor._load_ledger'):
        api = DummyAPI({'AAA': 100.0})
        ex = TradeExecutor(api)
        ex.configure(enabled=True, mode='live', base_size=1000.0, paper_starting_cash=10000.0)
        
        ex.on_signal('AAA', Sig('buy', index=1))
        
        snap = ex.portfolio_snapshot()
        assert snap['mode'] == 'live'
        assert snap['cash'] is None
        assert snap['equity'] is None
        assert len(snap['positions']) == 0


def test_complex_idempotency_scenario():
    """Test idempotency with mixed buy/sell signals and different indexes."""
    with patch('wsapp_gui.trade_executor.TradeExecutor._load_ledger'):
        api = DummyAPI({'AAA': 100.0, 'BBB': 50.0})
        ex = TradeExecutor(api)
        ex.configure(enabled=True, mode='paper', base_size=1000.0, paper_starting_cash=10000.0)
        
        # Execute various signals
        ex.on_signal('AAA', Sig('buy', index=1))    # Should execute
        ex.on_signal('AAA', Sig('buy', index=1))    # Should be blocked (same index)
        ex.on_signal('AAA', Sig('sell', index=1))   # Should execute (different kind)
        ex.on_signal('BBB', Sig('buy', index=1))    # Should execute (different symbol)
        ex.on_signal('AAA', Sig('buy', index=2))    # Should execute (different index)
        
        snap = ex.portfolio_snapshot()
        
        # AAA: buy then sell = 0, then buy again = 10 shares
        # BBB: buy = 20 shares
        assert len(snap['positions']) == 2
        aaa_pos = next(p for p in snap['positions'] if p['symbol'] == 'AAA')
        bbb_pos = next(p for p in snap['positions'] if p['symbol'] == 'BBB')
        assert pytest.approx(aaa_pos['qty'], rel=1e-6) == 10.0
        assert pytest.approx(bbb_pos['qty'], rel=1e-6) == 20.0


def test_ledger_persistence_with_multiple_entries():
    """Test ledger persistence with multiple symbols and operations."""
    mock_config = {}
    
    def mock_get(key, default=None):
        return mock_config.get(key, default)
    
    def mock_set(key, value):
        mock_config[key] = value
    
    with patch('wsapp_gui.config.app_config') as mock_app_config:
        mock_app_config.get = mock_get
        mock_app_config.set = mock_set
        
        api = DummyAPI({'AAA': 100.0, 'BBB': 50.0})
        ex = TradeExecutor(api)
        ex.configure(enabled=True, mode='paper', base_size=1000.0)
        
        # Execute multiple trades
        ex.on_signal('AAA', Sig('buy', index=1))
        ex.on_signal('BBB', Sig('buy', index=2))
        ex.on_signal('AAA', Sig('sell', index=3))
        
        # Verify ledger contains all entries
        ledger_data = mock_config['autotrade.ledger']
        assert len(ledger_data) == 3
        
        # Verify entries have correct structure
        for entry in ledger_data:
            assert 'timestamp' in entry
            assert 'symbol' in entry
            assert 'kind' in entry
            assert 'index' in entry
        
        # Verify specific entries
        symbols = [entry['symbol'] for entry in ledger_data]
        kinds = [entry['kind'] for entry in ledger_data]
        indexes = [entry['index'] for entry in ledger_data]
        
        assert 'AAA' in symbols
        assert 'BBB' in symbols
        assert 'buy' in kinds
        assert 'sell' in kinds
        assert 1 in indexes
        assert 2 in indexes
        assert 3 in indexes


def test_portfolio_equity_calculation_accuracy():
    """Test accurate equity calculation with multiple positions and price changes."""
    with patch('wsapp_gui.trade_executor.TradeExecutor._load_ledger'):
        api = DummyAPI({'AAA': 100.0, 'BBB': 50.0, 'CCC': 25.0})
        ex = TradeExecutor(api)
        ex.configure(enabled=True, mode='paper', base_size=1000.0, paper_starting_cash=15000.0)
        
        # Build diverse portfolio
        ex.on_signal('AAA', Sig('buy', index=1))  # 10 shares at $100
        ex.on_signal('BBB', Sig('buy', index=2))  # 20 shares at $50
        ex.on_signal('CCC', Sig('buy', index=3))  # 40 shares at $25
        
        # Test with significant price changes
        new_quotes = {
            'AAA': 120.0,  # +20% gain
            'BBB': 40.0,   # -20% loss
            'CCC': 30.0    # +20% gain
        }
        
        snap = ex.portfolio_snapshot(quotes=new_quotes)
        
        # Expected equity calculation:
        # Cash: 15000 - 3000 = 12000
        # AAA: 10 * 120 = 1200 (was 1000, +200 gain)
        # BBB: 20 * 40 = 800 (was 1000, -200 loss)
        # CCC: 40 * 30 = 1200 (was 1000, +200 gain)
        # Total: 12000 + 1200 + 800 + 1200 = 15200
        
        expected_equity = 15200.0
        assert pytest.approx(snap['equity'], rel=1e-3) == expected_equity


def test_error_handling_api_failures():
    """Test graceful handling of API quote failures."""
    class FailingAPI:
        def get_quote(self, symbol):
            raise Exception("API Error")
    
    with patch('wsapp_gui.trade_executor.TradeExecutor._load_ledger'):
        api = FailingAPI()
        ex = TradeExecutor(api)
        ex.configure(enabled=True, mode='paper', base_size=1000.0, paper_starting_cash=10000.0)
        
        # Should skip trade due to quote failure
        ex.on_signal('AAA', Sig('buy', index=1))
        
        snap = ex.portfolio_snapshot()
        assert len(snap['positions']) == 0
        assert snap['cash'] == 10000.0


def test_configuration_validation():
    """Test configuration parameter validation and edge cases."""
    with patch('wsapp_gui.trade_executor.TradeExecutor._load_ledger'):
        api = DummyAPI({'AAA': 100.0})
        ex = TradeExecutor(api)
        
        # Test negative values are handled
        ex.configure(
            enabled=True,
            mode='invalid_mode',  # Should default to 'paper'
            base_size=-1000.0,    # Should be set to 0
            max_trades_per_day=-5,  # Should be set to 0
            max_position_notional_per_symbol=-100.0,  # Should be set to 0
            max_position_qty_per_symbol=-50.0         # Should be set to 0
        )
        
        assert ex.mode == 'paper'
        assert ex.base_size == 0.0
        assert ex.max_trades_per_day == 0
        assert ex.max_position_notional_per_symbol == 0.0
        assert ex.max_position_qty_per_symbol == 0.0


def test_large_scale_trading_scenario():
    """Test performance and accuracy with many trades and positions."""
    with patch('wsapp_gui.trade_executor.TradeExecutor._load_ledger'):
        # Create many symbols
        symbols = [f'SYM{i:03d}' for i in range(100)]
        price_map = {sym: 50.0 + i for i, sym in enumerate(symbols)}
        
        api = DummyAPI(price_map)
        ex = TradeExecutor(api)
        ex.configure(enabled=True, mode='paper', base_size=100.0, paper_starting_cash=50000.0)
        
        # Execute trades for first 20 symbols
        for i, symbol in enumerate(symbols[:20]):
            ex.on_signal(symbol, Sig('buy', index=i))
        
        snap = ex.portfolio_snapshot()
        
        # Should have positions (may be less than 20 if cash runs out)
        assert len(snap['positions']) >= 10  # At least 10 positions should be possible
        assert len(snap['positions']) <= 20  # But not more than attempted
        
        # Verify total cash usage is reasonable
        expected_cash_used = 20 * 100.0  # 20 trades * $100 each
        expected_remaining_cash = 50000.0 - expected_cash_used
        assert snap['cash'] >= expected_remaining_cash * 0.9  # Allow for rounding and fewer positions
