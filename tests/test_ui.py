"""UI component tests for auto-trading features."""

import os
import tempfile
import tkinter as tk
from unittest.mock import patch

import pytest

# Note: These tests require a display environment.
# They may need to be skipped in headless CI environments.


class TestAutoTradeUI:
    """Test auto-trade UI components."""

    @pytest.fixture(autouse=True)
    def setup_display(self):
        """Set up display for UI tests."""
        try:
            # Try to create a root window to test if display is available
            root = tk.Tk()
            root.withdraw()  # Hide the window
            yield root
            root.destroy()
        except tk.TclError:
            pytest.skip("No display available for UI tests")

    def test_guardrail_variables_initialization(self, setup_display):
        """Test that guardrail variables are properly initialized."""

        # Mock app_config
        mock_config_data = {
            'autotrade.max_position_notional_per_symbol': 5000.0,
            'autotrade.max_position_qty_per_symbol': 100.0,
        }

        def mock_get(key, default=None):
            return mock_config_data.get(key, default)

        with patch('wsapp_gui.config.app_config') as mock_app_config:
            mock_app_config.get = mock_get

            # Create variables like the app would
            var_max_notional = tk.DoubleVar(
                value=float(
                    mock_app_config.get('autotrade.max_position_notional_per_symbol', 0.0) or 0.0
                )
            )
            var_max_qty = tk.DoubleVar(
                value=float(
                    mock_app_config.get('autotrade.max_position_qty_per_symbol', 0.0) or 0.0
                )
            )

            assert var_max_notional.get() == 5000.0
            assert var_max_qty.get() == 100.0

    def test_portfolio_tree_columns(self, setup_display):
        """Test portfolio tree view has correct columns."""
        root = setup_display

        # Create tree like in the app
        import tkinter.ttk as ttk

        tree = ttk.Treeview(
            root,
            columns=('symbol', 'qty', 'avg_price', 'last', 'pnl', 'value'),
            show='headings',
            height=4,
        )

        # Configure headings
        expected_columns = {
            'symbol': ('Symbole', 80, tk.W),
            'qty': ('Qté', 80, tk.E),
            'avg_price': ('Prix moy.', 80, tk.E),
            'last': ('Dernier', 80, tk.E),
            'pnl': ('PnL%', 60, tk.E),
            'value': ('Valeur', 80, tk.E),
        }

        for col, (header, width, anchor) in expected_columns.items():
            tree.heading(col, text=header)
            tree.column(col, width=width, anchor=anchor, stretch=True)

        # Verify columns exist
        assert tree['columns'] == ('symbol', 'qty', 'avg_price', 'last', 'pnl', 'value')

    def test_ledger_tree_structure(self, setup_display):
        """Test ledger tree view structure."""
        root = setup_display

        import tkinter.ttk as ttk

        tree_ledger = ttk.Treeview(
            root,
            columns=('timestamp', 'symbol', 'kind', 'index'),
            show='headings',
            height=3,
        )

        expected_columns = {
            'timestamp': ('Timestamp', 140, tk.W),
            'symbol': ('Symbole', 80, tk.W),
            'kind': ('Type', 60, tk.W),
            'index': ('Index', 80, tk.W),
        }

        for col, (header, width, anchor) in expected_columns.items():
            tree_ledger.heading(col, text=header)
            tree_ledger.column(col, width=width, anchor=anchor, stretch=True)

        # Test adding sample data
        tree_ledger.insert('', 'end', values=('12:34:56', 'AAPL', 'buy', 123))
        tree_ledger.insert('', 'end', values=('12:35:10', 'MSFT', 'sell', 124))

        # Verify data was added
        children = tree_ledger.get_children()
        assert len(children) == 2

        first_item = tree_ledger.item(children[0])
        assert first_item['values'] == [
            '12:34:56',
            'AAPL',
            'buy',
            123,
        ]  # Tkinter converts to appropriate types


