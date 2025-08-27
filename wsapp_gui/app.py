from __future__ import annotations
import threading
from datetime import datetime
from typing import List, Dict, Optional
import tkinter as tk
import os
from tkinter import ttk, messagebox, filedialog, simpledialog
import csv
from ws_api.exceptions import (
    OTPRequiredException,
    LoginFailedException,
    ManualLoginRequired,
    WSApiException,
)
from ws_api import WealthsimpleAPI
from ai_agent import AIAgent
from run_ws import load_session, save_session  # type: ignore
from .theming import PALETTES, apply_palette
from utils.env import load_dotenv_safe
from utils.logging_setup import setup_logging
from .agent_ui import AgentUI
from .charts import ChartController, HAS_MPL
from .diagnostics_ui import DiagnosticsPanel
from .strategy_runner import StrategyRunner
from .trade_executor import TradeExecutor
# messagebox is already imported above with ttk
from .screener_ui import ScreenerPanel
from .backtest_ui import BacktestPanel
from .media_manager import MediaManager
from .config import app_config
from .chat_manager import ChatManager

try:
    from external_apis import APIManager
    HAS_EXTERNAL_APIS = True
except ImportError:
    HAS_EXTERNAL_APIS = False
    APIManager = None

try:
    from symbol_analyzer import SymbolAnalyzer
    HAS_SYMBOL_ANALYZER = True
except ImportError:
    HAS_SYMBOL_ANALYZER = False
    SymbolAnalyzer = None


