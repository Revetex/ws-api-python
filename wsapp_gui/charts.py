from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

try:
    # Matplotlib imports
    import matplotlib as mpl  # type: ignore
    from matplotlib.backends.backend_tkagg import (  # type: ignore
        FigureCanvasTkAgg,
        NavigationToolbar2Tk,
    )
    from matplotlib.figure import Figure  # type: ignore

    # Optional date formatting
    try:
        import matplotlib.dates as mdates  # type: ignore
    except Exception:  # pragma: no cover
        mdates = None  # type: ignore
    try:
        from matplotlib.ticker import AutoMinorLocator, FuncFormatter  # type: ignore
    except Exception:  # pragma: no cover
        FuncFormatter = None  # type: ignore
        AutoMinorLocator = None  # type: ignore
    # Apply a pleasant default style safely
    try:  # pragma: no cover (style may vary by env)
        if 'seaborn-v0_8' in mpl.style.library:  # type: ignore
            mpl.style.use('seaborn-v0_8')  # type: ignore
        elif 'seaborn' in mpl.style.library:  # type: ignore
            mpl.style.use('seaborn')  # type: ignore
    except Exception:
        pass
    # Tweak rcParams for clearer charts
    try:  # pragma: no cover
        mpl.rcParams.update(
            {
                'figure.dpi': 120,
                'savefig.dpi': 220,
                'axes.grid': True,
                'grid.linestyle': '--',
                'grid.alpha': 0.25,
                'axes.spines.top': False,
                'axes.spines.right': False,
                'axes.titleweight': 'semibold',
                'axes.titlesize': 11,
                'axes.labelsize': 10,
                'font.size': 9,
                'lines.antialiased': True,
                'path.simplify': True,
            }
        )
    except Exception:
        pass
    HAS_MPL = True
except Exception:  # pragma: no cover
    HAS_MPL = False
    Figure = object  # type: ignore
    FigureCanvasTkAgg = object  # type: ignore
    NavigationToolbar2Tk = object  # type: ignore


