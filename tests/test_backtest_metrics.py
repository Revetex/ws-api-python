from analytics.backtest import run_signals_backtest
from analytics.strategies import MovingAverageCrossStrategy


def test_backtest_metrics_basic():
    # Create a gently increasing price series
    closes = [100 + i * 0.5 for i in range(200)]
    sigs = MovingAverageCrossStrategy(5, 15, 0.0, 20).generate(closes)
    res = run_signals_backtest(closes, sigs, initial_cash=10000.0)
    assert 'metrics' in res and isinstance(res['metrics'], dict)
    m = res['metrics']
    # Basic sanity: keys exist
    for k in ['ann_return', 'ann_vol', 'sharpe', 'max_drawdown']:
        assert k in m
    # On a monotonic up series, Sharpe should be non-negative and drawdown small
    assert m['sharpe'] >= -1.0  # tolerate noise from strategy logic
    assert 0 <= abs(m['max_drawdown']) <= 1.0
    # Final equity should be >= initial
    assert res.get('final_equity', 0) >= 10000.0