class WSApp(tk.Tk):
    def __init__(self):
        """Initialise la fenêtre principale et l'état de l'application."""
        super().__init__()
        # Setup logging & env (idempotent)
        setup_logging()
        load_dotenv_safe()

        self.title('Wealthsimple Portfolio')
        # Restaurer la géométrie de la fenêtre depuis la configuration
        try:
            self.geometry(app_config.get_window_geometry())
        except Exception:
            self.geometry('1200x780')
        # Sauvegarder la géométrie à la fermeture
        self.protocol('WM_DELETE_WINDOW', self._on_close)

        # Core state
        self.api = None  # type: Optional[WealthsimpleAPI]
        self.accounts = []  # type: List[dict]
        self.current_account_id = None  # type: Optional[str]
        self._positions_cache = []  # type: List[dict]
        self._activities_cache = []  # type: List[dict]
        self.base_currency = 'CAD'

        # Theming / helpers
        self._theme = 'light'
        self._palettes = PALETTES

        # Agents / controllers
        self.agent = AIAgent()
        self.agent_ui = None  # type: Optional[AgentUI]
        self.chart = ChartController(self)
        self.chat_manager = ChatManager(self)

        # External APIs
        self.api_manager = APIManager() if HAS_EXTERNAL_APIS else None

        # Symbol analyzer
        self.symbol_analyzer = (
            SymbolAnalyzer(self) if HAS_SYMBOL_ANALYZER else None
        )
        self.media = MediaManager()
        self._logo_images = {}
        self._news_articles = []
        self._news_image_ref = None

        # Tk variables
        self.var_email = tk.StringVar()
        self.var_pwd = tk.StringVar()
        self.var_password = self.var_pwd  # compat
        self.var_otp = tk.StringVar()
        self.var_status = tk.StringVar(value='Prêt')
        self.var_start = tk.StringVar()
        self.var_end = tk.StringVar()
        self.var_limit = tk.IntVar(value=10)
        self.var_act_filter = tk.StringVar()
        self.auto_refresh = tk.BooleanVar(value=False)
        self.auto_refresh_interval = tk.IntVar(value=60)
        self.var_chat = tk.StringVar()
        self.var_chart_range = tk.IntVar(value=30)
        # Per-account alerts toggle (persisted)
        self.alert_toggle = tk.BooleanVar(value=True)
        # Initialize technical alerts preference on agent from config
        try:
            self.agent.allow_technical_alerts = bool(app_config.get('integrations.telegram.include_technical', True))
        except Exception:
            pass

        # Build UI & attempt auto login
        self._build_ui()
        # Thème initial depuis la configuration
        try:
            self.apply_theme(app_config.get('theme', 'light') or 'light')
        except Exception:
            self.apply_theme('light')
        # Onboarding (premier démarrage)
        try:
            if not bool(app_config.get('ui.onboarded', False)):
                self._show_banner(
                    "Bienvenue 👋 Astuces: 1) Double-cliquez un symbole pour l'analyser, 2) Ajustez 'Top N' dans Mouvements, 3) Configurez Telegram dans son onglet.",
                    kind='info',
                    timeout_ms=10000,
                )
                app_config.set('ui.onboarded', True)
            
        except Exception:
            pass
        self._try_auto_login()
        self.after(3000, self._refresh_ai_signals_periodic)
        # Always-on AI watchdog: periodically re-evaluate signals from positions
        self.after(10000, self._ai_watchdog_tick)
        # Periodic insights badge refresh
        try:
            self.after(8000, self._refresh_insights_badge)
        except Exception:
            pass
        # Démarrage Telegram conditionnel selon la configuration
        try:
            if app_config.get('integrations.telegram.enabled', False):
                self._start_telegram_bridge()
        except Exception:
            pass
        # (fin __init__)

    # (legacy _load_env_vars removed; handled by utils.env.load_dotenv_safe)

    def _build_ui(self):
        top = ttk.Frame(self)
        top.pack(fill=tk.X, padx=8, pady=4)
        ttk.Label(top, text='Email').grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(top, textvariable=self.var_email, width=28).grid(
            row=0, column=1
        )
        ttk.Label(top, text='Mot de passe').grid(row=0, column=2, sticky=tk.W)
        ttk.Entry(top, textvariable=self.var_pwd, show='*', width=20).grid(
            row=0, column=3
        )
        ttk.Label(top, text='OTP').grid(row=0, column=4, sticky=tk.W)
        ttk.Entry(top, textvariable=self.var_otp, width=10).grid(
            row=0, column=5
        )
        self.btn_login = ttk.Button(
            top, text='Connexion', command=self.login_clicked
        )
        self.btn_login.grid(row=0, column=6, padx=4)
        ttk.Button(top, text='Thème', command=self.toggle_theme).grid(
            row=0, column=7
        )
        # Insights badge (truncated with click-to-expand)
        self._insights_full = ''
        self.var_insights = tk.StringVar(value='')
        self.lbl_insights = ttk.Label(top, textvariable=self.var_insights, foreground='gray', cursor='hand2')
        self.lbl_insights.grid(row=0, column=8, padx=(8, 0))
        self.lbl_insights.bind('<Button-1>', lambda e: self._show_insights_details())
        ttk.Label(self, textvariable=self.var_status, anchor='w').pack(
            fill=tk.X, padx=8
        )
        # Zone de bannière non bloquante (cachée par défaut)
        self._banner_container = ttk.Frame(self)
        self._banner_container.pack(fill=tk.X, padx=8, pady=(0, 4))
        self._banner_frame = ttk.Frame(self._banner_container)
        self._banner_msg = ttk.Label(self._banner_frame, text='', anchor='w')
        self._banner_msg.pack(side=tk.LEFT, fill=tk.X, expand=True)
        # Bouton détails (affiché en mode debug avec détails capturés)
        self._banner_details_button = ttk.Button(
            self._banner_frame,
            text='Voir détails',
            width=12,
            command=lambda: self._toggle_banner_details(),
        )
        # Ne pas pack tout de suite; visible seulement si debug + détails
        self._banner_close = ttk.Button(
            self._banner_frame,
            text='✕',
            width=2,
            command=lambda: self._hide_banner(),
        )
        self._banner_close.pack(side=tk.RIGHT)
        self._banner_container.pack_forget()  # caché tant qu'aucun message
        # Panneau de détails repliable
        self._banner_details_frame = ttk.Frame(self)
        self._banner_details_text = tk.Text(self._banner_details_frame, height=6, wrap='word')
        _scr = ttk.Scrollbar(self._banner_details_frame, orient='vertical', command=self._banner_details_text.yview)
        self._banner_details_text.configure(yscrollcommand=_scr.set, state=tk.DISABLED)
        self._banner_details_text.pack(side=tk.LEFT, fill=tk.X, expand=True)
        _scr.pack(side=tk.RIGHT, fill=tk.Y)
        self._banner_details_shown = False
        self._last_error_details = None
        main = ttk.Frame(self)
        main.pack(fill=tk.BOTH, expand=True, padx=6, pady=4)
        left = ttk.Frame(main)
        left.pack(side=tk.LEFT, fill=tk.Y)
        ttk.Label(left, text='Comptes').pack(anchor='w')
        self.list_accounts = tk.Listbox(
            left, height=20, width=32, selectmode=tk.EXTENDED
        )
        self.list_accounts.pack(fill=tk.Y)
        self.list_accounts.bind('<<ListboxSelect>>', self.on_account_selected)
        # Per-account alerts option
        ttk.Checkbutton(
            left,
            text='Alertes pour ce compte',
            variable=self.alert_toggle,
            command=self._on_alert_toggle,
        ).pack(anchor='w', pady=(6, 0))
        acc_btns = ttk.Frame(left)
        acc_btns.pack(fill=tk.X, pady=2)
        ttk.Button(
            acc_btns, text='Rafraîchir', command=self.refresh_accounts
        ).pack(side=tk.LEFT)
        ttk.Checkbutton(
            acc_btns,
            text='Auto',
            variable=self.auto_refresh,
            command=self.schedule_auto_refresh,
        ).pack(side=tk.LEFT, padx=4)
        ttk.Entry(
            acc_btns, width=5, textvariable=self.auto_refresh_interval
        ).pack(side=tk.LEFT)
        ttk.Label(acc_btns, text='s').pack(side=tk.LEFT)
        right = ttk.Frame(main)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        filt = ttk.Frame(right)
        filt.pack(fill=tk.X, pady=2)
        ttk.Label(filt, text='Début (YYYY-MM-DD)').grid(
            row=0, column=0, sticky=tk.W
        )
        ttk.Entry(filt, width=12, textvariable=self.var_start).grid(
            row=0, column=1, padx=2
        )
        ttk.Label(filt, text='Fin').grid(row=0, column=2, sticky=tk.W)
        ttk.Entry(filt, width=12, textvariable=self.var_end).grid(
            row=0, column=3, padx=2
        )
        ttk.Label(filt, text='Limite').grid(row=0, column=4, sticky=tk.W)
        ttk.Entry(filt, width=6, textvariable=self.var_limit).grid(
            row=0, column=5, padx=2
        )
        ttk.Button(
            filt, text='Charger', command=self.refresh_selected_account_details
        ).grid(row=0, column=6, padx=4)
        notebook = ttk.Notebook(right)
        notebook.pack(fill=tk.BOTH, expand=True)
        # Conserver une référence pour persistance d'onglet
        self._main_notebook = notebook
        self._main_notebook.bind('<<NotebookTabChanged>>', self._on_tab_changed)
        tab_pos = ttk.Frame(notebook)
        notebook.add(tab_pos, text='Positions')

        # Barre d'outils pour l'onglet positions
        pos_toolbar = ttk.Frame(tab_pos)
        pos_toolbar.pack(fill=tk.X, padx=4, pady=2)

        ttk.Label(pos_toolbar, text="Actions:").pack(side=tk.LEFT)
        ttk.Button(
            pos_toolbar,
            text="📊 Analyser sélection",
            command=self._analyze_selected_symbol,
        ).pack(side=tk.LEFT, padx=5)
        ttk.Button(
            pos_toolbar,
            text="📈 Graphique rapide",
            command=self._quick_chart_selected,
        ).pack(side=tk.LEFT, padx=5)

        # Séparateur
        ttk.Separator(pos_toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, padx=10, fill=tk.Y)

        # Info sur le double-clic
        ttk.Label(
            pos_toolbar,
            text="💡 Double-cliquez sur un symbole pour l'analyser",
            foreground="gray",
        ).pack(side=tk.RIGHT)
        cols = (
            'symbol',
            'name',
            'qty',
            'last',
            'value',
            'cur',
            'avg',
            'pnl',
            'pnl_abs',
        )
        self.tree_positions = ttk.Treeview(
            tab_pos, columns=cols, show='headings'
        )
        headers = {
            'symbol': ('Symbole', 95, tk.W, False),
            'name': ('Nom', 200, tk.W, False),
            'qty': ('Qté', 60, tk.E, True),
            'last': ('Prix', 70, tk.E, True),
            'value': ('Valeur', 85, tk.E, True),
            'cur': ('Devise', 55, tk.W, False),
            'avg': ('PrixMoy', 70, tk.E, True),
            'pnl': ('PnL%', 60, tk.E, True),
            'pnl_abs': ('PnL$', 80, tk.E, True),
        }
        for col, (hdr, w, anc, num) in headers.items():
            self.tree_positions.heading(
                col,
                text=hdr,
                command=lambda c=col, n=num: self.sort_tree(
                    self.tree_positions, c, numeric=n
                ),
            )
            self.tree_positions.column(col, width=w, anchor=anc, stretch=True)
        self.tree_positions.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self._add_tree_context(self.tree_positions)

        # Ajout du gestionnaire de double-clic pour les symboles
        self.tree_positions.bind('<Double-1>', self._on_symbol_double_click)
        tab_act = ttk.Frame(notebook)
        notebook.add(tab_act, text='Activités')
        act_bar = ttk.Frame(tab_act)
        act_bar.pack(fill=tk.X, padx=4, pady=2)
        ttk.Label(act_bar, text='Filtre texte:').pack(side=tk.LEFT)
        ttk.Entry(act_bar, textvariable=self.var_act_filter, width=25).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(
            act_bar, text='Appliquer', command=self.apply_activity_filter
        ).pack(side=tk.LEFT)
        ttk.Button(
            act_bar,
            text='Réinit',
            command=lambda: (
                self.var_act_filter.set(''), self.apply_activity_filter()
            ),
        ).pack(side=tk.LEFT, padx=4)
        act_cols = ('date', 'desc', 'amt')
        self.tree_acts = ttk.Treeview(
            tab_act, columns=act_cols, show='headings'
        )
        headings = {
            'date': ('Date', 155, tk.W, False),
            'desc': ('Description', 480, tk.W, False),
            'amt': ('Montant', 110, tk.E, True),
        }
        for col, (hdr, w, anc, num) in headings.items():
            self.tree_acts.heading(
                col,
                text=hdr,
                command=lambda c=col, n=num: self.sort_tree(
                    self.tree_acts, c, numeric=n
                ),
            )
            self.tree_acts.column(col, width=w, anchor=anc, stretch=True)
        self.tree_acts.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self._add_tree_context(self.tree_acts)
        tab_chart = ttk.Frame(notebook)
        notebook.add(tab_chart, text='Graphique')
        chart_btns = ttk.Frame(tab_chart)
        chart_btns.pack(fill=tk.X, pady=4)
        ttk.Label(chart_btns, text='Période:').pack(side=tk.LEFT)
        cb_range = ttk.Combobox(
            chart_btns,
            width=6,
            state='readonly',
            values=['1j', '3j', '7j', '30j', '90j', '180j', '365j'],
        )
        # Restore persisted chart period
        try:
            last_days = int(app_config.get('ui.charts.period_days', 30) or 30)
        except Exception:
            last_days = 30
        cb_range.set(f"{last_days}j")
        cb_range.pack(side=tk.LEFT, padx=2)
        def _on_range_change(_=None):  # noqa
            sel = cb_range.get().rstrip('j')
            try:
                days = int(sel)
            except Exception:
                days = 30
            self.var_chart_range.set(days)
            # persist period
            try:
                app_config.set('ui.charts.period_days', int(days))
            except Exception:
                pass
        cb_range.bind('<<ComboboxSelected>>', _on_range_change)
        # Options de style du graphique
        self._chart_show_grid = tk.BooleanVar(value=bool(app_config.get('ui.charts.show_grid', True)))
        self._chart_show_sma = tk.BooleanVar(value=bool(app_config.get('ui.charts.show_sma', False)))
        self._chart_sma_win = tk.IntVar(value=int(app_config.get('ui.charts.sma_window', 7)))

        def _persist_chart_prefs():
            try:
                app_config.set('ui.charts.show_grid', bool(self._chart_show_grid.get()))
                app_config.set('ui.charts.show_sma', bool(self._chart_show_sma.get()))
                app_config.set('ui.charts.sma_window', int(self._chart_sma_win.get()))
            except Exception:
                pass
        ttk.Checkbutton(
            chart_btns,
            text='Grille',
            variable=self._chart_show_grid,
            command=lambda: (self.chart.set_options(show_grid=self._chart_show_grid.get()), _persist_chart_prefs()) if HAS_MPL else _persist_chart_prefs(),
        ).pack(side=tk.LEFT, padx=(8, 2))
        ttk.Checkbutton(
            chart_btns,
            text='SMA',
            variable=self._chart_show_sma,
            command=lambda: (self.chart.set_options(show_sma=self._chart_show_sma.get(), sma_window=self._chart_sma_win.get()), _persist_chart_prefs()) if HAS_MPL else _persist_chart_prefs(),
        ).pack(side=tk.LEFT, padx=2)
        ttk.Spinbox(
            chart_btns,
            from_=3,
            to=60,
            width=4,
            textvariable=self._chart_sma_win,
            command=lambda: (self.chart.set_options(sma_window=self._chart_sma_win.get()), _persist_chart_prefs()) if HAS_MPL else _persist_chart_prefs(),
        ).pack(side=tk.LEFT)
        ttk.Button(
            chart_btns, text='NLV 30j', command=self.chart.load_nlv_single
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(
            chart_btns, text='NLV Multi', command=self.chart.load_nlv_multi
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(
            chart_btns, text='Composition', command=self.chart.load_composition
        ).pack(side=tk.LEFT, padx=2)
        # Exports

        def _export_png():
            if not HAS_MPL:
                return
            path = filedialog.asksaveasfilename(
                title='Exporter PNG', defaultextension='.png', filetypes=[('PNG', '*.png')]
            )
            if not path:
                return
            ok = self.chart.export_png(path)
            if ok:
                # Keep confirmation popup for export success as requested
                messagebox.showinfo('Export', 'Image exportée')
            else:
                self.set_status('Échec export PNG', error=True)

        def _export_csv():
            path = filedialog.asksaveasfilename(
                title='Exporter CSV', defaultextension='.csv', filetypes=[('CSV', '*.csv')]
            )
            if not path:
                return
            ok = self.chart.export_csv(path)
            if ok:
                messagebox.showinfo('Export', 'CSV exporté')
            else:
                self.set_status('Échec export CSV', error=True)
        ttk.Button(chart_btns, text='Exporter PNG', command=_export_png).pack(side=tk.RIGHT, padx=2)
        ttk.Button(chart_btns, text='Exporter CSV', command=_export_csv).pack(side=tk.RIGHT, padx=2)
        if HAS_MPL:
            self.chart.init_widgets(tab_chart)
            # Appliquer les options de graphique persistées
            try:
                self.chart.set_options(
                    show_grid=bool(self._chart_show_grid.get()),
                    show_sma=bool(self._chart_show_sma.get()),
                    sma_window=int(self._chart_sma_win.get()),
                )
            except Exception:
                pass
        else:
            ttk.Label(tab_chart, text='Matplotlib non installé').pack(
                padx=4, pady=10
            )
        # --- Onglet Diagnostics ---
        self.diagnostics = DiagnosticsPanel(self)
        self.diagnostics.build(notebook)
        # --- Onglet Screener ---
        try:
            self.screener = ScreenerPanel(self)
            self.screener.build(notebook)
        except Exception:
            pass
        # --- Onglet Backtest ---
        try:
            self.backtest = BacktestPanel(self)
            self.backtest.build(notebook)
        except Exception:
            pass
        # --- Onglet Stratégies (Runner) ---
        self._build_strategy_tab(notebook)
        # --- Onglet Signaux IA ---
        tab_signals = ttk.Frame(notebook)
        notebook.add(tab_signals, text='Signaux')
        top_ai = ttk.Frame(tab_signals)
        top_ai.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        # Ajout colonne 'symbol' pour rendre les signaux cliquables
        self.tree_signals = ttk.Treeview(
            top_ai,
            columns=('time', 'level', 'symbol', 'code', 'message'),
            show='headings',
            height=8,
        )
        for c, (h, w, a) in {
            'time': ('Heure', 110, tk.W),
            'level': ('Niv', 55, tk.W),
            'symbol': ('Symb', 70, tk.W),
            'code': ('Code', 90, tk.W),
            'message': ('Message', 500, tk.W),
        }.items():
            self.tree_signals.heading(c, text=h)
            self.tree_signals.column(c, width=w, anchor=a, stretch=True)
        self.tree_signals.pack(fill=tk.BOTH, expand=True)
        self._add_tree_context(self.tree_signals)
        self.agent_ui = AgentUI(self.agent, self.tree_signals)
        self.tree_signals.bind('<Double-1>', self._on_signal_double_click)

        # --- Onglet Chat IA ---
        tab_chat = ttk.Frame(notebook)
        notebook.add(tab_chat, text='Chat')
        chat_bar = ttk.Frame(tab_chat)
        chat_bar.pack(fill=tk.X, padx=4, pady=4)
        ttk.Label(chat_bar, text='Chat:').pack(side=tk.LEFT)
        # Champ de saisie du chat (garder une référence pour binding clavier)
        self.ent_chat = ttk.Entry(chat_bar, textvariable=self.var_chat, width=60)
        self.ent_chat.pack(side=tk.LEFT, padx=4)
        # Envoi avec Entrée
        self.ent_chat.bind('<Return>', lambda _e: self.chat_manager._chat_send())
        self.btn_chat_send = ttk.Button(
            chat_bar,
            text='Envoyer',
            command=self.chat_manager._chat_send,
        )
        self.btn_chat_send.pack(side=tk.LEFT)
        ttk.Button(
            chat_bar,
            text='📊 Analyser symbole',
            command=self._quick_symbol_analysis,
        ).pack(side=tk.LEFT, padx=5)
        self.txt_chat = tk.Text(tab_chat, height=12, wrap='word')
        self.txt_chat.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self.txt_chat.configure(state=tk.DISABLED)
        # Statut du chat (affiche "Réponse en cours…")
        self.lbl_chat_status = ttk.Label(tab_chat, text='', foreground='gray')
        self.lbl_chat_status.pack(fill=tk.X, padx=4, pady=(0, 4))
        # --- Onglet Recherche titres ---
        tab_search = ttk.Frame(notebook)
        notebook.add(tab_search, text='Recherche')
        sr_top = ttk.Frame(tab_search)
        sr_top.pack(fill=tk.X, padx=4, pady=4)
        ttk.Label(sr_top, text='Titre / symbole:').pack(side=tk.LEFT)
        # Rechercher: restaurer la dernière requête
        self.var_search_query = tk.StringVar(value=str(app_config.get('ui.search.last_query', '')))
        ttk.Entry(
            sr_top, textvariable=self.var_search_query, width=30
        ).pack(side=tk.LEFT, padx=4)
        # Liste déroulante de suggestions (apparait dynamiquement)
        self.lst_search_suggestions = tk.Listbox(sr_top, height=4)
        self.lst_search_suggestions.bind('<<ListboxSelect>>', lambda _e: self._apply_search_suggestion())
        # Mise à jour suggestions + persistance de la requête
        def _on_search_query_change(*_):  # noqa
            try:
                app_config.set('ui.search.last_query', (self.var_search_query.get() or '').strip())
            except Exception:
                pass
            self._update_search_suggestions()
        self.var_search_query.trace_add('write', _on_search_query_change)
        ttk.Button(
            sr_top, text='Chercher', command=self.search_securities
        ).pack(side=tk.LEFT)
        self.tree_search = ttk.Treeview(
            tab_search,
            columns=(
                'symbol',
                'name',
                'exchange',
                'status',
                'buyable',
                'market',
            ),
            show='headings',
            height=12,
        )
        headers_search = {
            'symbol': ('Symbole', 90, tk.W, False),
            'name': ('Nom', 220, tk.W, False),
            'exchange': ('Échange', 80, tk.W, False),
            'status': ('Statut', 70, tk.W, False),
            'buyable': ('Achetable', 70, tk.W, False),
            'market': ('Marché', 80, tk.W, False),
        }
        for col, (hdr, w, anc, num) in headers_search.items():
            self.tree_search.heading(col, text=hdr)
            self.tree_search.column(col, width=w, anchor=anc, stretch=True)
        self.tree_search.pack(fill=tk.BOTH, expand=True, padx=4, pady=2)
        self._add_tree_context(self.tree_search)
        self.tree_search.bind(
            '<Double-1>', lambda _e: self.open_search_security_details()
        )
        sr_details = ttk.LabelFrame(tab_search, text='Détails')
        sr_details.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        logo_frame = ttk.Frame(sr_details)
        logo_frame.pack(fill=tk.X, padx=2, pady=(2, 0))
        self.lbl_search_logo = ttk.Label(logo_frame, text='[Logo]')
        self.lbl_search_logo.pack(side=tk.LEFT, padx=(2, 10))
        self.txt_search_details = tk.Text(sr_details, height=8, wrap='word')
        self.txt_search_details.pack(
            fill=tk.BOTH, expand=True, padx=2, pady=2
        )
        self.txt_search_details.configure(state=tk.DISABLED)
        self._search_results = []  # stocke dicts résultats
        # --- Nouveau tab: Mouvements (gagnants, perdants, actifs, opps) ---
        tab_mv = ttk.Frame(notebook)
        notebook.add(tab_mv, text='Mouvements')
        # Contrôles du haut (Top N)
        mv_ctrl = ttk.Frame(tab_mv)
        mv_ctrl.pack(fill=tk.X, padx=4, pady=(6, 0))
        ttk.Label(mv_ctrl, text='Top N:').pack(side=tk.LEFT)
        self.var_movers_topn = tk.IntVar(value=int(app_config.get('ui.movers.top_n', 5)))

        def _persist_movers_topn():
            try:
                n = max(1, int(self.var_movers_topn.get() or 5))
            except Exception:
                n = 5
            try:
                app_config.set('ui.movers.top_n', int(n))
            except Exception:
                pass
            # Recalcule la vue
            try:
                self.update_movers(int(n))
            except Exception:
                pass

        ttk.Spinbox(
            mv_ctrl,
            from_=1,
            to=50,
            width=4,
            textvariable=self.var_movers_topn,
            command=_persist_movers_topn,
        ).pack(side=tk.LEFT, padx=(4, 0))
        mv_top = ttk.Frame(tab_mv)
        mv_top.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        # Gagnants
        frm_g = ttk.Labelframe(mv_top, text='Gagnants')
        frm_g.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=2, pady=2)
        self.tree_gainers = ttk.Treeview(
            frm_g,
            columns=('symbol', 'pnlpct', 'pnlabs', 'value', 'qty'),
            show='headings',
            height=8,
        )
        for c, (h, w, a, num) in {
            'symbol': ('Symbole', 80, tk.W, False),
            'pnlpct': ('PnL%', 65, tk.E, True),
            'pnlabs': ('PnL$', 80, tk.E, True),
            'value': ('Valeur', 90, tk.E, True),
            'qty': ('Qté', 60, tk.E, True),
        }.items():
            self.tree_gainers.heading(
                c,
                text=h,
                command=lambda col=c, n=num: self.sort_tree(
                    self.tree_gainers, col, numeric=n
                ),
            )
            self.tree_gainers.column(c, width=w, anchor=a, stretch=True)
        self.tree_gainers.pack(fill=tk.BOTH, expand=True)
        self._add_tree_context(self.tree_gainers)
        # Perdants
        frm_l = ttk.Labelframe(mv_top, text='Perdants')
        frm_l.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=2, pady=2)
        self.tree_losers = ttk.Treeview(
            frm_l,
            columns=('symbol', 'pnlpct', 'pnlabs', 'value', 'qty'),
            show='headings',
            height=8,
        )
        for c, (h, w, a, num) in {
            'symbol': ('Symbole', 80, tk.W, False),
            'pnlpct': ('PnL%', 65, tk.E, True),
            'pnlabs': ('PnL$', 80, tk.E, True),
            'value': ('Valeur', 90, tk.E, True),
            'qty': ('Qté', 60, tk.E, True),
        }.items():
            self.tree_losers.heading(
                c,
                text=h,
                command=lambda col=c, n=num: self.sort_tree(
                    self.tree_losers, col, numeric=n
                ),
            )
            self.tree_losers.column(c, width=w, anchor=a, stretch=True)
        self.tree_losers.pack(fill=tk.BOTH, expand=True)
        self._add_tree_context(self.tree_losers)
        # Actifs (par valeur)
        mv_bottom = ttk.Frame(tab_mv)
        mv_bottom.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        frm_a = ttk.Labelframe(mv_bottom, text='Plus actifs (valeur)')
        frm_a.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=2, pady=2)
        self.tree_active = ttk.Treeview(
            frm_a,
            columns=('symbol', 'value', 'pnlpct', 'pnlabs', 'qty'),
            show='headings',
            height=8,
        )
        for c, (h, w, a, num) in {
            'symbol': ('Symbole', 80, tk.W, False),
            'value': ('Valeur', 90, tk.E, True),
            'pnlpct': ('PnL%', 65, tk.E, True),
            'pnlabs': ('PnL$', 80, tk.E, True),
            'qty': ('Qté', 60, tk.E, True),
        }.items():
            self.tree_active.heading(
                c,
                text=h,
                command=lambda col=c, n=num: self.sort_tree(
                    self.tree_active, col, numeric=n
                ),
            )
            self.tree_active.column(c, width=w, anchor=a, stretch=True)
        self.tree_active.pack(fill=tk.BOTH, expand=True)
        self._add_tree_context(self.tree_active)
        # Opportunités (heuristique: grosses baisses)
        frm_o = ttk.Labelframe(mv_bottom, text='Opportunités (baisses)')
        frm_o.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=2, pady=2)
        self.tree_opps = ttk.Treeview(
            frm_o,
            columns=('symbol', 'pnlpct', 'pnlabs', 'value', 'qty'),
            show='headings',
            height=8,
        )
        for c, (h, w, a, num) in {
            'symbol': ('Symbole', 80, tk.W, False),
            'pnlpct': ('PnL%', 65, tk.E, True),
            'pnlabs': ('PnL$', 80, tk.E, True),
            'value': ('Valeur', 90, tk.E, True),
            'qty': ('Qté', 60, tk.E, True),
        }.items():
            self.tree_opps.heading(
                c,
                text=h,
                command=lambda col=c, n=num: self.sort_tree(
                    self.tree_opps, col, numeric=n
                ),
            )
            self.tree_opps.column(c, width=w, anchor=a, stretch=True)
        self.tree_opps.pack(fill=tk.BOTH, expand=True)
        self._add_tree_context(self.tree_opps)

        # --- Nouvel onglet: Actualités ---
        tab_news = ttk.Frame(notebook)
        notebook.add(tab_news, text='Actualités')

        # Top frame pour controls
        news_top = ttk.Frame(tab_news)
        news_top.pack(fill=tk.X, padx=4, pady=4)
        ttk.Label(news_top, text='Recherche:').pack(side=tk.LEFT)
        # Persisted news query
        self.var_news_query = tk.StringVar(
            value=str(app_config.get('ui.news.last_query', 'stock market'))
        )

        def _persist_news(*_):
            try:
                app_config.set(
                    'ui.news.last_query', (self.var_news_query.get() or '').strip()
                )
            except Exception:
                pass

        self.var_news_query.trace_add('write', _persist_news)
        ttk.Entry(
            news_top, textvariable=self.var_news_query, width=25
        ).pack(side=tk.LEFT, padx=4)
        ttk.Button(news_top, text='Actualiser', command=self.refresh_news).pack(
            side=tk.LEFT
        )
        ttk.Button(
            news_top, text='Aperçu marché', command=self.refresh_market_overview
        ).pack(side=tk.LEFT, padx=4)
        if HAS_EXTERNAL_APIS:
            ttk.Button(news_top, text='📱 Notifier', command=self.send_portfolio_notification).pack(side=tk.LEFT, padx=4)

        # Treeview pour les actualités
        self.tree_news = ttk.Treeview(
            tab_news,
            columns=('source', 'title', 'publishedAt', 'sentiment'),
            show='headings',
            height=12,
        )
        for c, (h, w, a) in {
            'source': ('Source', 100, tk.W),
            'title': ('Titre', 380, tk.W),
            'publishedAt': ('Date', 100, tk.W),
            'sentiment': ('Sentiment', 90, tk.W),
        }.items():
            self.tree_news.heading(c, text=h)
            self.tree_news.column(c, width=w, anchor=a, stretch=True)
        self.tree_news.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self.tree_news.bind('<Double-1>', self.on_news_double_click)
        self._add_tree_context(self.tree_news)

        # Zone de détails pour les articles
        self.txt_news_details = tk.Text(tab_news, height=6, wrap='word')
        self.txt_news_details.pack(fill=tk.X, padx=4, pady=4)
        self.txt_news_details.configure(state=tk.DISABLED)

        self.txt_output = tk.Text(right, height=4, wrap='word')
        self.txt_output.pack(fill=tk.X, padx=2, pady=2)
        self.txt_output.configure(state=tk.DISABLED)
        self.progress = ttk.Progressbar(self, mode='indeterminate')
        self.progress.pack(fill=tk.X, side=tk.BOTTOM)
        # Onglet Telegram (contrôle)
        if HAS_EXTERNAL_APIS:
            from .telegram_ui import TelegramUI

            self._telegram_ui = TelegramUI(
                parent=notebook,
                api_manager=self.api_manager,
                agent=self.agent,
                start_cb=self._start_telegram_bridge,
                stop_cb=self._stop_telegram_bridge,
                test_cb=self._send_test_tg_message,
            )
            self._telegram_ui.render()

        # Sélectionner l'onglet précédent si disponible
        try:
            last_idx = int(app_config.get('ui.last_tab', 0) or 0)
            tabs = notebook.tabs()
            if 0 <= last_idx < len(tabs):
                notebook.select(tabs[last_idx])
        except Exception:
            pass

    def _build_strategy_tab(self, notebook: ttk.Notebook):
        tab = ttk.Frame(notebook)
        notebook.add(tab, text='Stratégies')
        top = ttk.Frame(tab)
        top.pack(fill=tk.X, padx=6, pady=6)
        # Controls
        self.var_sr_enabled = tk.BooleanVar(value=bool(app_config.get('strategy_runner.enabled', False)))
        self.var_sr_interval = tk.IntVar(value=int(app_config.get('strategy_runner.interval_sec', 300) or 300))
        self.var_sr_strategy = tk.StringVar(value=str(app_config.get('strategy_runner.strategy', 'ma_cross') or 'ma_cross'))
        self.var_sr_fast = tk.IntVar(value=int(app_config.get('strategy_runner.fast', 10) or 10))
        self.var_sr_slow = tk.IntVar(value=int(app_config.get('strategy_runner.slow', 30) or 30))
        self.var_sr_rsi_low = tk.IntVar(value=int(app_config.get('strategy_runner.rsi_low', 30) or 30))
        self.var_sr_rsi_high = tk.IntVar(value=int(app_config.get('strategy_runner.rsi_high', 70) or 70))
        # Confluence/RSI period + thresholds
        self.var_sr_rsi_period = tk.IntVar(value=int(app_config.get('strategy_runner.rsi_period', 14) or 14))
        self.var_sr_rsi_buy = tk.IntVar(value=int(app_config.get('strategy_runner.rsi_buy', 55) or 55))
        self.var_sr_rsi_sell = tk.IntVar(value=int(app_config.get('strategy_runner.rsi_sell', 45) or 45))
        # Volatility filter (Bollinger bandwidth)
        try:
            _mbw = float(app_config.get('strategy_runner.min_bandwidth', 0.0) or 0.0)
        except Exception:
            _mbw = 0.0
        self.var_sr_min_bw = tk.DoubleVar(value=_mbw)
        self.var_sr_bb_window = tk.IntVar(value=int(app_config.get('strategy_runner.bb_window', 20) or 20))

        ttk.Checkbutton(top, text='Activer', variable=self.var_sr_enabled, command=self._strategy_apply).pack(side=tk.LEFT)
        ttk.Label(top, text='Intervalle (s):').pack(side=tk.LEFT, padx=(8, 2))
        ttk.Spinbox(top, from_=15, to=3600, width=6, textvariable=self.var_sr_interval, command=self._strategy_apply).pack(side=tk.LEFT)
        ttk.Label(top, text='Stratégie:').pack(side=tk.LEFT, padx=(8, 2))
        cb = ttk.Combobox(top, state='readonly', width=16, textvariable=self.var_sr_strategy, values=['ma_cross', 'rsi_reversion', 'confluence'])
        cb.pack(side=tk.LEFT)
        cb.bind('<<ComboboxSelected>>', lambda _e: self._strategy_apply())
        # Params frame
        prm = ttk.Frame(tab)
        prm.pack(fill=tk.X, padx=6)
        # MA params
        ttk.Label(prm, text='Fast:').pack(side=tk.LEFT)
        ttk.Spinbox(prm, from_=3, to=60, width=4, textvariable=self.var_sr_fast, command=self._strategy_apply).pack(side=tk.LEFT)
        ttk.Label(prm, text='Slow:').pack(side=tk.LEFT, padx=(6, 0))
        ttk.Spinbox(prm, from_=5, to=200, width=4, textvariable=self.var_sr_slow, command=self._strategy_apply).pack(side=tk.LEFT)
        # RSI params
        ttk.Label(prm, text='RSI Low:').pack(side=tk.LEFT, padx=(12, 2))
        ttk.Spinbox(prm, from_=5, to=45, width=4, textvariable=self.var_sr_rsi_low, command=self._strategy_apply).pack(side=tk.LEFT)
        ttk.Label(prm, text='RSI High:').pack(side=tk.LEFT, padx=(6, 2))
        ttk.Spinbox(prm, from_=55, to=95, width=4, textvariable=self.var_sr_rsi_high, command=self._strategy_apply).pack(side=tk.LEFT)
        # Confluence-specific RSI/period
        ttk.Label(prm, text='RSI Period:').pack(side=tk.LEFT, padx=(12, 2))
        ttk.Spinbox(prm, from_=5, to=50, width=4, textvariable=self.var_sr_rsi_period, command=self._strategy_apply).pack(side=tk.LEFT)
        ttk.Label(prm, text='RSI Buy≥').pack(side=tk.LEFT, padx=(6, 2))
        ttk.Spinbox(prm, from_=50, to=90, width=4, textvariable=self.var_sr_rsi_buy, command=self._strategy_apply).pack(side=tk.LEFT)
        ttk.Label(prm, text='RSI Sell≤').pack(side=tk.LEFT, padx=(6, 2))
        ttk.Spinbox(prm, from_=10, to=50, width=4, textvariable=self.var_sr_rsi_sell, command=self._strategy_apply).pack(side=tk.LEFT)
        # Volatility filter
        prm2 = ttk.Frame(tab)
        prm2.pack(fill=tk.X, padx=6, pady=(4, 0))
        lbl_bw = ttk.Label(prm2, text='Min BBand BW:')
        lbl_bw.pack(side=tk.LEFT)
        sp_bw = ttk.Spinbox(prm2, from_=0.0, to=1.0, increment=0.01, width=6, textvariable=self.var_sr_min_bw, command=self._strategy_apply)
        sp_bw.pack(side=tk.LEFT)
        ttk.Label(prm2, text='BBand Window:').pack(side=tk.LEFT, padx=(6, 2))
        ttk.Spinbox(prm2, from_=10, to=60, width=5, textvariable=self.var_sr_bb_window, command=self._strategy_apply).pack(side=tk.LEFT)
        try:
            from .ui_utils import attach_tooltip
            attach_tooltip(lbl_bw, 'Filtre de volatilité (Bollinger bandwidth). 0.00 = aucun filtre; 0.05–0.10 = faible vol; 0.10–0.20 = modérée; >0.20 = forte. Recommandé: 0.05–0.15 pour éviter le bruit.')
            attach_tooltip(sp_bw, 'Valeur minimale du Bollinger bandwidth pour générer des signaux. Échelle 0–1. Ex.: 0.08 laisse passer des tendances, 0.15 filtre les ranges trop serrés.')
        except Exception:
            pass
        # Runner
        # Trade executor (paper by default)
        self._trade_exec = TradeExecutor(self.api_manager)
        try:
            self._trade_exec.configure(
                enabled=bool(self.var_at_enabled.get()),
                mode=str(self.var_at_mode.get()),
                base_size=float(self.var_at_size.get()),
                max_trades_per_day=int(self.var_at_maxtr.get()),
            )
        except Exception:
            pass
        self._strategy_runner = StrategyRunner(
            api_manager=self.api_manager,
            get_universe=self.get_strategy_universe,
            send_alert=(lambda title, msg, level='ALERT': (self.api_manager.telegram.send_alert(title, msg, level) if (self.api_manager and getattr(self.api_manager, 'telegram', None)) else False)),
            trade_executor=self._trade_exec,
        )
        # apply initial config and start thread
        self._strategy_apply()
        try:
            self._strategy_runner.start()
        except Exception:
            pass
        try:
            self.after(15000, self._portfolio_tick)
        except Exception:
            pass
        # Schedule periodic AI watchlist upkeep (every ~60 min)
        try:
            self.after(60 * 60 * 1000, self._ai_watchlist_tick)
        except Exception:
            pass

        # --- Auto-Trade Controls ---
        at_frame = ttk.LabelFrame(tab, text='Auto-Trade')
        at_frame.pack(fill=tk.X, padx=6, pady=(8, 4))
        
        # Row 1: Enable, Mode, Base Size
        at_row1 = ttk.Frame(at_frame)
        at_row1.pack(fill=tk.X, padx=4, pady=2)
        
        # Auto-trade variables
        self.var_at_enabled = tk.BooleanVar(value=bool(app_config.get('autotrade.enabled', False)))
        self.var_at_mode = tk.StringVar(value=str(app_config.get('autotrade.mode', 'paper') or 'paper'))
        self.var_at_size = tk.DoubleVar(value=float(app_config.get('autotrade.base_size', 1000.0) or 1000.0))
        self.var_at_maxtr = tk.IntVar(value=int(app_config.get('autotrade.max_trades_per_day', 10) or 10))
        
        # Guardrails variables
        self.var_at_max_notional = tk.DoubleVar(value=float(app_config.get('autotrade.max_position_notional_per_symbol', 0.0) or 0.0))
        self.var_at_max_qty = tk.DoubleVar(value=float(app_config.get('autotrade.max_position_qty_per_symbol', 0.0) or 0.0))
        
        ttk.Checkbutton(at_row1, text='Activer', variable=self.var_at_enabled, command=self._strategy_apply).pack(side=tk.LEFT)
        ttk.Label(at_row1, text='Mode:').pack(side=tk.LEFT, padx=(8, 2))
        mode_cb = ttk.Combobox(at_row1, state='readonly', width=8, textvariable=self.var_at_mode, values=['paper', 'live'])
        mode_cb.pack(side=tk.LEFT)
        mode_cb.bind('<<ComboboxSelected>>', lambda _e: self._on_at_mode_change())
        ttk.Label(at_row1, text='Taille base:').pack(side=tk.LEFT, padx=(8, 2))
        ttk.Spinbox(at_row1, from_=100, to=50000, increment=100, width=8, textvariable=self.var_at_size, command=self._strategy_apply).pack(side=tk.LEFT)
        ttk.Label(at_row1, text='Max trades/jour:').pack(side=tk.LEFT, padx=(8, 2))
        ttk.Spinbox(at_row1, from_=1, to=100, width=5, textvariable=self.var_at_maxtr, command=self._strategy_apply).pack(side=tk.LEFT)
        
        # Row 2: Guardrails
        at_row2 = ttk.Frame(at_frame)
        at_row2.pack(fill=tk.X, padx=4, pady=2)
        
        ttk.Label(at_row2, text='Max notionnel/symbole:').pack(side=tk.LEFT)
        ttk.Spinbox(at_row2, from_=0, to=100000, increment=1000, width=8, textvariable=self.var_at_max_notional, command=self._strategy_apply).pack(side=tk.LEFT)
        ttk.Label(at_row2, text='(0=illimité)').pack(side=tk.LEFT, padx=(2, 8))
        ttk.Label(at_row2, text='Max qté/symbole:').pack(side=tk.LEFT)
        ttk.Spinbox(at_row2, from_=0, to=10000, increment=10, width=8, textvariable=self.var_at_max_qty, command=self._strategy_apply).pack(side=tk.LEFT)
        ttk.Label(at_row2, text='(0=illimité)').pack(side=tk.LEFT, padx=(2, 0))

        # --- Portfolio Paper Section ---
        pf_frame = ttk.LabelFrame(tab, text='Portefeuille Paper')
        pf_frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=(4, 0))
        
        # Summary label
        self.lbl_pf = ttk.Label(pf_frame, text='Chargement...', foreground='gray')
        self.lbl_pf.pack(fill=tk.X, padx=4, pady=2)
        
        # Portfolio tree
        pf_tree_frame = ttk.Frame(pf_frame)
        pf_tree_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=2)
        
        self.tree_pf = ttk.Treeview(
            pf_tree_frame,
            columns=('symbol', 'qty', 'avg_price', 'last', 'pnl', 'value'),
            show='headings',
            height=4,
        )
        for col, (header, width, anchor) in {
            'symbol': ('Symbole', 80, tk.W),
            'qty': ('Qté', 80, tk.E),
            'avg_price': ('Prix moy.', 80, tk.E),
            'last': ('Dernier', 80, tk.E),
            'pnl': ('PnL%', 60, tk.E),
            'value': ('Valeur', 80, tk.E),
        }.items():
            self.tree_pf.heading(col, text=header)
            self.tree_pf.column(col, width=width, anchor=anchor, stretch=True)
        
        pf_scroll = ttk.Scrollbar(pf_tree_frame, orient='vertical', command=self.tree_pf.yview)
        self.tree_pf.configure(yscrollcommand=pf_scroll.set)
        self.tree_pf.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        pf_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # Ledger table
        ledger_frame = ttk.LabelFrame(tab, text='Journal des Trades (Idempotence)')
        ledger_frame.pack(fill=tk.X, padx=6, pady=(4, 0))
        
        ledger_info = ttk.Label(ledger_frame, text='Dernières entrées du journal (évite les doublons de signaux)', foreground='gray', font=('TkDefaultFont', 8))
        ledger_info.pack(fill=tk.X, padx=4, pady=2)
        
        self.tree_ledger = ttk.Treeview(
            ledger_frame,
            columns=('timestamp', 'symbol', 'kind', 'index'),
            show='headings',
            height=3,
        )
        for col, (header, width, anchor) in {
            'timestamp': ('Timestamp', 140, tk.W),
            'symbol': ('Symbole', 80, tk.W),
            'kind': ('Type', 60, tk.W),
            'index': ('Index', 80, tk.W),
        }.items():
            self.tree_ledger.heading(col, text=header)
            self.tree_ledger.column(col, width=width, anchor=anchor, stretch=True)
        self.tree_ledger.pack(fill=tk.X, padx=4, pady=2)

        # --- Advisor (Enhanced AI) ---
        try:
            import os as _os
            # Setting overrides env when true; keep env as fallback
            _adv_enabled = bool(app_config.get('ai.enhanced', False)) or (_os.getenv('AI_ENHANCED', '0') == '1')
        except Exception:
            _adv_enabled = False
        adv_frame = ttk.LabelFrame(tab, text='Conseiller (AI)')
        adv_frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=(6, 8))
        # Advisor status row (small badge + info)
        self._adv_enabled = bool(_adv_enabled)
        status_row = ttk.Frame(adv_frame)
        status_row.pack(fill=tk.X, padx=4, pady=(2, 4))
        self.lbl_adv_status = ttk.Label(status_row)
        # Compose status text with a colored dot
        try:
            if self._adv_enabled:
                self.lbl_adv_status.configure(text='● Conseiller actif', foreground='green')
            else:
                self.lbl_adv_status.configure(text='● Conseiller désactivé', foreground='red')
        except Exception:
            self.lbl_adv_status.configure(text=('Conseiller actif' if self._adv_enabled else 'Conseiller désactivé'))
        self.lbl_adv_status.pack(side=tk.LEFT)
        self.lbl_adv_info = ttk.Label(status_row, text=(
            'Analyse et suggestion basées sur le portefeuille.' if self._adv_enabled else
            'Activez le Conseiller dans Préférences > Intelligence Artificielle, ou définissez AI_ENHANCED=1 avant le lancement.'
        ), foreground='gray')
        self.lbl_adv_info.pack(side=tk.LEFT, padx=(10, 0))
        btn_bar = ttk.Frame(adv_frame)
        btn_bar.pack(fill=tk.X, padx=4, pady=(0, 4))

        def _run_advisor():
            try:
                out = ''
                if not self.agent or not hasattr(self.agent, 'insights'):
                    out = 'Agent indisponible.'
                else:
                    out = self.agent.insights() or ''
                self.txt_advisor.configure(state=tk.NORMAL)
                self.txt_advisor.delete('1.0', tk.END)
                self.txt_advisor.insert('1.0', out.strip())
                self.txt_advisor.configure(state=tk.DISABLED)
            except Exception as e:
                try:
                    self.set_status(f"Conseiller: {e}", error=True)
                except Exception:
                    pass
            self.btn_advisor_analyze = ttk.Button(btn_bar, text='Analyser maintenant', command=_run_advisor, state=(tk.NORMAL if _adv_enabled else tk.DISABLED))
            self.btn_advisor_analyze.pack(side=tk.LEFT)
            ttk.Button(btn_bar, text='Copier', command=lambda: (self.clipboard_clear(), self.clipboard_append(self.txt_advisor.get('1.0', 'end').strip()))).pack(side=tk.LEFT, padx=(6, 0))
        self.txt_advisor = tk.Text(adv_frame, height=6, wrap='word')
        self.txt_advisor.configure(state=tk.DISABLED)
        _scr_adv = ttk.Scrollbar(adv_frame, orient='vertical', command=self.txt_advisor.yview)
        self.txt_advisor.configure(yscrollcommand=_scr_adv.set)
        self.txt_advisor.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(4, 0), pady=(0, 4))
        _scr_adv.pack(side=tk.RIGHT, fill=tk.Y, pady=(0, 4))

    def _strategy_apply(self):
        # persist
        try:
            app_config.set('strategy_runner.enabled', bool(self.var_sr_enabled.get()))
            app_config.set('strategy_runner.interval_sec', int(self.var_sr_interval.get()))
            app_config.set('strategy_runner.strategy', str(self.var_sr_strategy.get()))
            app_config.set('strategy_runner.fast', int(self.var_sr_fast.get()))
            app_config.set('strategy_runner.slow', int(self.var_sr_slow.get()))
            app_config.set('strategy_runner.rsi_low', int(self.var_sr_rsi_low.get()))
            app_config.set('strategy_runner.rsi_high', int(self.var_sr_rsi_high.get()))
            app_config.set('strategy_runner.rsi_period', int(self.var_sr_rsi_period.get()))
            app_config.set('strategy_runner.rsi_buy', int(self.var_sr_rsi_buy.get()))
            app_config.set('strategy_runner.rsi_sell', int(self.var_sr_rsi_sell.get()))
            app_config.set('strategy_runner.min_bandwidth', float(self.var_sr_min_bw.get()))
            app_config.set('strategy_runner.bb_window', int(self.var_sr_bb_window.get()))
            # autotrade
            app_config.set('autotrade.enabled', bool(self.var_at_enabled.get()))
            app_config.set('autotrade.mode', str(self.var_at_mode.get()))
            app_config.set('autotrade.base_size', float(self.var_at_size.get()))
            app_config.set('autotrade.max_trades_per_day', int(self.var_at_maxtr.get()))
            app_config.set('autotrade.max_position_notional_per_symbol', float(self.var_at_max_notional.get()))
            app_config.set('autotrade.max_position_qty_per_symbol', float(self.var_at_max_qty.get()))
        except Exception:
            pass
        # update runner
        if hasattr(self, '_strategy_runner') and self._strategy_runner:
            params = {
                'fast': int(self.var_sr_fast.get()),
                'slow': int(self.var_sr_slow.get()),
                'rsi_low': int(self.var_sr_rsi_low.get()),
                'rsi_high': int(self.var_sr_rsi_high.get()),
                'rsi_period': int(self.var_sr_rsi_period.get()),
                'period': int(self.var_sr_rsi_period.get()),
                'rsi_buy': int(self.var_sr_rsi_buy.get()),
                'rsi_sell': int(self.var_sr_rsi_sell.get()),
                'min_bandwidth': float(self.var_sr_min_bw.get()),
                'bb_window': int(self.var_sr_bb_window.get()),
            }
            try:
                self._strategy_runner.set_config(
                    enabled=bool(self.var_sr_enabled.get()),
                    interval_sec=int(self.var_sr_interval.get()),
                    strategy=str(self.var_sr_strategy.get()),
                    params=params,
                )
                # update trade executor
                if hasattr(self, '_trade_exec') and self._trade_exec:
                    self._trade_exec.configure(
                        enabled=bool(self.var_at_enabled.get()),
                        mode=str(self.var_at_mode.get()),
                        base_size=float(self.var_at_size.get()),
                        max_trades_per_day=int(self.var_at_maxtr.get()),
                        max_position_notional_per_symbol=float(self.var_at_max_notional.get()) if self.var_at_max_notional.get() > 0 else None,
                        max_position_qty_per_symbol=float(self.var_at_max_qty.get()) if self.var_at_max_qty.get() > 0 else None,
                    )
            except Exception:
                pass

    def _strategy_run_once(self):
        if not hasattr(self, '_strategy_runner') or not self._strategy_runner:
            return

        def worker():
            try:
                rep = self._strategy_runner.run_once()
                self.after(0, lambda: self._strategy_set_text(rep))
            except Exception as e:
                self.after(0, lambda e=e: self.set_status(f"Stratégies: {e}", error=True))
        threading.Thread(target=worker, daemon=True).start()

    def _strategy_set_text(self, text: str):
        try:
            self.txt_strategy.configure(state=tk.NORMAL)
            self.txt_strategy.delete('1.0', tk.END)
            self.txt_strategy.insert('end', (text or '').strip() + '\n')
            self.txt_strategy.configure(state=tk.DISABLED)
            # Refresh portfolio view after report updates
            if hasattr(self, '_update_portfolio_view'):
                self._update_portfolio_view()
        except Exception:
            pass

    def _apply_ai_prefs(self):
        """Persist Enhanced AI toggle and reflect in UI (Advisor enablement)."""
        try:
            from .config import app_config
            val = bool(getattr(self, 'var_ai_enhanced', None).get()) if hasattr(self, 'var_ai_enhanced') else False
            app_config.set('ai.enhanced', val)
            # Refresh Advisor badge and controls live
            self._adv_enabled = bool(val or (os.getenv('AI_ENHANCED', '0') == '1'))
            try:
                if hasattr(self, 'lbl_adv_status') and self.lbl_adv_status:
                    if self._adv_enabled:
                        self.lbl_adv_status.configure(text='● Conseiller actif', foreground='green')
                    else:
                        self.lbl_adv_status.configure(text='● Conseiller désactivé', foreground='red')
                if hasattr(self, 'lbl_adv_info') and self.lbl_adv_info:
                    self.lbl_adv_info.configure(text=(
                        'Analyse et suggestion basées sur le portefeuille.' if self._adv_enabled else
                        'Activez le Conseiller dans Préférences > Intelligence Artificielle, ou définissez AI_ENHANCED=1 avant le lancement.'
                    ))
                if hasattr(self, 'btn_advisor_analyze') and self.btn_advisor_analyze:
                    self.btn_advisor_analyze.configure(state=(tk.NORMAL if self._adv_enabled else tk.DISABLED))
            except Exception:
                pass
            self.set_status('Préférences IA appliquées')
        except Exception as e:
            try:
                self.set_status(f"IA: {e}", error=True)
            except Exception:
                pass

    # -------- Watchlist helpers --------
    def _on_at_mode_change(self):
        try:
            mode = str(self.var_at_mode.get())
            if mode == 'live' and not self._live_confirmed:
                ok = messagebox.askyesno(
                    'Confirmer le mode LIVE',
                    "Le mode LIVE n'exécute pas d'ordres réels pour l'instant (stub), mais doit être utilisé avec prudence. Voulez-vous vraiment passer en mode LIVE?",
                )
                if not ok:
                    self.var_at_mode.set('paper')
                else:
                    self._live_confirmed = True
            # apply config after change
            self._strategy_apply()
        except Exception:
            pass

    def _update_portfolio_view(self):
        try:
            if not hasattr(self, '_trade_exec') or not self._trade_exec:
                return
            snap = self._trade_exec.portfolio_snapshot(include_quotes=True)
            if snap.get('mode') != 'paper':
                self.lbl_pf.config(text="Mode LIVE (pas de portefeuille paper)")
                for i in self.tree_pf.get_children():
                    self.tree_pf.delete(i)
                return
            
            cash = snap.get('cash') or 0.0
            total_value = cash
            total_pnl = 0.0
            
            # Clear existing rows
            for iid in self.tree_pf.get_children():
                self.tree_pf.delete(iid)
            
            # Process positions with quotes
            for pos in snap.get('positions', []):
                symbol = pos['symbol']
                qty = pos['qty']
                avg_price = pos['avg_price']
                
                # Get current quote
                quote = snap.get('quotes', {}).get(symbol, {})
                last_price = quote.get('last', 0.0)
                
                # Calculate values
                cost_basis = qty * avg_price
                market_value = qty * last_price if last_price > 0 else cost_basis
                pnl_dollars = market_value - cost_basis
                pnl_percent = (pnl_dollars / cost_basis * 100) if cost_basis != 0 else 0.0
                
                total_value += market_value
                total_pnl += pnl_dollars
                
                # Format values for display
                last_str = f"{last_price:.2f}" if last_price > 0 else "N/A"
                pnl_str = f"{pnl_percent:+.1f}%" if last_price > 0 else "N/A"
                value_str = f"{market_value:.2f}"
                
                # Color-code PnL
                tags = []
                if last_price > 0:
                    if pnl_percent > 0:
                        tags = ['positive_pnl']
                    elif pnl_percent < 0:
                        tags = ['negative_pnl']
                
                self.tree_pf.insert('', 'end', values=(
                    symbol, 
                    f"{qty:.4f}", 
                    f"{avg_price:.2f}",
                    last_str,
                    pnl_str,
                    value_str
                ), tags=tags)
            
            # Configure PnL colors
            try:
                self.tree_pf.tag_configure('positive_pnl', foreground='#22c55e')  # green
                self.tree_pf.tag_configure('negative_pnl', foreground='#ef4444')  # red
            except Exception:
                pass
            
            # Update summary label
            equity = snap.get('equity') or total_value
            total_pnl_pct = (total_pnl / (total_value - total_pnl) * 100) if (total_value - total_pnl) != 0 else 0.0
            pnl_color = "#22c55e" if total_pnl >= 0 else "#ef4444"
            
            summary_text = f"Cash: {cash:.2f}  |  Valeur totale: {total_value:.2f}  |  PnL: {total_pnl:+.2f} ({total_pnl_pct:+.1f}%)  |  Positions: {len(snap.get('positions', []))}"
            self.lbl_pf.config(text=summary_text, foreground=pnl_color)
            
        except Exception:
            # Fallback to basic view on error
            try:
                snap = self._trade_exec.portfolio_snapshot(include_quotes=False)
                cash = snap.get('cash') or 0.0
                equity = snap.get('equity') or cash
                self.lbl_pf.config(text=f"Cash: {cash:.2f}  |  Équité: {equity:.2f}  |  Positions: {len(snap.get('positions', []))} (quotes unavailable)", foreground='gray')
            except Exception:
                pass

    def _portfolio_tick(self):
        try:
            self._update_portfolio_view()
            self._update_ledger_view()
            self.after(15000, self._portfolio_tick)
        except Exception:
            pass

    def _update_ledger_view(self):
        """Update the ledger display with recent idempotency entries."""
        try:
            if not hasattr(self, '_trade_exec') or not self._trade_exec:
                return
            
            # Clear existing rows
            for iid in self.tree_ledger.get_children():
                self.tree_ledger.delete(iid)
            
            # Get ledger from config (persisted entries)
            ledger_data = app_config.get('autotrade.ledger', []) or []
            
            # Show most recent entries (last 10)
            recent_entries = ledger_data[-10:] if len(ledger_data) > 10 else ledger_data
            
            for entry in reversed(recent_entries):  # Show most recent first
                timestamp = entry.get('timestamp', 'N/A')
                symbol = entry.get('symbol', 'N/A')
                kind = entry.get('kind', 'N/A')
                index = entry.get('index', 'N/A')
                
                # Format timestamp for display
                if timestamp != 'N/A':
                    try:
                        from datetime import datetime
                        if isinstance(timestamp, (int, float)):
                            dt = datetime.fromtimestamp(timestamp)
                            timestamp_str = dt.strftime('%H:%M:%S')
                        else:
                            timestamp_str = str(timestamp)
                    except Exception:
                        timestamp_str = str(timestamp)
                else:
                    timestamp_str = 'N/A'
                
                self.tree_ledger.insert('', 'end', values=(
                    timestamp_str,
                    symbol,
                    kind,
                    str(index)
                ))
                
        except Exception:
            pass

    def get_strategy_universe(self) -> list[str]:
        # merge positions + watchlist unique
        syms = []
        try:
            syms = [p.get('symbol') for p in (self._positions_cache or []) if p.get('symbol')]
        except Exception:
            syms = []
        try:
            wl = list(self._watchlist_read())
        except Exception:
            wl = []
        merged = []
        seen = set()
        for s in (syms + wl):
            s2 = (s or '').strip().upper()
            if s2 and s2 not in seen:
                seen.add(s2)
                merged.append(s2)
        return merged

    def _watchlist_read(self) -> list[str]:
        try:
            lst = app_config.get('strategy_runner.watchlist', []) or []
            if isinstance(lst, list):
                return [str(x).strip().upper() for x in lst if x]
        except Exception:
            pass
        return []

    def _watchlist_save(self, items: list[str]):
        try:
            app_config.set('strategy_runner.watchlist', [str(x).strip().upper() for x in (items or []) if x])
        except Exception:
            pass

    def _watchlist_load_from_config(self):
        try:
            self.list_watchlist.delete(0, tk.END)
            for s in self._watchlist_read():
                self.list_watchlist.insert(tk.END, s)
        except Exception:
            pass

    def _watchlist_add(self):
        try:
            s = (self.var_wl_add.get() or '').strip().upper()
            if not s:
                return
            current = self._watchlist_read()
            if s not in current:
                current.append(s)
                self._watchlist_save(current)
                self._watchlist_load_from_config()
            self.var_wl_add.set('')
        except Exception:
            pass

    def _watchlist_remove(self):
        try:
            sel = list(self.list_watchlist.curselection())
            if not sel:
                return
            items = [self.list_watchlist.get(i) for i in range(self.list_watchlist.size())]
            rem = set(self.list_watchlist.get(i) for i in sel)
            left = [x for x in items if x not in rem]
            self._watchlist_save(left)
            self._watchlist_load_from_config()
        except Exception:
            pass

    def _ai_watchlist_tick(self):
        try:
            if bool(self.var_sr_wl_auto.get()):
                self._ai_refresh_watchlist()
        except Exception:
            pass
        # reschedule
        try:
            self.after(60 * 60 * 1000, self._ai_watchlist_tick)
        except Exception:
            pass

    def _ai_refresh_watchlist(self):
        # Build watchlist using Screener + current strategy params (confluence by default)
        if not getattr(self, 'api_manager', None):
            return

        def worker():
            picks: list[str] = []
            try:
                # Take US day gainers top 40 then score via strategy
                scr = self.api_manager.yahoo.get_predefined_screener('day_gainers', count=40, region='US') or []
                # Prepare params from current UI
                fast = int(self.var_sr_fast.get()) if hasattr(self, 'var_sr_fast') else 10
                slow = int(self.var_sr_slow.get()) if hasattr(self, 'var_sr_slow') else 30
                rp = int(self.var_sr_rsi_period.get()) if hasattr(self, 'var_sr_rsi_period') else 14
                rb = int(self.var_sr_rsi_buy.get()) if hasattr(self, 'var_sr_rsi_buy') else 55
                rs = int(self.var_sr_rsi_sell.get()) if hasattr(self, 'var_sr_rsi_sell') else 45
                mbw = float(self.var_sr_min_bw.get()) if hasattr(self, 'var_sr_min_bw') else 0.0
                bbw = int(self.var_sr_bb_window.get()) if hasattr(self, 'var_sr_bb_window') else 20
                # Lazy import to avoid hard dep if analytics not present
                try:
                    from analytics.strategies import ConfluenceStrategy
                    HAS = True
                except Exception:
                    HAS = False
                scored: list[tuple[str, float]] = []
                for q in scr:
                    sym = q.get('symbol')
                    if not sym:
                        continue
                    try:
                        ts = self.api_manager.get_time_series(sym, interval='1day', outputsize='compact') or {}
                        closes = StrategyRunner._extract_closes(ts)  # reuse static method
                        if len(closes) < max(30, slow + 2):
                            continue
                        if HAS:
                            s = ConfluenceStrategy(fast, slow, rp, rb, rs, mbw, bbw)
                            sigs = s.generate(closes)
                            if not sigs:
                                continue
                            last_idx = len(closes) - 1
                            fresh = [sg for sg in sigs if sg.index == last_idx]
                            # prefer fresh signals; otherwise score by confidence of last
                            target = fresh[-1] if fresh else sigs[-1]
                            conf = float(target.confidence or 0.0)
                            # Favor buy signals slightly
                            if target.kind == 'buy':
                                conf += 0.05
                            scored.append((sym, conf))
                    except Exception:
                        continue
                # sort and take top 20 unique
                picks = [s for s, _ in sorted(scored, key=lambda t: t[1], reverse=True)[:20]]
            except Exception:
                picks = []
            # merge with manual watchlist (keep manual entries)
            try:
                manual = [x for x in self._watchlist_read() if x]
                merged = manual + [p for p in picks if p not in manual]
                self._watchlist_save(merged)
                self.after(0, self._watchlist_load_from_config)
                self.after(0, lambda: self.set_status(f"Watchlist AI: {len(merged)} symboles"))
            except Exception:
                pass
        threading.Thread(target=worker, daemon=True).start()

    def _strategy_copy_report(self):
        try:
            rep = ''
            if hasattr(self, '_strategy_runner') and self._strategy_runner:
                rep = self._strategy_runner.last_report() or ''
            self.clipboard_clear()
            self.clipboard_append(rep)
        except Exception:
            pass

    def apply_theme(self, name: str):
        applied = apply_palette(self, name)
        pal = self._palettes[applied]
        try:
            self.txt_output.configure(
                bg=pal['panel'],
                fg=pal['text'],
                insertbackground=pal['text'],
                highlightbackground=pal['border'],
            )
            self.list_accounts.configure(
                bg=pal['panel'],
                fg=pal['text'],
                selectbackground=pal['sel'],
                selectforeground=pal['sel_text'],
                highlightbackground=pal['border'],
            )
        except Exception:
            pass
        for tree in [
            getattr(self, 'tree_positions', None),
            getattr(self, 'tree_acts', None),
            getattr(self, 'tree_gainers', None),
            getattr(self, 'tree_losers', None),
            getattr(self, 'tree_active', None),
            getattr(self, 'tree_opps', None),
        ]:
            if tree:
                tree.tag_configure('odd', background=pal['panel'])
                tree.tag_configure('even', background=pal['surface'])
        self._theme = applied
        # Persister le thème choisi
        try:
            app_config.set('theme', applied)
        except Exception:
            pass

    def toggle_theme(self):
        self.apply_theme('dark' if self._theme == 'light' else 'light')

    def _try_auto_login(self):
        sess = load_session()
        if not sess:
            return
        self.set_status('Restauration de la session...')

        def worker():
            try:
                self.api = WealthsimpleAPI.from_token(
                    sess,
                    persist_session_fct=save_session,
                )
                self.set_status('Session restaurée')
                self.refresh_accounts()
            except ManualLoginRequired:
                self.set_status('Session expirée. Veuillez vous connecter.')

        threading.Thread(target=worker, daemon=True).start()

    # --- Telegram chat bridge ---
    def _start_telegram_bridge(self):
        if not (self.api_manager and getattr(self.api_manager, 'telegram', None)):
            return
        tg = self.api_manager.telegram
        if not tg.base_url:
            return

        # Override allowed chat id from UI if provided
        allowed_id = None
        try:
            allowed_id = (self.var_tg_chat.get() or '').strip() if hasattr(self, 'var_tg_chat') else None
        except Exception:
            allowed_id = None
        # Sauvegarder le chat id sur démarrage
        try:
            if allowed_id:
                app_config.set('integrations.telegram.chat_id', allowed_id)
        except Exception:
            pass
        if not allowed_id:
            allowed_id = tg.chat_id  # limit to configured chat if provided

        try:
            # Use command-aware handler; forwards non-commands to agent.chat too
            tg.start_command_handler(self.agent, allowed_chat_id=allowed_id)
            try:
                # update UI widget
                self._telegram_ui.set_connected(True)
            except Exception:
                pass
            self.set_status('Passerelle Telegram démarrée')
        except Exception as e:
            try:
                self._telegram_ui.set_connected(False)
            except Exception:
                pass
            self.set_status(f'Telegram: {e}', error=True, details=repr(e))

    def _stop_telegram_bridge(self):
        if self.api_manager and getattr(self.api_manager, 'telegram', None):
            try:
                self.api_manager.telegram.stop_polling()
                self.set_status('Passerelle Telegram arrêtée')
                try:
                    self._telegram_ui.set_connected(False)
                except Exception:
                    pass
            except Exception:
                pass

    def _send_test_tg_message(self):
        if not (self.api_manager and getattr(self.api_manager, 'telegram', None)):
            self.set_status('Telegram non disponible', error=True)
            return
        tg = self.api_manager.telegram
        chat_id = None
        try:
            chat_id = (self.var_tg_chat.get() or '').strip() if hasattr(self, 'var_tg_chat') else None
        except Exception:
            chat_id = None
        text = '🔔 Test de notification depuis WSApp'
        ok = False
        try:
            if chat_id:
                ok = tg.send_message_to(chat_id, text)
            else:
                ok = tg.send_message(text)
        except Exception:
            ok = False
        self.set_status('Message test envoyé' if ok else 'Échec envoi message test', error=not ok)

    def login_clicked(self):
        email = self.var_email.get().strip()
        pwd = self.var_pwd.get().strip()
        otp = self.var_otp.get().strip() or None
        if not email or not pwd:
            self.set_status('Email et mot de passe requis.', error=True)
            return
        self.set_status('Connexion en cours...')
        self.btn_login.configure(state=tk.DISABLED)

        def worker():
            try:
                # Static login returns a WSAPISession, not the API object.
                sess = WealthsimpleAPI.login(
                    email,
                    pwd,
                    otp_answer=otp,
                    persist_session_fct=save_session,
                )
                # Instantiate API bound to that session.
                self.api = WealthsimpleAPI(sess)
                self.set_status('Connecté')
                self.refresh_accounts()
            except OTPRequiredException:
                self.set_status('OTP requis - entrez le code et recliquez')
            except LoginFailedException as e:
                self.set_status(f"Login échoué: {e}", error=True, details=repr(e))
            except Exception as e:  # noqa
                self.set_status(f"Erreur: {e}", error=True, details=repr(e))
            finally:
                self.btn_login.configure(state=tk.NORMAL)

        threading.Thread(target=worker, daemon=True).start()

    def refresh_accounts(self):
        if not self.api:
            return
        self.set_status('Chargement des comptes...')
        self._busy(True)

        def worker():
            try:
                accounts = self.api.get_accounts()
                self.accounts = accounts

                def upd():
                    self.list_accounts.delete(0, tk.END)
                    for acc in accounts:
                        # Show bell icon depending on alerts setting
                        enabled = app_config.get(f"alerts.{acc['id']}", True)
                        icon = '🔔' if enabled else '🔕'
                        self.list_accounts.insert(
                            tk.END,
                            f"{icon} {acc['number']} | {acc['description']} ("
                            f"{acc['currency']})",
                        )
                    self.set_status(f"{len(accounts)} comptes chargés")
                    # Rétablir la sélection du compte précédent si possible
                    try:
                        last_id = app_config.get('ui.last_account_id')
                        if last_id:
                            for idx, acc in enumerate(accounts):
                                if acc.get('id') == last_id:
                                    self.list_accounts.selection_clear(0, tk.END)
                                    self.list_accounts.selection_set(idx)
                                    self.list_accounts.activate(idx)
                                    self.list_accounts.see(idx)
                                    # Déclencher la sélection
                                    self.on_account_selected()
                                    break
                    except Exception:
                        pass

                self.after(0, upd)
            except WSApiException as exc:
                self.after(0, lambda exc=exc: self.set_status(f"Erreur API: {exc}", error=True, details=repr(exc)))
            finally:
                self.after(0, lambda: self._busy(False))

        threading.Thread(target=worker, daemon=True).start()

    def on_account_selected(self, _=None):
        if not self.api:
            return
        sel = self.list_accounts.curselection()
        if not sel:
            return
        account = self.accounts[sel[0]]
        self.current_account_id = account['id']
        # Persister le dernier compte sélectionné
        try:
            app_config.set('ui.last_account_id', self.current_account_id)
        except Exception:
            pass
        # Sync alerts toggle from config
        self.alert_toggle.set(bool(app_config.get(f"alerts.{self.current_account_id}", True)))
        self.set_status('Récupération détails...')
        self.log(
            f"Compte: {account['description']} ({account['number']})",
            clear=True,
        )
        self.refresh_selected_account_details()
        # Draw chart automatically when account changes
        if HAS_MPL and hasattr(self, 'chart'):
            try:
                self.chart.load_nlv_single()
            except Exception:
                pass

    def _on_alert_toggle(self):
        """Persist alerts setting for the selected account and refresh list icons."""
        if not self.current_account_id:
            return
        enabled = bool(self.alert_toggle.get())
        app_config.set(f"alerts.{self.current_account_id}", enabled)
        # Refresh list to update bell icons
        if hasattr(self, 'accounts') and self.accounts:
            self.list_accounts.delete(0, tk.END)
            for acc in self.accounts:
                en = app_config.get(f"alerts.{acc['id']}", True)
                icon = '🔔' if en else '🔕'
                self.list_accounts.insert(
                    tk.END,
                    f"{icon} {acc['number']} | {acc['description']} ("
                    f"{acc['currency']})",
                )

    def parse_date(self, s: str):
        if not s:
            return None
        try:
            return datetime.strptime(s, '%Y-%m-%d')
        except ValueError:
            self.set_status(f"Date invalide: {s}", error=True)
            return None

    def _refresh_insights_badge(self):
        """Refresh the small insights label in the header.
        Non-blocking; uses agent._insights() if positions exist.
        """
        try:
            txt = ''
            if hasattr(self, 'agent') and self.agent and self.agent.last_positions:
                try:
                    # Prefer public wrapper to allow enhanced AI output when enabled
                    if hasattr(self.agent, 'insights'):
                        txt = self.agent.insights()
                    else:
                        txt = self.agent._insights()  # fallback
                except Exception:
                    txt = ''
            self._insights_full = txt or ''
            s = self._insights_full
            max_len = 90
            if len(s) > max_len:
                s = s[: max_len - 1].rstrip() + '…'
            self.var_insights.set(s)
        except Exception:
            pass
        try:
            self.after(15000, self._refresh_insights_badge)
        except Exception:
            pass

    def _show_insights_details(self):
        """Show full insights text in a small popup."""
        txt = (getattr(self, '_insights_full', '') or '').strip()
        if not txt:
            return
        try:
            win = tk.Toplevel(self)
            win.title('Insights')
            win.transient(self)
            win.resizable(True, True)
            frm = ttk.Frame(win, padding=10)
            frm.pack(fill='both', expand=True)
            body = tk.Text(frm, wrap='word', height=10, width=80)
            body.insert('1.0', txt)
            body.configure(state='disabled')
            body.pack(fill='both', expand=True)
            btns = ttk.Frame(frm)
            btns.pack(fill='x', pady=(8, 0))

            def _copy():
                try:
                    self.clipboard_clear()
                    self.clipboard_append(txt)
                except Exception:
                    pass
            ttk.Button(btns, text='Copier', command=_copy).pack(side='left')
            ttk.Button(btns, text='Fermer', command=win.destroy).pack(side='right')
        except Exception:
            pass

    def refresh_selected_account_details(self):
        if not (self.api and self.current_account_id):
            return
        start = self.parse_date(self.var_start.get())
        end = self.parse_date(self.var_end.get())
        limit = self.var_limit.get() or 10
        self._busy(True)

        def worker():
            try:
                positions = self.api.get_account_positions(
                    self.current_account_id
                )
                acts = self.api.get_activities(
                    self.current_account_id,
                    how_many=limit,
                    start_date=start,
                    end_date=end,
                )
                self.after(0, lambda: self.update_details(positions, acts))
            except Exception as e:  # noqa
                self.after(0, lambda e=e: self.set_status(f"Erreur: {e}", error=True, details=repr(e)))
            finally:
                self.after(0, lambda: self._busy(False))

        threading.Thread(target=worker, daemon=True).start()

    def update_details(self, positions: List[dict], acts: List[dict]):
        for row in self.tree_positions.get_children():
            self.tree_positions.delete(row)
        self._positions_cache = positions
        total_value = 0.0
        cur_totals: Dict[str, float] = {}
        total_pnl_abs = 0.0
        pnl_abs_by_cur: Dict[str, float] = {}
        for pos in positions:
            val = pos.get('value') or 0.0
            cur = pos.get('currency') or ''
            if val:
                total_value += val
                if cur:
                    cur_totals[cur] = cur_totals.get(cur, 0.0) + val
            pnl_pct = pos.get('pnlPct')
            pnl_abs = pos.get('pnlAbs')
            if isinstance(pnl_abs, (int, float)) and cur:
                total_pnl_abs += pnl_abs
                pnl_abs_by_cur[cur] = pnl_abs_by_cur.get(cur, 0.0) + pnl_abs
            arrow_pct = ''
            if isinstance(pnl_pct, (int, float)):
                arrow_pct = (
                    ('↑' if pnl_pct >= 0 else '↓') + f"{abs(pnl_pct):.2f}%"
                )
                if pos.get('pnlIsDaily'):
                    arrow_pct += '*'
            avg = pos.get('avgPrice')
            idx = len(self.tree_positions.get_children())
            base_tag = 'even' if idx % 2 == 0 else 'odd'
            pnl_tag = None
            if isinstance(pnl_pct, (int, float)):
                pnl_tag = 'pnl_pos' if pnl_pct >= 0 else 'pnl_neg'
            tags = (base_tag,) + ((pnl_tag,) if pnl_tag else tuple())
            self.tree_positions.insert(
                '',
                tk.END,
                values=(
                    pos.get('symbol'),
                    pos.get('name'),
                    pos.get('quantity'),
                    (
                        pos.get('lastPrice')
                        if pos.get('lastPrice') is not None
                        else ''
                    ),
                    f"{val:.2f}" if val else '',
                    cur,
                    f"{avg:.2f}" if isinstance(avg, (int, float)) else '',
                    arrow_pct,
                    (
                        f"{pnl_abs:,.2f}"
                        if isinstance(pnl_abs, (int, float))
                        else ''
                    ),
                ),
                tags=tags,
            )
        pal = self._palettes[self._theme]
        try:
            self.tree_positions.tag_configure(
                'pnl_pos', foreground=pal.get('pnl_pos', pal['success'])
            )
            self.tree_positions.tag_configure(
                'pnl_neg', foreground=pal.get('pnl_neg', pal['danger'])
            )
        except Exception:  # noqa
            pass
        try:
            # Gate AI notifications by per-account alerts toggle
            if self.agent and hasattr(self.agent, 'api_manager') and self.agent.api_manager:
                if self.current_account_id is not None:
                    enabled = app_config.get(f"alerts.{self.current_account_id}", True)
                    # Temporarily disable agent notifications if alerts off
                    prev = getattr(self.agent, 'enable_notifications', False)
                    self.agent.enable_notifications = bool(enabled)
                    try:
                        self.agent.on_positions(positions)
                    finally:
                        self.agent.enable_notifications = prev
                else:
                    self.agent.on_positions(positions)
            else:
                self.agent.on_positions(positions)
        except Exception:  # noqa
            pass
        daily_flag = any(p.get('pnlIsDaily') for p in positions)
        if total_value:
            cur_parts = ' '.join(
                f"{c}:{v:,.2f}" for c, v in cur_totals.items()
            )
            pnl_cur_parts = ' '.join(
                f"{c}:{v:,.2f}" for c, v in pnl_abs_by_cur.items()
            )
            pnl_part = (
                f" | PnL: {total_pnl_abs:,.2f} ({pnl_cur_parts})"
                if pnl_abs_by_cur
                else ''
            )
            conv_total = 0.0
            fx_missing = False
            for c, v in cur_totals.items():
                if c == self.base_currency:
                    conv_total += v
                    continue
                converted = None
                try:
                    if self.api and hasattr(self.api, 'convert_money'):
                        converted = self.api.convert_money(
                            v, c, self.base_currency
                        )
                except Exception:  # noqa
                    converted = None
                if converted is None:
                    fx_missing = True
                else:
                    conv_total += converted
            conv_part = ''
            if conv_total and conv_total != total_value:
                conv_part = (
                    " | Total "
                    f"{self.base_currency}: "
                    f"{'≈' if fx_missing else ''}{conv_total:,.2f}"
                )
            legend = ' *=PnL quotidien' if daily_flag else ''
            self.set_status(
                f"Détails chargés - Total: {total_value:,.2f} ("
                f"{cur_parts}){pnl_part}{conv_part}{legend}"
            )
        else:
            self.set_status('Détails chargés')
        for row in self.tree_acts.get_children():
            self.tree_acts.delete(row)
        self._activities_cache = acts
        for a in acts:
            idx = len(self.tree_acts.get_children())
            tag = 'even' if idx % 2 == 0 else 'odd'
            self.tree_acts.insert(
                '',
                tk.END,
                values=(
                    a.get('occurredAt'),
                    a.get('description'),
                    a.get('amount'),
                ),
                tags=(tag,),
            )
        self._refresh_ai_signals()
        # Met à jour le nouveau tab mouvements
        try:
            self.update_movers()
        except Exception:  # noqa
            pass
        # Met à jour recherche par défaut si aucun texte
        try:
            if not (self.var_search_query.get() or '').strip():
                self._populate_search_defaults()
        except Exception:
            pass

    def export_positions_csv(self):
        if not self._positions_cache:
            self.set_status('Aucune position à exporter', error=True)
            return
        path = filedialog.asksaveasfilename(
            title='Exporter positions',
            defaultextension='.csv',
            filetypes=[('CSV', '*.csv')],
        )
        if not path:
            return
        try:
            if self.api and hasattr(self.api, 'export_positions_csv'):
                self.api.export_positions_csv(self._positions_cache, path)
            else:
                fields = [
                    'symbol',
                    'name',
                    'quantity',
                    'lastPrice',
                    'value',
                    'currency',
                    'avgPrice',
                    'pnlAbs',
                    'pnlPct',
                ]
                with open(path, 'w', newline='', encoding='utf-8') as f:
                    w = csv.DictWriter(f, fieldnames=fields)
                    w.writeheader()
                    for p in self._positions_cache:
                        w.writerow({k: p.get(k) for k in fields})
            # Confirmation conservée
            messagebox.showinfo('Export', f'Positions exportées: {path}')
        except Exception as e:  # noqa
            self.set_status(f"Erreur export positions: {e}", error=True, details=repr(e))

    def export_activities_csv(self):
        if not self.tree_acts.get_children():
            self.set_status('Aucune activité à exporter', error=True)
            return
        path = filedialog.asksaveasfilename(
            title='Exporter activités',
            defaultextension='.csv',
            filetypes=[('CSV', '*.csv')],
        )
        if not path:
            return
        with open(path, 'w', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            w.writerow(['Date', 'Description', 'Montant'])
            for iid in self.tree_acts.get_children():
                w.writerow(self.tree_acts.item(iid, 'values'))
        # Confirmation conservée
        messagebox.showinfo('Export', f'Activités exportées: {path}')

    def sort_tree(self, tree: ttk.Treeview, col: str, numeric=False):
        items = list(tree.get_children(''))
        idx_col = tree['columns'].index(col)
        data = []
        for iid in items:
            vals = tree.item(iid, 'values')
            key = vals[idx_col]
            if numeric:
                try:
                    key = float(
                        str(key)
                        .replace('↑', '')
                        .replace('↓', '')
                        .replace('%', '')
                        .replace('*', '')
                        .replace(',', '')
                    )
                except Exception:
                    key = 0.0
            data.append((key, iid))
        descending = getattr(tree, f'_sort_desc_{col}', False)
        data.sort(reverse=not descending)
        for _, iid in data:
            tree.move(iid, '', 'end')
        setattr(tree, f'_sort_desc_{col}', not descending)

    def apply_activity_filter(self):
        flt = (self.var_act_filter.get() or '').lower()
        for row in self.tree_acts.get_children():
            self.tree_acts.delete(row)
        for a in self._activities_cache:
            if (
                flt
                and flt not in (a.get('description') or '').lower()
                and flt not in (a.get('occurredAt') or '').lower()
            ):
                continue
            self.tree_acts.insert(
                '',
                tk.END,
                values=(
                    a.get('occurredAt'),
                    a.get('description'),
                    a.get('amount'),
                ),
            )

    def _refresh_ai_signals_periodic(self):
        self._refresh_ai_signals()
        self.after(15000, self._refresh_ai_signals_periodic)

    def _refresh_ai_signals(self):
        if self.agent_ui:
            self.agent_ui.refresh_signals()
            pal = self._palettes[self._theme]
            colors = {
                'lvl_info': pal.get('text_muted', '#888'),
                'lvl_warn': '#d97706',
                'lvl_alert': pal.get('danger', '#dc2626'),
            }
            for tag, col in colors.items():
                try:
                    self.tree_signals.tag_configure(tag, foreground=col)
                except Exception:  # noqa
                    pass

    def _chat_send(self):
        msg = self.var_chat.get().strip()
        if not msg:
            return
        self.var_chat.set('')
        self._append_chat(f"Vous: {msg}\n")
        try:
            resp = self.agent.chat(msg)
        except Exception as e:  # noqa
            resp = f"Erreur agent: {e}"
        self._append_chat(f"Agent: {resp}\n")
        # Log Gemini erreurs dans la zone output
        if resp.lower().startswith('(gemini erreur') or 'gemini' in resp.lower():
            try:
                self.log(resp)
            except Exception:  # noqa
                pass

    def _append_chat(self, text: str):
        self.txt_chat.configure(state=tk.NORMAL)
        self.txt_chat.insert(tk.END, text)
        self.txt_chat.see(tk.END)
        self.txt_chat.configure(state=tk.DISABLED)

    def schedule_auto_refresh(self):
        # Persister les préférences d'auto actualisation
        try:
            app_config.set('ui.auto_refresh.enabled', bool(self.auto_refresh.get()))
            app_config.set('ui.auto_refresh.seconds', int(self.auto_refresh_interval.get()))
        except Exception:
            pass
        if self.auto_refresh.get():
            self.after(1000, self._auto_refresh_tick)

    def _auto_refresh_tick(self):
        if not self.auto_refresh.get():
            return
        # prevent overlapping refreshes
        if getattr(self, '_busy_refresh', False):
            # reschedule sooner to catch up
            self.after(1000, self._auto_refresh_tick)
            return
        self._busy_refresh = True
        try:
            self.refresh_accounts()
            if self.current_account_id:
                self.refresh_selected_account_details()
        finally:
            self._busy_refresh = False
        self.after(
            max(30, self.auto_refresh_interval.get()) * 1000,
            self._auto_refresh_tick,
        )

    def _add_tree_context(self, tree: ttk.Treeview):
        menu = tk.Menu(tree, tearoff=0)
        menu.add_command(
            label='Copier ligne', command=lambda: self._copy_selected(tree)
        )

        def popup(ev):  # noqa
            iid = tree.identify_row(ev.y)
            if iid:
                tree.selection_set(iid)
                menu.tk_popup(ev.x_root, ev.y_root)

        tree.bind('<Button-3>', popup)

    def _copy_selected(self, tree: ttk.Treeview):
        sel = tree.selection()
        if not sel:
            return
        vals = tree.item(sel[0], 'values')
        self.clipboard_clear()
        self.clipboard_append('\t'.join(str(v) for v in vals))
        self.update()

    def _on_symbol_double_click(self, event):
        """Gestionnaire de double-clic sur un symbole dans le tableau des positions."""
        item = self.tree_positions.selection()[0] if self.tree_positions.selection() else None
        if not item:
            return

        # Récupérer les valeurs de la ligne
        values = self.tree_positions.item(item, 'values')
        if not values or len(values) < 1:
            return

        # Le symbole est dans la première colonne
        symbol = values[0]

        if not symbol or symbol == 'N/A':
            self.set_status("Analyse: aucun symbole valide pour cette position.", error=True)
            return

        # Vérifier si l'analyseur de symboles est disponible
        if not self.symbol_analyzer:
            msg = (
                "L'analyseur de symboles n'est pas disponible.\n"
                "Veuillez installer les dépendances requises (matplotlib, numpy)."
            )
            self.set_status(msg, error=True)
            return

        # Ouvrir l'analyseur de symboles
        try:
            self.log(f"📊 Ouverture de l'analyse pour {symbol}...")
            self.symbol_analyzer.show_symbol_analysis(symbol)
        except Exception as e:
            self.set_status(f"Impossible d'ouvrir l'analyse pour {symbol}: {e}", error=True)

    def _analyze_selected_symbol(self):
        """Ouvre l'analyseur pour le symbole sélectionné."""
        selection = self.tree_positions.selection()
        if not selection:
            self.set_status("Analyse: veuillez sélectionner une position.", error=True)
            return

        # Simuler un double-clic
        event = type('Event', (), {'widget': self.tree_positions})()
        self._on_symbol_double_click(event)

    def _quick_chart_selected(self):
        """Affiche un graphique rapide pour le symbole sélectionné."""
        selection = self.tree_positions.selection()
        if not selection:
            self.set_status("Graphique rapide: sélectionnez une position.", error=True)
            return

        # Récupérer le symbole
        values = self.tree_positions.item(selection[0], 'values')
        if not values or len(values) < 1:
            return

        symbol = values[0]
        if not symbol or symbol == 'N/A':
            self.set_status("Graphique rapide: aucun symbole valide.", error=True)
            return

        try:
            # Demander à l'agent AI de rechercher le symbole et afficher des infos
            if self.api_manager:
                self.log(f"📈 Recherche d'informations rapides pour {symbol}...")

                def fetch_quick_info():
                    try:
                        quote = self.api_manager.alpha_vantage.get_quote(symbol)
                        if quote:
                            price = float(quote.get('05. price', 0))
                            change = float(quote.get('09. change', 0))
                            change_pct = quote.get('10. change percent', '0%')
                            volume = quote.get('06. volume', 'N/A')

                            info_msg = f"""📊 Informations rapides pour {symbol}:

• Prix actuel: ${price:.2f}
• Changement: ${change:.2f} ({change_pct})
• Volume: {volume}
• Mise à jour: {quote.get('07. latest trading day', 'N/A')}

💡 Double-cliquez sur le symbole dans le tableau pour une analyse complète."""

                            self.after(0, lambda: messagebox.showinfo(f"Aperçu rapide - {symbol}", info_msg))
                        else:
                            self.after(0, lambda: messagebox.showwarning(
                                "Aperçu rapide", f"Impossible de récupérer les données pour {symbol}"
                            ))
                    except Exception as e:
                        self.after(0, lambda err=e: self.set_status(f"Erreur lors de la récupération: {err}", error=True))

                threading.Thread(target=fetch_quick_info, daemon=True).start()
            else:
                message = (
                    f"Symbole sélectionné: {symbol}\n\n"
                    "APIs externes non configurées.\n"
                    "Pour des informations en temps réel, configurez les clés API."
                )
                messagebox.showinfo("Aperçu rapide", message)
        except Exception as e:
            self.set_status(f"Erreur lors de l'aperçu rapide: {e}", error=True)

    def _quick_symbol_analysis(self):
        """Ouvre une boîte de dialogue pour analyser rapidement un symbole."""
        symbol = simpledialog.askstring(
            "Analyse de symbole", "Entrez le symbole à analyser (ex: AAPL, TSLA, GOOGL):"
        )
        if not symbol:
            return

        symbol = symbol.upper().strip()

        if self.symbol_analyzer:
            try:
                self.log(f"📊 Ouverture de l'analyse pour {symbol} via chat...")
                self.symbol_analyzer.show_symbol_analysis(symbol)
            except Exception as e:
                self.set_status(f"Erreur lors de l'analyse: {e}", error=True, details=repr(e))
                messagebox.showerror("Erreur", f"Impossible d'analyser {symbol}:\n{e}")
        else:
            # Fallback: demander à l'agent AI une analyse textuelle
            try:
                self._append_chat(f"Vous: Analyse {symbol}\n")
                if self.api_manager:

                    def fetch_analysis():
                        try:
                            quote = self.api_manager.alpha_vantage.get_quote(symbol)
                            news = self.api_manager.news.get_company_news(symbol, 3)

                            analysis_prompt = f"Analysez le symbole {symbol}:"
                            if quote:
                                price = float(quote.get('05. price', 0))
                                change = float(quote.get('09. change', 0))
                                change_pct = quote.get('10. change percent', '0%')
                                analysis_prompt += f" Prix: ${price:.2f}, Changement: ${change:.2f} ({change_pct})"

                            if news:
                                analysis_prompt += f", {len(news)} actualités récentes disponibles"

                            resp = self.agent.chat(analysis_prompt)
                            self.after(0, lambda: self._append_chat(f"Agent: {resp}\n"))
                        except Exception as e:
                            self.after(0, lambda err=e: self._append_chat(f"Erreur: {err}\n"))

                    threading.Thread(target=fetch_analysis, daemon=True).start()
                else:
                    resp = self.agent.chat(
                        f"Donnez-moi une analyse générale du symbole {symbol}"
                    )
                    self._append_chat(f"Agent: {resp}\n")
            except Exception as e:
                self.set_status(f"Erreur lors de l'analyse: {e}", error=True)

    def _busy(self, on: bool):
        try:
            if on:
                self.progress.start(10)
            else:
                self.progress.stop()
        except Exception:  # noqa
            pass

    def log(self, msg: str, clear=False):
        self.txt_output.configure(state=tk.NORMAL)
        if clear:
            self.txt_output.delete('1.0', tk.END)
        self.txt_output.insert(tk.END, msg + '\n')
        self.txt_output.see(tk.END)
        self.txt_output.configure(state=tk.DISABLED)

    def _append_output(self, msg: str):
        """Ajoute un message à la zone de sortie."""
        self.log(msg)

    def set_status(self, msg: str, error: bool = False, details: Optional[str] = None):
        self.var_status.set(msg)
        self.update_idletasks()
        if error:
            self.log(f"❌ {msg}")
            try:
                # Si on a des détails et debug, ne pas timeout automatiquement
                debug = bool(app_config.get('app.debug', False))
                self._show_banner(str(msg), kind='error', timeout_ms=(0 if (debug and details) else 8000), details=details)
            except Exception:
                pass

    # ------------------- Diagnostics (cache, circuits) -------------------
    # diagnostics helpers removed; handled by DiagnosticsPanel

    # ------------------- Bandeau d'information/erreur -------------------
    def _show_banner(self, text: str, kind: str = 'info', timeout_ms: int = 0, details: Optional[str] = None):
        """Affiche une bannière non bloquante en haut de l'app.

        kind: 'info' | 'error'
        timeout_ms: cache automatiquement après X ms si > 0
        """
        try:
            pal = self._palettes.get(self._theme, {})
            bg = pal.get('panel')
            fg = pal.get('text')
            if kind == 'error':
                bg = pal.get('danger_bg', bg)
                fg = pal.get('danger', fg)
            elif kind == 'info':
                bg = pal.get('accent_bg', bg)
                fg = pal.get('accent', fg)

            # Configure ttk styles for banner (frame + label) to ensure background/foreground are applied
            try:
                style = ttk.Style(self)
                suffix = 'Error' if kind == 'error' else 'Info'
                frame_style = f'Banner{suffix}.TFrame'
                label_style = f'Banner{suffix}.TLabel'
                # Apply styles (idempotent)
                style.configure(frame_style, background=bg)
                style.configure(label_style, background=bg, foreground=fg)
                # Apply styles to widgets
                self._banner_container.configure(style=frame_style)
                self._banner_frame.configure(style=frame_style)
                self._banner_msg.configure(style=label_style)
            except Exception:
                # Fallback: set foreground directly on label
                try:
                    self._banner_msg.configure(foreground=fg)
                except Exception:
                    pass
            self._banner_msg.configure(text=text)
            # Enregistrer les détails (si fournis)
            if details:
                self._set_last_error_details(details)
            # Pack et afficher
            try:
                self._banner_container.pack_forget()
            except Exception:
                pass
            self._banner_container.pack(fill=tk.X, padx=8, pady=(0, 4))
            self._banner_frame.pack(fill=tk.X)
            # Couleurs appliquées via styles ci-dessus (aucune action supplémentaire)
            # Afficher le bouton détails si en mode debug et détails disponibles
            try:
                if bool(app_config.get('app.debug', False)) and bool(self._last_error_details):
                    self._banner_details_button.pack(side=tk.RIGHT, padx=(0, 6))
                else:
                    self._banner_details_button.pack_forget()
            except Exception:
                pass
            if timeout_ms and timeout_ms > 0:
                self.after(timeout_ms, self._hide_banner)
        except Exception:
            pass

    def _hide_banner(self):
        try:
            self._banner_frame.pack_forget()
            self._banner_container.pack_forget()
            if self._banner_details_shown:
                self._toggle_banner_details(force_hide=True)
        except Exception:
            pass

    def _set_last_error_details(self, details: Optional[str]):
        try:
            self._last_error_details = details
            # Préparer le texte
            self._banner_details_text.configure(state=tk.NORMAL)
            self._banner_details_text.delete('1.0', tk.END)
            if details:
                self._banner_details_text.insert(tk.END, details)
            self._banner_details_text.configure(state=tk.DISABLED)
        except Exception:
            pass

    def _toggle_banner_details(self, force_hide: bool = False):
        try:
            if force_hide or self._banner_details_shown:
                self._banner_details_frame.pack_forget()
                self._banner_details_shown = False
                try:
                    self._banner_details_button.configure(text='Voir détails')
                except Exception:
                    pass
            else:
                # Afficher seulement si on a des détails
                if not self._last_error_details:
                    return
                self._banner_details_frame.pack(fill=tk.X, padx=8, pady=(0, 8))
                self._banner_details_shown = True
                try:
                    self._banner_details_button.configure(text='Masquer détails')
                except Exception:
                    pass
        except Exception:
            pass

    # ------------------- Recherche titres -------------------
    def search_securities(self):
        if not self.api:
            self.set_status("Connectez-vous d'abord.", error=True)
            return
        q = (self.var_search_query.get() or '').strip()
        if not q:
            return
        self.set_status(f'Recherche: {q} ...')
        self._busy(True)

        def worker():
            try:
                results = self.api.search_security(q)
                # results: list d'objets GraphQL -> dicts
                # Normaliser
                norm = []
                for r in results:
                    stock = r.get('stock') or {}
                    quoteV2 = r.get('quoteV2') or {}
                    norm.append(
                        {
                            'id': r.get('id'),
                            'symbol': stock.get('symbol'),
                            'name': stock.get('name'),
                            'exchange': stock.get('primaryExchange'),
                            'status': r.get('status'),
                            'buyable': r.get('buyable'),
                            'marketStatus': quoteV2.get('marketStatus'),
                        }
                    )
                self.after(0, lambda n=norm: self._update_search_results(n))
            except Exception as e:  # noqa
                self.after(0, lambda e=e: self.set_status(f"Erreur recherche: {e}", error=True))
            finally:
                self.after(
                    0,
                    lambda: (
                        self._busy(False),
                        self.set_status('Recherche terminée'),
                    ),
                )

        threading.Thread(target=worker, daemon=True).start()

    def _update_search_results(self, results):
        self._search_results = results
        for row in self.tree_search.get_children():
            self.tree_search.delete(row)
        for i, r in enumerate(results):
            tag = 'even' if i % 2 == 0 else 'odd'
            self.tree_search.insert(
                '',
                tk.END,
                values=(
                    r.get('symbol'),
                    r.get('name'),
                    r.get('exchange'),
                    r.get('status'),
                    'Oui' if r.get('buyable') else 'Non',
                    r.get('marketStatus'),
                ),
                tags=(tag,),
            )

    def open_search_security_details(self):
        """Open details for the selected security (search tab)."""
        sel = self.tree_search.selection()
        if not sel:
            return
        idx = self.tree_search.index(sel[0])
        if idx >= len(self._search_results):
            return
        sec = self._search_results[idx]
        sec_id = sec.get('id')
        if not self.api or not sec_id:
            return
        self.set_status(f"Détails: {sec.get('symbol')} ...")
        self._busy(True)
        # Trigger async logo fetch (non-blocking)
        self._set_logo_image(sec.get('symbol'))

        def worker():
            try:
                md = self.api.get_security_market_data(sec_id)
                lines: List[str] = []
                stock = md.get('stock') or {}
                quote = md.get('quote') or {}
                fund = md.get('fundamentals') or {}
                lines.append(f"Nom: {stock.get('name')}")
                lines.append(f"Symbole: {stock.get('symbol')}")
                lines.append(f"Échange: {stock.get('primaryExchange')}")
                if quote:
                    lines.append(
                        'Prix: ' + str(quote.get('last'))
                        + ' | Volume: ' + str(quote.get('volume'))
                    )
                    lines.append(
                        'High: ' + str(quote.get('high'))
                        + ' Low: ' + str(quote.get('low'))
                        + ' PrevClose: ' + str(quote.get('previousClose'))
                    )
                if fund:
                    lines.append(
                        '52w High: ' + str(fund.get('high52Week'))
                        + ' 52w Low: ' + str(fund.get('low52Week'))
                        + ' PE: ' + str(fund.get('peRatio'))
                        + ' Rendement: ' + str(fund.get('yield'))
                    )
                    lines.append(
                        'MarketCap: ' + str(fund.get('marketCap'))
                        + ' Devise: ' + str(fund.get('currency'))
                    )
                desc = fund.get('description')
                if desc:
                    lines.append('--- Description ---')
                    lines.append(desc)
                txt = '\n'.join(lines)
                self.after(0, lambda t=txt: self._set_search_details(t))
            except Exception as e:  # noqa
                self.after(0, lambda e=e: self.set_status(f"Erreur détails: {e}", error=True))
            finally:
                self.after(0, lambda: (self._busy(False), self.set_status('Prêt')))

        threading.Thread(target=worker, daemon=True).start()

    def _set_search_details(self, text: str):
        self.txt_search_details.configure(state=tk.NORMAL)
        self.txt_search_details.delete('1.0', tk.END)
        self.txt_search_details.insert(tk.END, text)
        self.txt_search_details.see(tk.END)
        self.txt_search_details.configure(state=tk.DISABLED)

    # --------- Logos & images (new) ---------
    def _set_logo_image(self, symbol: Optional[str]):
        symbol = (symbol or '').strip()
        if not symbol:
            self.lbl_search_logo.configure(text='[Logo]', image='')
            return

        def cb(img):
            try:
                self.after(0, lambda: self._apply_logo(symbol, img))
            except Exception:
                pass
        self.media.get_logo_async(symbol, cb)

    def _apply_logo(self, symbol: str, img):
        if img:
            self._logo_images[symbol] = img
            self.lbl_search_logo.configure(image=img, text='')
        else:
            self.lbl_search_logo.configure(text=symbol, image='')

    def _apply_news_image(self, img, title: str):
        if img:
            self._news_image_ref = img
            self.lbl_news_image.configure(image=img, text='')
        else:
            self.lbl_news_image.configure(text=f'(Image indisponible) {title[:30]}', image='')

    def _populate_search_defaults(self):
        """Affiche par défaut les positions actuelles (top valeur) si aucune recherche."""
        try:
            items = sorted(self._positions_cache, key=lambda p: p.get('value') or 0, reverse=True)[:20]
            for row in self.tree_search.get_children():
                self.tree_search.delete(row)
            for i, p in enumerate(items):
                tag = 'even' if i % 2 == 0 else 'odd'
                self.tree_search.insert('', tk.END, values=(
                    p.get('symbol'), p.get('name'), '', 'Held', 'Oui', p.get('currency') or ''
                ), tags=(tag,))
            self._set_search_details("Suggestions par défaut: vos positions principales affichées. Lancez une recherche pour plus de titres.")
        except Exception:
            pass

    def _update_search_suggestions(self):
        query = (self.var_search_query.get() or '').strip().upper()
        # Cacher si vide
        if not query:
            if self.lst_search_suggestions.winfo_ismapped():
                self.lst_search_suggestions.place_forget()
            return
        # Générer suggestions basées sur positions + codes fréquents
        symbols = {
            (p.get('symbol') or '').upper() for p in self._positions_cache if p.get('symbol')
        }
        common = {'AAPL', 'MSFT', 'TSLA', 'NVDA', 'GOOGL', 'AMZN', 'META', 'BTC', 'ETH'}
        matches = [s for s in sorted(symbols | common) if s.startswith(query)][:8]
        if not matches:
            if self.lst_search_suggestions.winfo_ismapped():
                self.lst_search_suggestions.place_forget()
            return
        # Debounce UI updates to avoid flicker

        def _apply_list():
            if not self.lst_search_suggestions.winfo_exists():
                return
            self.lst_search_suggestions.delete(0, tk.END)
            for m in matches:
                self.lst_search_suggestions.insert(tk.END, m)

        try:
            if hasattr(self, '_search_debounce_id') and self._search_debounce_id:
                self.after_cancel(self._search_debounce_id)
        except Exception:
            pass
        self._search_debounce_id = self.after(300, _apply_list)
        # Positionner sous le champ (approx) - placement simple
        self.lst_search_suggestions.place(x=200, y=0)

    def _apply_search_suggestion(self):
        sel = self.lst_search_suggestions.curselection()
        if not sel:
            return
        symbol = self.lst_search_suggestions.get(sel[0])
        self.var_search_query.set(symbol)
        self.lst_search_suggestions.place_forget()
        self.search_securities()

    # ------------------- Persistance UI divers -------------------
    def _on_tab_changed(self, _event=None):
        try:
            nb = self._main_notebook
            idx = nb.index(nb.select())
            app_config.set('ui.last_tab', int(idx))
        except Exception:
            pass

    def _on_close(self):
        try:
            app_config.save_window_geometry(self.geometry())
        except Exception:
            pass
        self.destroy()

    # ------------------- Surveillance AI continue -------------------
    def _ai_watchdog_tick(self):
        """Background monitor: re-run agent rules and refresh UI.

        Keeps signals fresh even if no manual action; throttled and resilient.
        """
        try:
            if getattr(self, 'agent', None) and self.agent.last_positions:
                # Produce any new signals
                new_sigs = []
                try:
                    new_sigs = self.agent.generate_market_signals() or []
                except Exception:
                    new_sigs = []
                if new_sigs and hasattr(self, 'agent_ui') and self.agent_ui:
                    self.agent_ui.refresh_signals()
                # Optional: notify in status minimally
                if new_sigs:
                    try:
                        codes = ', '.join({s.code for s in new_sigs})
                        self.set_status(f"Nouveaux signaux: {len(new_sigs)} ({codes})")
                    except Exception:
                        pass
        except Exception:
            pass
        # Schedule next check
        self.after(30000, self._ai_watchdog_tick)

    # ------------------- Mouvements -------------------
    def update_movers(self, top_n: Optional[int] = None):
        """Remplit les tableaux gagnants / perdants / actifs / opportunités.

        Priorité:
          - Si API externe disponible: scan marché canadien (gainers/losers/actives) via Yahoo screener
          - Sinon: fallback heuristique basé sur PnL des positions du portefeuille
        """
        if not hasattr(self, 'tree_gainers'):
            return
        # Déterminer le Top N effectif
        try:
            top_n = int(top_n) if top_n is not None else int(app_config.get('ui.movers.top_n', 5))
        except Exception:
            top_n = 5

        # Essayer d'abord marché canadien si APIManager dispo
        if self.api_manager:
            def worker_market():
                try:
                    movers = self.api_manager.get_market_movers_ca(top_n=top_n)
                except Exception:
                    movers = None
                if movers and isinstance(movers, dict):
                    def _fill_from_market():
                        def fill_tree(tree, items, cols_map):
                            for row in tree.get_children():
                                tree.delete(row)
                            for i, q in enumerate(items):
                                tag = 'even' if i % 2 == 0 else 'odd'
                                vals = cols_map(q)
                                tree.insert('', tk.END, values=vals, tags=(tag,))
                        gainers = movers.get('gainers') or []
                        losers = movers.get('losers') or []
                        actives = movers.get('actives') or []
                        opps = movers.get('opportunities') or (losers[:max(1, top_n//2)])
                        fill_tree(self.tree_gainers, gainers, lambda q: (
                            q.get('symbol'), f"{q.get('changePct', 0):.2f}", f"{q.get('change', 0):.2f}", f"{q.get('price', 0):.2f}", q.get('volume')
                        ))
                        fill_tree(self.tree_losers, losers, lambda q: (
                            q.get('symbol'), f"{q.get('changePct', 0):.2f}", f"{q.get('change', 0):.2f}", f"{q.get('price', 0):.2f}", q.get('volume')
                        ))
                        fill_tree(self.tree_active, actives, lambda q: (
                            q.get('symbol'), f"{q.get('price', 0):.2f}", f"{q.get('changePct', 0):.2f}", f"{q.get('change', 0):.2f}", q.get('volume')
                        ))
                        fill_tree(self.tree_opps, opps, lambda q: (
                            q.get('symbol'), f"{q.get('changePct', 0):.2f}", f"{q.get('change', 0):.2f}", f"{q.get('price', 0):.2f}", q.get('volume')
                        ))
                        self.set_status(f"Mouvements (CA): +{len(gainers)} / -{len(losers)} / actifs {len(actives)}")
                        # Recolor according to Pct change
                        try:
                            pal = self._palettes[self._theme]
                            for tree in [self.tree_gainers, self.tree_losers, self.tree_active, self.tree_opps]:
                                for iid in tree.get_children():
                                    cols = tree.item(iid, 'values')
                                    pnl_idx = 2 if tree is self.tree_active else 1
                                    try:
                                        v = float(str(cols[pnl_idx]).replace('%', '').replace('*', ''))
                                    except Exception:
                                        v = 0.0
                                    color = pal.get('success') if v >= 0 else pal.get('danger')
                                    tag_name = f"pnl_{iid}"
                                    tree.tag_configure(tag_name, foreground=color)
                                    tree.item(iid, tags=(tree.item(iid, 'tags') + (tag_name,)))
                        except Exception:
                            pass
                    try:
                        self.after(0, _fill_from_market)
                        return
                    except Exception:
                        pass
            threading.Thread(target=worker_market, daemon=True).start()

        # Fallback local basé sur portefeuille
        positions = list(self._positions_cache)

        def pnl_pct(p):  # local helpers
            v = p.get('pnlPct')
            return v if isinstance(v, (int, float)) else 0.0

        def pnl_abs(p):
            v = p.get('pnlAbs')
            return v if isinstance(v, (int, float)) else 0.0

        def val(p):
            v = p.get('value')
            return v if isinstance(v, (int, float)) else 0.0

        gainers = [p for p in positions if pnl_pct(p) > 0]
        gainers.sort(key=pnl_pct, reverse=True)
        losers = [p for p in positions if pnl_pct(p) < 0]
        losers.sort(key=pnl_pct)  # plus négatif en premier
        actives = sorted(positions, key=val, reverse=True)
        # Opportunités: combiner plusieurs heuristiques (baisses fortes, retournement possible)
        opps = [
            p for p in losers
            if (
                pnl_pct(p) <= -5  # Forte baisse relative
                or pnl_abs(p) <= -100  # Perte absolue significative
                or (pnl_pct(p) < 0 and val(p) > 500 and abs(pnl_pct(p)) <= 8)  # Baisse modérée sur grosse position
            )
        ]
        opps.sort(key=pnl_pct)
        # Fallback: si aucune opportunité stricte trouvée, prendre les 3 plus grosses pertes
        if not opps:
            opps = losers[:3]

        def fill(tree, items):
            for row in tree.get_children():
                tree.delete(row)
            for i, p in enumerate(items[:top_n]):
                tag = 'even' if i % 2 == 0 else 'odd'
                pnl_or_val = (
                    f"{pnl_pct(p):.2f}"
                    if tree is not self.tree_active
                    else f"{val(p):.2f}"
                )
                tree.insert(
                    '',
                    tk.END,
                    values=(
                        p.get('symbol'),
                        pnl_or_val,
                        f"{pnl_abs(p):.2f}",
                        f"{val(p):.2f}",
                        p.get('quantity'),
                    ),
                    tags=(tag,),
                )

        def fill_specific(tree, items, cols):
            for row in tree.get_children():
                tree.delete(row)
            for i, p in enumerate(items[:top_n]):
                tag = 'even' if i % 2 == 0 else 'odd'
                tree.insert('', tk.END, values=cols(p), tags=(tag,))

        fill(self.tree_gainers, gainers)
        fill(self.tree_losers, losers)
        fill_specific(
            self.tree_active,
            actives,
            lambda p: (
                p.get('symbol'),
                f"{val(p):.2f}",
                f"{pnl_pct(p):.2f}{'*' if p.get('pnlIsDaily') else ''}",
                f"{pnl_abs(p):.2f}",
                p.get('quantity'),
            ),
        )
        fill(self.tree_opps, opps)
        # Résumé automatique opportunités
        try:
            if opps:
                resume = ", ".join(
                    f"{p.get('symbol')} ({p.get('pnlPct'):.1f}%)" if isinstance(p.get('pnlPct'), (int, float)) else p.get('symbol')
                    for p in opps[:5]
                )
                self.set_status(f"{len(opps)} opportunités détectées: {resume}")
        except Exception:
            pass
        pal = self._palettes[self._theme]
        try:
            for tree in [
                self.tree_gainers,
                self.tree_losers,
                self.tree_active,
                self.tree_opps,
            ]:
                for iid in tree.get_children():
                    cols = tree.item(iid, 'values')
                    pnl_idx = 2 if tree is self.tree_active else 1
                    try:
                        v = float(
                            str(cols[pnl_idx])
                            .replace('%', '')
                            .replace('*', '')
                        )
                    except Exception:
                        v = 0.0
                    color = pal.get('success') if v >= 0 else pal.get(
                        'danger'
                    )
                    tag_name = f"pnl_{iid}"
                    tree.tag_configure(tag_name, foreground=color)
                    tree.item(
                        iid,
                        tags=(tree.item(iid, 'tags') + (tag_name,)),
                    )
        except Exception:  # noqa
            pass

    # ------------------- Actualités -------------------

    def refresh_news(self):
        """Actualise les actualités financières."""
        if not self.api_manager:
            self.set_status("APIs externes non disponibles", error=True)
            return

        def worker():
            try:
                query = self.var_news_query.get() or "stock market"
                articles = self.api_manager.news.get_financial_news(query, 20)
                # Fallback sur un mot-clé générique si rien
                if not articles and query != 'stock market':
                    articles = self.api_manager.news.get_financial_news('stock market', 15)
                # Ajouter un score de sentiment basique
                enriched = []
                pos_words = {'up', 'gain', 'beat', 'growth', 'surge', 'rise'}
                neg_words = {'down', 'loss', 'miss', 'decline', 'drop', 'fall'}
                for a in articles:
                    text = ((a.get('title') or '') + ' ' + (a.get('description') or '')).lower()
                    score = sum(1 for w in pos_words if w in text) - sum(1 for w in neg_words if w in text)
                    a['sentimentScore'] = score
                    enriched.append(a)
                articles = enriched
                self.after(0, lambda: self._update_news_tree(articles))
            except Exception as e:
                self.after(0, lambda e=e: self.set_status(f"Erreur actualités: {e}", error=True))

        threading.Thread(target=worker, daemon=True).start()

    def refresh_market_overview(self):
        """Récupère un aperçu du marché pour les positions actuelles."""
        if not self.api_manager:
            self.set_status("APIs externes non disponibles", error=True)
            return

        if not self._positions_cache:
            self.set_status("Aucune position pour l'aperçu marché", error=True)
            return

        def worker():
            try:
                symbols = [p.get('symbol') for p in self._positions_cache if p.get('symbol')][:5]
                overview = self.api_manager.get_market_overview(symbols)
                self.after(0, lambda: self._display_market_overview(overview))
            except Exception as e:
                self.after(0, lambda e=e: self.set_status(f"Erreur aperçu marché: {e}", error=True))

        threading.Thread(target=worker, daemon=True).start()

    def _update_news_tree(self, articles: List[Dict]):
        """Met à jour le TreeView des actualités."""
        # Clear existing
        for item in self.tree_news.get_children():
            self.tree_news.delete(item)

        for article in articles:
            source = article.get('source', {}).get('name', 'N/A')
            raw_title = article.get('title', 'Sans titre')
            title = raw_title[:80] + '...' if len(raw_title) > 80 else raw_title
            published = article.get('publishedAt', '')[:10]
            score = article.get('sentimentScore', 0)
            if score > 0:
                sentiment = f"🟢 +{score}" if score > 1 else "🟢 +1"
            elif score < 0:
                sentiment = f"🔴 {score}"
            else:
                sentiment = "🟡 0"
            self.tree_news.insert('', tk.END, values=(source, title, published, sentiment))

        self.set_status(f"Actualités mises à jour: {len(articles)} articles")

    def _on_signal_double_click(self, _event=None):
        sel = self.tree_signals.selection()
        if not sel:
            return
        vals = self.tree_signals.item(sel[0], 'values')
        if len(vals) < 3:
            return
        symbol = vals[2]
        if not symbol:
            return
        if hasattr(self, 'symbol_analyzer') and self.symbol_analyzer:
            try:
                self.symbol_analyzer.show_symbol_analysis(symbol)
            except Exception as e:  # noqa
                self.set_status(f"Erreur ouverture analyse: {e}", error=True)
        else:
            self.log(f"Analyse symbole indisponible pour {symbol}. Installez matplotlib.")

    def _display_market_overview(self, overview: Dict):
        """Affiche l'aperçu du marché dans la zone de sortie."""
        lines = ["📊 APERÇU MARCHÉ\n"]

        quotes = overview.get('quotes', {})
        for symbol, quote in quotes.items():
            price = quote.get('05. price', 'N/A')
            change = quote.get('09. change', 'N/A')
            change_pct = quote.get('10. change percent', 'N/A')
            lines.append(f"{symbol}: {price} ({change}, {change_pct})")

        news = overview.get('news', [])
        if news:
            lines.append("\n📰 ACTUALITÉS RÉCENTES:")
            for article in news[:3]:
                title = article.get('title', '')[:60] + '...' if len(article.get('title', '')) > 60 else article.get('title', '')
                lines.append(f"• {title}")

        self._append_output('\n'.join(lines))

    def on_news_double_click(self, event):
        """Affiche les détails d'un article sélectionné."""
        selection = self.tree_news.selection()
        if not selection:
            return

        if not self.api_manager:
            return

        # Get the selected article details
        item = self.tree_news.item(selection[0])
        title = item['values'][1]  # Title column

        # Try to find the full article in the last news fetch
        # For now, just show basic info
        details = f"Titre: {title}\n\nPour plus de détails, visitez le site de la source."

        self.txt_news_details.configure(state=tk.NORMAL)
        self.txt_news_details.delete(1.0, tk.END)
        self.txt_news_details.insert(tk.END, details)
        self.txt_news_details.configure(state=tk.DISABLED)

    def send_portfolio_notification(self):
        """Envoie une notification Telegram du résumé du portfolio."""
        # Respect per-account alerts setting
        if self.current_account_id is not None:
            enabled = app_config.get(f"alerts.{self.current_account_id}", True)
            if not enabled:
                self.set_status("Alertes désactivées pour ce compte", error=True)
                return
        if not self.api_manager:
            self.set_status("APIs externes non disponibles", error=True)
            return

        if not self._positions_cache:
            self.set_status("Aucune position pour la notification", error=True)
            return

        def worker():
            try:
                total_value = sum(float(p.get('value', 0)) for p in self._positions_cache)
                total_pnl = sum(float(p.get('pnlAbs', 0)) for p in self._positions_cache if p.get('pnlAbs'))
                positions_count = len([p for p in self._positions_cache if float(p.get('value', 0)) > 0])

                success = self.api_manager.telegram.send_portfolio_summary(
                    total_value, total_pnl, positions_count
                )

                if success:
                    self.after(0, lambda: self.set_status("Notification Telegram envoyée"))
                else:
                    self.after(0, lambda: self.set_status("Erreur envoi notification Telegram", error=True))

            except Exception as e:
                self.after(0, lambda e=e: self.set_status(f"Erreur notification: {e}", error=True))

        threading.Thread(target=worker, daemon=True).start()


# Fin de classe
__all__ = ["WSApp"]


if __name__ == '__main__':
    app = WSApp()
    app.mainloop()
