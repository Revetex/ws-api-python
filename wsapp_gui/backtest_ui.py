from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk

try:
    from analytics.backtest import run_signals_backtest
    from analytics.strategies import (
        ConfluenceStrategy,
        MovingAverageCrossStrategy,
        RSIReversionStrategy,
    )

    HAS_ANALYTICS = True
except Exception:  # pragma: no cover
    HAS_ANALYTICS = False

try:
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.figure import Figure

    HAS_MPL = True
except Exception:  # pragma: no cover
    HAS_MPL = False
    Figure = object  # type: ignore
    FigureCanvasTkAgg = object  # type: ignore


class BacktestPanel:
    def __init__(self, app):
        self.app = app
        self.tab = None
        # Vars
        self.var_symbol = tk.StringVar(value='AAPL')
        self.var_interval = tk.StringVar(value='1day')
        self.var_outputsize = tk.StringVar(value='compact')
        self.var_strategy = tk.StringVar(value='ma_cross')
        self.var_fast = tk.IntVar(value=10)
        self.var_slow = tk.IntVar(value=30)
        self.var_rsi_low = tk.IntVar(value=30)
        self.var_rsi_high = tk.IntVar(value=70)
        self.var_rsi_period = tk.IntVar(value=14)
        self.var_min_bw = tk.DoubleVar(value=0.0)
        self.var_bb_win = tk.IntVar(value=20)
        self.var_cash = tk.DoubleVar(value=10000.0)
        # Widgets
        self.txt = None
        self.figure = None
        self.ax = None
        self.canvas = None
        self.lbl_status = None

    def build(self, notebook: ttk.Notebook):
        tab = ttk.Frame(notebook)
        notebook.add(tab, text='Backtest')
        self.tab = tab
        # Top controls
        top = ttk.Frame(tab)
        top.pack(fill=tk.X, padx=6, pady=6)
        ttk.Label(top, text='Symbole:').pack(side=tk.LEFT)
        ttk.Entry(top, textvariable=self.var_symbol, width=10).pack(side=tk.LEFT, padx=3)
        ttk.Label(top, text='Intervalle:').pack(side=tk.LEFT)
        ttk.Combobox(
            top,
            width=10,
            state='readonly',
            textvariable=self.var_interval,
            values=['1day', '1week', '1month'],
        ).pack(side=tk.LEFT, padx=3)
        ttk.Label(top, text='Taille:').pack(side=tk.LEFT)
        ttk.Combobox(
            top,
            width=8,
            state='readonly',
            textvariable=self.var_outputsize,
            values=['compact', 'full'],
        ).pack(side=tk.LEFT, padx=3)
        ttk.Separator(top, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)
        ttk.Label(top, text='Stratégie:').pack(side=tk.LEFT)
        ttk.Combobox(
            top,
            width=14,
            state='readonly',
            textvariable=self.var_strategy,
            values=['ma_cross', 'rsi_reversion', 'confluence'],
        ).pack(side=tk.LEFT, padx=3)
        # Param row 1
        prm = ttk.Frame(tab)
        prm.pack(fill=tk.X, padx=6)
        ttk.Label(prm, text='Fast:').pack(side=tk.LEFT)
        ttk.Spinbox(prm, from_=3, to=60, width=4, textvariable=self.var_fast).pack(side=tk.LEFT)
        ttk.Label(prm, text='Slow:').pack(side=tk.LEFT, padx=(6, 0))
        ttk.Spinbox(prm, from_=5, to=200, width=4, textvariable=self.var_slow).pack(side=tk.LEFT)
        ttk.Label(prm, text='RSI Low:').pack(side=tk.LEFT, padx=(12, 2))
        ttk.Spinbox(prm, from_=5, to=45, width=4, textvariable=self.var_rsi_low).pack(side=tk.LEFT)
        ttk.Label(prm, text='RSI High:').pack(side=tk.LEFT, padx=(6, 2))
        ttk.Spinbox(prm, from_=55, to=95, width=4, textvariable=self.var_rsi_high).pack(
            side=tk.LEFT
        )
        ttk.Label(prm, text='RSI Period:').pack(side=tk.LEFT, padx=(12, 2))
        ttk.Spinbox(prm, from_=5, to=50, width=4, textvariable=self.var_rsi_period).pack(
            side=tk.LEFT
        )
        ttk.Label(prm, text='Cash:').pack(side=tk.LEFT, padx=(12, 2))
        ttk.Spinbox(
            prm, from_=1000, to=1000000, increment=500, width=10, textvariable=self.var_cash
        ).pack(side=tk.LEFT)
        # Param row 2 - Volatility
        prm2 = ttk.Frame(tab)
        prm2.pack(fill=tk.X, padx=6)
        lbl_bw = ttk.Label(prm2, text='Min BBand BW:')
        lbl_bw.pack(side=tk.LEFT)
        sp_bw = ttk.Spinbox(
            prm2, from_=0.0, to=1.0, increment=0.01, width=6, textvariable=self.var_min_bw
        )
        sp_bw.pack(side=tk.LEFT)
        ttk.Label(prm2, text='BBand Window:').pack(side=tk.LEFT, padx=(6, 2))
        ttk.Spinbox(prm2, from_=10, to=60, width=5, textvariable=self.var_bb_win).pack(side=tk.LEFT)
        try:
            from .ui_utils import attach_tooltip

            attach_tooltip(
                lbl_bw,
                'Filtre de volatilité (Bollinger bandwidth). 0.00 = aucun filtre; 0.05–0.10 = faible vol; 0.10–0.20 = modérée; >0.20 = forte. Recommandé: 0.05–0.15 pour éviter le bruit.',
            )
            attach_tooltip(
                sp_bw,
                'Valeur minimale du Bollinger bandwidth pour générer des signaux. Échelle 0–1. Ex.: 0.08 laisse passer des tendances, 0.15 filtre les ranges trop serrés.',
            )
        except Exception:
            pass
        # Actions
        act = ttk.Frame(tab)
        act.pack(fill=tk.X, padx=6, pady=4)
        ttk.Button(act, text='Lancer le backtest', command=self.run_backtest).pack(side=tk.LEFT)
        # Inline status
        self.lbl_status = ttk.Label(tab, text='')
        self.lbl_status.pack(fill=tk.X, padx=6)
        # Output section
        body = ttk.Frame(tab)
        body.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        if HAS_MPL:
            left = ttk.Frame(body)
            left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            self.figure = Figure(figsize=(5, 3), dpi=100)
            self.ax = self.figure.add_subplot(111)
            self.ax.set_title('Courbe de capital')
            self.ax.set_xlabel('Index')
            self.ax.set_ylabel('Équité')
            self.canvas = FigureCanvasTkAgg(self.figure, master=left)
            self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
            right = ttk.Frame(body)
            right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            self.txt = tk.Text(right, height=10, wrap='word')
            self.txt.pack(fill=tk.BOTH, expand=True)
            self.txt.configure(state=tk.DISABLED)
        else:
            self.txt = tk.Text(body, height=14, wrap='word')
            self.txt.pack(fill=tk.BOTH, expand=True)
            self.txt.configure(state=tk.DISABLED)

    def run_backtest(self):
        if not HAS_ANALYTICS:
            self.app.set_status('Analytics non disponibles', error=True)
            return
        if not getattr(self.app, 'api_manager', None):
            self.app.set_status('APIs externes non disponibles', error=True)
            return
        sym = (self.var_symbol.get() or '').strip().upper()
        if not sym:
            return
        interval = self.var_interval.get()
        out = self.var_outputsize.get()
        # Minimal validation
        try:
            cash = float(self.var_cash.get() or 10000.0)
        except Exception:
            self._set_status('Montant de cash invalide', error=True)
            return
        if cash <= 0:
            self._set_status('Cash doit être > 0', error=True)
            return
        if self.var_strategy.get() == 'ma_cross':
            try:
                fast = int(self.var_fast.get() or 10)
                slow = int(self.var_slow.get() or 30)
                if fast < 2 or slow <= fast:
                    self._set_status('Paramètres invalides: Fast doit être < Slow', error=True)
                    return
            except Exception:
                self._set_status('Paramètres SMA invalides', error=True)
                return
        elif self.var_strategy.get() == 'rsi_reversion':
            try:
                lo = int(self.var_rsi_low.get() or 30)
                hi = int(self.var_rsi_high.get() or 70)
                if not (5 <= lo < hi <= 95):
                    self._set_status('RSI Low/High doivent être 5<=low<high<=95', error=True)
                    return
            except Exception:
                self._set_status('Paramètres RSI invalides', error=True)
                return
        else:  # confluence
            try:
                fast = int(self.var_fast.get() or 10)
                slow = int(self.var_slow.get() or 30)
                if fast < 2 or slow <= fast:
                    self._set_status('Paramètres invalides: Fast doit être < Slow', error=True)
                    return
                rsi_buy = int(self.var_rsi_high.get() or 55)
                rsi_sell = int(self.var_rsi_low.get() or 45)
                if not (0 < rsi_sell < rsi_buy < 100):
                    self._set_status('Seuils RSI invalides', error=True)
                    return
            except Exception:
                self._set_status('Paramètres Confluence invalides', error=True)
                return

        self._set_status('Backtest en cours…')

        def worker():
            try:
                ts = (
                    self.app.api_manager.get_time_series(sym, interval=interval, outputsize=out)
                    or {}
                )
                closes = self._extract_closes(ts)
                if len(closes) < 20:
                    raise RuntimeError('Série insuffisante')
                sigs = self._generate_signals(closes)
                res = run_signals_backtest(closes, sigs, initial_cash=cash)
                self.app.after(0, lambda r=res: self._render_result(r, sym))
            except Exception as e:
                self.app.after(
                    0,
                    lambda e=e: (
                        self.app.set_status(f"Backtest: {e}", error=True),
                        self._set_status(f"Erreur: {e}", error=True),
                    ),
                )

        threading.Thread(target=worker, daemon=True).start()

    def _generate_signals(self, closes):
        kind = self.var_strategy.get()
        if kind == 'rsi_reversion':
            return RSIReversionStrategy(
                int(self.var_rsi_period.get() or 14),
                int(self.var_rsi_low.get() or 30),
                int(self.var_rsi_high.get() or 70),
                float(self.var_min_bw.get() or 0.0),
                int(self.var_bb_win.get() or 20),
            ).generate(closes)
        if kind == 'confluence':
            fast = int(self.var_fast.get() or 10)
            slow = int(self.var_slow.get() or 30)
            if fast >= slow:
                slow = max(fast + 1, 5)
            # reuse rsi_low as sell threshold and rsi_high as buy threshold for UI simplicity
            rb = int(self.var_rsi_high.get() or 55)
            rs = int(self.var_rsi_low.get() or 45)
            return ConfluenceStrategy(
                fast,
                slow,
                int(self.var_rsi_period.get() or 14),
                rb,
                rs,
                float(self.var_min_bw.get() or 0.0),
                int(self.var_bb_win.get() or 20),
            ).generate(closes)
        fast = int(self.var_fast.get() or 10)
        slow = int(self.var_slow.get() or 30)
        if fast >= slow:
            slow = max(fast + 1, 5)
        return MovingAverageCrossStrategy(
            fast, slow, float(self.var_min_bw.get() or 0.0), int(self.var_bb_win.get() or 20)
        ).generate(closes)

    def _render_result(self, res: dict, sym: str):
        self._set_status('Terminé')
        # Text
        stats = self._compute_stats(res)
        txt = (
            f"Symbole: {sym}\n"
            f"Cash initial: {res.get('initial_cash', 0):.2f}\n"
            f"Équité finale: {res.get('final_equity', 0):.2f}\n"
            f"Rendement: {res.get('total_return', 0)*100:.2f}%\n"
            f"Max Drawdown: {stats.get('max_drawdown', 0)*100:.2f}%\n"
            f"Trades: {len(res.get('trades', []))}\n"
        )
        try:
            self.txt.configure(state=tk.NORMAL)
            self.txt.delete('1.0', tk.END)
            self.txt.insert('end', txt)
            self.txt.configure(state=tk.DISABLED)
        except Exception:
            pass
        # Chart
        if HAS_MPL and self.ax:
            try:
                eq = res.get('equity_curve', [])
                self.ax.clear()
                self.ax.plot(list(range(len(eq))), eq, color='#2563eb', linewidth=1.2)
                self.ax.set_title('Courbe de capital')
                self.ax.set_xlabel('Index')
                self.ax.set_ylabel('Équité')
                self.figure.tight_layout()
                self.canvas.draw_idle()
            except Exception:
                pass

    def _set_status(self, msg: str, error: bool = False):
        try:
            if self.lbl_status is not None:
                self.lbl_status.configure(text=msg)
        except Exception:
            pass

    @staticmethod
    def _extract_closes(series: dict):
        closes = []
        try:
            k = next((k for k in series.keys() if 'Time Series' in k), None)
            ts = series.get(k) if k else None
            if isinstance(ts, dict):
                for _d, row in list(sorted(ts.items())):
                    try:
                        closes.append(float(row.get('4. close') or row.get('4. Close') or 0.0))
                    except Exception:
                        pass
        except Exception:
            pass
        return closes

    @staticmethod
    def _compute_stats(res: dict) -> dict:
        eq = res.get('equity_curve', []) or []
        if not eq:
            return {'max_drawdown': 0.0}
        peak = eq[0]
        mdd = 0.0
        for v in eq:
            if v > peak:
                peak = v
            dd = (v / peak) - 1.0 if peak else 0.0
            if dd < mdd:
                mdd = dd
        return {'max_drawdown': abs(mdd)}


__all__ = ["BacktestPanel"]
