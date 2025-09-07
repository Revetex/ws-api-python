from __future__ import annotations

from collections.abc import Sequence

from .strategies import Signal


def run_signals_backtest(
    closes: Sequence[float], signals: list[Signal], initial_cash: float = 10000.0
) -> dict:
    """Very simple backtest: enter/exit full position on buy/sell signals at close prices.

    - Long-only, no fees/slippage. If multiple signals occur, process in order.
    """
    cash = float(initial_cash)
    qty = 0.0
    equity_curve: list[float] = []
    sig_idx = 0
    sigs_sorted = sorted(signals, key=lambda s: s.index)
    for i, close in enumerate(closes):
        # process any signals at i
        while sig_idx < len(sigs_sorted) and sigs_sorted[sig_idx].index == i:
            s = sigs_sorted[sig_idx]
            price = float(close)
            if s.kind == 'buy' and qty == 0.0:
                # buy max
                qty = cash / price if price > 0 else 0.0
                cash -= qty * price
            elif s.kind == 'sell' and qty > 0.0:
                # sell all
                cash += qty * price
                qty = 0.0
            sig_idx += 1
        # mark-to-market
        equity_curve.append(cash + qty * float(close))
    total_return = (equity_curve[-1] / initial_cash - 1.0) if equity_curve else 0.0
    return {
        'initial_cash': initial_cash,
        'final_equity': equity_curve[-1] if equity_curve else initial_cash,
        'total_return': total_return,
        'equity_curve': equity_curve,
        'trades': [s.to_dict() for s in sigs_sorted],
    }


def quick_backtest(
    closes: Sequence[float],
    signals: Sequence[Signal | tuple[int, str] | dict],
    initial_cash: float = 10000.0,
) -> dict:
    """Simplified backtest wrapper.

    Accepts signals as:
      - Signal objects
      - (index, kind) tuples
      - dicts with keys {index, kind}
    """
    norm_signals: list[Signal] = []
    for s in signals:
        if isinstance(s, Signal):
            norm_signals.append(s)
        elif isinstance(s, tuple) and len(s) == 2:
            idx, kind = s
            norm_signals.append(Signal(int(idx), str(kind), reason=f"tuple({idx},{kind})"))
        elif isinstance(s, dict) and 'index' in s and 'kind' in s:
            norm_signals.append(
                Signal(int(s['index']), str(s['kind']), reason=s.get('reason') or 'dict')
            )
    return run_signals_backtest(closes, norm_signals, initial_cash)


__all__ = ['run_signals_backtest', 'quick_backtest']
