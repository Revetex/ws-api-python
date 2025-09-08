from __future__ import annotations

from collections.abc import Sequence

from .strategies import Signal


def _equity_metrics(equity: Sequence[float], periods_per_year: int = 252) -> dict:
    """Compute basic performance metrics from an equity curve.

    - Annualized return (CAGR), annualized volatility, Sharpe (rf~0), and max drawdown.
    """
    try:
        n = len(equity)
        if n < 2:
            return {
                'ann_return': 0.0,
                'ann_vol': 0.0,
                'sharpe': 0.0,
                'max_drawdown': 0.0,
                'max_drawdown_start': None,
                'max_drawdown_end': None,
            }
        import math

        # Simple returns
        rets = []
        for i in range(1, n):
            prev = float(equity[i - 1])
            cur = float(equity[i])
            if prev <= 0:
                continue
            rets.append(cur / prev - 1.0)
        total = float(equity[-1]) / float(equity[0]) if equity[0] > 0 else 1.0
        ann_return = (total ** (periods_per_year / max(1, len(rets)))) - 1.0 if total > 0 else 0.0
        # Volatility (population std) annualized
        if len(rets) >= 2:
            mean = sum(rets) / len(rets)
            var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
            vol = math.sqrt(var) * math.sqrt(periods_per_year)
        else:
            vol = 0.0
        sharpe = (ann_return / vol) if vol > 1e-12 else 0.0
        # Max drawdown
        peak = float(equity[0])
        max_dd = 0.0
        dd_start = 0
        dd_end = 0
        cur_start = 0
        for i, v in enumerate(equity):
            x = float(v)
            if x > peak:
                peak = x
                cur_start = i
            drawdown = (x / peak - 1.0) if peak > 0 else 0.0
            if drawdown < max_dd:
                max_dd = drawdown
                dd_start = cur_start
                dd_end = i
        return {
            'ann_return': ann_return,
            'ann_vol': vol,
            'sharpe': sharpe,
            'max_drawdown': max_dd,
            'max_drawdown_start': dd_start if max_dd < 0 else None,
            'max_drawdown_end': dd_end if max_dd < 0 else None,
        }
    except Exception:
        # Fail-soft
        return {
            'ann_return': 0.0,
            'ann_vol': 0.0,
            'sharpe': 0.0,
            'max_drawdown': 0.0,
            'max_drawdown_start': None,
            'max_drawdown_end': None,
        }


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
    # Trade stats (pair BUY then SELL at signal indices)
    trade_stats = {'count': 0, 'winners': 0, 'win_rate': 0.0, 'avg_return': 0.0}
    try:
        in_price: float | None = None
        per_trade_returns: list[float] = []
        for s in sigs_sorted:
            px = float(closes[s.index]) if 0 <= s.index < len(closes) else None
            if px is None or px <= 0:
                continue
            if s.kind == 'buy' and in_price is None:
                in_price = px
            elif s.kind == 'sell' and in_price is not None:
                r = (px / in_price) - 1.0
                per_trade_returns.append(r)
                in_price = None
        if per_trade_returns:
            winners = sum(1 for r in per_trade_returns if r > 0)
            trade_stats['count'] = len(per_trade_returns)
            trade_stats['winners'] = winners
            trade_stats['win_rate'] = winners / len(per_trade_returns)
            trade_stats['avg_return'] = sum(per_trade_returns) / len(per_trade_returns)
    except Exception:
        pass
    metrics = _equity_metrics(equity_curve)
    return {
        'initial_cash': initial_cash,
        'final_equity': equity_curve[-1] if equity_curve else initial_cash,
        'total_return': total_return,
        'equity_curve': equity_curve,
        'trades': [s.to_dict() for s in sigs_sorted],
        'metrics': metrics,
        'trade_stats': trade_stats,
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


if __name__ == '__main__':  # simple CLI for quick backtests
    import argparse
    import json
    from pathlib import Path

    try:
        # Prefer absolute import when running as a script from project root
        from analytics.strategies import (  # type: ignore
            ConfluenceStrategy,
            MovingAverageCrossStrategy,
            RSIReversionStrategy,
        )
    except Exception:  # pragma: no cover - fallback for package execution
        from .strategies import (  # type: ignore
            ConfluenceStrategy,
            MovingAverageCrossStrategy,
            RSIReversionStrategy,
        )

    def _extract_closes(series: dict) -> list[float]:
        closes: list[float] = []
        try:
            k = next((k for k in series.keys() if 'Time Series' in k), None)
            ts = series.get(k) if k else None
            if isinstance(ts, dict):
                for _d, row in sorted(ts.items()):
                    try:
                        closes.append(float(row.get('4. close') or row.get('4. Close') or 0.0))
                    except Exception:
                        pass
        except Exception:
            pass
        return closes

    ap = argparse.ArgumentParser(description='Quick backtest CLI')
    ap.add_argument('symbol', nargs='?', help='Symbol (uses API if available)')
    ap.add_argument('--csv', help='CSV file with one close per line (fallback if no API)')
    ap.add_argument('--interval', default='1day', help='1day|1week|1month (API mode)')
    ap.add_argument('--size', default='compact', help='compact|full (API mode)')
    ap.add_argument('--cash', type=float, default=10000.0, help='Initial cash')
    ap.add_argument('--strategy', default='ma_cross', choices=['ma_cross', 'rsi', 'confluence'])
    ap.add_argument('--fast', type=int, default=10)
    ap.add_argument('--slow', type=int, default=30)
    ap.add_argument('--rsi-period', type=int, default=14)
    ap.add_argument('--rsi-low', type=int, default=30)
    ap.add_argument('--rsi-high', type=int, default=70)
    ap.add_argument('--min-bw', type=float, default=0.0, help='Min Bollinger bandwidth filter')
    ap.add_argument('--bb-window', type=int, default=20)
    ap.add_argument('--json', action='store_true', help='Output JSON summary')
    args = ap.parse_args()

    closes: list[float] = []
    symbol = (args.symbol or '').upper()
    # Prefer CSV if provided
    if args.csv:
        p = Path(args.csv)
        if not p.exists():
            ap.error(f'CSV file not found: {p}')
        with p.open('r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                try:
                    closes.append(float(line.split(',')[0]))
                except Exception:
                    continue
    elif symbol:
        try:
            # Best-effort API fetch via external_apis APIManager
            from external_apis import APIManager  # type: ignore

            api = APIManager()
            series = api.get_time_series(symbol, interval=args.interval, outputsize=args.size)
            closes = _extract_closes(series or {})
        except Exception:
            pass
    if len(closes) < 5:
        ap.error('Not enough data. Provide --csv with closes or a valid symbol with API access.')

    # Build signals
    if args.strategy == 'rsi':
        sigs = RSIReversionStrategy(
            args.rsi_period, args.rsi_low, args.rsi_high, args.min_bw, args.bb_window
        ).generate(closes)
    elif args.strategy == 'confluence':
        fast = args.fast
        slow = args.slow if args.slow > fast else fast + 1
        sigs = ConfluenceStrategy(
            fast,
            slow,
            args.rsi_period,
            max(args.rsi_high, args.rsi_low + 1),
            min(args.rsi_low, args.rsi_high - 1),
            args.min_bw,
            args.bb_window,
        ).generate(closes)
    else:
        fast = args.fast
        slow = args.slow if args.slow > fast else fast + 1
        sigs = MovingAverageCrossStrategy(fast, slow, args.min_bw, args.bb_window).generate(closes)

    res = run_signals_backtest(closes, sigs, initial_cash=args.cash)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        m = res.get('metrics', {})
        ts = res.get('trade_stats', {})
        print(
            f"Final: {res.get('final_equity'):.2f} | Return: {res.get('total_return', 0)*100:.2f}%\n"
            f"Ann: {m.get('ann_return', 0)*100:.2f}% | Vol: {m.get('ann_vol', 0)*100:.2f}% | Sharpe: {m.get('sharpe', 0):.2f}\n"
            f"MaxDD: {abs(m.get('max_drawdown', 0))*100:.2f}% | Trades: {ts.get('count', 0)} | WinRate: {ts.get('win_rate', 0)*100:.1f}%"
        )
