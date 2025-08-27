from __future__ import annotations
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Dict, List

try:
    from analytics.strategies import MovingAverageCrossStrategy, RSIReversionStrategy, ConfluenceStrategy
    HAS_ANALYTICS = True
except Exception:  # pragma: no cover
    HAS_ANALYTICS = False


class ScreenerPanel:
    """Screener UI: uses Yahoo screeners + local strategies to produce explainable picks."""

    def __init__(self, app):
        self.app = app
        self.tab = None
        # Controls
        self.var_scr = tk.StringVar(value='day_gainers')
        self.var_region = tk.StringVar(value='CA')
        self.var_count = tk.IntVar(value=25)
        self.var_strategy = tk.StringVar(value='ma_cross')
        self.var_fast = tk.IntVar(value=10)
        self.var_slow = tk.IntVar(value=30)
        self.var_rsi_low = tk.IntVar(value=30)
        self.var_rsi_high = tk.IntVar(value=70)
        self.var_rsi_period = tk.IntVar(value=14)
        self.var_min_bw = tk.DoubleVar(value=0.0)
        self.var_bb_win = tk.IntVar(value=20)
        # Widgets
        self.tree = None
        self.lbl_status = None

    def build(self, notebook: ttk.Notebook):
        tab = ttk.Frame(notebook)
        notebook.add(tab, text="Screener")
        self.tab = tab
        # Top bar
        top = ttk.Frame(tab)
        top.pack(fill=tk.X, padx=6, pady=6)
        ttk.Label(top, text='Screener:').pack(side=tk.LEFT)
        cb = ttk.Combobox(top, width=16, state='readonly', textvariable=self.var_scr, values=['day_gainers', 'day_losers', 'most_actives'])
        cb.pack(side=tk.LEFT, padx=4)
        ttk.Label(top, text='Région:').pack(side=tk.LEFT)
        ttk.Combobox(top, width=5, state='readonly', textvariable=self.var_region, values=['CA', 'US']).pack(side=tk.LEFT, padx=2)
        ttk.Label(top, text='N:').pack(side=tk.LEFT)
        ttk.Spinbox(top, from_=5, to=100, width=5, textvariable=self.var_count).pack(side=tk.LEFT, padx=2)
        ttk.Separator(top, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)
        ttk.Label(top, text='Stratégie:').pack(side=tk.LEFT)
        cb2 = ttk.Combobox(top, width=14, state='readonly', textvariable=self.var_strategy, values=['ma_cross', 'rsi_reversion', 'confluence'])
        cb2.pack(side=tk.LEFT, padx=2)
        # Params row
        prm = ttk.Frame(tab)
        prm.pack(fill=tk.X, padx=6)
        ttk.Label(prm, text='Fast:').pack(side=tk.LEFT)
        ttk.Spinbox(prm, from_=3, to=60, width=4, textvariable=self.var_fast).pack(side=tk.LEFT)
        ttk.Label(prm, text='Slow:').pack(side=tk.LEFT, padx=(6, 0))
        ttk.Spinbox(prm, from_=5, to=200, width=4, textvariable=self.var_slow).pack(side=tk.LEFT)
        ttk.Label(prm, text='RSI Low:').pack(side=tk.LEFT, padx=(12, 2))
        ttk.Spinbox(prm, from_=5, to=45, width=4, textvariable=self.var_rsi_low).pack(side=tk.LEFT)
        ttk.Label(prm, text='RSI High:').pack(side=tk.LEFT, padx=(6, 2))
        ttk.Spinbox(prm, from_=55, to=95, width=4, textvariable=self.var_rsi_high).pack(side=tk.LEFT)
        ttk.Label(prm, text='RSI Period:').pack(side=tk.LEFT, padx=(12, 2))
        ttk.Spinbox(prm, from_=5, to=50, width=4, textvariable=self.var_rsi_period).pack(side=tk.LEFT)
        # Volatility
        prm2 = ttk.Frame(tab)
        prm2.pack(fill=tk.X, padx=6)
        lbl_bw = ttk.Label(prm2, text='Min BBand BW:')
        lbl_bw.pack(side=tk.LEFT)
        sp_bw = ttk.Spinbox(prm2, from_=0.0, to=1.0, increment=0.01, width=6, textvariable=self.var_min_bw)
        sp_bw.pack(side=tk.LEFT)
        ttk.Label(prm2, text='BBand Window:').pack(side=tk.LEFT, padx=(6, 2))
        ttk.Spinbox(prm2, from_=10, to=60, width=5, textvariable=self.var_bb_win).pack(side=tk.LEFT)
        try:
            from .ui_utils import attach_tooltip
            attach_tooltip(lbl_bw, 'Filtre de volatilité (Bollinger bandwidth). 0.00 = aucun filtre; 0.05–0.10 = faible vol; 0.10–0.20 = modérée; >0.20 = forte. Recommandé: 0.05–0.15 pour éviter le bruit.')
            attach_tooltip(sp_bw, 'Valeur minimale du Bollinger bandwidth pour générer des signaux. Échelle 0–1. Ex.: 0.08 laisse passer des tendances, 0.15 filtre les ranges trop serrés.')
        except Exception:
            pass
        # Action bar
        act = ttk.Frame(tab)
        act.pack(fill=tk.X, padx=6, pady=(4, 2))
        ttk.Button(act, text='Scanner maintenant', command=self.scan_now).pack(side=tk.LEFT)
        ttk.Button(act, text='Analyser sélection', command=self.analyze_selected).pack(side=tk.LEFT, padx=6)
        ttk.Button(act, text='Notifier sélection', command=self.notify_selected).pack(side=tk.LEFT)
        # Inline status
        self.lbl_status = ttk.Label(tab, text='')
        self.lbl_status.pack(fill=tk.X, padx=6)
        # Results
        self.tree = ttk.Treeview(tab, columns=('symbol', 'name', 'price', 'changePct', 'volume', 'signal', 'explanation', 'exchange'), show='headings', height=12)
        for c, (h, w, a) in {
            'symbol': ('Symbole', 90, tk.W),
            'name': ('Nom', 220, tk.W),
            'price': ('Prix', 80, tk.E),
            'changePct': ('%Chg', 70, tk.E),
            'volume': ('Volume', 100, tk.E),
            'signal': ('Signal', 90, tk.W),
            'explanation': ('Explications', 420, tk.W),
            'exchange': ('Échange', 90, tk.W),
        }.items():
            self.tree.heading(c, text=h)
            self.tree.column(c, width=w, anchor=a, stretch=True)
        self.tree.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

    def _set_status(self, msg: str, error: bool = False):
        try:
            if self.lbl_status is not None:
                self.lbl_status.configure(text=msg)
        except Exception:
            pass

    def scan_now(self):
        if not getattr(self.app, 'api_manager', None):
            self.app.set_status("APIs externes non disponibles", error=True)
            return

        scr = self.var_scr.get()
        region = self.var_region.get()
        n = int(self.var_count.get() or 25)
        # Minimal validation
        if n < 5 or n > 100:
            self._set_status('N doit être entre 5 et 100', error=True)
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

        self._set_status('Scan en cours…')

        def worker():
            try:
                raw = self.app.api_manager.yahoo.get_predefined_screener(scr, count=n, region=region)
            except Exception as e:
                self.app.after(0, lambda e=e: (self.app.set_status(f"Screener: {e}", error=True), self._set_status(f"Erreur: {e}", error=True)))
                return
            # Evaluate signals (optional)
            rows: List[Dict] = []
            for q in raw:
                sym = q.get('symbol')
                name = q.get('name')
                price = q.get('price')
                changePct = q.get('changePct')
                vol = q.get('volume')
                exch = q.get('exchange')
                sig_kind = ''
                reason = ''
                if HAS_ANALYTICS:
                    try:
                        ts = self.app.api_manager.get_time_series(sym, interval='1day', outputsize='compact') or {}
                        closes = self._extract_closes(ts)
                        if len(closes) >= 30:
                            sigs = self._generate_signals(closes)
                            if sigs:
                                last_idx = len(closes) - 1
                                fresh = [s for s in sigs if s.index == last_idx]
                                s = fresh[-1] if fresh else sigs[-1]
                                sig_kind = s.kind
                                reason = s.reason
                    except Exception:
                        pass
                rows.append({
                    'symbol': sym, 'name': name, 'price': price, 'changePct': changePct, 'volume': vol,
                    'signal': sig_kind, 'explanation': reason, 'exchange': exch
                })

            def _apply():
                try:
                    self._fill_tree(rows)
                    self.app.set_status(f"Screener {scr}/{region}: {len(rows)} lignes")
                    self._set_status(f"Terminé: {len(rows)} résultats")
                except Exception:
                    pass
            self.app.after(0, _apply)

        threading.Thread(target=worker, daemon=True).start()

    def _fill_tree(self, rows: List[Dict]):
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        for i, r in enumerate(rows):
            tag = 'even' if i % 2 == 0 else 'odd'
            vals = (r.get('symbol'), r.get('name'), f"{(r.get('price') or 0):.2f}",
                    f"{(r.get('changePct') or 0):.2f}", r.get('volume'), r.get('signal') or '', r.get('explanation') or '', r.get('exchange') or '')
            self.tree.insert('', tk.END, values=vals, tags=(tag,))

    def analyze_selected(self):
        try:
            sel = self.tree.selection()
            if not sel:
                return
            vals = self.tree.item(sel[0], 'values')
            sym = vals[0]
            if hasattr(self.app, 'symbol_analyzer') and self.app.symbol_analyzer:
                self.app.symbol_analyzer.show_symbol_analysis(sym)
            else:
                messagebox.showinfo('Analyse', f'Aucun analyseur disponible pour {sym}')
        except Exception:
            pass

    def notify_selected(self):
        try:
            sel = self.tree.selection()
            if not sel:
                return
            vals = self.tree.item(sel[0], 'values')
            sym = vals[0]
            sig = vals[5] or 'signal'
            exp = vals[6] or ''
            if getattr(self.app, 'api_manager', None) and getattr(self.app.api_manager, 'telegram', None):
                title = f"Strategy Alert - TECH_{sig.upper()} {sym}"
                msg = f"{sym}: {exp}"
                ok = self.app.api_manager.telegram.send_alert(title, msg, level='ALERT')
                self.app.set_status('Notification envoyée' if ok else 'Échec notification', error=not ok)
        except Exception:
            pass

    def _generate_signals(self, closes: List[float]):
        if self.var_strategy.get() == 'rsi_reversion':
            # Use RSI period and thresholds from UI and pass volatility filter
            period = int(self.var_rsi_period.get() or 14)
            lo = int(self.var_rsi_low.get() or 30)
            hi = int(self.var_rsi_high.get() or 70)
            return RSIReversionStrategy(period, lo, hi, float(self.var_min_bw.get() or 0.0), int(self.var_bb_win.get() or 20)).generate(closes)
        if self.var_strategy.get() == 'confluence':
            fast = int(self.var_fast.get() or 10)
            slow = int(self.var_slow.get() or 30)
            if fast >= slow:
                slow = max(fast + 1, 5)
            rb = int(self.var_rsi_high.get() or 55)
            rs = int(self.var_rsi_low.get() or 45)
            return ConfluenceStrategy(fast, slow, int(self.var_rsi_period.get() or 14), rb, rs, float(self.var_min_bw.get() or 0.0), int(self.var_bb_win.get() or 20)).generate(closes)
        fast = int(self.var_fast.get() or 10)
        slow = int(self.var_slow.get() or 30)
        if fast >= slow:
            slow = max(fast + 1, 5)
        return MovingAverageCrossStrategy(fast, slow, float(self.var_min_bw.get() or 0.0), int(self.var_bb_win.get() or 20)).generate(closes)

    @staticmethod
    def _extract_closes(series: Dict) -> List[float]:
        closes: List[float] = []
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


__all__ = ["ScreenerPanel"]