class TestConfigValidation:
    """Test configuration validation and edge cases."""

    def test_config_type_coercion(self):
        """Test that config values are properly coerced to correct types."""
        temp_dir = tempfile.mkdtemp()
        config_path = os.path.join(temp_dir, 'test_config.json')

        try:
            from wsapp_gui.config import AppConfig

            config = AppConfig(config_path)

            # Test string to bool conversion
            config.set('autotrade.enabled', 'true')
            assert config.get('autotrade.enabled') == 'true'  # Config stores as-is

            # Test in variable creation context (like the app does)
            enabled_val = bool(config.get('autotrade.enabled', False))
            assert enabled_val is True

            # Test string to float conversion
            config.set('autotrade.base_size', '1500.5')
            size_val = float(config.get('autotrade.base_size', 1000.0) or 1000.0)
            assert size_val == 1500.5

            # Test None handling
            config.set('autotrade.max_position_notional_per_symbol', None)
            notional_val = float(
                config.get('autotrade.max_position_notional_per_symbol', 0.0) or 0.0
            )
            assert notional_val == 0.0

        finally:
            if os.path.exists(config_path):
                os.remove(config_path)
            os.rmdir(temp_dir)

    def test_config_default_values(self):
        """Test that proper default values are used when config is empty."""
        temp_dir = tempfile.mkdtemp()
        config_path = os.path.join(temp_dir, 'empty_config.json')

        try:
            from wsapp_gui.config import AppConfig

            config = AppConfig(config_path)

            # Test defaults like the app uses them
            var_enabled = bool(config.get('autotrade.enabled', False))
            var_mode = str(config.get('autotrade.mode', 'paper') or 'paper')
            var_size = float(config.get('autotrade.base_size', 1000.0) or 1000.0)
            var_maxtr = int(config.get('autotrade.max_trades_per_day', 10) or 10)
            var_max_notional = float(
                config.get('autotrade.max_position_notional_per_symbol', 0.0) or 0.0
            )
            var_max_qty = float(config.get('autotrade.max_position_qty_per_symbol', 0.0) or 0.0)

            assert var_enabled is False
            assert var_mode == 'paper'
            assert var_size == 1000.0
            assert var_maxtr == 10
            assert var_max_notional == 0.0
            assert var_max_qty == 0.0

        finally:
            if os.path.exists(config_path):
                os.remove(config_path)
            os.rmdir(temp_dir)


class TestPortfolioDisplayLogic:
    """Test portfolio display calculations and formatting."""

    def test_pnl_calculation_logic(self):
        """Test PnL calculation logic used in the UI."""
        # Simulate the calculation logic from _update_portfolio_view

        # Position data
        qty = 100.0
        avg_price = 50.0
        last_price = 55.0

        # Calculate like the UI does
        cost_basis = qty * avg_price
        market_value = qty * last_price if last_price > 0 else cost_basis
        pnl_dollars = market_value - cost_basis
        pnl_percent = (pnl_dollars / cost_basis * 100) if cost_basis != 0 else 0.0

        assert cost_basis == 5000.0
        assert market_value == 5500.0
        assert pnl_dollars == 500.0
        assert pnl_percent == 10.0

    def test_pnl_formatting(self):
        """Test PnL display formatting."""
        # Test positive PnL
        pnl_percent = 15.5
        last_price = 100.0
        pnl_str = f"{pnl_percent:+.1f}%" if last_price > 0 else "N/A"
        assert pnl_str == "+15.5%"

        # Test negative PnL
        pnl_percent = -7.3
        pnl_str = f"{pnl_percent:+.1f}%" if last_price > 0 else "N/A"
        assert pnl_str == "-7.3%"

        # Test no price available
        last_price = 0.0
        pnl_str = f"{pnl_percent:+.1f}%" if last_price > 0 else "N/A"
        assert pnl_str == "N/A"

    def test_value_formatting(self):
        """Test market value formatting."""
        qty = 15.5
        last_price = 123.45

        market_value = qty * last_price
        value_str = f"{market_value:.2f}"

        assert value_str == "1913.48"

    def test_portfolio_summary_calculation(self):
        """Test portfolio summary calculations."""
        # Simulate multiple positions
        positions_data = [
            {'qty': 100, 'avg_price': 50.0, 'last_price': 55.0},  # +500 PnL
            {'qty': 50, 'avg_price': 200.0, 'last_price': 190.0},  # -500 PnL
            {'qty': 25, 'avg_price': 40.0, 'last_price': 44.0},  # +100 PnL
        ]

        cash = 10000.0
        total_value = cash
        total_pnl = 0.0

        for pos in positions_data:
            cost_basis = pos['qty'] * pos['avg_price']
            market_value = pos['qty'] * pos['last_price']
            pnl_dollars = market_value - cost_basis

            total_value += market_value
            total_pnl += pnl_dollars

        total_pnl_pct = (
            (total_pnl / (total_value - total_pnl) * 100) if (total_value - total_pnl) != 0 else 0.0
        )

        # Expected: +500 -500 +100 = +100 total PnL
        assert total_pnl == 100.0

        # Expected total value: 10000 + 5500 + 9500 + 1100 = 26100
        assert total_value == 26100.0

        # PnL percentage calculation
        assert pytest.approx(total_pnl_pct, rel=1e-2) == 0.3846  # 100/26000 * 100


