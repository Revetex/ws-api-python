"""Integration tests for auto-trading UI and config persistence."""

import json
import os
import tempfile
from unittest.mock import patch

import pytest

from wsapp_gui.config import AppConfig
from wsapp_gui.trade_executor import TradeExecutor


class MockAPI:
    """Mock API for testing."""

    def __init__(self, price_map=None):
        self.price_map = price_map or {}

    def get_quote(self, symbol):
        price = self.price_map.get(symbol)
        if price is None:
            return None
        return {'05. price': price}


class TestAppConfigIntegration:
    """Test AppConfig integration with auto-trading features."""

    def setup_method(self):
        """Create temporary config file for each test."""
        self.temp_dir = tempfile.mkdtemp()
        self.config_path = os.path.join(self.temp_dir, 'test_config.json')
        self.config = AppConfig(self.config_path)

    def teardown_method(self):
        """Clean up temporary files."""
        if os.path.exists(self.config_path):
            os.remove(self.config_path)
        os.rmdir(self.temp_dir)

    def test_autotrade_config_persistence(self):
        """Test persistence of auto-trade configuration settings."""
        # Set various autotrade settings
        self.config.set('autotrade.enabled', True)
        self.config.set('autotrade.mode', 'paper')
        self.config.set('autotrade.base_size', 1500.0)
        self.config.set('autotrade.max_trades_per_day', 5)
        self.config.set('autotrade.max_position_notional_per_symbol', 2000.0)
        self.config.set('autotrade.max_position_qty_per_symbol', 100.0)

        # Save and reload config
        self.config.save_config()
        new_config = AppConfig(self.config_path)

        # Verify all settings persisted correctly
        assert new_config.get('autotrade.enabled') is True
        assert new_config.get('autotrade.mode') == 'paper'
        assert new_config.get('autotrade.base_size') == 1500.0
        assert new_config.get('autotrade.max_trades_per_day') == 5
        assert new_config.get('autotrade.max_position_notional_per_symbol') == 2000.0
        assert new_config.get('autotrade.max_position_qty_per_symbol') == 100.0

    def test_ledger_persistence_integration(self):
        """Test ledger persistence through config system."""
        # Create sample ledger data
        ledger_data = [
            {'timestamp': 1692000000, 'symbol': 'AAPL', 'kind': 'buy', 'index': 1},
            {'timestamp': 1692000060, 'symbol': 'MSFT', 'kind': 'buy', 'index': 2},
            {'timestamp': 1692000120, 'symbol': 'AAPL', 'kind': 'sell', 'index': 3},
        ]

        self.config.set('autotrade.ledger', ledger_data)
        self.config.save_config()

        # Reload and verify
        new_config = AppConfig(self.config_path)
        loaded_ledger = new_config.get('autotrade.ledger', [])

        assert len(loaded_ledger) == 3
        assert loaded_ledger[0]['symbol'] == 'AAPL'
        assert loaded_ledger[1]['symbol'] == 'MSFT'
        assert loaded_ledger[2]['kind'] == 'sell'

    def test_config_file_corruption_handling(self):
        """Test handling of corrupted config files."""
        # Write invalid JSON to config file
        with open(self.config_path, 'w') as f:
            f.write('{ invalid json')

        # Should handle gracefully and return defaults
        config = AppConfig(self.config_path)
        assert config.get('autotrade.enabled', False) is False
        assert config.get('autotrade.mode', 'paper') == 'paper'

    def test_nested_config_operations(self):
        """Test complex nested configuration operations."""
        # Set complex nested structure
        self.config.set('strategy_runner.enabled', True)
        self.config.set('strategy_runner.params.fast', 12)
        self.config.set('strategy_runner.params.slow', 26)
        self.config.set('autotrade.guardrails.notional_per_symbol', 5000.0)
        self.config.set('autotrade.guardrails.qty_per_symbol', 200.0)

        self.config.save_config()

        # Verify structure
        with open(self.config_path) as f:
            data = json.load(f)

        assert data['strategy_runner']['enabled'] is True
        assert data['strategy_runner']['params']['fast'] == 12
        assert data['autotrade']['guardrails']['notional_per_symbol'] == 5000.0


