from __future__ import annotations
from typing import Dict, List, Sequence
from .strategies import Signal


def run_signals_backtest(closes: Sequence[float], signals: List[Signal], initial_cash: float = 10000.0) -> Dict:
    """Very simple backtest: enter/exit full position on buy/sell signals at close prices.

    - Long-only, no fees/slippage. If multiple signals occur, process in order.
    """
    cash = float(initial_cash)
    qty = 0.0
    equity_curve: List[float] = []
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


__all__ = ['run_signals_backtest']