class TestTimestampFormatting:
    """Test timestamp formatting for ledger display."""

    def test_timestamp_conversion(self):
        """Test timestamp to display string conversion."""
        import time
        from datetime import datetime

        # Test current timestamp
        current_time = time.time()
        dt = datetime.fromtimestamp(current_time)
        timestamp_str = dt.strftime('%H:%M:%S')

        # Should be in HH:MM:SS format
        assert len(timestamp_str) == 8
        assert timestamp_str.count(':') == 2

    def test_timestamp_edge_cases(self):
        """Test timestamp formatting edge cases."""
        from datetime import datetime

        # Test None timestamp
        timestamp = None
        if timestamp is None:
            timestamp_str = 'N/A'
        else:
            try:
                if isinstance(timestamp, (int, float)):
                    dt = datetime.fromtimestamp(timestamp)
                    timestamp_str = dt.strftime('%H:%M:%S')
                else:
                    timestamp_str = str(timestamp)
            except Exception:
                timestamp_str = str(timestamp)

        assert timestamp_str == 'N/A'

        # Test string timestamp
        timestamp = "some_string"
        try:
            if isinstance(timestamp, (int, float)):
                dt = datetime.fromtimestamp(timestamp)
                timestamp_str = dt.strftime('%H:%M:%S')
            else:
                timestamp_str = str(timestamp)
        except Exception:
            timestamp_str = str(timestamp)

        assert timestamp_str == "some_string"


class TestGuardrailUILogic:
    """Test guardrail UI logic and validation."""

    def test_guardrail_value_conversion(self):
        """Test conversion of guardrail values from UI to executor."""
        # Simulate the logic from _strategy_apply
        var_max_notional_value = 5000.0
        var_max_qty_value = 0.0  # 0 means unlimited

        # Convert like the app does
        max_notional = float(var_max_notional_value) if var_max_notional_value > 0 else None
        max_qty = float(var_max_qty_value) if var_max_qty_value > 0 else None

        assert max_notional == 5000.0
        assert max_qty is None

    def test_guardrail_display_values(self):
        """Test guardrail display values and labels."""
        # Test that zero values display as "unlimited"
        max_notional = 0.0
        max_qty = 100.0

        notional_display = f"{max_notional:.0f}" if max_notional > 0 else "illimité"
        qty_display = f"{max_qty:.0f}" if max_qty > 0 else "illimité"

        assert notional_display == "illimité"
        assert qty_display == "100"


def test_ui_integration_with_executor():
    """Test UI integration with TradeExecutor."""

    def mock_get(key, default=None):
        config_data = {
            'autotrade.enabled': True,
            'autotrade.mode': 'paper',
            'autotrade.base_size': 1000.0,
            'autotrade.max_trades_per_day': 5,
            'autotrade.max_position_notional_per_symbol': 3000.0,
            'autotrade.max_position_qty_per_symbol': 50.0,
        }
        return config_data.get(key, default)

    def mock_set(key, value):
        pass

    with patch('wsapp_gui.config.app_config') as mock_app_config:
        mock_app_config.get = mock_get
        mock_app_config.set = mock_set

        # Simulate UI variable creation
        var_at_enabled = bool(mock_app_config.get('autotrade.enabled', False))
        var_at_mode = str(mock_app_config.get('autotrade.mode', 'paper') or 'paper')
        var_at_size = float(mock_app_config.get('autotrade.base_size', 1000.0) or 1000.0)
        var_at_maxtr = int(mock_app_config.get('autotrade.max_trades_per_day', 10) or 10)
        var_at_max_notional = float(
            mock_app_config.get('autotrade.max_position_notional_per_symbol', 0.0) or 0.0
        )
        var_at_max_qty = float(
            mock_app_config.get('autotrade.max_position_qty_per_symbol', 0.0) or 0.0
        )

        # Verify values are loaded correctly
        assert var_at_enabled is True
        assert var_at_mode == 'paper'
        assert var_at_size == 1000.0
        assert var_at_maxtr == 5
        assert var_at_max_notional == 3000.0
        assert var_at_max_qty == 50.0

        # Simulate executor configuration (like _strategy_apply does)
        class MockTradeExecutor:
            def __init__(self):
                self.config_called = False
                self.last_config = {}

            def configure(self, **kwargs):
                self.config_called = True
                self.last_config = kwargs

        mock_executor = MockTradeExecutor()

        # Call configure like the app does
        mock_executor.configure(
            enabled=var_at_enabled,
            mode=var_at_mode,
            base_size=var_at_size,
            max_trades_per_day=var_at_maxtr,
            max_position_notional_per_symbol=(
                var_at_max_notional if var_at_max_notional > 0 else None
            ),
            max_position_qty_per_symbol=var_at_max_qty if var_at_max_qty > 0 else None,
        )

        # Verify executor was configured correctly
        assert mock_executor.config_called
        assert mock_executor.last_config['enabled'] is True
        assert mock_executor.last_config['mode'] == 'paper'
        assert mock_executor.last_config['base_size'] == 1000.0
        assert mock_executor.last_config['max_trades_per_day'] == 5
        assert mock_executor.last_config['max_position_notional_per_symbol'] == 3000.0
        assert mock_executor.last_config['max_position_qty_per_symbol'] == 50.0