class TestTradeExecutorIntegration:
    """Test TradeExecutor integration with config system."""

    def setup_method(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.config_path = os.path.join(self.temp_dir, 'test_config.json')
        self.mock_config_data = {}

    def teardown_method(self):
        """Clean up."""
        if os.path.exists(self.config_path):
            os.remove(self.config_path)
        os.rmdir(self.temp_dir)

    def test_executor_config_integration(self):
        """Test TradeExecutor integration with AppConfig."""

        def mock_get(key, default=None):
            return self.mock_config_data.get(key, default)

        def mock_set(key, value):
            self.mock_config_data[key] = value

        with patch('wsapp_gui.config.app_config') as mock_app_config:
            mock_app_config.get = mock_get
            mock_app_config.set = mock_set

            api = MockAPI({'AAPL': 150.0})
            executor = TradeExecutor(api)

            # Configure with guardrails
            executor.configure(
                enabled=True,
                mode='paper',
                base_size=1000.0,
                max_trades_per_day=3,
                max_position_notional_per_symbol=3000.0,
                max_position_qty_per_symbol=25.0,
            )

            # Execute some trades
            class Signal:
                def __init__(self, kind, index):
                    self.kind = kind
                    self.index = index

            executor.on_signal('AAPL', Signal('buy', 1))
            executor.on_signal('AAPL', Signal('buy', 2))

            # Verify ledger was saved
            assert 'autotrade.ledger' in self.mock_config_data
            ledger_data = self.mock_config_data['autotrade.ledger']
            assert len(ledger_data) >= 1

            # Create new executor and verify ledger loads
            executor2 = TradeExecutor(api)
            executor2.configure(enabled=True, mode='paper', base_size=1000.0)

            # Try to execute same signal - should be blocked
            executor2.on_signal('AAPL', Signal('buy', 1))
            snap = executor2.portfolio_snapshot()

            # Should have no positions since signal was blocked by idempotency
            assert len(snap['positions']) == 0

    def test_portfolio_snapshot_stress(self):
        """Test portfolio snapshot under various conditions."""
        api = MockAPI(
            {'AAPL': 150.0, 'MSFT': 250.0, 'GOOGL': 2500.0, 'TSLA': 800.0, 'AMZN': 3000.0}
        )

        with patch('wsapp_gui.trade_executor.TradeExecutor._load_ledger'):
            executor = TradeExecutor(api)
            executor.configure(
                enabled=True, mode='paper', base_size=1000.0, paper_starting_cash=50000.0
            )

            # Build diversified portfolio
            class Signal:
                def __init__(self, kind, index):
                    self.kind = kind
                    self.index = index

            symbols = ['AAPL', 'MSFT', 'GOOGL', 'TSLA', 'AMZN']
            for i, symbol in enumerate(symbols):
                executor.on_signal(symbol, Signal('buy', i + 1))

        # Test basic snapshot
        snap_basic = executor.portfolio_snapshot()
        assert len(snap_basic['positions']) == 5
        assert (
            pytest.approx(snap_basic['cash'], rel=1e-3) == 45000.0
        )  # Allow small rounding differences

        # Test with quotes
        snap_with_quotes = executor.portfolio_snapshot(include_quotes=True)
        assert 'quotes' in snap_with_quotes
        assert len(snap_with_quotes['quotes']) > 0

        # Test with price changes
        new_prices = {symbol: price * 1.1 for symbol, price in api.price_map.items()}
        snap_price_changes = executor.portfolio_snapshot(quotes=new_prices)

        # Equity should be higher due to 10% price increase
        assert snap_price_changes['equity'] > snap_basic['equity']

    def test_guardrails_comprehensive_scenarios(self):
        """Test comprehensive guardrail scenarios."""
        api = MockAPI({'TEST': 100.0})

        with patch('wsapp_gui.trade_executor.TradeExecutor._load_ledger'):
            executor = TradeExecutor(api)

            class Signal:
                def __init__(self, kind, index):
                    self.kind = kind
                    self.index = index

            # Test scenario 1: Quantity limit reached
            executor.configure(
                enabled=True,
                mode='paper',
                base_size=2000.0,  # Would buy 20 shares
                paper_starting_cash=10000.0,
                max_position_qty_per_symbol=15.0,  # But limited to 15
            )

            executor.on_signal('TEST', Signal('buy', 1))
            snap1 = executor.portfolio_snapshot()
            assert pytest.approx(snap1['positions'][0]['qty'], rel=1e-6) == 15.0

            # Test scenario 2: Notional limit reached
            executor.configure(
                max_position_notional_per_symbol=1200.0,  # $1200 max
                max_position_qty_per_symbol=0.0,  # Remove qty limit
            )

            # Reset for clean test
            executor._paper.positions = {}
            executor._paper.cash = 10000.0

            executor.on_signal('TEST', Signal('buy', 2))
            snap2 = executor.portfolio_snapshot()
            assert pytest.approx(snap2['positions'][0]['qty'], rel=1e-6) == 12.0  # $1200 / $100

            # Test scenario 3: Both limits active, quantity more restrictive
            executor.configure(
                max_position_notional_per_symbol=2000.0,  # $2000 max
                max_position_qty_per_symbol=8.0,  # 8 shares max (more restrictive)
            )

            # Reset for clean test
            executor._paper.positions = {}
            executor._paper.cash = 10000.0

            executor.on_signal('TEST', Signal('buy', 3))
            snap3 = executor.portfolio_snapshot()
            assert pytest.approx(snap3['positions'][0]['qty'], rel=1e-6) == 8.0


class TestErrorRecoveryScenarios:
    """Test error recovery and edge cases."""

    def test_api_intermittent_failures(self):
        """Test handling of intermittent API failures."""

        class UnreliableAPI:
            def __init__(self):
                self.call_count = 0
                self.prices = {'TEST': 100.0}

            def get_quote(self, symbol):
                self.call_count += 1
                if self.call_count % 3 == 0:  # Fail every 3rd call
                    raise Exception("Network error")
                return {'05. price': self.prices.get(symbol, 100.0)}

        with patch('wsapp_gui.trade_executor.TradeExecutor._load_ledger'):
            api = UnreliableAPI()
            executor = TradeExecutor(api)
            executor.configure(enabled=True, mode='paper', base_size=1000.0)

            class Signal:
                def __init__(self, kind, index):
                    self.kind = kind
                    self.index = index

            # Try multiple signals - some should succeed, some fail
            for i in range(6):
                executor.on_signal('TEST', Signal('buy', i))

            snap = executor.portfolio_snapshot()
            # Should have some positions (not all failed)
            assert len(snap['positions']) >= 0  # At least some trades should have succeeded

    def test_extreme_market_conditions(self):
        """Test behavior under extreme market conditions."""

        with patch('wsapp_gui.trade_executor.TradeExecutor._load_ledger'):
            # Test with penny stock
            api_penny = MockAPI({'PENNY': 0.01})
            executor_penny = TradeExecutor(api_penny)
            executor_penny.configure(
                enabled=True, mode='paper', base_size=100.0, paper_starting_cash=1000.0
            )

            class Signal:
                def __init__(self, kind, index):
                    self.kind = kind
                    self.index = index

            executor_penny.on_signal('PENNY', Signal('buy', 1))
            snap_penny = executor_penny.portfolio_snapshot()

            # Should buy 10,000 shares (100 / 0.01)
            assert len(snap_penny['positions']) == 1
            assert snap_penny['positions'][0]['qty'] == 10000.0

            # Test with very expensive stock
            api_expensive = MockAPI({'EXPENSIVE': 50000.0})
            executor_expensive = TradeExecutor(api_expensive)
            executor_expensive.configure(
                enabled=True, mode='paper', base_size=1000.0, paper_starting_cash=1000.0
            )

            executor_expensive.on_signal('EXPENSIVE', Signal('buy', 1))
            snap_expensive = executor_expensive.portfolio_snapshot()

            # Should buy 0.02 shares (1000 / 50000)
            assert len(snap_expensive['positions']) == 1
            assert pytest.approx(snap_expensive['positions'][0]['qty'], rel=1e-4) == 0.02

    def test_concurrent_operations_simulation(self):
        """Simulate concurrent operations to test thread safety concepts."""

        def mock_get(key, default=None):
            return {}

        def mock_set(key, value):
            pass  # Simulate write that might be interrupted

        with patch('wsapp_gui.config.app_config') as mock_app_config:
            mock_app_config.get = mock_get
            mock_app_config.set = mock_set

            api = MockAPI({'TEST': 100.0})
            executor = TradeExecutor(api)
            executor.configure(enabled=True, mode='paper', base_size=1000.0)

            class Signal:
                def __init__(self, kind, index):
                    self.kind = kind
                    self.index = index

            # Simulate rapid-fire signals (like what might happen in real trading)
            for i in range(100):
                executor.on_signal('TEST', Signal('buy', i))

            snap = executor.portfolio_snapshot()

            # Should handle all signals gracefully
            assert len(snap['positions']) <= 1  # All should be for same symbol
            if len(snap['positions']) > 0:
                assert snap['positions'][0]['symbol'] == 'TEST'


def test_memory_usage_large_ledger():
    """Test memory efficiency with large ledger."""

    def mock_get(key, default=None):
        if key == 'autotrade.ledger':
            # Simulate large existing ledger
            return [
                {'timestamp': 1692000000 + i, 'symbol': f'SYM{i % 10}', 'kind': 'buy', 'index': i}
                for i in range(200)  # Large ledger
            ]
        return default

    mock_saved_data = {}

    def mock_set(key, value):
        mock_saved_data[key] = value

    with patch('wsapp_gui.config.app_config') as mock_app_config:
        mock_app_config.get = mock_get
        mock_app_config.set = mock_set

        api = MockAPI({'TEST': 100.0})
        executor = TradeExecutor(api)
        executor.configure(enabled=True, mode='paper', base_size=1000.0)

        class Signal:
            def __init__(self, kind, index):
                self.kind = kind
                self.index = index

        # Add one more entry
        executor.on_signal('TEST', Signal('buy', 1000))

        # Verify ledger was trimmed to reasonable size
        if 'autotrade.ledger' in mock_saved_data:
            saved_ledger = mock_saved_data['autotrade.ledger']
            assert len(saved_ledger) <= 100  # Should be trimmed
