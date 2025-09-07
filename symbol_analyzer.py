"""Analyseur de symboles avec graphiques et stratégies"""

from __future__ import annotations

import math
import random
import statistics
import threading
import tkinter as tk
from tkinter import ttk

try:
    from analytics.backtest import run_signals_backtest as _run_bt
    from analytics.indicators import macd as _macd_ind
    from analytics.indicators import rsi as _rsi_ind
    from analytics.indicators import sma as _sma_ind
    from analytics.strategies import MovingAverageCrossStrategy
    from analytics.strategies import RSIReversionStrategy as _RSIrev

    HAS_ANALYTICS = True
except Exception:  # pragma: no cover
    HAS_ANALYTICS = False

try:
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.figure import Figure

    HAS_MPL = True
except ImportError:
    HAS_MPL = False
    Figure = None

try:
    from external_apis import APIManager

    HAS_EXTERNAL_APIS = True
except ImportError:
    HAS_EXTERNAL_APIS = False
    APIManager = None


class SymbolAnalyzer:
    """Analyseur avancé de symboles avec graphiques et stratégies."""

    def __init__(self, parent_app):
        self.app = parent_app
        self.api_manager = getattr(parent_app, 'api_manager', None)
        self.window = None
        self.figure = None
        self.canvas = None
        self.current_symbol = ""
        self.current_data = {}
        self._loading = False

    def show_symbol_analysis(self, symbol: str):
        """Affiche la fenêtre d'analyse pour un symbole donné."""
        self.current_symbol = symbol.upper()

        if self.window:
            self.window.destroy()

        self._create_window()
        self._load_symbol_data()
        # Optional: append quick indicators/backtest summary to strategies box when available
        if HAS_ANALYTICS and self.api_manager:

            def _enrich():
                try:
                    ts = (
                        self.api_manager.get_time_series(
                            self.current_symbol, interval='1day', outputsize='compact'
                        )
                        or {}
                    )
                    closes = []
                    try:
                        k = next((k for k in ts.keys() if 'Time Series' in k), None)
                        series = ts.get(k) if k else None
                        if isinstance(series, dict):
                            for _d, row in list(sorted(series.items())):
                                try:
                                    closes.append(
                                        float(row.get('4. close') or row.get('4. Close') or 0.0)
                                    )
                                except Exception:
                                    pass
                    except Exception:
                        pass
                    if len(closes) >= 30:
                        ma10 = _sma_ind(closes, 10)[-1]
                        ma30 = _sma_ind(closes, 30)[-1]
                        r = _rsi_ind(closes, 14)[-1]
                        m_line, m_sig, _ = _macd_ind(closes)
                        macd_last = (m_line[-1] if m_line else None, m_sig[-1] if m_sig else None)
                        msgs = [
                            f"MA10={ma10:.2f} MA30={ma30:.2f}" if (ma10 and ma30) else None,
                            f"RSI(14)={r:.1f}" if r else None,
                            (
                                f"MACD={macd_last[0]:.3f} signal={macd_last[1]:.3f}"
                                if (macd_last[0] and macd_last[1])
                                else None
                            ),
                        ]
                        msgs = [m for m in msgs if m]
                        sigs = MovingAverageCrossStrategy(10, 30).generate(closes) + _RSIrev(
                            14, 30, 70
                        ).generate(closes)
                        res = _run_bt(closes, sigs)
                        if self.txt_strategies:
                            txt = (
                                "\n".join([s for s in msgs])
                                + f"\nBacktest rapide: {res['total_return']*100:.1f}%"
                            )
                            self.txt_strategies.after(
                                0,
                                lambda t=txt: (
                                    self.txt_strategies.insert('end', t + '\n'),
                                    self.txt_strategies.see('end'),
                                ),
                            )
                except Exception:
                    pass

            threading.Thread(target=_enrich, daemon=True).start()

    def _create_window(self):
        """Crée la fenêtre d'analyse."""
        self.window = tk.Toplevel(self.app)
        self.window.title(f"Analyse de {self.current_symbol}")
        self.window.geometry("1000x700")
        self.window.transient(self.app)

        # Frame principal avec Notebook
        main_frame = ttk.Frame(self.window)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Notebook pour les différents onglets
        notebook = ttk.Notebook(main_frame)
        notebook.pack(fill=tk.BOTH, expand=True)

        # Onglet Graphique
        self._create_chart_tab(notebook)

        # Onglet Analyses techniques
        self._create_analysis_tab(notebook)

        # Onglet Stratégies
        self._create_strategy_tab(notebook)

        # Onglet Actualités
        self._create_news_tab(notebook)

        # Barre de contrôles en bas
        self._create_controls_bar(main_frame)

    def _create_chart_tab(self, notebook):
        """Crée l'onglet des graphiques."""
        chart_tab = ttk.Frame(notebook)
        notebook.add(chart_tab, text="📊 Graphique")

        # Frame pour les contrôles du graphique
        controls_frame = ttk.Frame(chart_tab)
        controls_frame.pack(fill=tk.X, padx=5, pady=5)

        # Sélection d'intervalle
        ttk.Label(controls_frame, text="Intervalle:").pack(side=tk.LEFT)
        self.var_interval = tk.StringVar(value="1day")
        interval_combo = ttk.Combobox(
            controls_frame,
            textvariable=self.var_interval,
            values=["1min", "5min", "15min", "30min", "1hour", "1day", "1week", "1month"],
            state="readonly",
            width=10,
        )
        interval_combo.pack(side=tk.LEFT, padx=5)
        interval_combo.bind('<<ComboboxSelected>>', self._on_interval_change)

        # Sélection de période
        ttk.Label(controls_frame, text="Période:").pack(side=tk.LEFT, padx=(20, 0))
        self.var_period = tk.StringVar(value="30")
        period_combo = ttk.Combobox(
            controls_frame,
            textvariable=self.var_period,
            values=["1", "7", "14", "30", "90", "180", "365"],
            state="readonly",
            width=8,
        )
        period_combo.pack(side=tk.LEFT, padx=5)
        period_combo.bind('<<ComboboxSelected>>', self._on_period_change)
        ttk.Label(controls_frame, text="jours").pack(side=tk.LEFT)

        # Indicateurs techniques
        ttk.Label(controls_frame, text="Indicateurs:").pack(side=tk.LEFT, padx=(20, 0))
        self.var_show_sma = tk.BooleanVar(value=True)
        self.var_show_ema = tk.BooleanVar(value=False)
        self.var_show_bb = tk.BooleanVar(value=False)
        self.var_show_candles = tk.BooleanVar(value=True)
        self.var_show_rsi = tk.BooleanVar(value=False)
        self.var_show_macd = tk.BooleanVar(value=False)

        ttk.Checkbutton(
            controls_frame, text="SMA", variable=self.var_show_sma, command=self._update_chart
        ).pack(side=tk.LEFT, padx=2)
        self.var_sma_period = tk.IntVar(value=20)
        tk.Spinbox(
            controls_frame,
            from_=3,
            to=300,
            width=4,
            textvariable=self.var_sma_period,
            command=self._update_chart,
        ).pack(side=tk.LEFT, padx=(0, 6))

        ttk.Checkbutton(
            controls_frame, text="EMA", variable=self.var_show_ema, command=self._update_chart
        ).pack(side=tk.LEFT, padx=2)
        self.var_ema_period = tk.IntVar(value=12)
        tk.Spinbox(
            controls_frame,
            from_=3,
            to=300,
            width=4,
            textvariable=self.var_ema_period,
            command=self._update_chart,
        ).pack(side=tk.LEFT, padx=(0, 6))

        ttk.Checkbutton(
            controls_frame, text="Bollinger", variable=self.var_show_bb, command=self._update_chart
        ).pack(side=tk.LEFT, padx=2)
        self.var_bb_period = tk.IntVar(value=20)
        tk.Spinbox(
            controls_frame,
            from_=5,
            to=300,
            width=4,
            textvariable=self.var_bb_period,
            command=self._update_chart,
        ).pack(side=tk.LEFT)
        ttk.Label(controls_frame, text="σ").pack(side=tk.LEFT)
        self.var_bb_std = tk.DoubleVar(value=2.0)
        tk.Spinbox(
            controls_frame,
            from_=1.0,
            to=4.0,
            increment=0.5,
            width=4,
            textvariable=self.var_bb_std,
            command=self._update_chart,
        ).pack(side=tk.LEFT, padx=(0, 6))

        ttk.Checkbutton(
            controls_frame, text="RSI", variable=self.var_show_rsi, command=self._update_chart
        ).pack(side=tk.LEFT, padx=2)
        ttk.Checkbutton(
            controls_frame, text="MACD", variable=self.var_show_macd, command=self._update_chart
        ).pack(side=tk.LEFT, padx=2)

        ttk.Checkbutton(
            controls_frame,
            text="Candles",
            variable=self.var_show_candles,
            command=self._update_chart,
        ).pack(side=tk.LEFT, padx=8)

        # Bouton de rafraîchissement
        ttk.Button(controls_frame, text="🔄 Actualiser", command=self._load_symbol_data).pack(
            side=tk.RIGHT, padx=5
        )

        # Zone graphique
        if HAS_MPL:
            self.figure = Figure(figsize=(12, 8), dpi=100)
            self.canvas = FigureCanvasTkAgg(self.figure, chart_tab)
            self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        else:
            ttk.Label(chart_tab, text="Matplotlib non disponible", font=("Arial", 16)).pack(
                expand=True
            )

    def _create_analysis_tab(self, notebook):
        """Crée l'onglet des analyses techniques."""
        analysis_tab = ttk.Frame(notebook)
        notebook.add(analysis_tab, text="🔍 Analyses")

        # Frame pour les analyses
        analysis_frame = ttk.LabelFrame(analysis_tab, text="Indicateurs Techniques")
        analysis_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Treeview pour afficher les analyses
        columns = ("indicator", "value", "signal", "description")
        self.tree_analysis = ttk.Treeview(
            analysis_frame, columns=columns, show="headings", height=15
        )

        # Configuration des colonnes
        self.tree_analysis.heading("indicator", text="Indicateur")
        self.tree_analysis.heading("value", text="Valeur")
        self.tree_analysis.heading("signal", text="Signal")
        self.tree_analysis.heading("description", text="Description")

        self.tree_analysis.column("indicator", width=120)
        self.tree_analysis.column("value", width=100)
        self.tree_analysis.column("signal", width=80)
        self.tree_analysis.column("description", width=400)

        self.tree_analysis.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Scrollbar
        scrollbar_analysis = ttk.Scrollbar(
            analysis_frame, orient=tk.VERTICAL, command=self.tree_analysis.yview
        )
        scrollbar_analysis.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree_analysis.configure(yscrollcommand=scrollbar_analysis.set)

    def _create_strategy_tab(self, notebook):
        """Crée l'onglet des stratégies."""
        strategy_tab = ttk.Frame(notebook)
        notebook.add(strategy_tab, text="⚡ Stratégies")

        # Frame pour les stratégies recommandées
        strategy_frame = ttk.LabelFrame(strategy_tab, text="Stratégies Recommandées")
        strategy_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Zone de texte pour les stratégies
        self.txt_strategies = tk.Text(strategy_frame, wrap=tk.WORD, font=("Consolas", 10))
        self.txt_strategies.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Scrollbar pour le texte
        scrollbar_strategies = ttk.Scrollbar(
            strategy_frame, orient=tk.VERTICAL, command=self.txt_strategies.yview
        )
        scrollbar_strategies.pack(side=tk.RIGHT, fill=tk.Y)
        self.txt_strategies.configure(yscrollcommand=scrollbar_strategies.set)

        # Paramètres + Boutons d'action
        action_frame = ttk.Frame(strategy_tab)
        action_frame.pack(fill=tk.X, padx=5, pady=5)

        # Backtest params
        ttk.Label(action_frame, text="SMA Rapide:").pack(side=tk.LEFT)
        self.var_bt_fast = tk.IntVar(value=10)
        tk.Spinbox(action_frame, from_=3, to=200, width=4, textvariable=self.var_bt_fast).pack(
            side=tk.LEFT, padx=(0, 8)
        )
        ttk.Label(action_frame, text="SMA Lente:").pack(side=tk.LEFT)
        self.var_bt_slow = tk.IntVar(value=30)
        tk.Spinbox(action_frame, from_=5, to=300, width=4, textvariable=self.var_bt_slow).pack(
            side=tk.LEFT, padx=(0, 12)
        )

        ttk.Button(action_frame, text="📊 Backtesting", command=self._run_backtest).pack(
            side=tk.LEFT, padx=5
        )
        ttk.Button(action_frame, text="📈 Simulation", command=self._run_simulation).pack(
            side=tk.LEFT, padx=5
        )
        ttk.Button(action_frame, text="🎯 Optimisation", command=self._optimize_strategy).pack(
            side=tk.LEFT, padx=5
        )

        # Surveillance IA
        monitor_frame = ttk.LabelFrame(strategy_tab, text="Surveillance IA")
        monitor_frame.pack(fill=tk.X, padx=5, pady=5)
        self.var_mon_sma = tk.BooleanVar(value=True)
        self.var_mon_rsi = tk.BooleanVar(value=False)
        self.var_mon_interval = tk.IntVar(value=60)
        ttk.Checkbutton(
            monitor_frame, text="Croisement SMA (rapide/lente)", variable=self.var_mon_sma
        ).pack(side=tk.LEFT, padx=5)
        ttk.Checkbutton(monitor_frame, text="RSI (30/70)", variable=self.var_mon_rsi).pack(
            side=tk.LEFT, padx=5
        )
        ttk.Label(monitor_frame, text="Toutes les (s):").pack(side=tk.LEFT)
        tk.Spinbox(
            monitor_frame, from_=15, to=600, width=5, textvariable=self.var_mon_interval
        ).pack(side=tk.LEFT, padx=(0, 10))
        self.btn_monitor = ttk.Button(
            monitor_frame, text="Démarrer", command=self._toggle_monitoring
        )
        self.btn_monitor.pack(side=tk.LEFT, padx=5)

    def _create_news_tab(self, notebook):
        """Crée l'onglet des actualités."""
        news_tab = ttk.Frame(notebook)
        notebook.add(news_tab, text="📰 Actualités")

        # Treeview pour les actualités
        news_columns = ("date", "title", "sentiment")
        self.tree_news = ttk.Treeview(news_tab, columns=news_columns, show="headings", height=10)

        self.tree_news.heading("date", text="Date")
        self.tree_news.heading("title", text="Titre")
        self.tree_news.heading("sentiment", text="Sentiment")

        self.tree_news.column("date", width=100)
        self.tree_news.column("title", width=500)
        self.tree_news.column("sentiment", width=100)

        self.tree_news.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Zone de détail pour l'article sélectionné
        detail_frame = ttk.LabelFrame(news_tab, text="Détail de l'article")
        detail_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.txt_news_detail = tk.Text(detail_frame, height=8, wrap=tk.WORD)
        self.txt_news_detail.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.tree_news.bind('<<TreeviewSelect>>', self._on_news_select)

    def _create_controls_bar(self, parent):
        """Crée la barre de contrôles en bas."""
        controls_bar = ttk.Frame(parent)
        controls_bar.pack(fill=tk.X, padx=5, pady=5)

        # Informations sur le symbole
        self.lbl_symbol_info = ttk.Label(
            controls_bar, text=f"Analyse de {self.current_symbol}", font=("Arial", 12, "bold")
        )
        self.lbl_symbol_info.pack(side=tk.LEFT)

        # Boutons d'action
        ttk.Button(controls_bar, text="💾 Sauvegarder analyse", command=self._save_analysis).pack(
            side=tk.RIGHT, padx=5
        )
        ttk.Button(controls_bar, text="📤 Exporter données", command=self._export_data).pack(
            side=tk.RIGHT, padx=5
        )
        ttk.Button(controls_bar, text="📱 Créer alerte", command=self._create_alert).pack(
            side=tk.RIGHT, padx=5
        )

    def _load_symbol_data(self):
        """Charge les données du symbole."""
        if not self.api_manager:
            self._show_no_api_message()
            return

        # Debounce: avoid concurrent/rapid repeated loads
        if self._loading:
            return
        self._loading = True

        def worker():
            try:
                # Récupération des données
                # Use resilient API wrappers (Alpha first, auto-fallback to Yahoo)
                provider = (
                    getattr(self.api_manager, 'market', None) or self.api_manager.alpha_vantage
                )
                quote = (
                    self.api_manager.get_quote(self.current_symbol)
                    if hasattr(self.api_manager, 'get_quote')
                    else provider.get_quote(self.current_symbol)
                )
                # Fetch according to chosen interval/period
                interval = (
                    getattr(self, 'var_interval', None).get()
                    if hasattr(self, 'var_interval')
                    else '1day'
                )
                if hasattr(self.api_manager, 'get_time_series'):
                    series = self.api_manager.get_time_series(
                        self.current_symbol, interval=interval
                    )
                else:
                    series = provider.get_time_series(self.current_symbol, interval=interval)
                # Technical indicators computed locally (RSI/MACD)
                # Build closes from series for local calculations
                closes_local: list[float] = []
                try:
                    keys = list(series.keys())
                    time_series_key = next((k for k in keys if 'Time Series' in k), None)
                    if not time_series_key:
                        time_series_key = next(
                            (
                                k
                                for k in keys
                                if k.lower().startswith('weekly ')
                                or k.lower().startswith('monthly ')
                            ),
                            None,
                        )
                    ts = series.get(time_series_key) if time_series_key else None
                    if not ts:
                        # attempt structural detection
                        for k, v in series.items():
                            if isinstance(v, dict):
                                try:
                                    any_item = next(iter(v.values()))
                                    if isinstance(any_item, dict) and any(
                                        sub_key.startswith('1. open') for sub_key in any_item.keys()
                                    ):
                                        ts = v
                                        break
                                except Exception:
                                    pass
                    if isinstance(ts, dict) and ts:
                        items_sorted = list(sorted(ts.items()))
                        for _d, row in items_sorted:
                            try:
                                closes_local.append(
                                    float(row.get('4. close') or row.get('4. Close') or 0.0)
                                )
                            except Exception:
                                closes_local.append(0.0)
                except Exception:
                    closes_local = []

                # Local RSI/MACD packaged similarly to Alpha Vantage shape for reuse
                rsi = {}
                macd = {}
                try:
                    if closes_local and len(closes_local) >= 16:
                        r_vals = self._calculate_rsi(closes_local, 14)
                        # Construct AV-like mapping with synthetic dates index numbers
                        if r_vals:
                            rsi_series = {}
                            base_idx = len(closes_local) - len(r_vals)
                            for i, v in enumerate(r_vals):
                                rsi_series[str(i + base_idx)] = {'RSI': f"{float(v):.4f}"}
                            rsi = {'Technical Analysis: RSI': rsi_series}
                except Exception:
                    rsi = {}
                try:
                    if closes_local and len(closes_local) >= 35:
                        macd_line, signal_line, _hist = self._calculate_macd(closes_local)
                        if macd_line and signal_line:
                            macd_series = {}
                            # align by shortest length
                            length = min(len(macd_line), len(signal_line))
                            base_idx = len(closes_local) - length
                            for i in range(length):
                                macd_series[str(i + base_idx)] = {
                                    'MACD': f"{float(macd_line[-length + i]):.6f}",
                                    'MACD_Signal': f"{float(signal_line[-length + i]):.6f}",
                                }
                            macd = {'Technical Analysis: MACD': macd_series}
                except Exception:
                    macd = {}

                news = self.api_manager.news.get_company_news(self.current_symbol, 10)

                self.current_data = {
                    'quote': quote,
                    'series': series,
                    'rsi': rsi,
                    'macd': macd,
                    'news': news,
                }

                # Mise à jour de l'interface dans le thread principal (si fenêtre encore présente)
                try:
                    w = self.window
                    if w and int(w.winfo_exists()):
                        w.after(0, self._update_all_tabs)
                except Exception:
                    pass

            except Exception as e:  # log simplified
                err = str(e)
                try:
                    w = self.window
                    if w and int(w.winfo_exists()):
                        w.after(0, lambda err=err: self._show_error(f"Erreur de chargement: {err}"))
                except Exception:
                    pass
            finally:
                self._loading = False

        threading.Thread(target=worker, daemon=True).start()

    def _update_all_tabs(self):
        """Met à jour tous les onglets avec les nouvelles données."""
        # If window has been destroyed, skip updates
        try:
            if not self.window or not int(self.window.winfo_exists()):
                return
        except Exception:
            return

        self._update_chart()
        self._update_analysis()
        self._update_strategies()
        self._update_news()

    def _update_chart(self):
        """Met à jour le graphique."""
        if not HAS_MPL or not self.figure:
            return

        self.figure.clear()

        # Données disponibles ?
        series_all = self.current_data.get('series')
        if not series_all:
            ax = self.figure.add_subplot(111)
            ax.text(
                0.5,
                0.5,
                f"Aucune donnée disponible pour {self.current_symbol}",
                ha='center',
                va='center',
                transform=ax.transAxes,
                fontsize=14,
            )
            self.canvas.draw()
            return

        # Trouver la clé de série temporelle (robuste aux variantes Alpha Vantage)
        keys = list(series_all.keys())
        time_series_key = next((k for k in keys if 'Time Series' in k), None)
        if not time_series_key:
            time_series_key = next(
                (
                    k
                    for k in keys
                    if k.lower().startswith('weekly ') or k.lower().startswith('monthly ')
                ),
                None,
            )
        # Fallback: détection structurelle d'une mapping OHLC
        if not time_series_key:
            for k, v in series_all.items():
                if isinstance(v, dict):
                    # Prendre un échantillon et vérifier des clés OHLC
                    try:
                        any_item = next(iter(v.values()))
                    except StopIteration:
                        continue
                    if isinstance(any_item, dict) and any(
                        sub_key.startswith('1. open') or sub_key.startswith('1. Open')
                        for sub_key in any_item.keys()
                    ):
                        time_series_key = k
                        break
        # Si rien n'est trouvé, afficher un message de données vides plutôt qu'une erreur
        if not time_series_key:
            ax = self.figure.add_subplot(111)
            ax.text(
                0.5,
                0.5,
                f"Aucune donnée disponible pour {self.current_symbol}",
                ha='center',
                va='center',
                transform=ax.transAxes,
                fontsize=14,
            )
            self.canvas.draw()
            return

        time_series = series_all[time_series_key]

        # Conversion en listes et limitation par période
        opens: list[float] = []
        highs: list[float] = []
        lows: list[float] = []
        closes: list[float] = []
        volumes: list[int] = []

        try:
            n = int(self.var_period.get()) if hasattr(self, 'var_period') else 30
        except Exception:
            n = 30
        n = min(max(n, 1), 300)

        for _, data in list(sorted(time_series.items()))[-n:]:
            opens.append(float(data.get('1. open') or data.get('1. Open') or 0))
            highs.append(float(data.get('2. high') or data.get('2. High') or 0))
            lows.append(float(data.get('3. low') or data.get('3. Low') or 0))
            closes.append(float(data.get('4. close') or data.get('4. Close') or 0))
            vol = data.get('5. volume') or data.get('5. Volume') or 0
            try:
                volumes.append(int(vol))
            except Exception:
                volumes.append(0)

        # Graphique principal
        ax1 = self.figure.add_subplot(211)
        show_candles = getattr(self, 'var_show_candles', None) and self.var_show_candles.get()
        if show_candles and len(closes) > 0:
            try:
                from matplotlib.patches import Rectangle  # type: ignore

                for i in range(len(closes)):
                    c_open, c_close, c_high, c_low = opens[i], closes[i], highs[i], lows[i]
                    color = '#16a34a' if c_close >= c_open else '#dc2626'
                    ax1.vlines(i, c_low, c_high, colors=color, linewidth=1)
                    bottom = min(c_open, c_close)
                    height = abs(c_close - c_open) or 1e-9
                    ax1.add_patch(Rectangle((i - 0.3, bottom), 0.6, height, color=color, alpha=0.8))
            except Exception:
                ax1.plot(
                    range(len(closes)), closes, label='Prix de clôture', color='blue', linewidth=2
                )
        else:
            ax1.plot(range(len(closes)), closes, label='Prix de clôture', color='blue', linewidth=2)

        # Indicateurs (paramétrables)
        if getattr(self, 'var_show_sma', None) and self.var_show_sma.get():
            p = max(3, int(self.var_sma_period.get())) if hasattr(self, 'var_sma_period') else 20
            if len(closes) >= p:
                sma = self._calculate_sma(closes, p)
                ax1.plot(range(len(sma)), sma, label=f'SMA {p}', color='red', alpha=0.8)

        if getattr(self, 'var_show_ema', None) and self.var_show_ema.get():
            p = max(3, int(self.var_ema_period.get())) if hasattr(self, 'var_ema_period') else 12
            if len(closes) >= p:
                ema = self._calculate_ema(closes, p)
                ax1.plot(range(len(ema)), ema, label=f'EMA {p}', color='green', alpha=0.75)

        if getattr(self, 'var_show_bb', None) and self.var_show_bb.get():
            p = max(5, int(self.var_bb_period.get())) if hasattr(self, 'var_bb_period') else 20
            std = float(self.var_bb_std.get()) if hasattr(self, 'var_bb_std') else 2.0
            if len(closes) >= p:
                bb_upper, bb_middle, bb_lower = self._calculate_bollinger_bands(
                    closes, p, std_dev=std
                )
                ax1.plot(
                    range(len(bb_upper)), bb_upper, label='BB Supérieure', color='gray', alpha=0.45
                )
                ax1.plot(
                    range(len(bb_middle)), bb_middle, label='BB Moyenne', color='gray', alpha=0.6
                )
                ax1.plot(
                    range(len(bb_lower)), bb_lower, label='BB Inférieure', color='gray', alpha=0.45
                )
                ax1.fill_between(range(len(bb_upper)), bb_upper, bb_lower, alpha=0.08, color='gray')

        ax1.set_title(f"{self.current_symbol} - Analyse Technique")
        ax1.set_ylabel("Prix")
        # Only show legend if there are labeled artists to display
        try:
            handles, labels = ax1.get_legend_handles_labels()
            if any(lbl and not str(lbl).startswith('_') for lbl in labels):
                ax1.legend(loc='upper left', fontsize=8)
        except Exception:
            pass
        ax1.grid(True, alpha=0.3)

        # Volume + RSI/MACD panel if selected
        show_lower = (
            getattr(self, 'var_show_rsi', None)
            and self.var_show_rsi.get()
            or (getattr(self, 'var_show_macd', None) and self.var_show_macd.get())
        )
        if show_lower:
            ax2 = self.figure.add_subplot(313)
        else:
            ax2 = self.figure.add_subplot(212)
        ax2.bar(range(len(volumes)), volumes, alpha=0.6, color='orange')
        ax2.set_ylabel("Volume")
        ax2.set_xlabel("Temps")
        ax2.grid(True, alpha=0.3)

        if show_lower:
            ax3 = self.figure.add_subplot(312)
            plotted = False
            if (
                getattr(self, 'var_show_rsi', None)
                and self.var_show_rsi.get()
                and len(closes) >= 15
            ):
                rsi = self._calculate_rsi(closes, 14)
                ax3.plot(range(len(rsi)), rsi, label='RSI 14', color='#9333ea')
                ax3.axhline(70, color='red', linestyle='--', alpha=0.6)
                ax3.axhline(30, color='green', linestyle='--', alpha=0.6)
                ax3.set_ylim(0, 100)
                plotted = True
            if (
                getattr(self, 'var_show_macd', None)
                and self.var_show_macd.get()
                and len(closes) >= 35
            ):
                macd_line, signal_line, hist = self._calculate_macd(closes)
                ax3.plot(range(len(macd_line)), macd_line, label='MACD', color='#2563eb')
                ax3.plot(range(len(signal_line)), signal_line, label='Signal', color='#f59e0b')
                ax3.bar(range(len(hist)), hist, label='Hist', color='#94a3b8', alpha=0.6)
                plotted = True
            if plotted:
                try:
                    h, lab = ax3.get_legend_handles_labels()
                    if any(lab):
                        ax3.legend(loc='upper left', fontsize=8)
                except Exception:
                    pass
            ax3.grid(True, alpha=0.3)

        self.figure.tight_layout()
        self.canvas.draw()

    def _update_analysis(self):
        """Met à jour l'onglet des analyses."""
        # Widget may be destroyed; guard all UI ops
        try:
            if not self.tree_analysis or not int(self.tree_analysis.winfo_exists()):
                return
        except Exception:
            return

        # Effacer les analyses précédentes
        for item in self.tree_analysis.get_children():
            self.tree_analysis.delete(item)

        # Analyse du quote actuel
        quote = self.current_data.get('quote', {})
        if quote:
            price = float(quote.get('05. price', 0))
            change = float(quote.get('09. change', 0))
            change_pct = quote.get('10. change percent', '0%').replace('%', '')

            # Signal de tendance basé sur le changement
            trend_signal = (
                "🟢 HAUSSIER" if change > 0 else "🔴 BAISSIER" if change < 0 else "🟡 NEUTRE"
            )

            self.tree_analysis.insert(
                "",
                "end",
                values=(
                    "Prix actuel",
                    f"${price:.2f}",
                    trend_signal,
                    f"Changement: ${change:.2f} ({change_pct}%)",
                ),
            )

        # Analyse RSI
        rsi_data = self.current_data.get('rsi', {})
        if rsi_data and 'Technical Analysis: RSI' in rsi_data:
            rsi_series = rsi_data['Technical Analysis: RSI']
            if rsi_series:
                latest_date = max(rsi_series.keys())
                rsi_value = float(rsi_series[latest_date]['RSI'])

                if rsi_value > 70:
                    rsi_signal = "🔴 SURVENTE"
                    rsi_desc = "RSI > 70: Possible retournement baissier"
                elif rsi_value < 30:
                    rsi_signal = "🟢 SURACH"
                    rsi_desc = "RSI < 30: Possible retournement haussier"
                else:
                    rsi_signal = "🟡 NEUTRE"
                    rsi_desc = "RSI entre 30 et 70: Pas de signal extrême"

                self.tree_analysis.insert(
                    "", "end", values=("RSI (14)", f"{rsi_value:.2f}", rsi_signal, rsi_desc)
                )

        # Analyse MACD
        macd_data = self.current_data.get('macd', {})
        if macd_data and 'Technical Analysis: MACD' in macd_data:
            macd_series = macd_data['Technical Analysis: MACD']
            if macd_series:
                latest_date = max(macd_series.keys())
                macd_value = float(macd_series[latest_date]['MACD'])
                signal_value = float(macd_series[latest_date]['MACD_Signal'])

                if macd_value > signal_value:
                    macd_signal = "🟢 ACHAT"
                    macd_desc = "MACD au-dessus du signal: Tendance haussière"
                else:
                    macd_signal = "🔴 VENTE"
                    macd_desc = "MACD en-dessous du signal: Tendance baissière"

                self.tree_analysis.insert(
                    "", "end", values=("MACD", f"{macd_value:.4f}", macd_signal, macd_desc)
                )

        # Ajout d'analyses synthétiques
        self._add_synthetic_analysis()

    def _add_synthetic_analysis(self):
        """Ajoute des analyses synthétiques basées sur les données."""
        # Score de sentiment des news
        news = self.current_data.get('news', [])
        if news:
            sentiment_score = self._calculate_news_sentiment(news)
            if sentiment_score > 0.2:
                sentiment_signal = "🟢 POSITIF"
                sentiment_desc = "Sentiment des actualités généralement positif"
            elif sentiment_score < -0.2:
                sentiment_signal = "🔴 NÉGATIF"
                sentiment_desc = "Sentiment des actualités généralement négatif"
            else:
                sentiment_signal = "🟡 NEUTRE"
                sentiment_desc = "Sentiment des actualités mitigé"

            self.tree_analysis.insert(
                "",
                "end",
                values=(
                    "Sentiment News",
                    f"{sentiment_score:.2f}",
                    sentiment_signal,
                    sentiment_desc,
                ),
            )

        # Score global de recommandation
        overall_score = self._calculate_overall_score()
        if overall_score > 0.6:
            overall_signal = "🟢 ACHAT FORT"
            overall_desc = "Convergence d'indicateurs positifs"
        elif overall_score > 0.2:
            overall_signal = "🟢 ACHAT"
            overall_desc = "Signaux généralement positifs"
        elif overall_score < -0.6:
            overall_signal = "🔴 VENTE FORTE"
            overall_desc = "Convergence d'indicateurs négatifs"
        elif overall_score < -0.2:
            overall_signal = "🔴 VENTE"
            overall_desc = "Signaux généralement négatifs"
        else:
            overall_signal = "🟡 ATTENTE"
            overall_desc = "Signaux mitigés, attendre confirmation"

        self.tree_analysis.insert(
            "", "end", values=("Score Global", f"{overall_score:.2f}", overall_signal, overall_desc)
        )

    def _update_strategies(self):
        """Met à jour l'onglet des stratégies."""
        try:
            if not self.txt_strategies or not int(self.txt_strategies.winfo_exists()):
                return
        except Exception:
            return
        self.txt_strategies.delete(1.0, tk.END)

        strategies_text = f"""
📊 STRATÉGIES RECOMMANDÉES POUR {self.current_symbol}
{'=' * 60}

🎯 STRATÉGIE COURT TERME (1-7 jours)
"""

        # Stratégie basée sur RSI
        rsi_data = self.current_data.get('rsi', {})
        if rsi_data and 'Technical Analysis: RSI' in rsi_data:
            rsi_series = rsi_data['Technical Analysis: RSI']
            if rsi_series:
                latest_date = max(rsi_series.keys())
                rsi_value = float(rsi_series[latest_date]['RSI'])

                if rsi_value > 70:
                    strategies_text += """
• Stratégie RSI Survente:
  - Attendre une cassure sous 70 pour vendre
  - Stop-loss à +5% du prix actuel
  - Take-profit à -10% du prix actuel
  - Horizon: 3-5 jours
"""
                elif rsi_value < 30:
                    strategies_text += """
• Stratégie RSI Surachat:
  - Acheter dès maintenant ou sur rebond
  - Stop-loss à -8% du prix actuel
  - Take-profit à +15% du prix actuel
  - Horizon: 5-10 jours
"""

        # Stratégie MACD
        macd_data = self.current_data.get('macd', {})
        if macd_data and 'Technical Analysis: MACD' in macd_data:
            strategies_text += """

🔄 STRATÉGIE MOYEN TERME (1-4 semaines)
• Stratégie MACD:
  - Suivre les croisements MACD/Signal
  - Position longue si MACD > Signal
  - Position courte si MACD < Signal
  - Stop-loss mobile à 10%
"""

        # Stratégies de trading algorithmique
        strategies_text += """

🤖 STRATÉGIES ALGORITHMIQUES

• Stratégie Mean Reversion:
  - Acheter quand le prix s'écarte de -2σ de la moyenne
  - Vendre quand le prix revient à la moyenne
  - Utiliser Bollinger Bands comme référence

• Stratégie Momentum:
  - Acheter sur cassure de résistance + volume
  - Vendre sur cassure de support
  - Confirmer avec RSI et MACD

• Stratégie DCA (Dollar Cost Averaging):
  - Achats réguliers indépendamment du prix
  - Recommandé si score global > 0
  - Montant: 1-5% du capital par semaine

🎯 NIVEAUX CLÉS:
"""

        # Calcul des niveaux de support/résistance
        quote = self.current_data.get('quote', {})
        if quote:
            current_price = float(quote.get('05. price', 0))
            strategies_text += f"""
• Prix actuel: ${current_price:.2f}
• Support: ${current_price * 0.95:.2f} (-5%)
• Résistance: ${current_price * 1.05:.2f} (+5%)
• Stop-loss suggéré: ${current_price * 0.92:.2f} (-8%)
• Take-profit suggéré: ${current_price * 1.12:.2f} (+12%)
"""

        strategies_text += """

⚠️ GESTION DU RISQUE:
• Ne jamais risquer plus de 2-3% du capital par trade
• Diversifier sur plusieurs positions
• Adapter la taille de position selon la volatilité
• Utiliser des stops-loss systématiques

📈 INDICATEURS À SURVEILLER:
• Volume de transaction (confirme les mouvements)
• Actualités sectorielles et économiques
• Corrélation avec les indices de marché
• Calendrier économique (earnings, Fed, etc.)
"""

        self.txt_strategies.insert(1.0, strategies_text)

    def _update_news(self):
        """Met à jour l'onglet des actualités."""
        # Guard widget existence
        try:
            if not self.tree_news or not int(self.tree_news.winfo_exists()):
                return
        except Exception:
            return

        # Effacer les actualités précédentes
        for item in self.tree_news.get_children():
            self.tree_news.delete(item)

        news = self.current_data.get('news', [])
        for article in news:
            date = article.get('publishedAt', '')[:10]
            title = article.get('title', 'Sans titre')

            # Analyse de sentiment simple
            sentiment = self._analyze_article_sentiment(article)

            self.tree_news.insert("", "end", values=(date, title, sentiment))

    def _analyze_article_sentiment(self, article):
        """Analyse le sentiment d'un article."""
        # Robust extraction (avoid None.lower errors)
        if not isinstance(article, dict):
            return "🟡 Neutre"
        title_raw = article.get('title') or ''
        description_raw = article.get('description') or ''
        try:
            title = title_raw.lower()
        except Exception:
            title = ''
        try:
            description = description_raw.lower()
        except Exception:
            description = ''
        text = f"{title} {description}"

        positive_words = ['up', 'rise', 'gain', 'positive', 'growth', 'strong', 'beat', 'exceed']
        negative_words = ['down', 'fall', 'loss', 'negative', 'decline', 'weak', 'miss', 'below']

        positive_count = sum(1 for word in positive_words if word in text)
        negative_count = sum(1 for word in negative_words if word in text)

        if positive_count > negative_count:
            return "🟢 Positif"
        elif negative_count > positive_count:
            return "🔴 Négatif"
        else:
            return "🟡 Neutre"

    def _calculate_news_sentiment(self, news_list):
        """Calcule un score de sentiment global pour les actualités."""
        if not news_list:
            return 0
        total_score = 0
        considered = 0
        for article in news_list[:5]:  # Prendre seulement les 5 plus récents
            if not isinstance(article, dict):
                continue
            try:
                sentiment = self._analyze_article_sentiment(article)
            except Exception:  # sécurité
                continue
            considered += 1
            if "Positif" in sentiment:
                total_score += 1
            elif "Négatif" in sentiment:
                total_score -= 1
        if not considered:
            return 0
        return total_score / considered

    def _calculate_overall_score(self):
        """Calcule un score global basé sur tous les indicateurs."""
        score = 0
        indicators_count = 0

        # Score RSI
        rsi_data = self.current_data.get('rsi', {})
        if rsi_data and 'Technical Analysis: RSI' in rsi_data:
            rsi_series = rsi_data['Technical Analysis: RSI']
            if rsi_series:
                latest_date = max(rsi_series.keys())
                rsi_value = float(rsi_series[latest_date]['RSI'])

                if rsi_value < 30:
                    score += 1  # Surachat = positif
                elif rsi_value > 70:
                    score -= 1  # Survente = négatif

                indicators_count += 1

        # Score MACD
        macd_data = self.current_data.get('macd', {})
        if macd_data and 'Technical Analysis: MACD' in macd_data:
            macd_series = macd_data['Technical Analysis: MACD']
            if macd_series:
                latest_date = max(macd_series.keys())
                macd_value = float(macd_series[latest_date]['MACD'])
                signal_value = float(macd_series[latest_date]['MACD_Signal'])

                if macd_value > signal_value:
                    score += 1
                else:
                    score -= 1

                indicators_count += 1

        # Score sentiment des news
        news = self.current_data.get('news', [])
        if news:
            sentiment_score = self._calculate_news_sentiment(news)
            score += sentiment_score
            indicators_count += 1

        # Score basé sur le changement de prix
        quote = self.current_data.get('quote', {})
        if quote:
            change = float(quote.get('09. change', 0))
            if change > 0:
                score += 0.5
            elif change < 0:
                score -= 0.5
            indicators_count += 1

        return score / indicators_count if indicators_count > 0 else 0

    def _calculate_sma(self, prices, period):
        """Calcule la moyenne mobile simple."""
        if len(prices) < period:
            return []

        sma = []
        for i in range(period - 1, len(prices)):
            sma.append(sum(prices[i - period + 1 : i + 1]) / period)

        return sma

    def _calculate_ema(self, prices, period):
        """Calcule la moyenne mobile exponentielle."""
        if len(prices) < period:
            return []

        multiplier = 2 / (period + 1)
        ema = [sum(prices[:period]) / period]  # Premier EMA = SMA

        for i in range(period, len(prices)):
            ema.append((prices[i] * multiplier) + (ema[-1] * (1 - multiplier)))

        return ema

    def _calculate_bollinger_bands(self, prices, period, std_dev=2):
        """Calcule les bandes de Bollinger."""
        if len(prices) < period:
            return [], [], []

        sma = self._calculate_sma(prices, period)
        upper_band = []
        lower_band = []

        for i in range(period - 1, len(prices)):
            subset = prices[i - period + 1 : i + 1]
            std = (sum([(x - sma[i - period + 1]) ** 2 for x in subset]) / period) ** 0.5
            upper_band.append(sma[i - period + 1] + (std * std_dev))
            lower_band.append(sma[i - period + 1] - (std * std_dev))

        return upper_band, sma, lower_band

    def _on_interval_change(self, event=None):
        """Appelé quand l'intervalle change."""
        self._load_symbol_data()

    def _on_period_change(self, event=None):
        """Appelé quand la période change."""
        self._load_symbol_data()

    def _on_news_select(self, event):
        """Appelé quand une actualité est sélectionnée."""
        selection = self.tree_news.selection()
        if selection:
            item = self.tree_news.item(selection[0])
            title = item['values'][1]

            # Trouver l'article complet
            news = self.current_data.get('news', [])
            for article in news:
                if article.get('title') == title:
                    details = f"Titre: {article.get('title', 'N/A')}\n\n"
                    details += f"Source: {article.get('source', {}).get('name', 'N/A')}\n"
                    details += f"Date: {article.get('publishedAt', 'N/A')}\n\n"
                    details += f"Description:\n{article.get('description', 'Aucune description disponible')}\n\n"
                    details += f"URL: {article.get('url', 'N/A')}"

                    self.txt_news_detail.delete(1.0, tk.END)
                    self.txt_news_detail.insert(1.0, details)
                    break

    def _show_no_api_message(self):
        """Affiche un message quand les APIs ne sont pas disponibles."""
        if self.figure:
            self.figure.clear()
            ax = self.figure.add_subplot(111)
            ax.text(
                0.5,
                0.5,
                "APIs externes non configurées\n\nVeuillez configurer les clés API dans .env",
                ha='center',
                va='center',
                transform=ax.transAxes,
                fontsize=14,
                color='red',
            )
            ax.set_xticks([])
            ax.set_yticks([])
            if self.canvas:
                self.canvas.draw()

    def _show_error(self, message):
        """Affiche un message d'erreur."""
        if hasattr(self.app, 'set_status'):
            self.app.set_status(message, error=True)

    def _run_backtest(self):
        """Lance un backtest simple (SMA crossover) et affiche les résultats."""
        if not self.current_data.get('series'):
            tk.messagebox.showwarning("Backtesting", "Données historiques indisponibles.")
            return

        def worker():
            try:
                dates, closes = self._extract_closes(limit=500)
                if len(closes) < 60:
                    raise ValueError("Pas assez de données pour un backtest (>=60 bougies requis)")

                # Paramètres UI (avec défauts)
                fast = int(self.var_bt_fast.get()) if hasattr(self, 'var_bt_fast') else 10
                slow = int(self.var_bt_slow.get()) if hasattr(self, 'var_bt_slow') else 30
                res = self._backtest_sma_crossover(closes, fast=fast, slow=slow)

                # Compose results text
                txt = []
                txt.append(f"Backtest SMA({fast}) / SMA({slow}) sur {len(closes)} bougies")
                txt.append("-")
                txt.append(f"Trades exécutés: {res['trades']}")
                txt.append(f"Rendement total: {res['total_return']*100:.2f}%")
                txt.append(f"CAGR (approx.): {res['cagr']*100:.2f}%")
                txt.append(f"Max drawdown: {res['max_dd']*100:.2f}%")
                txt.append(f"Win rate: {res['win_rate']*100:.1f}%")
                txt.append(f"Sharpe (ann.): {res['sharpe']:.2f}")
                text_final = "\n".join(txt)

                def show():
                    win = tk.Toplevel(self.window or self.app)
                    win.title(f"Backtesting - {self.current_symbol}")
                    win.geometry("720x520")
                    frm = ttk.Frame(win)
                    frm.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
                    tv = tk.Text(frm, height=10, wrap=tk.WORD)
                    tv.pack(fill=tk.X)
                    tv.insert(1.0, text_final)
                    tv.configure(state=tk.DISABLED)
                    if HAS_MPL:
                        fig = Figure(figsize=(7, 3), dpi=100)
                        ax = fig.add_subplot(111)
                        eq = res['equity']
                        ax.plot(eq, label='Courbe de capital', color='#2563eb')
                        ax.set_title('Équity')
                        ax.grid(True, alpha=0.3)
                        ax.legend(loc='upper left')
                        canvas = FigureCanvasTkAgg(fig, frm)
                        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True, pady=8)
                        canvas.draw()
                    ttk.Button(frm, text='Fermer', command=win.destroy).pack(anchor='e')

                # ensure UI exists
                try:
                    w = self.window
                    if w and int(w.winfo_exists()):
                        w.after(0, show)
                    else:
                        self.app.after(0, show)
                except Exception:
                    self.app.after(0, show)
            except Exception as e:
                try:
                    tk.messagebox.showerror("Backtesting", str(e))
                except Exception:
                    pass

        threading.Thread(target=worker, daemon=True).start()

    def _run_simulation(self):
        """Lance une simulation Monte Carlo basée sur les rendements journaliers."""
        if not self.current_data.get('series'):
            tk.messagebox.showwarning("Simulation", "Données historiques indisponibles.")
            return

        def worker():
            try:
                _, closes = self._extract_closes(limit=500)
                if len(closes) < 50:
                    raise ValueError("Pas assez de données pour simuler (>=50 bougies requis)")
                rets = self._daily_returns(closes)
                # Monte Carlo parameters
                horizon = 252  # ~1 an
                runs = 500
                start_cap = 10000.0
                outcomes = []
                for _ in range(runs):
                    cap = start_cap
                    for _d in range(horizon):
                        r = random.choice(rets)  # bootstrap
                        cap *= 1.0 + r
                    outcomes.append(cap)
                outcomes.sort()
                p5 = outcomes[int(0.05 * runs)]
                p50 = outcomes[int(0.50 * runs)]
                p95 = outcomes[int(0.95 * runs)]
                txt = [
                    f"Simulation Monte Carlo ({runs} runs, {horizon} jours)",
                    "-",
                    f"Capital initial: ${start_cap:,.0f}",
                    f"P5:  ${p5:,.0f}",
                    f"P50: ${p50:,.0f}",
                    f"P95: ${p95:,.0f}",
                ]
                text_final = "\n".join(txt)

                def show():
                    win = tk.Toplevel(self.window or self.app)
                    win.title(f"Simulation - {self.current_symbol}")
                    win.geometry("720x520")
                    frm = ttk.Frame(win)
                    frm.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
                    tv = tk.Text(frm, height=8, wrap=tk.WORD)
                    tv.pack(fill=tk.X)
                    tv.insert(1.0, text_final)
                    tv.configure(state=tk.DISABLED)
                    if HAS_MPL:
                        fig = Figure(figsize=(7, 3), dpi=100)
                        ax = fig.add_subplot(111)
                        ax.hist(outcomes, bins=30, color='#22c55e', alpha=0.8)
                        ax.set_title('Distribution des capitaux finaux')
                        ax.grid(True, alpha=0.3)
                        canvas = FigureCanvasTkAgg(fig, frm)
                        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True, pady=8)
                        canvas.draw()
                    ttk.Button(frm, text='Fermer', command=win.destroy).pack(anchor='e')

                try:
                    w = self.window
                    if w and int(w.winfo_exists()):
                        w.after(0, show)
                    else:
                        self.app.after(0, show)
                except Exception:
                    self.app.after(0, show)
            except Exception as e:
                try:
                    tk.messagebox.showerror("Simulation", str(e))
                except Exception:
                    pass

        threading.Thread(target=worker, daemon=True).start()

    def _optimize_strategy(self):
        """Optimise une stratégie SMA crossover via recherche en grille simple."""
        if not self.current_data.get('series'):
            tk.messagebox.showwarning("Optimisation", "Données historiques indisponibles.")
            return

        def worker():
            try:
                _, closes = self._extract_closes(limit=600)
                if len(closes) < 120:
                    raise ValueError("Pas assez de données pour optimiser (>=120 bougies requis)")
                # Utilise les voisinages autour des paramètres actuels
                base_f = int(self.var_bt_fast.get()) if hasattr(self, 'var_bt_fast') else 10
                base_s = int(self.var_bt_slow.get()) if hasattr(self, 'var_bt_slow') else 30
                candidates_fast = sorted(
                    set(
                        [
                            max(3, base_f - 2),
                            base_f - 1,
                            base_f,
                            base_f + 1,
                            base_f + 2,
                            5,
                            8,
                            12,
                            15,
                        ]
                    )
                )
                candidates_slow = sorted(
                    set(
                        [
                            max(5, base_s - 10),
                            base_s - 5,
                            base_s,
                            base_s + 5,
                            base_s + 10,
                            20,
                            30,
                            40,
                            50,
                            100,
                            150,
                        ]
                    )
                )
                results = []
                for f in candidates_fast:
                    for s in candidates_slow:
                        if f >= s:
                            continue
                        r = self._backtest_sma_crossover(closes, fast=f, slow=s)
                        score = r['total_return']  # could blend Sharpe too
                        results.append((score, r, f, s))
                results.sort(key=lambda x: x[0], reverse=True)
                top = results[:5]
                lines = ["Top paramètres SMA (max rendement):", "-"]
                for rank, (score, r, f, s) in enumerate(top, 1):
                    lines.append(
                        f"#{rank} SMA({f},{s}) | Ret: {r['total_return']*100:.2f}% | Sharpe: {r['sharpe']:.2f} | MDD: {r['max_dd']*100:.1f}% | Trades: {r['trades']}"
                    )
                text_final = "\n".join(lines)

                def show():
                    win = tk.Toplevel(self.window or self.app)
                    win.title(f"Optimisation - {self.current_symbol}")
                    win.geometry("780x360")
                    frm = ttk.Frame(win)
                    frm.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
                    tv = tk.Text(frm, height=12, wrap=tk.WORD)
                    tv.pack(fill=tk.BOTH, expand=True)
                    tv.insert(1.0, text_final)
                    tv.configure(state=tk.DISABLED)
                    ttk.Button(frm, text='Fermer', command=win.destroy).pack(anchor='e')

                try:
                    w = self.window
                    if w and int(w.winfo_exists()):
                        w.after(0, show)
                    else:
                        self.app.after(0, show)
                except Exception:
                    self.app.after(0, show)
            except Exception as e:
                try:
                    tk.messagebox.showerror("Optimisation", str(e))
                except Exception:
                    pass

        threading.Thread(target=worker, daemon=True).start()

    # ----------------- Helpers: data and metrics -----------------
    def _extract_closes(self, limit: int = 500):
        """Return (dates, closes) ascending, limited to last N."""
        series_all = self.current_data.get('series') or {}
        if not series_all:
            return [], []
        # Find time series key similar to _update_chart
        keys = list(series_all.keys())
        time_series_key = next((k for k in keys if 'Time Series' in k), None)
        if not time_series_key:
            time_series_key = next(
                (
                    k
                    for k in keys
                    if k.lower().startswith('weekly ') or k.lower().startswith('monthly ')
                ),
                None,
            )
        if not time_series_key:
            for k, v in series_all.items():
                if isinstance(v, dict):
                    try:
                        any_item = next(iter(v.values()))
                    except StopIteration:
                        continue
                    if isinstance(any_item, dict) and any(
                        sub_key.startswith('1. open') or sub_key.startswith('1. Open')
                        for sub_key in any_item.keys()
                    ):
                        time_series_key = k
                        break
        ts = series_all.get(time_series_key, {}) if time_series_key else {}
        items = list(sorted(ts.items()))
        if limit and len(items) > limit:
            items = items[-limit:]
        dates = [d for d, _ in items]
        closes = [float(v.get('4. close') or v.get('4. Close') or 0) for _, v in items]
        return dates, closes

    def _daily_returns(self, closes):
        rets = []
        for i in range(1, len(closes)):
            prev, nxt = closes[i - 1], closes[i]
            if prev and nxt:
                rets.append((nxt / prev) - 1.0)
        return rets

    def _max_drawdown(self, equity):
        peak = equity[0] if equity else 0
        mdd = 0.0
        for v in equity:
            if v > peak:
                peak = v
            dd = (v / peak) - 1.0 if peak else 0.0
            if dd < mdd:
                mdd = dd
        return abs(mdd)

    def _sharpe(self, rets):
        if not rets:
            return 0.0
        mu = statistics.fmean(rets) if hasattr(statistics, 'fmean') else sum(rets) / len(rets)
        sd = statistics.pstdev(rets) if len(rets) > 1 else 0.0
        if sd == 0:
            return 0.0
        return (mu / sd) * math.sqrt(252.0)

    def _backtest_sma_crossover(self, closes, fast=10, slow=30):
        """Simple long-only SMA crossover backtest."""
        if slow >= len(closes):
            raise ValueError("Périodes SMA trop longues pour la série fournie")
        # compute SMAs
        sma_f = self._calculate_sma(closes, fast)
        sma_s = self._calculate_sma(closes, slow)
        # align lengths to closes: pad with Nones at beginning to match index
        pad_f = [None] * (fast - 1) + sma_f
        pad_s = [None] * (slow - 1) + sma_s
        pos = 0  # 0 cash, 1 long
        equity = [1.0]
        trades = 0
        wins = 0
        daily = []
        for i in range(1, len(closes)):
            sf = pad_f[i]
            ss = pad_s[i]
            # signal only when both valid
            if sf is not None and ss is not None:
                new_pos = 1 if sf > ss else 0
                if new_pos != pos:
                    # count a trade; mark win if equity increased since last trade
                    trades += 1
                    if daily and sum(daily[-5:]) > 0:  # crude win heuristic
                        wins += 1
                pos = new_pos
            r = (closes[i] / closes[i - 1]) - 1.0
            pr = r * pos
            daily.append(pr)
            equity.append(equity[-1] * (1.0 + pr))
        total_return = equity[-1] - 1.0
        years = max(1e-9, len(daily) / 252.0)
        cagr = (equity[-1] ** (1 / years)) - 1.0 if equity[-1] > 0 else -1.0
        mdd = self._max_drawdown(equity)
        shp = self._sharpe(daily)
        win_rate = (wins / trades) if trades else 0.0
        return {
            'equity': equity,
            'trades': trades,
            'win_rate': win_rate,
            'total_return': total_return,
            'cagr': cagr,
            'max_dd': mdd,
            'sharpe': shp,
        }

    # --------- Monitoring IA (alerts) ---------
    def _toggle_monitoring(self):
        active = getattr(self, '_monitoring_active', False)
        self._monitoring_active = not active
        if hasattr(self, 'btn_monitor') and self.btn_monitor:
            self.btn_monitor.config(text='Arrêter' if self._monitoring_active else 'Démarrer')
        if self._monitoring_active:
            self._last_signal_state = getattr(
                self, '_last_signal_state', {'sma': None, 'rsi': None}
            )
            self._monitor_tick()

    def _monitor_tick(self):
        if not getattr(self, '_monitoring_active', False):
            return
        try:
            interval = (
                getattr(self, 'var_interval', None).get()
                if hasattr(self, 'var_interval')
                else '1day'
            )
            if self.api_manager and hasattr(self.api_manager, 'get_time_series'):
                series = self.api_manager.get_time_series(self.current_symbol, interval=interval)
            else:
                series = None
            if series:
                self.current_data['series'] = series
                _, closes = self._extract_closes(limit=400)
                # SMA crossover alert
                if (
                    getattr(self, 'var_mon_sma', None)
                    and self.var_mon_sma.get()
                    and len(closes) > 60
                ):
                    f = int(self.var_bt_fast.get()) if hasattr(self, 'var_bt_fast') else 10
                    s = int(self.var_bt_slow.get()) if hasattr(self, 'var_bt_slow') else 30
                    prev_state, new_state = self._detect_sma_cross(closes, f, s)
                    if prev_state != new_state and new_state in ('bull', 'bear'):
                        self._emit_alert(
                            'SMA Crossover',
                            f"{self.current_symbol}: Croisement {new_state.upper()} (SMA{f}/{s})",
                            level='WARN',
                        )
                        self._last_signal_state['sma'] = new_state
                # RSI thresholds alert
                if (
                    getattr(self, 'var_mon_rsi', None)
                    and self.var_mon_rsi.get()
                    and len(closes) > 20
                ):
                    rsi = self._calculate_rsi(closes, 14)
                    if len(rsi) >= 2:
                        curr = rsi[-1]
                        state = (
                            'overbought' if curr > 70 else 'oversold' if curr < 30 else 'neutral'
                        )
                        last = self._last_signal_state.get('rsi')
                        if last != state and state in ('overbought', 'oversold'):
                            label = 'RSI > 70' if state == 'overbought' else 'RSI < 30'
                            self._emit_alert(
                                'RSI Seuil', f"{self.current_symbol}: {label}", level='INFO'
                            )
                            self._last_signal_state['rsi'] = state
        except Exception:
            pass
        # Reschedule
        try:
            delay = (
                max(15, int(self.var_mon_interval.get())) * 1000
                if hasattr(self, 'var_mon_interval')
                else 60000
            )
        except Exception:
            delay = 60000
        try:
            w = self.window
            if w and int(w.winfo_exists()):
                w.after(delay, self._monitor_tick)
            else:
                self.app.after(delay, self._monitor_tick)
        except Exception:
            # fallback
            self.app.after(delay, self._monitor_tick)

    def _emit_alert(self, title: str, message: str, level: str = 'INFO'):
        # App status
        try:
            if hasattr(self.app, 'set_status'):
                self.app.set_status(f"{title}: {message}")
        except Exception:
            pass
        # Telegram via APIManager if available
        try:
            if self.api_manager and hasattr(self.api_manager, 'notify_alert'):
                self.api_manager.notify_alert(level, title, message)
        except Exception:
            pass

    def _detect_sma_cross(self, closes, fast, slow):
        sma_f = self._calculate_sma(closes, fast)
        sma_s = self._calculate_sma(closes, slow)
        pad_f = [None] * (fast - 1) + sma_f
        pad_s = [None] * (slow - 1) + sma_s
        last_diff = None
        prev_state = getattr(self, '_last_signal_state', {}).get('sma')
        for i in range(len(closes) - 2, len(closes)):
            if i <= 0 or i >= len(pad_f) or i >= len(pad_s):
                continue
            if pad_f[i] is None or pad_s[i] is None:
                continue
            diff = pad_f[i] - pad_s[i]
            last_diff = diff if last_diff is None else last_diff
        # Determine new state from last valid values
        new_state = prev_state
        try:
            i = len(closes) - 1
            if (
                pad_f[i] is not None
                and pad_s[i] is not None
                and pad_f[i - 1] is not None
                and pad_s[i - 1] is not None
            ):
                prev_diff = pad_f[i - 1] - pad_s[i - 1]
                curr_diff = pad_f[i] - pad_s[i]
                if prev_diff <= 0 and curr_diff > 0:
                    new_state = 'bull'
                elif prev_diff >= 0 and curr_diff < 0:
                    new_state = 'bear'
        except Exception:
            pass
        return prev_state, new_state

    # --------- Additional indicator helpers ---------
    def _calculate_rsi(self, prices, period=14):
        if len(prices) < period + 1:
            return []
        gains = []
        losses = []
        for i in range(1, len(prices)):
            ch = prices[i] - prices[i - 1]
            gains.append(max(0.0, ch))
            losses.append(max(0.0, -ch))
        # Wilder's smoothing
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period
        rsi = [None] * period
        for i in range(period, len(prices) - 1):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
            rs = (avg_gain / avg_loss) if avg_loss != 0 else float('inf')
            val = 100 - (100 / (1 + rs)) if rs != float('inf') else 100.0
            rsi.append(val)
        return [v for v in rsi if v is not None]

    def _calculate_macd(self, prices, fast=12, slow=26, signal=9):
        if len(prices) < slow + signal:
            return [], [], []
        ema_fast = self._calculate_ema(prices, fast)
        ema_slow = self._calculate_ema(prices, slow)
        # Align
        pad_fast = [None] * (fast - 1) + ema_fast
        pad_slow = [None] * (slow - 1) + ema_slow
        macd_line = []
        for i in range(len(prices)):
            if (
                i < len(pad_fast)
                and i < len(pad_slow)
                and pad_fast[i] is not None
                and pad_slow[i] is not None
            ):
                macd_line.append(pad_fast[i] - pad_slow[i])
        signal_line = self._calculate_ema(macd_line, signal) if len(macd_line) >= signal else []
        # align
        pad_signal = [None] * (signal - 1) + signal_line
        hist = []
        for i in range(len(macd_line)):
            s = pad_signal[i] if i < len(pad_signal) else None
            if s is not None:
                hist.append(macd_line[i] - s)
        return macd_line, signal_line, hist

    def _save_analysis(self):
        """Sauvegarde l'analyse."""
        # TODO: Implémenter la sauvegarde
        tk.messagebox.showinfo("Sauvegarde", f"Analyse de {self.current_symbol} sauvegardée")

    def _export_data(self):
        """Exporte les données."""
        # TODO: Implémenter l'export
        tk.messagebox.showinfo("Export", f"Données de {self.current_symbol} exportées")

    def _create_alert(self):
        """Crée une alerte."""
        # TODO: Implémenter les alertes
        tk.messagebox.showinfo("Alerte", f"Alerte créée pour {self.current_symbol}")


__all__ = ['SymbolAnalyzer']