class ChartController:
    def __init__(self, app):
        self.app = app
        # Matplotlib objects (lazy-created in init_widgets)
        self.figure = None
        self.ax = None
        self.canvas = None
        self.toolbar = None
        # Cached plot state
        self._last_points: list[tuple[str, float]] = []
        self._last_title: str = ''
        # Options
        self._show_grid: bool = True
        self._show_sma: bool = False
        self._sma_window: int = 7
        # Trade/signal markers overlay
        # Each marker: {date: 'YYYY-MM-DD', kind: 'buy'|'sell', y?: float, label?: str}
        self._markers: list[dict] = []

    def init_widgets(self, parent):
        if not HAS_MPL:
            return None
        # Slightly higher DPI and softer background
        self.figure = Figure(figsize=(6, 3.6), dpi=120, facecolor='#fafafa')
        self.ax = self.figure.add_subplot(111)
        self.ax.set_title('Net Liquidation Value')
        self.ax.set_xlabel('Date')
        self.ax.set_ylabel('Valeur')
        self.canvas = FigureCanvasTkAgg(self.figure, master=parent)
        self.canvas.get_tk_widget().pack(fill='both', expand=True)
        # Optional toolbar (only if packing parent wants it inline)
        try:
            self.toolbar = NavigationToolbar2Tk(self.canvas, parent, pack_toolbar=False)  # type: ignore
            self.toolbar.update()  # type: ignore
            # Place toolbar at bottom of chart area
            self.toolbar.pack(side='bottom', fill='x')  # type: ignore
        except Exception:
            self.toolbar = None
        return self.canvas

    def load_nlv_single(self):
        if not HAS_MPL:
            self.app.set_status('Graphique: Matplotlib non disponible.', error=True)
            return
        if not (self.app.api and self.app.current_account_id):
            self.app.set_status('Graphique: sélectionnez un compte.', error=True)
            return
        self.app._busy(True)
        end = datetime.now(timezone.utc)
        sel_var = getattr(self.app, 'var_chart_range', None)
        try:
            days = int(sel_var.get()) if sel_var else 30
        except Exception:
            days = 30
        if days <= 0:
            days = 30
        start = end - timedelta(days=days)
        # Wealthsimple GraphQL exposes historicalDaily; force DAILY resolution
        resolution = 'DAILY'

        def worker():
            try:
                data = self.app.api.get_account_historical_financials(
                    self.app.current_account_id,
                    start_date=start,
                    end_date=end,
                    currency='CAD',
                    resolution=resolution,
                    first=500,
                )
                pts: list[tuple[str, float]] = []
                if data:  # API returns a list of nodes already
                    for node in data:
                        if not isinstance(node, dict):
                            continue
                        date = node.get('date')
                        nlv = node.get('netLiquidationValueV2') or node.get('netLiquidationValue')
                        if date and nlv and 'amount' in nlv:
                            pts.append((date, float(nlv['amount'])))
                # Fallback: try identity-level financials filtered by account if no points
                if not pts:
                    try:
                        id_data = self.app.api.get_identity_historical_financials(
                            account_ids=[self.app.current_account_id],
                            currency='CAD',
                            start_date=start,
                            end_date=end,
                            first=500,
                        )
                        for node in id_data or []:
                            if not isinstance(node, dict):
                                continue
                            date = node.get('date')
                            nlv = node.get('netLiquidationValueV2') or {}
                            amt = nlv.get('amount')
                            if date and amt is not None:
                                pts.append((date, float(amt)))
                    except Exception:
                        pass
                pts.sort()
                self.app.after(
                    0,
                    lambda: self._update_line(pts, title=f'Net Liquidation Value ({days}j)'),
                )
            except Exception as e:
                self.app.after(
                    0, lambda e=e: self.app.set_status(f'Erreur historique: {e}', error=True)
                )
            finally:
                self.app.after(0, lambda: self.app._busy(False))

        threading.Thread(target=worker, daemon=True).start()

    def _update_line(self, points: list[tuple[str, float]], title: str):
        if not HAS_MPL or not self.ax:
            return
        self.ax.clear()
        self._last_points = list(points)
        self._last_title = title
        if points:
            xs_raw, ys = zip(*points)
            # Try to parse dates for nicer axis formatting if mpl dates available
            xs = list(xs_raw)
            # Map of date string (YYYY-MM-DD) to index for marker alignment
            try:
                idx_map = {str(d)[:10]: i for i, d in enumerate(xs_raw)}
            except Exception:
                idx_map = {}
            try:
                from datetime import datetime as _dt

                xs_dt = []
                for s in xs_raw:
                    try:
                        xs_dt.append(_dt.strptime(s[:10], '%Y-%m-%d'))
                    except Exception:
                        xs_dt = []
                        break
                if xs_dt and 'mdates' in globals() and mdates:  # type: ignore
                    xs = xs_dt
                    self.ax.plot(
                        xs,
                        ys,
                        marker='o',
                        markersize=3.5,
                        markeredgewidth=0,
                        linewidth=1.8,
                        color='#2563eb',
                        alpha=0.95,
                        antialiased=True,
                    )
                    # Date locator/formatter
                    try:
                        locator = mdates.AutoDateLocator()
                        formatter = mdates.ConciseDateFormatter(locator)
                        self.ax.xaxis.set_major_locator(locator)
                        self.ax.xaxis.set_major_formatter(formatter)
                        if AutoMinorLocator:
                            self.ax.xaxis.set_minor_locator(AutoMinorLocator())  # type: ignore
                    except Exception:
                        pass
                else:
                    self.ax.plot(
                        xs,
                        ys,
                        marker='o',
                        markersize=3.5,
                        markeredgewidth=0,
                        linewidth=1.8,
                        color='#2563eb',
                        alpha=0.95,
                        antialiased=True,
                    )
                    self.ax.set_xticks(xs[:: max(1, len(xs) // 8)])
            except Exception:
                self.ax.plot(
                    xs,
                    ys,
                    marker='o',
                    markersize=3.5,
                    markeredgewidth=0,
                    linewidth=1.8,
                    color='#2563eb',
                    alpha=0.95,
                    antialiased=True,
                )
                try:
                    self.ax.set_xticks(xs[:: max(1, len(xs) // 8)])
                except Exception:
                    pass
            self.ax.tick_params(axis='x', rotation=26)
            # Grid & axis polishing
            try:
                self.ax.grid(self._show_grid, which='major', linestyle='--', alpha=0.28)
                if AutoMinorLocator:
                    self.ax.yaxis.set_minor_locator(AutoMinorLocator())  # type: ignore
                self.ax.set_axisbelow(True)
            except Exception:
                pass
            # SMA overlay
            if self._show_sma and len(ys) >= self._sma_window:
                try:
                    sma_vals = self._moving_average(list(ys), self._sma_window)
                    # align SMA with xs (pad head with Nones)
                    pad = [None] * (self._sma_window - 1)
                    sma_plot = pad + sma_vals
                    # Filter None for plotting by replacing with NaN
                    sma_plot = [float('nan') if v is None else v for v in sma_plot]
                    self.ax.plot(
                        xs,
                        sma_plot,
                        color='#059669',
                        linewidth=1.8,
                        alpha=0.9,
                        label=f'SMA {self._sma_window}j',
                    )
                    # Guard legend only if labeled artists exist
                    handles, labels = self.ax.get_legend_handles_labels()
                    if labels:
                        self.ax.legend()
                except Exception:
                    pass
            # Trade/signal markers overlay (optional)
            try:
                if self._markers:
                    for m in self._markers:
                        if not isinstance(m, dict):
                            continue
                        kind = str(m.get('kind', 'buy')).lower()
                        d = str(m.get('date', ''))[:10]
                        if not d or d not in idx_map:
                            continue
                        i = idx_map[d]
                        if i < 0 or i >= len(xs):
                            continue
                        x = xs[i]
                        y = m.get('y')
                        try:
                            y = float(y) if y is not None else float(ys[i])
                        except Exception:
                            continue
                        color, mark = ('#10b981', '^') if kind == 'buy' else ('#ef4444', 'v')
                        self.ax.scatter(
                            [x],
                            [y],
                            color=color,
                            s=36,
                            marker=mark,
                            zorder=5,
                            edgecolors='white',
                            linewidth=0.5,
                        )
                        label = m.get('label')
                        if label:
                            try:
                                self.ax.annotate(
                                    str(label),
                                    (x, y),
                                    textcoords='offset points',
                                    xytext=(0, 8 if kind == 'buy' else -10),
                                    ha='center',
                                    fontsize=8,
                                    color=color,
                                    alpha=0.9,
                                )
                            except Exception:
                                pass
            except Exception:
                pass
        else:
            self.ax.text(
                0.5,
                0.5,
                'Aucune donnée pour la période sélectionnée',
                ha='center',
                va='center',
                transform=self.ax.transAxes,
                color='red',
            )
        self.ax.set_title(title)
        self.ax.set_xlabel('Date')
        # Apply compact currency formatter on Y axis if available
        try:
            if FuncFormatter:
                self.ax.yaxis.set_major_formatter(FuncFormatter(self._fmt_currency))  # type: ignore
        except Exception:
            pass
        self.ax.set_ylabel('Valeur CAD')
        try:
            self.figure.tight_layout()  # type: ignore
        except Exception:
            pass
        self.canvas.draw_idle()  # type: ignore

    # ---- Multi-account aggregated NLV (30 days) ----
    def load_nlv_multi(self):
        if not HAS_MPL:
            self.app.set_status('Graphique: Matplotlib non disponible.', error=True)
            return
        sel = self.app.list_accounts.curselection() if hasattr(self.app, 'list_accounts') else []
        if not sel:
            self.app.set_status(
                'Graphique: sélectionnez plusieurs comptes (ou au moins un).', error=True
            )
            return
        account_ids = [self.app.accounts[i]['id'] for i in sel]
        self.app._busy(True)
        end = datetime.now(timezone.utc)
        sel_var = getattr(self.app, 'var_chart_range', None)
        try:
            days = int(sel_var.get()) if sel_var else 30
        except Exception:
            days = 30
        if days <= 0:
            days = 30
        start = end - timedelta(days=days)
        # Wealthsimple GraphQL exposes historicalDaily; force DAILY resolution
        resolution = 'DAILY'

        def worker():
            try:
                aggregates = {}
                for acc_id in account_ids:
                    data = self.app.api.get_account_historical_financials(
                        acc_id,
                        start_date=start,
                        end_date=end,
                        currency='CAD',
                        resolution=resolution,
                        first=500,
                    )
                    if data:  # API returns a list of nodes already
                        for node in data:
                            if not isinstance(node, dict):
                                continue
                            date = node.get('date')
                            nlv = node.get('netLiquidationValueV2') or node.get(
                                'netLiquidationValue'
                            )
                            if date and nlv and 'amount' in nlv:
                                aggregates[date] = aggregates.get(date, 0.0) + float(nlv['amount'])
                pts = sorted(aggregates.items())
                self.app.after(
                    0,
                    lambda: self._update_line(pts, title=f'Valeur Agrégée ({days}j)'),
                )
            except Exception as e:  # noqa
                self.app.after(
                    0,
                    lambda e=e: self.app.set_status(f"Graphique: {e}", error=True, details=repr(e)),
                )
            finally:
                self.app.after(0, lambda: self.app._busy(False))

        threading.Thread(target=worker, daemon=True).start()

    # ---- Composition pie chart (current positions of selected accounts) ----
    def load_composition(self):
        if not HAS_MPL:
            self.app.set_status('Graphique: Matplotlib non disponible.', error=True)
            return
        sel = self.app.list_accounts.curselection() if hasattr(self.app, 'list_accounts') else []
        if not sel:
            self.app.set_status('Graphique: sélectionnez des comptes.', error=True)
            return
        account_ids = [self.app.accounts[i]['id'] for i in sel]
        self.app._busy(True)

        def worker():
            try:
                symbol_totals = {}
                for acc_id in account_ids:
                    positions = self.app.api.get_account_positions(acc_id)
                    for p in positions:
                        val = p.get('value') or 0
                        if not val:
                            continue
                        sym = p.get('symbol') or 'N/A'
                        symbol_totals[sym] = symbol_totals.get(sym, 0.0) + val
                items = sorted(
                    symbol_totals.items(),
                    key=lambda kv: kv[1],
                    reverse=True,
                )
                top = items[:8]
                other = sum(v for _, v in items[8:])
                if other:
                    top.append(('Autres', other))
                self.app.after(
                    0,
                    lambda: self._update_pie(top, 'Composition du portefeuille'),
                )
            except Exception as e:  # noqa
                self.app.after(
                    0,
                    lambda e=e: self.app.set_status(f"Graphique: {e}", error=True, details=repr(e)),
                )
            finally:
                self.app.after(0, lambda: self.app._busy(False))

        threading.Thread(target=worker, daemon=True).start()

    def _update_pie(self, data: list[tuple[str, float]], title: str):
        if not HAS_MPL or not self.ax:
            return
        self.ax.clear()
        if data:
            labels, sizes = zip(*data)
            # pleasant color cycle if available
            colors = None
            try:
                colors = mpl.rcParams['axes.prop_cycle'].by_key().get('color')  # type: ignore
            except Exception:
                colors = None
            self.ax.pie(
                sizes,
                labels=labels,
                autopct='%1.1f%%',
                startangle=90,
                colors=colors,
                wedgeprops={'linewidth': 0.75, 'edgecolor': '#ffffff'},
                textprops={'fontsize': 9},
            )
            self.ax.axis('equal')
        self.ax.set_title(title)
        try:
            self.figure.tight_layout()  # type: ignore
        except Exception:
            pass
        self.canvas.draw_idle()  # type: ignore

    # ---- Options & helpers ----
    def set_options(
        self,
        show_grid: bool | None = None,
        show_sma: bool | None = None,
        sma_window: int | None = None,
    ):
        if show_grid is not None:
            self._show_grid = bool(show_grid)
        if show_sma is not None:
            self._show_sma = bool(show_sma)
        if sma_window is not None and isinstance(sma_window, int) and sma_window > 1:
            self._sma_window = sma_window
        # Replot if we have points cached
        self.replot()

    def replot(self):
        if self._last_points and self._last_title:
            self._update_line(self._last_points, self._last_title)

    # ---- Markers API ----
    def set_markers(self, markers: list[dict] | None):
        """Set trade/signal markers and replot if data is cached.

        Each marker: {date: 'YYYY-MM-DD', kind: 'buy'|'sell', y?: float, label?: str}
        """
        self._markers = list(markers or [])
        self.replot()

    def clear_markers(self):
        self._markers = []
        self.replot()

    @staticmethod
    def _moving_average(values: list[float], window: int) -> list[float]:
        out: list[float] = []
        acc = 0.0
        for i, v in enumerate(values):
            acc += float(v)
            if i >= window:
                acc -= float(values[i - window])
            if i >= window - 1:
                out.append(acc / window)
        return out

    # ---- Export helpers ----
    def export_png(self, path: str) -> bool:
        if not HAS_MPL or not self.figure:
            return False
        try:
            self.figure.savefig(path, dpi=220)
            return True
        except Exception:
            return False

    # ---- Formatters ----
    @staticmethod
    def _fmt_currency(y, _pos=None):  # pragma: no cover (visual)
        try:
            y = float(y)
            abs_y = abs(y)
            if abs_y >= 1_000_000_000:
                return f"{y/1_000_000_000:.1f}B"
            if abs_y >= 1_000_000:
                return f"{y/1_000_000:.1f}M"
            if abs_y >= 1_000:
                return f"{y/1_000:.1f}k"
            return f"{y:.0f}"
        except Exception:
            return str(y)

    def export_csv(self, path: str) -> bool:
        if not self._last_points:
            return False
        try:
            import csv

            with open(path, 'w', newline='', encoding='utf-8') as f:
                w = csv.writer(f)
                w.writerow(['date', 'value'])
                for d, v in self._last_points:
                    w.writerow([d, v])
            return True
        except Exception:
            return False


__all__ = ["ChartController", "HAS_MPL"]
