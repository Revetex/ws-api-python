from __future__ import annotations

# Standard library
import csv
import os
import threading
import tkinter as tk
import webbrowser
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

# Local / project imports
from ai_agent import AIAgent
from run_ws import load_session, save_session  # type: ignore
from utils.env import load_dotenv_safe
from utils.logging_setup import setup_logging
from ws_api import WealthsimpleAPI
from ws_api.exceptions import (
    LoginFailedException,
    ManualLoginRequired,
    OTPRequiredException,
    WSApiException,
)

from .agent_ui import AgentUI
from .backtest_ui import BacktestPanel
from .charts import HAS_MPL, ChartController
from .chat_manager import ChatManager
from .config import app_config
from .diagnostics_ui import DiagnosticsPanel
from .export_manager import ExportManager
from .login_dialog import LoginDialog
from .media_manager import MediaManager
from .news_manager import NewsManager
from .portfolio_manager import PortfolioManager
from .screener_ui import ScreenerPanel
from .search_manager import SearchManager
from .strategy_runner import StrategyRunner
from .theming import PALETTES, apply_palette
from .trade_executor import TradeExecutor
from .ui_utils import attach_tooltip, format_money

# External APIs and Symbol Analyzer availability
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
        try:
            setup_logging()
            load_dotenv_safe()
        except Exception:
            pass

        self.title('Wealthsimple Portfolio')
        # Set app icon (best-effort) using bundled logo_victaure.png
        try:
            icon_path = Path(__file__).resolve().parent.parent / 'logo_victaure.png'
            if icon_path.exists():
                try:
                    from PIL import Image, ImageTk  # type: ignore

                    im = Image.open(str(icon_path))
                    im = im.resize((64, 64)) if max(im.size) > 64 else im
                    self._app_icon_img = ImageTk.PhotoImage(im)
                    self.iconphoto(True, self._app_icon_img)  # type: ignore[arg-type]
                except Exception:
                    # Fallback: use tk.PhotoImage if available
                    try:
                        self._app_icon_img = tk.PhotoImage(file=str(icon_path))
                        self.iconphoto(True, self._app_icon_img)
                    except Exception:
                        pass
        except Exception:
            pass
        # Restaurer la géométrie de la fenêtre depuis la configuration
        try:
            self.geometry(app_config.get_window_geometry())
        except Exception:
            self.geometry('1200x780')
        # Sauvegarder la géométrie à la fermeture
        self.protocol('WM_DELETE_WINDOW', self._on_close)

        # Core state
        self.api: WealthsimpleAPI | None = None
        self.accounts: list[dict] = []
        self.current_account_id: str | None = None
        self._positions_cache: list[dict] = []
        self._activities_cache: list[dict] = []
        self.base_currency = 'CAD'

        # Theming / helpers
        self._theme = 'light'
        self._palettes = PALETTES

        # Agents / controllers
        self.agent = AIAgent()
        self.agent_ui = None  # will be set in _build_ui
        self.chart = ChartController(self)
        self.chat_manager = ChatManager(self)
        # Modular managers
        self.export_manager = ExportManager(self)
        self.search_manager = SearchManager(self)
        self.portfolio_manager = PortfolioManager(self)
        self.news_manager = NewsManager(self)

        # External APIs
        self.api_manager = APIManager() if HAS_EXTERNAL_APIS else None

        # Symbol analyzer and media helpers
        self.symbol_analyzer = (
            SymbolAnalyzer(self) if 'SymbolAnalyzer' in globals() and HAS_SYMBOL_ANALYZER else None
        )
        # Media manager: small logos for tables; allow larger ones for detail panes
        try:
            ttl = int(app_config.get('media.cache_ttl_sec', 3600) or 3600)
        except Exception:
            ttl = 3600
        try:
            dpx = int(app_config.get('media.detail_logo_px', 64) or 64)
        except Exception:
            dpx = 64
        self.media = MediaManager(max_logo_px=20, detail_logo_px=dpx, ttl_sec=float(ttl))
        self._logo_images = {}
        self._news_articles = []
        self._news_url_by_iid = {}
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
        # Manual Order vars (for Discover/Search panel)
        self.var_order_symbol = tk.StringVar()
        self.var_order_side = tk.StringVar(value='buy')  # 'buy' | 'sell'
        self.var_order_type = tk.StringVar(
            value='market'
        )  # 'market' | 'limit' | 'stop' | 'stop_limit'
        self.var_order_qty = tk.StringVar()  # optional
        self.var_order_notional = tk.StringVar()  # optional
        self.var_order_limit = tk.StringVar()
        self.var_order_stop = tk.StringVar()
        self.var_order_tif = tk.StringVar(value='day')
        self.var_order_live = tk.BooleanVar(value=False)
        # Panel auto-refresh toggles (persisted)
        try:
            self.var_news_auto = tk.BooleanVar(value=bool(app_config.get('ui.news.auto', False)))
            self.var_news_seconds = tk.IntVar(
                value=int(app_config.get('ui.news.seconds', 120) or 120)
            )
        except Exception:
            self.var_news_auto = tk.BooleanVar(value=False)
            self.var_news_seconds = tk.IntVar(value=120)
        try:
            self.var_movers_auto = tk.BooleanVar(
                value=bool(app_config.get('ui.movers.auto', False))
            )
            self.var_movers_seconds = tk.IntVar(
                value=int(app_config.get('ui.movers.seconds', 120) or 120)
            )
        except Exception:
            self.var_movers_auto = tk.BooleanVar(value=False)
            self.var_movers_seconds = tk.IntVar(value=120)
        try:
            self.var_search_auto = tk.BooleanVar(
                value=bool(app_config.get('ui.search.auto', False))
            )
            self.var_search_seconds = tk.IntVar(
                value=int(app_config.get('ui.search.seconds', 180) or 180)
            )
        except Exception:
            self.var_search_auto = tk.BooleanVar(value=False)
            self.var_search_seconds = tk.IntVar(value=180)
        # Accessibility: font family & size (persisted)
        try:
            self._font_scale = tk.IntVar(
                value=int(app_config.get('ui.font.size', app_config.get('ui.font.size', 10)) or 10)
            )
        except Exception:
            self._font_scale = tk.IntVar(value=10)
        try:
            self._font_family = tk.StringVar(
                value=str(app_config.get('ui.font.family', 'Segoe UI') or 'Segoe UI')
            )
        except Exception:
            self._font_family = tk.StringVar(value='Segoe UI')
        # Vars used by modular managers
        self.var_intraday_symbol = tk.StringVar()
        self.var_search = tk.StringVar()

        # Per-account alerts toggle (persisted)
        self.alert_toggle = tk.BooleanVar(value=True)
        # Initialize technical alerts preference on agent from config
        try:
            self.agent.allow_technical_alerts = bool(
                app_config.get('integrations.telegram.include_technical', True)
            )
        except Exception:
            pass

        # Build UI & attempt auto login
        self._build_ui()
        # Thème initial depuis la configuration
        try:
            pref = str(app_config.get('theme', 'light') or 'light')
            # Support system theme if requested
            if pref == 'system':
                pref = self._detect_system_theme()
            self.apply_theme(pref)
        except Exception:
            self.apply_theme('light')
        # Onboarding (premier démarrage)
        try:
            if not bool(app_config.get('ui.onboarded', False)):
                self._show_banner(
                    "Bienvenue 👋 Astuces: 1) Double-cliquez un symbole pour l'analyser, "
                    "2) Ajustez 'Top N' dans Mouvements, 3) Configurez Telegram dans son onglet.",
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
    # ------------------- Raccourcis clavier & helpers -------------------
    def _bind_shortcuts(self) -> None:
        try:
            # Rafraîchir comptes/positions
            self.bind_all('<F5>', lambda _e: self.refresh_selected_account_details())
            # Basculer thème
            self.bind_all('<Control-t>', lambda _e: self.toggle_theme())
            # Focus filtre rapide Positions
            self.bind_all('<Control-f>', lambda _e: self._focus_positions_filter())
            # Zoom: Ctrl+=, Ctrl++ (some keyboards), Ctrl+- and Ctrl+0 reset
            self.bind_all('<Control-=>', lambda _e: self._zoom_in())
            self.bind_all('<Control-plus>', lambda _e: self._zoom_in())
            self.bind_all('<Control-KP_Add>', lambda _e: self._zoom_in())
            self.bind_all('<Control-minus>', lambda _e: self._zoom_out())
            self.bind_all('<Control-KP_Subtract>', lambda _e: self._zoom_out())
            self.bind_all('<Control-0>', lambda _e: self._zoom_reset())
        except Exception:
            pass

    def _focus_positions_filter(self) -> None:
        try:
            ent = getattr(self, '_ent_pos_quick', None)
            if ent:
                ent.focus_set()
                ent.select_range(0, 'end')
        except Exception:
            pass

    def _zoom_in(self) -> None:
        try:
            cur = int(self._font_scale.get() or 10)
            self._font_scale.set(min(20, cur + 1))
            self._apply_font_size()
        except Exception:
            pass

    def _zoom_out(self) -> None:
        try:
            cur = int(self._font_scale.get() or 10)
            self._font_scale.set(max(8, cur - 1))
            self._apply_font_size()
        except Exception:
            pass

    def _zoom_reset(self) -> None:
        try:
            self._font_scale.set(10)
            self._apply_font_size()
        except Exception:
            pass

    def _show_about_banner(self) -> None:
        try:
            messagebox.showinfo(
                "À propos",
                "WS App\nAméliorations: raccourcis clavier (Ctrl+F/T/+/−/0), zoom, et plus.",
            )
        except Exception:
            pass

    def _build_ui(self):
        # Top-level menu bar (uses ExportManager and helpers)
        try:
            menubar = tk.Menu(self)
            # Fichier
            m_file = tk.Menu(menubar, tearoff=0)
            menubar.add_cascade(label='Fichier', menu=m_file)
            # Lazy-init export manager if not yet
            if not hasattr(self, 'export_manager'):
                self.export_manager = ExportManager(self)  # type: ignore[attr-defined]
            m_file.add_command(
                label='Exporter positions…',
                command=lambda: self.export_manager.export_positions_csv(),
            )
            m_file.add_command(
                label='Exporter activités…',
                command=lambda: self.export_manager.export_activities_csv(),
            )
            m_file.add_command(
                label='Exporter résultats recherche…',
                command=lambda: self.export_manager.export_search_results_csv(),
            )
            m_file.add_separator()
            m_file.add_command(
                label='Rapport de portefeuille…',
                command=lambda: self.export_manager.generate_portfolio_report(),
            )
            m_file.add_separator()
            m_file.add_command(label='Quitter', command=self.destroy)
            # Affichage
            m_view = tk.Menu(menubar, tearoff=0)
            menubar.add_cascade(label='Affichage', menu=m_view)
            m_view.add_command(label='Basculer thème\tCtrl+T', command=self.toggle_theme)
            m_view.add_separator()
            m_view.add_command(label='Zoom +\tCtrl++', command=lambda: self._zoom_in())
            m_view.add_command(label='Zoom −\tCtrl+-', command=lambda: self._zoom_out())
            m_view.add_command(
                label='Réinitialiser zoom\tCtrl+0', command=lambda: self._zoom_reset()
            )
            m_view.add_command(label='Vider les caches', command=self.clear_all_caches)
            # Aide
            m_help = tk.Menu(menubar, tearoff=0)
            menubar.add_cascade(label='Aide', menu=m_help)
            m_help.add_command(label='À propos', command=self._show_about_banner)
            self.config(menu=menubar)
        except Exception:
            pass
        top = ttk.Frame(self)
        top.pack(fill=tk.X, padx=8, pady=4)
        self.btn_connect = ttk.Button(top, text='Se connecter', command=self.open_login_dialog)
        self.btn_connect.grid(row=0, column=0, padx=(0, 6))
        self.var_greeting = tk.StringVar(value='')
        self.lbl_greeting = ttk.Label(top, textvariable=self.var_greeting, foreground='gray')
        self.lbl_greeting.grid(row=0, column=0, padx=(0, 6))
        self.lbl_greeting.grid_remove()
        # Thème déplacé dans Paramètres (bouton supprimé)
        # Insights badge (truncated with click-to-expand)
        self._insights_full = ''
        self.var_insights = tk.StringVar(value='')
        self.lbl_insights = ttk.Label(
            top, textvariable=self.var_insights, foreground='gray', cursor='hand2'
        )
        self.lbl_insights.grid(row=0, column=2, padx=(8, 0))
        self.lbl_insights.bind('<Button-1>', lambda e: self._show_insights_details())
        ttk.Label(self, textvariable=self.var_status, anchor='w').pack(fill=tk.X, padx=8)
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
        _scr = ttk.Scrollbar(
            self._banner_details_frame, orient='vertical', command=self._banner_details_text.yview
        )
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
        self.list_accounts = tk.Listbox(left, height=20, width=32, selectmode=tk.EXTENDED)
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
        ttk.Button(acc_btns, text='Rafraîchir', command=self.refresh_accounts).pack(side=tk.LEFT)
        ttk.Checkbutton(
            acc_btns,
            text='Auto',
            variable=self.auto_refresh,
            command=self.schedule_auto_refresh,
        ).pack(side=tk.LEFT, padx=4)
        ttk.Entry(acc_btns, width=5, textvariable=self.auto_refresh_interval).pack(side=tk.LEFT)
        ttk.Label(acc_btns, text='s').pack(side=tk.LEFT)
        right = ttk.Frame(main)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        filt = ttk.Frame(right)
        filt.pack(fill=tk.X, pady=2)
        ttk.Label(filt, text='Début (YYYY-MM-DD)').grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(filt, width=12, textvariable=self.var_start).grid(row=0, column=1, padx=2)
        ttk.Label(filt, text='Fin').grid(row=0, column=2, sticky=tk.W)
        ttk.Entry(filt, width=12, textvariable=self.var_end).grid(row=0, column=3, padx=2)
        ttk.Label(filt, text='Limite').grid(row=0, column=4, sticky=tk.W)
        ttk.Entry(filt, width=6, textvariable=self.var_limit).grid(row=0, column=5, padx=2)
        ttk.Button(filt, text='Charger', command=self.refresh_selected_account_details).grid(
            row=0, column=6, padx=4
        )
        notebook = ttk.Notebook(right)
        notebook.pack(fill=tk.BOTH, expand=True)
        # Conserver une référence pour persistance d'onglet
        self._main_notebook = notebook
        self._main_notebook.bind('<<NotebookTabChanged>>', self._on_tab_changed)

        # -------- Group 1: Positions + Graphique + Activités --------
        grp1 = ttk.Frame(notebook)
        notebook.add(grp1, text='Portefeuille')
        grp1_nb = ttk.Notebook(grp1)
        grp1_nb.pack(fill=tk.BOTH, expand=True)
        # Persist selection for Group 1 (Portefeuille)
        try:
            self._bind_persist_notebook(grp1_nb, 'portefeuille')
        except Exception:
            pass
        tab_pos = ttk.Frame(grp1_nb)
        grp1_nb.add(tab_pos, text='Positions')

        # Barre d'outils pour l'onglet positions
        pos_toolbar = ttk.Frame(tab_pos)
        pos_toolbar.pack(fill=tk.X, padx=4, pady=2)

        ttk.Label(pos_toolbar, text="Actions:").pack(side=tk.LEFT)
        btn_analyze = ttk.Button(
            pos_toolbar,
            text="📊 Analyser sélection",
            command=self._analyze_selected_symbol,
        )
        btn_analyze.pack(side=tk.LEFT, padx=5)
        attach_tooltip(btn_analyze, "Analyser rapidement le symbole sélectionné avec l'IA")
        btn_quick = ttk.Button(
            pos_toolbar,
            text="📈 Graphique rapide",
            command=self._quick_chart_selected,
        )
        btn_quick.pack(side=tk.LEFT, padx=5)
        attach_tooltip(btn_quick, "Afficher un mini-graph 30–365j pour la sélection")

        # Séparateur
        ttk.Separator(pos_toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, padx=10, fill=tk.Y)

        # Info sur le double-clic
        ttk.Label(
            pos_toolbar,
            text="💡 Double-cliquez sur un symbole pour l'analyser",
            foreground="gray",
        ).pack(side=tk.RIGHT)

        # Filtre rapide au-dessus de la table Positions
        quick_f = ttk.Frame(tab_pos)
        quick_f.pack(fill=tk.X, padx=4, pady=(2, 0))
        ttk.Label(quick_f, text='Filtre rapide:').pack(side=tk.LEFT)
        self.var_pos_quick = tk.StringVar()
        ent_q = ttk.Entry(quick_f, textvariable=self.var_pos_quick, width=20)
        ent_q.pack(side=tk.LEFT, padx=4)
        # Référence pour raccourci Ctrl+F
        self._ent_pos_quick = ent_q
        attach_tooltip(ent_q, "Filtrer les positions (symbole/nom)")
        self.var_pos_quick.trace_add('write', lambda *_: self._apply_positions_quick_filter())

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
        self.tree_positions = ttk.Treeview(tab_pos, columns=cols, show='tree headings')
        # Tree column (#0) will hold symbol text + logo image
        self.tree_positions.heading('#0', text='Symbole')
        self.tree_positions.column('#0', width=110, anchor=tk.W, stretch=False)
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
            # Add sort indicator toggle and callback
            self.tree_positions.heading(
                col,
                text=hdr,
                command=lambda c=col, n=num: self._on_tree_heading_click(self.tree_positions, c, n),
            )
            self.tree_positions.column(col, width=w, anchor=anc, stretch=True)
        # Hide duplicate text 'symbol' column (we show symbol+logo in tree column)
        try:
            self.tree_positions.column('symbol', width=0, minwidth=0, stretch=False)
        except Exception:
            pass
        self.tree_positions.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self._add_tree_context(self.tree_positions)
        # Restore column widths if saved
        try:
            self._restore_tree_layout(self.tree_positions, 'positions')
        except Exception:
            pass

        # Ajout du gestionnaire de double-clic pour les symboles
        self.tree_positions.bind('<Double-1>', self._on_symbol_double_click)
        tab_act = ttk.Frame(grp1_nb)
        grp1_nb.add(tab_act, text='Activités')
        act_bar = ttk.Frame(tab_act)
        act_bar.pack(fill=tk.X, padx=4, pady=2)
        ttk.Label(act_bar, text='Filtre texte:').pack(side=tk.LEFT)
        ttk.Entry(act_bar, textvariable=self.var_act_filter, width=25).pack(side=tk.LEFT, padx=4)
        ttk.Button(act_bar, text='Appliquer', command=self.apply_activity_filter).pack(side=tk.LEFT)
        ttk.Button(
            act_bar,
            text='Réinit',
            command=lambda: (self.var_act_filter.set(''), self.apply_activity_filter()),
        ).pack(side=tk.LEFT, padx=4)
        act_cols = ('date', 'desc', 'amt')
        self.tree_acts = ttk.Treeview(tab_act, columns=act_cols, show='headings')
        headings = {
            'date': ('Date', 155, tk.W, False),
            'desc': ('Description', 480, tk.W, False),
            'amt': ('Montant', 110, tk.E, True),
        }
        for col, (hdr, w, anc, num) in headings.items():
            self.tree_acts.heading(
                col,
                text=hdr,
                command=lambda c=col, n=num: self._on_tree_heading_click(self.tree_acts, c, n),
            )
            self.tree_acts.column(col, width=w, anchor=anc, stretch=True)
        self.tree_acts.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self._add_tree_context(self.tree_acts)
        try:
            self._restore_tree_layout(self.tree_acts, 'activities')
        except Exception:
            pass
        tab_chart = ttk.Frame(grp1_nb)
        grp1_nb.add(tab_chart, text='Graphique')
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
        self._chart_show_grid = tk.BooleanVar(
            value=bool(app_config.get('ui.charts.show_grid', True))
        )
        self._chart_show_sma = tk.BooleanVar(
            value=bool(app_config.get('ui.charts.show_sma', False))
        )
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
            command=lambda: (
                (
                    self.chart.set_options(show_grid=self._chart_show_grid.get()),
                    _persist_chart_prefs(),
                )
                if HAS_MPL
                else _persist_chart_prefs()
            ),
        ).pack(side=tk.LEFT, padx=(8, 2))
        ttk.Checkbutton(
            chart_btns,
            text='SMA',
            variable=self._chart_show_sma,
            command=lambda: (
                (
                    self.chart.set_options(
                        show_sma=self._chart_show_sma.get(), sma_window=self._chart_sma_win.get()
                    ),
                    _persist_chart_prefs(),
                )
                if HAS_MPL
                else _persist_chart_prefs()
            ),
        ).pack(side=tk.LEFT, padx=2)
        ttk.Spinbox(
            chart_btns,
            from_=3,
            to=60,
            width=4,
            textvariable=self._chart_sma_win,
            command=lambda: (
                (
                    self.chart.set_options(sma_window=self._chart_sma_win.get()),
                    _persist_chart_prefs(),
                )
                if HAS_MPL
                else _persist_chart_prefs()
            ),
        ).pack(side=tk.LEFT)
        ttk.Button(chart_btns, text='NLV 30j', command=self.chart.load_nlv_single).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(chart_btns, text='NLV Multi', command=self.chart.load_nlv_multi).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(chart_btns, text='Composition', command=self.chart.load_composition).pack(
            side=tk.LEFT, padx=2
        )
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
            ttk.Label(tab_chart, text='Matplotlib non installé').pack(padx=4, pady=10)
        # -------- Group 2: Actualités + Recherche + Screener + Mouvements --------
        grp2 = ttk.Frame(notebook)
        notebook.add(grp2, text='Marché')
        grp2_nb = ttk.Notebook(grp2)
        grp2_nb.pack(fill=tk.BOTH, expand=True)
        # Persist selection for Group 2 (Marché)
        try:
            self._bind_persist_notebook(grp2_nb, 'marche')
        except Exception:
            pass

        # Placeholders for later tab additions in Group 2
        tab_search_parent = grp2_nb
        tab_mv_parent = grp2_nb
        tab_news_parent = grp2_nb

        # New: Combined discovery tab with Search + Movers + Screener
        try:
            tab_discovery = ttk.Frame(grp2_nb)
            grp2_nb.add(tab_discovery, text='Découverte')
            # Layout: left = Search, right = Movers (top) + Screener (bottom)
            disc_main = ttk.Frame(tab_discovery)
            disc_main.pack(fill=tk.BOTH, expand=True)
            left = ttk.Frame(disc_main)
            left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            right = ttk.Frame(disc_main)
            right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

            # Build Search section (reuse existing widgets bound later in the dedicated tab)
            sr_top = ttk.LabelFrame(left, text='Recherche')
            sr_top.pack(fill=tk.X, padx=4, pady=(4, 2))
            ttk.Label(sr_top, text='Titre / symbole:').pack(side=tk.LEFT)
            # Ensure a single shared query var for both tabs
            if not hasattr(self, 'var_search_query'):
                self.var_search_query = tk.StringVar(
                    value=str(app_config.get('ui.search.last_query', ''))
                )
            self.cb_search2 = ttk.Combobox(
                sr_top,
                textvariable=self.var_search_query,
                width=28,
                values=(
                    (app_config.get('ui.search.recent', []) or [])
                    if isinstance(app_config.get('ui.search.recent', []), list)
                    else []
                ),
            )
            self.cb_search2.pack(side=tk.LEFT, padx=4)
            self.lst_search_suggestions2 = tk.Listbox(sr_top, height=4)
            self.lst_search_suggestions2.bind(
                '<<ListboxSelect>>', lambda _e: self._apply_search_suggestion()
            )

            def _on_search_query_change(*_):
                try:
                    app_config.set(
                        'ui.search.last_query', (self.var_search_query.get() or '').strip()
                    )
                    q = (self.var_search_query.get() or '').strip()
                    if q:
                        lst = app_config.get('ui.search.recent', []) or []
                        if not isinstance(lst, list):
                            lst = []
                        if q in lst:
                            lst.remove(q)
                        lst.insert(0, q)
                        app_config.set('ui.search.recent', lst[:10])
                        try:
                            # Update both combo values if present
                            if hasattr(self, 'cb_search'):
                                self.cb_search.configure(values=lst[:10])
                            if hasattr(self, 'cb_search2'):
                                self.cb_search2.configure(values=lst[:10])
                        except Exception:
                            pass
                except Exception:
                    pass
                try:
                    self._update_search_suggestions()
                except Exception:
                    pass

            self.var_search_query.trace_add('write', _on_search_query_change)
            ttk.Button(sr_top, text='Chercher', command=self.search_securities).pack(side=tk.LEFT)
            # Results tree
            self.tree_search2 = ttk.Treeview(
                left,
                columns=('symbol', 'name', 'exchange', 'status', 'buyable', 'market'),
                show='tree headings',
                height=10,
            )
            self.tree_search2.heading('#0', text='Symbole')
            self.tree_search2.column('#0', width=90, anchor=tk.W, stretch=False)
            for col, (hdr, w, anc, num) in {
                'symbol': ('Symbole', 90, tk.W, False),
                'name': ('Nom', 200, tk.W, False),
                'exchange': ('Échange', 80, tk.W, False),
                'status': ('Statut', 70, tk.W, False),
                'buyable': ('Achetable', 70, tk.W, False),
                'market': ('Marché', 80, tk.W, False),
            }.items():
                self.tree_search2.heading(
                    col,
                    text=hdr,
                    command=lambda c=col, n=num: self._on_tree_heading_click(
                        self.tree_search2, c, n
                    ),
                )
                self.tree_search2.column(col, width=w, anchor=anc, stretch=True)
            try:
                self.tree_search2.column('symbol', width=0, minwidth=0, stretch=False)
            except Exception:
                pass
            self.tree_search2.pack(fill=tk.BOTH, expand=True, padx=4, pady=2)
            self._add_tree_context(self.tree_search2)
            self.tree_search2.bind(
                '<Double-1>', lambda _e: self._open_search_from_tree(self.tree_search2)
            )
            # Details under search
            sr_details = ttk.LabelFrame(left, text='Détails')
            sr_details.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
            logo_frame = ttk.Frame(sr_details)
            logo_frame.pack(fill=tk.X, padx=2, pady=(2, 0))
            self.lbl_search_logo2 = ttk.Label(logo_frame, text='[Logo]')
            self.lbl_search_logo2.pack(side=tk.LEFT, padx=(2, 10))
            self.txt_search_details2 = tk.Text(sr_details, height=6, wrap='word')
            self.txt_search_details2.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
            self.txt_search_details2.configure(state=tk.DISABLED)
            if not hasattr(self, '_search_results'):
                self._search_results = []
            try:
                self.text_search_details2 = self.txt_search_details2  # compat
                self.var_search = self.var_search_query  # align naming
            except Exception:
                pass

            # Manual Order Panel (compact)
            try:
                ord_frame = ttk.LabelFrame(left, text='Ordre')
                ord_frame.pack(fill=tk.X, padx=4, pady=(0, 4))
                # Row 0: symbol + side + type
                ttk.Label(ord_frame, text='Symbole:').grid(row=0, column=0, sticky=tk.W)
                self.ent_order_symbol = ttk.Entry(
                    ord_frame, width=10, textvariable=self.var_order_symbol
                )
                self.ent_order_symbol.grid(row=0, column=1, padx=2)
                ttk.Label(ord_frame, text='Côté:').grid(row=0, column=2, sticky=tk.W)
                cb_side = ttk.Combobox(
                    ord_frame,
                    width=6,
                    state='readonly',
                    textvariable=self.var_order_side,
                    values=['buy', 'sell'],
                )
                cb_side.grid(row=0, column=3, padx=2)
                ttk.Label(ord_frame, text='Type:').grid(row=0, column=4, sticky=tk.W)
                self.cb_order_type = ttk.Combobox(
                    ord_frame,
                    width=10,
                    state='readonly',
                    textvariable=self.var_order_type,
                    values=['market', 'limit', 'stop', 'stop_limit'],
                )
                self.cb_order_type.grid(row=0, column=5, padx=2)

                # Row 1: qty / notional
                ttk.Label(ord_frame, text='Qté:').grid(row=1, column=0, sticky=tk.W)
                ttk.Entry(ord_frame, width=8, textvariable=self.var_order_qty).grid(
                    row=1, column=1, padx=2
                )
                ttk.Label(ord_frame, text='Notionnel:').grid(row=1, column=2, sticky=tk.W)
                ttk.Entry(ord_frame, width=10, textvariable=self.var_order_notional).grid(
                    row=1, column=3, padx=2
                )
                ttk.Label(ord_frame, text='TIF:').grid(row=1, column=4, sticky=tk.W)
                cb_tif = ttk.Combobox(
                    ord_frame,
                    width=8,
                    state='readonly',
                    textvariable=self.var_order_tif,
                    values=['day', 'gtc'],
                )
                cb_tif.grid(row=1, column=5, padx=2)

                # Row 2: prices + mode
                ttk.Label(ord_frame, text='Limite:').grid(row=2, column=0, sticky=tk.W)
                self.ent_order_limit = ttk.Entry(
                    ord_frame, width=8, textvariable=self.var_order_limit
                )
                self.ent_order_limit.grid(row=2, column=1, padx=2)
                ttk.Label(ord_frame, text='Stop:').grid(row=2, column=2, sticky=tk.W)
                self.ent_order_stop = ttk.Entry(
                    ord_frame, width=8, textvariable=self.var_order_stop
                )
                self.ent_order_stop.grid(row=2, column=3, padx=2)
                self.chk_order_live = ttk.Checkbutton(
                    ord_frame, text='Live', variable=self.var_order_live
                )
                self.chk_order_live.grid(row=2, column=4, sticky=tk.W)
                btn_send = ttk.Button(ord_frame, text='Envoyer', command=self._submit_manual_order)
                btn_send.grid(row=2, column=5, padx=2, pady=2)

                # Behaviors
                def _order_type_changed(_e=None):
                    self._update_order_form_state()

                self.cb_order_type.bind('<<ComboboxSelected>>', _order_type_changed)
                self._update_order_form_state()
            except Exception:
                pass

            # Movers (top-right)
            mv_ctrl = ttk.LabelFrame(right, text='Mouvements')
            mv_ctrl.pack(fill=tk.X, padx=4, pady=(4, 2))
            ttk.Label(mv_ctrl, text='Top N:').pack(side=tk.LEFT)
            self.var_movers_topn = tk.IntVar(value=int(app_config.get('ui.movers.top_n', 5)))

            def _persist_movers_topn():
                try:
                    n = max(1, int(self.var_movers_topn.get() or 5))
                except Exception:
                    n = 5
                app_config.set('ui.movers.top_n', int(n))
                try:
                    self.update_movers(int(n))
                except Exception:
                    pass

            ttk.Spinbox(
                mv_ctrl,
                from_=1,
                to=25,
                width=4,
                textvariable=self.var_movers_topn,
                command=_persist_movers_topn,
            ).pack(side=tk.LEFT, padx=(2, 8))
            ttk.Button(mv_ctrl, text='Rafraîchir', command=self.update_movers).pack(side=tk.LEFT)
            # Two columns: Gagnants/Perdants lists (compact)
            mv_lists = ttk.Frame(right)
            mv_lists.pack(fill=tk.BOTH, expand=True, padx=4, pady=2)
            frm_g = ttk.Labelframe(mv_lists, text='Gagnants')
            frm_g.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 2))
            self.tree_gainers_compact = ttk.Treeview(
                frm_g,
                columns=('symbol', 'chg', 'price', 'vol'),
                show='headings',
                height=8,
            )
            for c, (h, w, a, n) in {
                'symbol': ('Symb', 80, tk.W, False),
                'chg': ('%Chg', 60, tk.E, True),
                'price': ('Prix', 70, tk.E, True),
                'vol': ('Vol', 80, tk.E, True),
            }.items():
                self.tree_gainers_compact.heading(
                    c,
                    text=h,
                    command=lambda col=c, nn=n: self._on_tree_heading_click(
                        self.tree_gainers_compact, col, nn
                    ),
                )
                self.tree_gainers_compact.column(c, width=w, anchor=a, stretch=True)
            self.tree_gainers_compact.pack(fill=tk.BOTH, expand=True)
            frm_l = ttk.Labelframe(mv_lists, text='Perdants')
            frm_l.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(2, 0))
            self.tree_losers_compact = ttk.Treeview(
                frm_l,
                columns=('symbol', 'chg', 'price', 'vol'),
                show='headings',
                height=8,
            )
            for c, (h, w, a, n) in {
                'symbol': ('Symb', 80, tk.W, False),
                'chg': ('%Chg', 60, tk.E, True),
                'price': ('Prix', 70, tk.E, True),
                'vol': ('Vol', 80, tk.E, True),
            }.items():
                self.tree_losers_compact.heading(
                    c,
                    text=h,
                    command=lambda col=c, nn=n: self._on_tree_heading_click(
                        self.tree_losers_compact, col, nn
                    ),
                )
                self.tree_losers_compact.column(c, width=w, anchor=a, stretch=True)
            self.tree_losers_compact.pack(fill=tk.BOTH, expand=True)

            # Compact Screener (bottom-right)
            try:
                self.screener = ScreenerPanel(self)
                scr_frame = ttk.Labelframe(right, text='Screener & Signaux')
                scr_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=(2, 4))
                self.screener.build_compact(scr_frame)
            except Exception:
                pass
        except Exception:
            pass

        # -------- Group 3: Backtest + Stratégies + Signaux + Diagnostics --------
        grp3 = ttk.Frame(notebook)
        notebook.add(grp3, text='Analyse')
        grp3_nb = ttk.Notebook(grp3)
        grp3_nb.pack(fill=tk.BOTH, expand=True)
        # Persist selection for Group 3 (Analyse)
        try:
            self._bind_persist_notebook(grp3_nb, 'analyse')
        except Exception:
            pass
        # --- Onglet Diagnostics ---
        self.diagnostics = DiagnosticsPanel(self)
        self.diagnostics.build(grp3_nb)
        # --- Onglet Screener ---
        try:
            self.screener = ScreenerPanel(self)
            self.screener.build(grp2_nb)
        except Exception:
            pass
        # --- Onglet Backtest ---
        try:
            self.backtest = BacktestPanel(self)
            self.backtest.build(grp3_nb)
        except Exception:
            pass
        # --- Onglet Stratégies (Runner) ---
        self._build_strategy_tab(grp3_nb)
        # --- Onglet Signaux IA ---
        tab_signals = ttk.Frame(grp3_nb)
        grp3_nb.add(tab_signals, text='Signaux')
        top_ai = ttk.Frame(tab_signals)
        top_ai.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        # Filters and quick actions
        ai_controls = ttk.Frame(top_ai)
        ai_controls.pack(fill=tk.X, padx=0, pady=(0, 4))
        ttk.Label(ai_controls, text='Filtre:').pack(side=tk.LEFT)
        self.var_ai_level = tk.StringVar(value='ALL')
        cb_ai = ttk.Combobox(
            ai_controls,
            state='readonly',
            width=8,
            textvariable=self.var_ai_level,
            values=['ALL', 'INFO', 'WARN', 'ALERT'],
        )
        cb_ai.pack(side=tk.LEFT, padx=(4, 8))
        cb_ai.bind('<<ComboboxSelected>>', lambda _e: self._refresh_ai_signals())
        ttk.Button(
            ai_controls, text='Paper BUY', command=lambda: self._ai_signal_trade('buy')
        ).pack(side=tk.LEFT)
        ttk.Button(
            ai_controls, text='Paper SELL', command=lambda: self._ai_signal_trade('sell')
        ).pack(side=tk.LEFT, padx=(4, 0))
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
        # Ensure non-empty state initially
        try:
            if not self.tree_signals.get_children():
                self.tree_signals.insert(
                    '', tk.END, values=('—', '', '', '', 'Aucun signal'), tags=('even',)
                )
        except Exception:
            pass

        # --- Onglet Chat IA (top-level) ---
        tab_chat = ttk.Frame(notebook)
        notebook.add(tab_chat, text='Chat')
        chat_bar = ttk.Frame(tab_chat)
        chat_bar.pack(fill=tk.X, padx=8, pady=(6, 2))
        ttk.Label(chat_bar, text='Chat:').pack(side=tk.LEFT)
        # Champ de saisie du chat (garder une référence pour binding clavier)
        self.ent_chat = ttk.Entry(chat_bar, textvariable=self.var_chat, width=60)
        self.ent_chat.pack(side=tk.LEFT, padx=6)
        # Placeholder léger
        self._chat_placeholder = "Posez une question…"
        if not (self.var_chat.get() or '').strip():
            try:
                self.var_chat.set(self._chat_placeholder)
                self._chat_placeholder_active = True
            except Exception:
                self._chat_placeholder_active = False
        else:
            self._chat_placeholder_active = False
        # Envoi avec Entrée + raccourcis utiles
        self.ent_chat.bind('<Return>', lambda _e: self.chat_manager._chat_send())
        self.ent_chat.bind('<Control-Return>', lambda _e: self.chat_manager._chat_send())
        self.ent_chat.bind('<Up>', self.chat_manager.history_prev)
        self.ent_chat.bind('<Down>', self.chat_manager.history_next)
        self.ent_chat.bind('<Control-k>', self.chat_manager.clear_entry)
        self.ent_chat.bind('<FocusIn>', self._on_chat_focus_in)
        self.ent_chat.bind('<FocusOut>', self._on_chat_focus_out)
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
        # Quick prompts for chat improvements
        ttk.Button(
            chat_bar,
            text='📈 Movers',
            command=lambda: self._append_chat(self.agent.chat('movers') + "\n"),
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(
            chat_bar,
            text='💡 Insights',
            command=lambda: self._append_chat(self.agent.chat('insights') + "\n"),
        ).pack(side=tk.LEFT, padx=2)
        # Astuce d'utilisation
        ttk.Label(
            tab_chat,
            text="Astuce: Entrée pour envoyer • Ctrl+Entrée aussi • ↑/↓ pour l'historique • "
                 "Ctrl+K pour effacer",
            foreground='gray',
        ).pack(fill=tk.X, padx=8)
        # Séparateur discret entre l'entrée et l'historique
        ttk.Separator(tab_chat, orient='horizontal').pack(fill=tk.X, padx=8, pady=(2, 4))
        self.txt_chat = tk.Text(tab_chat, height=12, wrap='word')
        self.txt_chat.pack(fill=tk.BOTH, expand=True, padx=8, pady=6)
        # Configurer les tags pour styliser l'horodatage et les locuteurs
        try:
            self.txt_chat.tag_config('ts', foreground='gray')
            self.txt_chat.tag_config('speaker_user', font=('TkDefaultFont', 9, 'bold'))
            self.txt_chat.tag_config(
                'speaker_agent', foreground='#1f6feb', font=('TkDefaultFont', 9, 'bold')
            )
        except Exception:
            pass
        self.txt_chat.configure(state=tk.DISABLED)
        # Statut du chat (affiche "Réponse en cours…")
        self.lbl_chat_status = ttk.Label(tab_chat, text='', foreground='gray')
        self.lbl_chat_status.pack(fill=tk.X, padx=8, pady=(0, 6))

        # --- Onglet Recherche titres (Group 2) ---
        tab_search = ttk.Frame(tab_search_parent)
        tab_search_parent.add(tab_search, text='Recherche')
        sr_top = ttk.Frame(tab_search)
        sr_top.pack(fill=tk.X, padx=4, pady=4)
        ttk.Label(sr_top, text='Titre / symbole:').pack(side=tk.LEFT)
        # Rechercher: restaurer la dernière requête
        self.var_search_query = tk.StringVar(value=str(app_config.get('ui.search.last_query', '')))
        # Historique de recherche (combobox)
        try:
            recent = app_config.get('ui.search.recent', []) or []
            if not isinstance(recent, list):
                recent = []
        except Exception:
            recent = []
        self.cb_search = ttk.Combobox(
            sr_top, textvariable=self.var_search_query, width=30, values=recent
        )
        self.cb_search.pack(side=tk.LEFT, padx=4)
        # Liste déroulante de suggestions (apparait dynamiquement)
        self.lst_search_suggestions = tk.Listbox(sr_top, height=4)
        self.lst_search_suggestions.bind(
            '<<ListboxSelect>>', lambda _e: self._apply_search_suggestion()
        )

        # Mise à jour suggestions + persistance de la requête
        def _on_search_query_change(*_):  # noqa
            try:
                app_config.set('ui.search.last_query', (self.var_search_query.get() or '').strip())
                q = (self.var_search_query.get() or '').strip()
                if q:
                    lst = app_config.get('ui.search.recent', []) or []
                    if not isinstance(lst, list):
                        lst = []
                    if q in lst:
                        lst.remove(q)
                    lst.insert(0, q)
                    app_config.set('ui.search.recent', lst[:10])
                    try:
                        self.cb_search.configure(values=lst[:10])
                    except Exception:
                        pass
            except Exception:
                pass
            self._update_search_suggestions()

        self.var_search_query.trace_add('write', _on_search_query_change)
        ttk.Button(sr_top, text='Chercher', command=self.search_securities).pack(side=tk.LEFT)
        # Auto-refresh controls (Search)
        chk_sa = ttk.Checkbutton(
            sr_top, text='Auto', variable=self.var_search_auto, command=self._schedule_search_auto
        )
        chk_sa.pack(side=tk.LEFT, padx=(8, 2))
        sp_sa = ttk.Spinbox(
            sr_top,
            from_=30,
            to=3600,
            width=5,
            textvariable=self.var_search_seconds,
            command=self._schedule_search_auto,
        )
        sp_sa.pack(side=tk.LEFT)
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
            show='tree headings',
            height=12,
        )
        # Tree column for symbol+logo
        self.tree_search.heading('#0', text='Symbole')
        self.tree_search.column('#0', width=100, anchor=tk.W, stretch=False)
        headers_search = {
            'symbol': ('Symbole', 90, tk.W, False),
            'name': ('Nom', 220, tk.W, False),
            'exchange': ('Échange', 80, tk.W, False),
            'status': ('Statut', 70, tk.W, False),
            'buyable': ('Achetable', 70, tk.W, False),
            'market': ('Marché', 80, tk.W, False),
        }
        for col, (hdr, w, anc, num) in headers_search.items():
            self.tree_search.heading(
                col,
                text=hdr,
                command=lambda c=col, n=num: self._on_tree_heading_click(self.tree_search, c, n),
            )
            self.tree_search.column(col, width=w, anchor=anc, stretch=True)
        # Hide duplicate 'symbol' column
        try:
            self.tree_search.column('symbol', width=0, minwidth=0, stretch=False)
        except Exception:
            pass
        self.tree_search.pack(fill=tk.BOTH, expand=True, padx=4, pady=2)
        self._add_tree_context(self.tree_search)
        try:
            self._restore_tree_layout(self.tree_search, 'search')
        except Exception:
            pass
        # Placeholder to avoid empty table on first load
        try:
            if not self.tree_search.get_children():
                self.tree_search.insert(
                    '',
                    tk.END,
                    text='—',
                    values=('—', 'Aucun résultat', '', '', '', ''),
                    tags=('even',),
                )
        except Exception:
            pass
        self.tree_search.bind('<Double-1>', lambda _e: self.open_search_security_details())
        sr_details = ttk.LabelFrame(tab_search, text='Détails')
        sr_details.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        logo_frame = ttk.Frame(sr_details)
        logo_frame.pack(fill=tk.X, padx=2, pady=(2, 0))
        self.lbl_search_logo = ttk.Label(logo_frame, text='[Logo]')
        self.lbl_search_logo.pack(side=tk.LEFT, padx=(2, 10))
        self.txt_search_details = tk.Text(sr_details, height=8, wrap='word')
        self.txt_search_details.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        self.txt_search_details.configure(state=tk.DISABLED)
        self._search_results = []  # stocke dicts résultats
        # Alias for modular manager compatibility
        try:
            self.text_search_details = self.txt_search_details  # type: ignore[attr-defined]
            # Align var name used by SearchManager to existing query var
            self.var_search = self.var_search_query  # type: ignore[assignment]
        except Exception:
            pass

        # --- Onglet Mouvements (Group 2) ---
        tab_mv = ttk.Frame(tab_mv_parent)
        tab_mv_parent.add(tab_mv, text='Mouvements')
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
        # Auto-refresh controls (Movers)
        ttk.Checkbutton(
            mv_ctrl, text='Auto', variable=self.var_movers_auto, command=self._schedule_movers_auto
        ).pack(side=tk.LEFT, padx=(10, 2))
        ttk.Spinbox(
            mv_ctrl,
            from_=30,
            to=3600,
            width=5,
            textvariable=self.var_movers_seconds,
            command=self._schedule_movers_auto,
        ).pack(side=tk.LEFT)
        mv_top = ttk.Frame(tab_mv)
        mv_top.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        # Gagnants
        frm_g = ttk.Labelframe(mv_top, text='Gagnants')
        frm_g.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=2, pady=2)
        self.tree_gainers = ttk.Treeview(
            frm_g,
            columns=('symbol', 'pnlpct', 'pnlabs', 'value', 'qty'),
            show='tree headings',
            height=8,
        )
        self.tree_gainers.heading('#0', text='Symb')
        self.tree_gainers.column('#0', width=90, anchor=tk.W, stretch=False)
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
                command=lambda col=c, n=num: self._on_tree_heading_click(self.tree_gainers, col, n),
            )
            self.tree_gainers.column(c, width=w, anchor=a, stretch=True)
        try:
            self.tree_gainers.column('symbol', width=0, minwidth=0, stretch=False)
        except Exception:
            pass
        self.tree_gainers.pack(fill=tk.BOTH, expand=True)
        self._add_tree_context(self.tree_gainers)
        try:
            self._restore_tree_layout(self.tree_gainers, 'gainers')
        except Exception:
            pass
        try:
            if not self.tree_gainers.get_children():
                self.tree_gainers.insert(
                    '', tk.END, text='—', values=('—', '', '', '', ''), tags=('even',)
                )
        except Exception:
            pass
        # Perdants
        frm_l = ttk.Labelframe(mv_top, text='Perdants')
        frm_l.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=2, pady=2)
        self.tree_losers = ttk.Treeview(
            frm_l,
            columns=('symbol', 'pnlpct', 'pnlabs', 'value', 'qty'),
            show='tree headings',
            height=8,
        )
        self.tree_losers.heading('#0', text='Symb')
        self.tree_losers.column('#0', width=90, anchor=tk.W, stretch=False)
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
                command=lambda col=c, n=num: self._on_tree_heading_click(self.tree_losers, col, n),
            )
            self.tree_losers.column(c, width=w, anchor=a, stretch=True)
        try:
            self.tree_losers.column('symbol', width=0, minwidth=0, stretch=False)
        except Exception:
            pass
        self.tree_losers.pack(fill=tk.BOTH, expand=True)
        self._add_tree_context(self.tree_losers)
        try:
            self._restore_tree_layout(self.tree_losers, 'losers')
        except Exception:
            pass
        try:
            if not self.tree_losers.get_children():
                self.tree_losers.insert(
                    '', tk.END, text='—', values=('—', '', '', '', ''), tags=('even',)
                )
        except Exception:
            pass
        # Actifs (par valeur)
        mv_bottom = ttk.Frame(tab_mv)
        mv_bottom.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        frm_a = ttk.Labelframe(mv_bottom, text='Plus actifs (valeur)')
        frm_a.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=2, pady=2)
        self.tree_active = ttk.Treeview(
            frm_a,
            columns=('symbol', 'value', 'pnlpct', 'pnlabs', 'qty'),
            show='tree headings',
            height=8,
        )
        self.tree_active.heading('#0', text='Symb')
        self.tree_active.column('#0', width=90, anchor=tk.W, stretch=False)
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
                command=lambda col=c, n=num: self._on_tree_heading_click(self.tree_active, col, n),
            )
            self.tree_active.column(c, width=w, anchor=a, stretch=True)
        try:
            self.tree_active.column('symbol', width=0, minwidth=0, stretch=False)
        except Exception:
            pass
        self.tree_active.pack(fill=tk.BOTH, expand=True)
        self._add_tree_context(self.tree_active)
        try:
            self._restore_tree_layout(self.tree_active, 'active')
        except Exception:
            pass
        try:
            if not self.tree_active.get_children():
                self.tree_active.insert(
                    '', tk.END, text='—', values=('—', '', '', '', ''), tags=('even',)
                )
        except Exception:
            pass
        # Opportunités (heuristique: grosses baisses)
        frm_o = ttk.Labelframe(mv_bottom, text='Opportunités (baisses)')
        frm_o.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=2, pady=2)
        self.tree_opps = ttk.Treeview(
            frm_o,
            columns=('symbol', 'pnlpct', 'pnlabs', 'value', 'qty'),
            show='tree headings',
            height=8,
        )
        self.tree_opps.heading('#0', text='Symb')
        self.tree_opps.column('#0', width=90, anchor=tk.W, stretch=False)
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
                command=lambda col=c, n=num: self._on_tree_heading_click(self.tree_opps, col, n),
            )
            self.tree_opps.column(c, width=w, anchor=a, stretch=True)
        try:
            self.tree_opps.column('symbol', width=0, minwidth=0, stretch=False)
        except Exception:
            pass
        self.tree_opps.pack(fill=tk.BOTH, expand=True)
        self._add_tree_context(self.tree_opps)
        try:
            self._restore_tree_layout(self.tree_opps, 'opps')
        except Exception:
            pass
        try:
            if not self.tree_opps.get_children():
                self.tree_opps.insert(
                    '', tk.END, text='—', values=('—', '', '', '', ''), tags=('even',)
                )
        except Exception:
            pass

        # --- Onglet Actualités (Group 2) ---
        tab_news = ttk.Frame(tab_news_parent)
        tab_news_parent.add(tab_news, text='Actualités')

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
                app_config.set('ui.news.last_query', (self.var_news_query.get() or '').strip())
            except Exception:
                pass

        self.var_news_query.trace_add('write', _persist_news)
        ttk.Entry(news_top, textvariable=self.var_news_query, width=25).pack(side=tk.LEFT, padx=4)
        ttk.Button(news_top, text='Actualiser', command=self.refresh_news).pack(side=tk.LEFT)
        ttk.Button(news_top, text='Aperçu marché', command=self.refresh_market_overview).pack(
            side=tk.LEFT, padx=4
        )
        if HAS_EXTERNAL_APIS:
            ttk.Button(news_top, text='📱 Notifier', command=self.send_portfolio_notification).pack(
                side=tk.LEFT, padx=4
            )
        # Auto-refresh controls (News)
        ttk.Checkbutton(
            news_top, text='Auto', variable=self.var_news_auto, command=self._schedule_news_auto
        ).pack(side=tk.LEFT, padx=(10, 2))
        ttk.Spinbox(
            news_top,
            from_=30,
            to=3600,
            width=5,
            textvariable=self.var_news_seconds,
            command=self._schedule_news_auto,
        ).pack(side=tk.LEFT)

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
            self.tree_news.heading(
                c,
                text=h,
                command=lambda col=c: self._on_tree_heading_click(
                    self.tree_news, col, numeric=False
                ),
            )
            self.tree_news.column(c, width=w, anchor=a, stretch=True)
        self.tree_news.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self.tree_news.bind('<Double-1>', self.on_news_double_click)
        self._add_tree_context(self.tree_news)
        try:
            self._restore_tree_layout(self.tree_news, 'news')
        except Exception:
            pass

        # Schedule panel auto-refresh if enabled
        try:
            self._schedule_news_auto()
            self._schedule_movers_auto()
            self._schedule_search_auto()
            # Auto-load news once on startup for convenience
            if not getattr(self, '_news_loaded_once', False):
                self._news_loaded_once = True
                self.refresh_news()
        except Exception:
            pass

        # Zone de détails pour les articles
        self.txt_news_details = tk.Text(tab_news, height=6, wrap='word')
        self.txt_news_details.pack(fill=tk.X, padx=4, pady=4)
        self.txt_news_details.configure(state=tk.DISABLED)

        # Output and progress at bottom of main right area
        self.txt_output = tk.Text(right, height=4, wrap='word')
        self.txt_output.pack(fill=tk.X, padx=2, pady=2)
        self.txt_output.configure(state=tk.DISABLED)
        self.progress = ttk.Progressbar(self, mode='indeterminate')
        self.progress.pack(fill=tk.X, side=tk.BOTTOM)

        # Raccourcis clavier globaux
        try:
            self._bind_shortcuts()
        except Exception:
            pass

        # ---- Onglet Paramètres (top-level) ----
        tab_settings = ttk.Frame(notebook)
        notebook.add(tab_settings, text='Paramètres')

        # Section Profil
        frm_profile = ttk.LabelFrame(tab_settings, text='Profil')
        frm_profile.pack(fill=tk.X, padx=6, pady=6)
        self._var_prof_name = tk.StringVar(value='Non connecté')
        self._var_prof_email = tk.StringVar(value='')
        ttk.Label(frm_profile, text='Nom:').pack(side=tk.LEFT, padx=(6, 2))
        ttk.Label(frm_profile, textvariable=self._var_prof_name).pack(side=tk.LEFT)
        ttk.Label(frm_profile, text='  Email:').pack(side=tk.LEFT, padx=(12, 2))
        ttk.Label(frm_profile, textvariable=self._var_prof_email).pack(side=tk.LEFT)

        # Section Apparence
        frm_theme = ttk.LabelFrame(tab_settings, text='Apparence')
        frm_theme.pack(fill=tk.X, padx=6, pady=(0, 6))
        ttk.Label(frm_theme, text='Thème:').pack(side=tk.LEFT, padx=(6, 2))
        self._var_theme_choice = tk.StringVar(value=self._theme)

        def _on_theme_choice():
            try:
                choice = self._var_theme_choice.get()
                if choice == 'system':
                    choice = self._detect_system_theme()
                self.apply_theme(choice)
            except Exception:
                pass

        ttk.Radiobutton(
            frm_theme,
            text='Clair',
            value='light',
            variable=self._var_theme_choice,
            command=_on_theme_choice,
        ).pack(side=tk.LEFT)
        ttk.Radiobutton(
            frm_theme,
            text='Sombre',
            value='dark',
            variable=self._var_theme_choice,
            command=_on_theme_choice,
        ).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Radiobutton(
            frm_theme,
            text='Contraste élevé',
            value='high',
            variable=self._var_theme_choice,
            command=_on_theme_choice,
        ).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Radiobutton(
            frm_theme,
            text='Système',
            value='system',
            variable=self._var_theme_choice,
            command=_on_theme_choice,
        ).pack(side=tk.LEFT, padx=(6, 0))

        # Aide sur les thèmes (en dessous de la ligne d'options)
        try:
            ttk.Label(
                frm_theme,
                text="Conseil: 'Système' suit le thème Windows. Raccourci: Ctrl+T pour basculer.",
                style='Muted.TLabel',
                anchor='w',
            ).pack(fill=tk.X, padx=6, pady=(4, 0))
        except Exception:
            pass

        # Font family & size
        ttk.Label(frm_theme, text='  Police:').pack(side=tk.LEFT, padx=(12, 2))
        try:
            import tkinter.font as tkfont

            families = sorted(set(tkfont.families()))
        except Exception:
            families = ['Segoe UI', 'Arial', 'Calibri', 'Sans']
        cmb_font = ttk.Combobox(
            frm_theme, values=families, width=16, textvariable=self._font_family, state='readonly'
        )
        cmb_font.pack(side=tk.LEFT)
        cmb_font.bind('<<ComboboxSelected>>', lambda _e: self._apply_font_size())
        ttk.Label(frm_theme, text='  Taille:').pack(side=tk.LEFT, padx=(8, 2))
        spn_font = ttk.Spinbox(
            frm_theme,
            from_=8,
            to=20,
            width=3,
            textvariable=self._font_scale,
            command=self._apply_font_size,
        )
        spn_font.pack(side=tk.LEFT)
        attach_tooltip(spn_font, "Ajuster la taille de police de l'interface")

        # Media settings (logo size & cache TTL)
        frm_media = ttk.LabelFrame(tab_settings, text='Média (logos & images)')
        frm_media.pack(fill=tk.X, padx=6, pady=(0, 6))
        try:
            _ttl = int(app_config.get('media.cache_ttl_sec', 3600) or 3600)
        except Exception:
            _ttl = 3600
        try:
            _dpx = int(app_config.get('media.detail_logo_px', 64) or 64)
        except Exception:
            _dpx = 64
        self.var_media_ttl = tk.IntVar(value=_ttl)
        self.var_media_dpx = tk.IntVar(value=_dpx)

        def _apply_media_settings():
            try:
                ttl = max(0, int(self.var_media_ttl.get()))
                dpx = max(16, int(self.var_media_dpx.get()))
                app_config.set('media.cache_ttl_sec', ttl)
                app_config.set('media.detail_logo_px', dpx)
                # Apply live
                try:
                    self.media.set_ttl(float(ttl))
                except Exception:
                    pass
                try:
                    self.media.set_detail_logo_px(int(dpx))
                except Exception:
                    pass
            except Exception:
                pass

        ttk.Label(frm_media, text='TTL cache (s):').pack(side=tk.LEFT, padx=(6, 2))
        ttk.Spinbox(
            frm_media,
            from_=0,
            to=86400,
            width=8,
            textvariable=self.var_media_ttl,
            command=_apply_media_settings,
        ).pack(side=tk.LEFT)
        ttk.Label(frm_media, text='  Logo détail (px):').pack(side=tk.LEFT, padx=(8, 2))
        ttk.Spinbox(
            frm_media,
            from_=16,
            to=256,
            width=5,
            textvariable=self.var_media_dpx,
            command=_apply_media_settings,
        ).pack(side=tk.LEFT)

        # Section Session
        frm_session = ttk.LabelFrame(tab_settings, text='Session')
        frm_session.pack(fill=tk.X, padx=6, pady=(0, 6))
        ttk.Button(frm_session, text='Se déconnecter', command=self._logout).pack(
            side=tk.LEFT, padx=6, pady=4
        )

        # Section Intégrations (Telegram)
        frm_integr = ttk.LabelFrame(tab_settings, text='Intégrations')
        frm_integr.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 6))
        integ_nb = ttk.Notebook(frm_integr)
        integ_nb.pack(fill=tk.BOTH, expand=True)
        # Persist selection for Integrations
        try:
            self._bind_persist_notebook(integ_nb, 'integrations')
        except Exception:
            pass
        if HAS_EXTERNAL_APIS:
            from .telegram_ui import TelegramUI

            self._telegram_ui = TelegramUI(
                parent=integ_nb,
                api_manager=self.api_manager,
                agent=self.agent,
                start_cb=self._start_telegram_bridge,
                stop_cb=self._stop_telegram_bridge,
                test_cb=self._send_test_tg_message,
            )
            self._telegram_ui.render()
            # Expose chat var for bridge compat
            try:
                self.var_tg_chat = self._telegram_ui.var_tg_chat  # type: ignore[attr-defined]
            except Exception:
                pass

        # Restaurer les sous-onglets (groupes) si disponibles
        try:
            self._restore_notebook_tab(grp1_nb, 'portefeuille')
            self._restore_notebook_tab(grp2_nb, 'marche')
            self._restore_notebook_tab(grp3_nb, 'analyse')
            self._restore_notebook_tab(integ_nb, 'integrations')
        except Exception:
            pass

        # Sélectionner l'onglet précédent (niveau principal) si disponible
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
        self.var_sr_enabled = tk.BooleanVar(
            value=bool(app_config.get('strategy_runner.enabled', False))
        )
        self.var_sr_interval = tk.IntVar(
            value=int(app_config.get('strategy_runner.interval_sec', 300) or 300)
        )
        self.var_sr_strategy = tk.StringVar(
            value=str(app_config.get('strategy_runner.strategy', 'auto') or 'auto')
        )
        self.var_sr_fast = tk.IntVar(value=int(app_config.get('strategy_runner.fast', 10) or 10))
        self.var_sr_slow = tk.IntVar(value=int(app_config.get('strategy_runner.slow', 30) or 30))
        self.var_sr_rsi_low = tk.IntVar(
            value=int(app_config.get('strategy_runner.rsi_low', 30) or 30)
        )
        self.var_sr_rsi_high = tk.IntVar(
            value=int(app_config.get('strategy_runner.rsi_high', 70) or 70)
        )
        # Confluence/RSI period + thresholds
        self.var_sr_rsi_period = tk.IntVar(
            value=int(app_config.get('strategy_runner.rsi_period', 14) or 14)
        )
        self.var_sr_rsi_buy = tk.IntVar(
            value=int(app_config.get('strategy_runner.rsi_buy', 55) or 55)
        )
        self.var_sr_rsi_sell = tk.IntVar(
            value=int(app_config.get('strategy_runner.rsi_sell', 45) or 45)
        )
        # Volatility filter (Bollinger bandwidth)
        try:
            _mbw = float(app_config.get('strategy_runner.min_bandwidth', 0.0) or 0.0)
        except Exception:
            _mbw = 0.0
        self.var_sr_min_bw = tk.DoubleVar(value=_mbw)
        self.var_sr_bb_window = tk.IntVar(
            value=int(app_config.get('strategy_runner.bb_window', 20) or 20)
        )
        # Auto-window (bars) for auto strategy chooser
        try:
            _aw = int(app_config.get('strategy_runner.auto_window', 160) or 160)
        except Exception:
            _aw = 160
        self.var_sr_auto_window = tk.IntVar(value=_aw)

        ttk.Checkbutton(
            top, text='Activer', variable=self.var_sr_enabled, command=self._strategy_apply
        ).pack(side=tk.LEFT)
        ttk.Label(top, text='Intervalle (s):').pack(side=tk.LEFT, padx=(8, 2))
        ttk.Spinbox(
            top,
            from_=15,
            to=3600,
            width=6,
            textvariable=self.var_sr_interval,
            command=self._strategy_apply,
        ).pack(side=tk.LEFT)
        ttk.Label(top, text='Stratégie:').pack(side=tk.LEFT, padx=(8, 2))
        cb = ttk.Combobox(
            top,
            state='readonly',
            width=16,
            textvariable=self.var_sr_strategy,
            values=['auto', 'ma_cross', 'rsi_reversion', 'confluence'],
        )
        cb.pack(side=tk.LEFT)
        # Strategy tooltip (explains Auto)
        try:
            from .ui_utils import attach_tooltip as _attach_tt_strat

            _attach_tt_strat(
                cb,
                "Auto: backtest rapide sur N barres (Fenêtre auto) choisit la meilleure "
                "stratégie récente (MA, RSI, Confluence).",
            )
        except Exception:
            pass
        cb.bind(
            '<<ComboboxSelected>>',
            lambda _e: (self._strategy_apply(), self._update_strategy_param_states()),
        )

        # Params frame
        prm = ttk.Frame(tab)
        prm.pack(fill=tk.X, padx=6)
        # MA params
        ttk.Label(prm, text='Fast:').pack(side=tk.LEFT)
        sp_fast = ttk.Spinbox(
            prm,
            from_=3,
            to=60,
            width=4,
            textvariable=self.var_sr_fast,
            command=self._strategy_apply,
        )
        sp_fast.pack(side=tk.LEFT)
        ttk.Label(prm, text='Slow:').pack(side=tk.LEFT, padx=(6, 0))
        sp_slow = ttk.Spinbox(
            prm,
            from_=5,
            to=200,
            width=4,
            textvariable=self.var_sr_slow,
            command=self._strategy_apply,
        )
        sp_slow.pack(side=tk.LEFT)
        # RSI params
        ttk.Label(prm, text='RSI Low:').pack(side=tk.LEFT, padx=(12, 2))
        sp_rsi_low = ttk.Spinbox(
            prm,
            from_=5,
            to=45,
            width=4,
            textvariable=self.var_sr_rsi_low,
            command=self._strategy_apply,
        )
        sp_rsi_low.pack(side=tk.LEFT)
        ttk.Label(prm, text='RSI High:').pack(side=tk.LEFT, padx=(6, 2))
        sp_rsi_high = ttk.Spinbox(
            prm,
            from_=55,
            to=95,
            width=4,
            textvariable=self.var_sr_rsi_high,
            command=self._strategy_apply,
        )
        sp_rsi_high.pack(side=tk.LEFT)
        # Confluence-specific RSI/period
        ttk.Label(prm, text='RSI Period:').pack(side=tk.LEFT, padx=(12, 2))
        sp_rsi_period = ttk.Spinbox(
            prm,
            from_=5,
            to=50,
            width=4,
            textvariable=self.var_sr_rsi_period,
            command=self._strategy_apply,
        )
        sp_rsi_period.pack(side=tk.LEFT)
        ttk.Label(prm, text='RSI Buy≥').pack(side=tk.LEFT, padx=(6, 2))
        sp_rsi_buy = ttk.Spinbox(
            prm,
            from_=50,
            to=90,
            width=4,
            textvariable=self.var_sr_rsi_buy,
            command=self._strategy_apply,
        )
        sp_rsi_buy.pack(side=tk.LEFT)
        ttk.Label(prm, text='RSI Sell≤').pack(side=tk.LEFT, padx=(6, 2))
        sp_rsi_sell = ttk.Spinbox(
            prm,
            from_=10,
            to=50,
            width=4,
            textvariable=self.var_sr_rsi_sell,
            command=self._strategy_apply,
        )
        sp_rsi_sell.pack(side=tk.LEFT)
        # Keep references for dynamic state toggle in auto mode
        self._sr_manual_spinboxes = [
            sp_fast,
            sp_slow,
            sp_rsi_low,
            sp_rsi_high,
            sp_rsi_period,
            sp_rsi_buy,
            sp_rsi_sell,
        ]

        # Volatility filter
        prm2 = ttk.Frame(tab)
        prm2.pack(fill=tk.X, padx=6, pady=(4, 0))
        lbl_bw = ttk.Label(prm2, text='Min BBand BW:')
        lbl_bw.pack(side=tk.LEFT)
        sp_bw = ttk.Spinbox(
            prm2,
            from_=0.0,
            to=1.0,
            increment=0.01,
            width=6,
            textvariable=self.var_sr_min_bw,
            command=self._strategy_apply,
        )
        sp_bw.pack(side=tk.LEFT)
        ttk.Label(prm2, text='BBand Window:').pack(side=tk.LEFT, padx=(6, 2))
        sp_bb = ttk.Spinbox(
            prm2,
            from_=10,
            to=60,
            width=5,
            textvariable=self.var_sr_bb_window,
            command=self._strategy_apply,
        )
        sp_bb.pack(side=tk.LEFT)
        # Auto window control (only meaningful for 'auto' strategy)
        ttk.Label(prm2, text='Fenêtre auto (barres):').pack(side=tk.LEFT, padx=(12, 2))
        self.sp_auto_window = ttk.Spinbox(
            prm2,
            from_=40,
            to=1000,
            width=6,
            textvariable=self.var_sr_auto_window,
            command=self._strategy_apply,
        )
        self.sp_auto_window.pack(side=tk.LEFT)
        try:
            from .ui_utils import attach_tooltip

            attach_tooltip(
                lbl_bw,
                'Filtre de volatilité (Bollinger bandwidth). 0.00 = aucun filtre; '
                '0.05–0.10 = faible vol; 0.10–0.20 = modérée; >0.20 = forte. '
                'Recommandé: 0.05–0.15 pour éviter le bruit.',
            )
            attach_tooltip(
                sp_bw,
                'Valeur minimale du Bollinger bandwidth pour générer des signaux. Échelle 0–1. '
                'Ex.: 0.08 laisse passer des tendances, 0.15 filtre les ranges trop serrés.',
            )
            attach_tooltip(
                self.sp_auto_window,
                "Nombre de barres utilisées par le mode Auto pour évaluer les stratégies "
                "(40–1000). Par défaut 160.",
            )
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
        self.var_at_mode = tk.StringVar(
            value=str(app_config.get('autotrade.mode', 'paper') or 'paper')
        )
        self.var_at_size = tk.DoubleVar(
            value=float(app_config.get('autotrade.base_size', 1000.0) or 1000.0)
        )
        self.var_at_maxtr = tk.IntVar(
            value=int(app_config.get('autotrade.max_trades_per_day', 10) or 10)
        )
        # Guardrails variables
        self.var_at_max_notional = tk.DoubleVar(
            value=float(app_config.get('autotrade.max_position_notional_per_symbol', 0.0) or 0.0)
        )
        self.var_at_max_qty = tk.DoubleVar(
            value=float(app_config.get('autotrade.max_position_qty_per_symbol', 0.0) or 0.0)
        )
        ttk.Checkbutton(
            at_row1, text='Activer', variable=self.var_at_enabled, command=self._strategy_apply
        ).pack(side=tk.LEFT)
        ttk.Label(at_row1, text='Mode:').pack(side=tk.LEFT, padx=(8, 2))
        mode_cb = ttk.Combobox(
            at_row1,
            state='readonly',
            width=8,
            textvariable=self.var_at_mode,
            values=['paper', 'live'],
        )
        mode_cb.pack(side=tk.LEFT)
        mode_cb.bind('<<ComboboxSelected>>', lambda _e: self._on_at_mode_change())
        ttk.Label(at_row1, text='Taille base:').pack(side=tk.LEFT, padx=(8, 2))
        ttk.Spinbox(
            at_row1,
            from_=100,
            to=50000,
            increment=100,
            width=8,
            textvariable=self.var_at_size,
            command=self._strategy_apply,
        ).pack(side=tk.LEFT)
        ttk.Label(at_row1, text='Max trades/jour:').pack(side=tk.LEFT, padx=(8, 2))
        ttk.Spinbox(
            at_row1,
            from_=1,
            to=100,
            width=5,
            textvariable=self.var_at_maxtr,
            command=self._strategy_apply,
        ).pack(side=tk.LEFT)
        # Row 2: Guardrails
        at_row2 = ttk.Frame(at_frame)
        at_row2.pack(fill=tk.X, padx=4, pady=2)
        ttk.Label(at_row2, text='Max notionnel/symbole:').pack(side=tk.LEFT)
        ttk.Spinbox(
            at_row2,
            from_=0,
            to=100000,
            increment=1000,
            width=8,
            textvariable=self.var_at_max_notional,
            command=self._strategy_apply,
        ).pack(side=tk.LEFT)
        ttk.Label(at_row2, text='(0=illimité)').pack(side=tk.LEFT, padx=(2, 8))
        ttk.Label(at_row2, text='Max qté/symbole:').pack(side=tk.LEFT)
        ttk.Spinbox(
            at_row2,
            from_=0,
            to=10000,
            increment=10,
            width=8,
            textvariable=self.var_at_max_qty,
            command=self._strategy_apply,
        ).pack(side=tk.LEFT)
        ttk.Label(at_row2, text='(0=illimité)').pack(side=tk.LEFT, padx=(2, 0))

        # --- Portfolio Paper Section ---
        pf_frame = ttk.LabelFrame(tab, text='Portefeuille Paper')
        pf_frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=(4, 0))
        self.lbl_pf = ttk.Label(pf_frame, text='Chargement...', foreground='gray')
        self.lbl_pf.pack(fill=tk.X, padx=4, pady=2)
        pf_tree_frame = ttk.Frame(pf_frame)
        pf_tree_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=2)
        self.tree_pf = ttk.Treeview(
            pf_tree_frame,
            columns=('symbol', 'qty', 'avg_price', 'last', 'pnl', 'value'),
            show='tree headings',
            height=4,
        )
        self.tree_pf.heading('#0', text='Symb')
        self.tree_pf.column('#0', width=90, anchor=tk.W, stretch=False)
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
        try:
            self.tree_pf.column('symbol', width=0, minwidth=0, stretch=False)
        except Exception:
            pass
        pf_scroll = ttk.Scrollbar(pf_tree_frame, orient='vertical', command=self.tree_pf.yview)
        self.tree_pf.configure(yscrollcommand=pf_scroll.set)
        self.tree_pf.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        pf_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # Ledger table
        ledger_frame = ttk.LabelFrame(tab, text='Journal des Trades (Idempotence)')
        ledger_frame.pack(fill=tk.X, padx=6, pady=(4, 0))
        ledger_info = ttk.Label(
            ledger_frame,
            text='Dernières entrées du journal (évite les doublons de signaux)',
            foreground='gray',
            font=('TkDefaultFont', 8),
        )
        ledger_info.pack(fill=tk.X, padx=4, pady=2)
        self.tree_ledger = ttk.Treeview(
            ledger_frame,
            columns=('timestamp', 'symbol', 'kind', 'index'),
            show='tree headings',
            height=3,
        )
        self.tree_ledger.heading('#0', text='Symb')
        self.tree_ledger.column('#0', width=90, anchor=tk.W, stretch=False)
        for col, (header, width, anchor) in {
            'timestamp': ('Timestamp', 140, tk.W),
            'symbol': ('Symbole', 80, tk.W),
            'kind': ('Type', 60, tk.W),
            'index': ('Index', 80, tk.W),
        }.items():
            self.tree_ledger.heading(col, text=header)
            self.tree_ledger.column(col, width=width, anchor=anchor, stretch=True)
        try:
            self.tree_ledger.column('symbol', width=0, minwidth=0, stretch=False)
        except Exception:
            pass
        self.tree_ledger.pack(fill=tk.X, padx=4, pady=2)

        # Runner recent signals + AutoTrade activity
        rs_frame = ttk.Frame(tab)
        rs_frame.pack(fill=tk.X, padx=6, pady=(4, 0))
        left_rs = ttk.Labelframe(rs_frame, text='Derniers signaux')
        left_rs.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.tree_recent_signals = ttk.Treeview(
            left_rs,
            columns=('time', 'symbol', 'kind', 'reason'),
            show='headings',
            height=5,
        )
        for c, (h, w, a) in {
            'time': ('Heure', 90, tk.W),
            'symbol': ('Symb', 70, tk.W),
            'kind': ('Type', 60, tk.W),
            'reason': ('Raison', 420, tk.W),
        }.items():
            self.tree_recent_signals.heading(c, text=h)
            self.tree_recent_signals.column(c, width=w, anchor=a, stretch=True)
        self.tree_recent_signals.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        right_rs = ttk.Labelframe(rs_frame, text='AutoTrade: activité récente')
        right_rs.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(6, 0))
        self.lst_at_activity = tk.Listbox(right_rs, height=5)
        self.lst_at_activity.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        try:
            self.after(8000, self._recent_signals_tick)
        except Exception:
            pass

        # --- Advisor (Enhanced AI) ---
        try:
            import os as _os

            _adv_enabled = bool(app_config.get('ai.enhanced', False)) or (
                _os.getenv('AI_ENHANCED', '0') == '1'
            )
        except Exception:
            _adv_enabled = False
        adv_frame = ttk.LabelFrame(tab, text='Conseiller (AI)')
        adv_frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=(6, 8))
        self._adv_enabled = bool(_adv_enabled)
        status_row = ttk.Frame(adv_frame)
        status_row.pack(fill=tk.X, padx=4, pady=(2, 4))
        self.lbl_adv_status = ttk.Label(status_row)
        try:
            if self._adv_enabled:
                self.lbl_adv_status.configure(text='● Conseiller actif', foreground='green')
            else:
                self.lbl_adv_status.configure(text='● Conseiller désactivé', foreground='red')
        except Exception:
            self.lbl_adv_status.configure(
                text=('Conseiller actif' if self._adv_enabled else 'Conseiller désactivé')
            )
        self.lbl_adv_status.pack(side=tk.LEFT)
        self.lbl_adv_info = ttk.Label(
            status_row,
            text=(
                'Analyse et suggestion basées sur le portefeuille.'
                if self._adv_enabled
                else 'Activez le Conseiller dans Préférences > Intelligence Artificielle, '
                     'ou définissez AI_ENHANCED=1 avant le lancement.'
            ),
            foreground='gray',
        )
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

        self.btn_advisor_analyze = ttk.Button(
            btn_bar,
            text='Analyser maintenant',
            command=_run_advisor,
            state=(tk.NORMAL if _adv_enabled else tk.DISABLED),
        )
        self.btn_advisor_analyze.pack(side=tk.LEFT)
        ttk.Button(
            btn_bar,
            text='Copier',
            command=lambda: (
                self.clipboard_clear(),
                self.clipboard_append(self.txt_advisor.get('1.0', 'end').strip()),
            ),
        ).pack(side=tk.LEFT, padx=(6, 0))
        self.txt_advisor = tk.Text(adv_frame, height=6, wrap='word')
        self.txt_advisor.configure(state=tk.DISABLED)
        _scr_adv = ttk.Scrollbar(adv_frame, orient='vertical', command=self.txt_advisor.yview)
        self.txt_advisor.configure(yscrollcommand=_scr_adv.set)
        self.txt_advisor.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(4, 0), pady=(0, 4))
        _scr_adv.pack(side=tk.RIGHT, fill=tk.Y, pady=(0, 4))

        # Create runner and start after UI/vars are ready
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
            send_alert=(
                lambda title, msg, level='ALERT': (
                    self.api_manager.telegram.send_alert(title, msg, level)
                    if (self.api_manager and getattr(self.api_manager, 'telegram', None))
                    else False
                )
            ),
            trade_executor=self._trade_exec,
            on_signal=self._on_strategy_signal,
        )
        self._strategy_apply()
        # Initial state sync for params visibility/enabling
        try:
            self._update_strategy_param_states()
        except Exception:
            pass
        try:
            self._strategy_runner.start()
        except Exception:
            pass
        try:
            self.after(15000, self._portfolio_tick)
        except Exception:
            pass
        try:
            self.after(60 * 60 * 1000, self._ai_watchlist_tick)
        except Exception:
            pass

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
            app_config.set('strategy_runner.auto_window', int(self.var_sr_auto_window.get()))
            # autotrade
            app_config.set('autotrade.enabled', bool(self.var_at_enabled.get()))
            app_config.set('autotrade.mode', str(self.var_at_mode.get()))
            app_config.set('autotrade.base_size', float(self.var_at_size.get()))
            app_config.set('autotrade.max_trades_per_day', int(self.var_at_maxtr.get()))
            app_config.set(
                'autotrade.max_position_notional_per_symbol', float(self.var_at_max_notional.get())
            )
            app_config.set(
                'autotrade.max_position_qty_per_symbol', float(self.var_at_max_qty.get())
            )
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
                'auto_window': int(self.var_sr_auto_window.get()),
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
                        max_position_notional_per_symbol=(
                            float(self.var_at_max_notional.get())
                            if self.var_at_max_notional.get() > 0
                            else None
                        ),
                        max_position_qty_per_symbol=(
                            float(self.var_at_max_qty.get())
                            if self.var_at_max_qty.get() > 0
                            else None
                        ),
                    )
            except Exception:
                pass

    def _update_strategy_param_states(self):
        """Enable/disable manual parameter controls when 'auto' is selected.
        Keeps UI simple in auto mode, while still allowing volatility filters and auto window.
        """
        try:
            strat = str(self.var_sr_strategy.get())
            is_auto = strat == 'auto'
            state_manual = tk.DISABLED if is_auto else tk.NORMAL
            # Manual strategy param spinboxes
            for w in getattr(self, '_sr_manual_spinboxes', []) or []:
                try:
                    w.configure(state=state_manual)
                except Exception:
                    pass
            # Auto window relevant only in auto mode
            try:
                self.sp_auto_window.configure(state=(tk.NORMAL if is_auto else tk.DISABLED))
            except Exception:
                pass
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

            val = (
                bool(getattr(self, 'var_ai_enhanced', None).get())
                if hasattr(self, 'var_ai_enhanced')
                else False
            )
            app_config.set('ai.enhanced', val)
            # Refresh Advisor badge and controls live
            self._adv_enabled = bool(val or (os.getenv('AI_ENHANCED', '0') == '1'))
            try:
                if hasattr(self, 'lbl_adv_status') and self.lbl_adv_status:
                    if self._adv_enabled:
                        self.lbl_adv_status.configure(text='● Conseiller actif', foreground='green')
                    else:
                        self.lbl_adv_status.configure(
                            text='● Conseiller désactivé', foreground='red'
                        )
                if hasattr(self, 'lbl_adv_info') and self.lbl_adv_info:
                    self.lbl_adv_info.configure(
                        text=(
                            'Analyse et suggestion basées sur le portefeuille.'
                            if self._adv_enabled
                            else 'Activez le Conseiller dans Préférences > Intelligence '
                                 'Artificielle, ou définissez AI_ENHANCED=1 avant le lancement.'
                        )
                    )
                if hasattr(self, 'btn_advisor_analyze') and self.btn_advisor_analyze:
                    self.btn_advisor_analyze.configure(
                        state=(tk.NORMAL if self._adv_enabled else tk.DISABLED)
                    )
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
                    "Le mode LIVE n'exécute pas d'ordres réels pour l'instant (stub), "
                    "mais doit être utilisé avec prudence. Voulez-vous vraiment passer "
                    "en mode LIVE?",
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

                # Format values for display (prices with currency symbol; totals with codes)
                last_str = (
                    format_money(last_price, self.base_currency, with_symbol=True)
                    if last_price > 0
                    else "N/A"
                )
                pnl_str = f"{pnl_percent:+.1f}%" if last_price > 0 else "N/A"
                value_str = format_money(market_value, self.base_currency, with_symbol=False)

                # Color-code PnL
                tags = []
                if last_price > 0:
                    if pnl_percent > 0:
                        tags = ['positive_pnl']
                    elif pnl_percent < 0:
                        tags = ['negative_pnl']

                iid = self.tree_pf.insert(
                    '',
                    'end',
                    text=symbol,
                    values=(symbol, f"{qty:.4f}", f"{avg_price:.2f}", last_str, pnl_str, value_str),
                    tags=tags,
                )
                try:
                    self._attach_logo_to_item(self.tree_pf, iid, symbol)
                except Exception:
                    pass

            # Configure PnL colors
            try:
                self.tree_pf.tag_configure('positive_pnl', foreground='#22c55e')  # green
                self.tree_pf.tag_configure('negative_pnl', foreground='#ef4444')  # red
            except Exception:
                pass

            # Update summary label
            equity = snap.get('equity') or total_value
            total_pnl_pct = (
                (total_pnl / (total_value - total_pnl) * 100)
                if (total_value - total_pnl) != 0
                else 0.0
            )
            pnl_color = "#22c55e" if total_pnl >= 0 else "#ef4444"

            cash_str = format_money(cash, self.base_currency, with_symbol=False)
            total_value_str = format_money(total_value, self.base_currency, with_symbol=False)
            pnl_str = format_money(total_pnl, self.base_currency, with_symbol=False)
            
            summary_text = (
                f"Cash: {cash_str}  |  "
                f"Valeur totale: {total_value_str}  |  "
                f"PnL: {pnl_str} ({total_pnl_pct:+.1f}%)  |  "
                f"Positions: {len(snap.get('positions', []))}"
            )
            self.lbl_pf.config(text=summary_text, foreground=pnl_color)

        except Exception:
            # Fallback to basic view on error
            try:
                snap = self._trade_exec.portfolio_snapshot(include_quotes=False)
                cash = snap.get('cash') or 0.0
                equity = snap.get('equity') or cash
                cash_str = format_money(cash, self.base_currency, with_symbol=False)
                equity_str = format_money(equity, self.base_currency, with_symbol=False)
                self.lbl_pf.config(
                    text=(
                        f"Cash: {cash_str}  |  "
                        f"Équité: {equity_str}  |  "
                        f"Positions: {len(snap.get('positions', []))} (quotes unavailable)"
                    ),
                    foreground='gray',
                )
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

                iid = self.tree_ledger.insert(
                    '', 'end', text=symbol, values=(timestamp_str, symbol, kind, str(index))
                )
                try:
                    self._attach_logo_to_item(self.tree_ledger, iid, symbol)
                except Exception:
                    pass

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
        for s in syms + wl:
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
            app_config.set(
                'strategy_runner.watchlist', [str(x).strip().upper() for x in (items or []) if x]
            )
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
                scr = (
                    self.api_manager.yahoo.get_predefined_screener(
                        'day_gainers', count=40, region='US'
                    )
                    or []
                )
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

                    has_strategy = True
                except Exception:
                    has_strategy = False
                scored: list[tuple[str, float]] = []
                for q in scr:
                    sym = q.get('symbol')
                    if not sym:
                        continue
                    try:
                        ts = (
                            self.api_manager.get_time_series(
                                sym, interval='1day', outputsize='compact'
                            )
                            or {}
                        )
                        closes = StrategyRunner._extract_closes(ts)  # reuse static method
                        if len(closes) < max(30, slow + 2):
                            continue
                        if has_strategy:
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
        # Ensure rows are tall enough for logos
        try:
            style = ttk.Style(self)
            style.configure('Treeview', rowheight=24)
        except Exception:
            pass
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
        # Prefetch logos on idle
        try:
            self.after_idle(self._prefetch_logos_idle)
        except Exception:
            pass

    def _prefetch_logos_idle(self):
        """Warm the logo cache for watchlist and current positions when idle."""
        try:
            symbols = set()
            for p in getattr(self, '_positions_cache', []) or []:
                s = (p.get('symbol') or '').strip().upper()
                if s:
                    symbols.add(s)
            try:
                for s in self._watchlist_read():
                    s = (s or '').strip().upper()
                    if s:
                        symbols.add(s)
            except Exception:
                pass
            count = 0
            for s in symbols:
                if count >= 40:
                    break
                try:
                    self.media.get_logo_async(s, lambda _img: None)
                except Exception:
                    pass
                count += 1
        except Exception:
            pass

    def toggle_theme(self):
        self.apply_theme('dark' if self._theme == 'light' else 'light')

    def _try_auto_login(self):
        sess = load_session()
        if not sess:
            # No session: open login dialog shortly after UI shows
            self.after(200, self.open_login_dialog)
            return
        self.set_status('Restauration de la session...')

        def worker():
            try:
                self.api = WealthsimpleAPI.from_token(
                    sess,
                    persist_session_fct=save_session,
                )
                self.set_status('Session restaurée')
                self._update_connected_state()
                self.refresh_accounts()
            except ManualLoginRequired:
                self.set_status('Session expirée. Veuillez vous connecter.')

        threading.Thread(target=worker, daemon=True).start()

    def open_login_dialog(self):
        def on_success(api: WealthsimpleAPI):
            self.api = api
            self.set_status('Connecté')
            self._update_connected_state()
            try:
                self.refresh_accounts()
            except Exception:
                pass

        try:
            from .config import app_config as _cfg

            LoginDialog(
                self,
                on_success=on_success,
                save_session=save_session,
                remember_email_key='auth.email',
                get_config=_cfg.get,
                set_config=_cfg.set,
            )
        except Exception:
            # Fallback without config persistence
            LoginDialog(self, on_success=on_success, save_session=save_session)

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
            allowed_id = (
                (self.var_tg_chat.get() or '').strip() if hasattr(self, 'var_tg_chat') else None
            )
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
            tg.start_command_handler(
                self.agent,
                allowed_chat_id=allowed_id,
                trade_executor=getattr(self, '_trade_exec', None),
                strategy_runner=getattr(self, '_strategy_runner', None),
            )
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
            chat_id = (
                (self.var_tg_chat.get() or '').strip() if hasattr(self, 'var_tg_chat') else None
            )
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

    def _update_connected_state(self):
        # Hide connect button, show greeting with user's name if available
        try:
            name = None
            try:
                if self.api and hasattr(self.api, 'get_identity_display_name'):
                    name = self.api.get_identity_display_name()
            except Exception:
                name = None
            if not name:
                name = 'connecté'
            self.var_greeting.set(f"Bonjour, {name}")
            self.btn_connect.grid_remove()
            self.lbl_greeting.grid()
            # Update profile info in settings page if present
            try:
                self._refresh_profile_info()
            except Exception:
                pass
        except Exception:
            # Fail-safe: keep button visible
            pass

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
                self.after(
                    0,
                    lambda exc=exc: self.set_status(
                        f"Erreur API: {exc}", error=True, details=repr(exc)
                    ),
                )
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
                    f"{icon} {acc['number']} | {acc['description']} (" f"{acc['currency']})",
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
                positions = self.api.get_account_positions(self.current_account_id)
                acts = self.api.get_activities(
                    self.current_account_id,
                    how_many=limit,
                    start_date=start,
                    end_date=end,
                )
                self.after(0, lambda: self.update_details(positions, acts))
            except Exception as e:  # noqa
                self.after(
                    0, lambda e=e: self.set_status(f"Erreur: {e}", error=True, details=repr(e))
                )
            finally:
                self.after(0, lambda: self._busy(False))

        threading.Thread(target=worker, daemon=True).start()

    def update_details(self, positions: list[dict], acts: list[dict]):
        for row in self.tree_positions.get_children():
            self.tree_positions.delete(row)
        self._positions_cache = positions
        total_value = 0.0
        cur_totals: dict[str, float] = {}
        total_pnl_abs = 0.0
        pnl_abs_by_cur: dict[str, float] = {}
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
                arrow_pct = ('↑' if pnl_pct >= 0 else '↓') + f"{abs(pnl_pct):.2f}%"
                if pos.get('pnlIsDaily'):
                    arrow_pct += '*'
            avg = pos.get('avgPrice')
            idx = len(self.tree_positions.get_children())
            base_tag = 'even' if idx % 2 == 0 else 'odd'
            pnl_tag = None
            if isinstance(pnl_pct, (int, float)):
                pnl_tag = 'pnl_pos' if pnl_pct >= 0 else 'pnl_neg'
            tags = (base_tag,) + ((pnl_tag,) if pnl_tag else tuple())
            # Format monetary fields: prices with symbol; totals with currency code
            try:
                lp = pos.get('lastPrice')
                last_str = (
                    format_money(lp, (cur or self.base_currency), with_symbol=True)
                    if isinstance(lp, (int, float))
                    else (lp or '')
                )
            except Exception:
                last_str = pos.get('lastPrice')
            try:
                val_str = (
                    format_money(val, (cur or self.base_currency), with_symbol=False) if val else ''
                )
            except Exception:
                val_str = f"{val:.2f}" if val else ''
            try:
                avg_str = (
                    format_money(avg, (cur or self.base_currency), with_symbol=True)
                    if isinstance(avg, (int, float))
                    else ''
                )
            except Exception:
                avg_str = f"{avg:.2f}" if isinstance(avg, (int, float)) else ''
            try:
                pnl_abs_str = (
                    format_money(pnl_abs, (cur or self.base_currency), with_symbol=False)
                    if isinstance(pnl_abs, (int, float))
                    else ''
                )
            except Exception:
                pnl_abs_str = f"{pnl_abs:,.2f}" if isinstance(pnl_abs, (int, float)) else ''

            iid = self.tree_positions.insert(
                '',
                tk.END,
                text=str(pos.get('symbol') or ''),
                values=(
                    pos.get('symbol'),
                    pos.get('name'),
                    pos.get('quantity'),
                    last_str,
                    val_str,
                    cur,
                    avg_str,
                    arrow_pct,
                    pnl_abs_str,
                ),
                tags=tags,
            )
            try:
                self._attach_logo_to_item(self.tree_positions, iid, pos.get('symbol') or '')
            except Exception:
                pass
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
            cur_parts = ' '.join(f"{c}:{v:,.2f}" for c, v in cur_totals.items())
            pnl_cur_parts = ' '.join(f"{c}:{v:,.2f}" for c, v in pnl_abs_by_cur.items())
            pnl_part = f" | PnL: {total_pnl_abs:,.2f} ({pnl_cur_parts})" if pnl_abs_by_cur else ''
            conv_total = 0.0
            fx_missing = False
            for c, v in cur_totals.items():
                if c == self.base_currency:
                    conv_total += v
                    continue
                converted = None
                try:
                    if self.api and hasattr(self.api, 'convert_money'):
                        converted = self.api.convert_money(v, c, self.base_currency)
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
        if not acts:
            self.tree_acts.insert(
                '', tk.END, values=('—', 'Aucune activité', '', ''), tags=('even',)
            )
        for a in acts:
            idx = len(self.tree_acts.get_children())
            tag = 'even' if idx % 2 == 0 else 'odd'
            amt = a.get('amount')
            cur = a.get('currency') or self.base_currency
            self.tree_acts.insert(
                '',
                tk.END,
                values=(
                    a.get('occurredAt'),
                    a.get('description'),
                    (
                        format_money(amt, cur, with_symbol=False)
                        if isinstance(amt, (int, float))
                        else amt
                    ),
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

    # ---- Logos in Treeviews ----
    def _attach_logo_to_item(self, tree: ttk.Treeview, iid: str, symbol: str):
        symbol = (symbol or '').strip().upper()
        if not symbol:
            try:
                tree.item(iid, text='')
            except Exception:
                pass
            return
        try:
            tree.item(iid, text=symbol)
        except Exception:
            pass

        def cb(img):
            def apply_image():
                try:
                    # Ensure item still exists
                    if not (tree.exists(iid)):  # type: ignore[attr-defined]
                        return
                    if img:
                        self._logo_images[symbol] = img
                        tree.item(iid, image=img)
                    else:
                        # Clear any stale image if fetch failed
                        tree.item(iid, image='')
                except Exception:
                    pass

            try:
                # Ensure UI-thread update
                self.after(0, apply_image)
            except Exception:
                apply_image()

        try:
            self.media.get_logo_async(symbol, cb)
        except Exception:
            pass

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
            # Refresh and then apply level filter if set
            self.agent_ui.refresh_signals()
            try:
                level = (
                    self.var_ai_level.get() if hasattr(self, 'var_ai_level') else 'ALL'
                ) or 'ALL'
                if level and level != 'ALL':
                    lvl_idx = list(self.tree_signals['columns']).index('level')
                    for iid in self.tree_signals.get_children():
                        vals = self.tree_signals.item(iid, 'values')
                        if vals and len(vals) > lvl_idx and str(vals[lvl_idx]).upper() != level:
                            self.tree_signals.detach(iid)
            except Exception:
                pass
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

    def _recent_signals_tick(self):
        try:
            self._update_recent_signals()
            self._update_at_activity()
        except Exception:
            pass
        try:
            self.after(8000, self._recent_signals_tick)
        except Exception:
            pass

    def _update_recent_signals(self):
        try:
            if not hasattr(self, '_strategy_runner') or not self._strategy_runner:
                return
            for iid in self.tree_recent_signals.get_children():
                self.tree_recent_signals.delete(iid)
            from datetime import datetime as _dt

            for sym, kind, idx, reason in self._strategy_runner.recent_signals()[-20:][::-1]:
                ts = _dt.now().strftime('%H:%M:%S')
                self.tree_recent_signals.insert('', tk.END, values=(ts, sym, kind, reason))
        except Exception:
            pass

    def _update_at_activity(self):
        try:
            if not hasattr(self, '_trade_exec') or not self._trade_exec:
                return
            acts = self._trade_exec.last_actions(10)
            self.lst_at_activity.delete(0, tk.END)
            for a in acts:
                self.lst_at_activity.insert(tk.END, a)
        except Exception:
            pass

    def _on_strategy_signal(self, symbol: str, signal):
        """Callback from StrategyRunner when a fresh signal is emitted.

        - Update recent signals panel immediately
        - If a chart view for this symbol is available, set markers accordingly
        """
        try:
            self._update_recent_signals()
            self._update_at_activity()
        except Exception:
            pass
        # Chart markers: only if main ChartController is available and has data cached
        try:
            # Determine if analyzer window is open on this symbol; prefer it if so
            if getattr(self, 'symbol_analyzer', None) and getattr(
                self.symbol_analyzer, 'window', None
            ):
                if (
                    str(getattr(self.symbol_analyzer, 'current_symbol', '')).upper()
                    == str(symbol).upper()
                ):
                    # symbol analyzer uses its own plotting; skip here
                    return
            # Fallback to main ChartController (account charts)
            if hasattr(self, 'chart') and getattr(self.chart, '_last_points', None):
                # Build a marker for today
                from datetime import datetime as _dt

                d = _dt.now().strftime('%Y-%m-%d')
                lbl = getattr(signal, 'reason', '') or getattr(signal, 'kind', '')
                kind = str(getattr(signal, 'kind', 'buy')).lower()
                self.chart.set_markers([{'date': d, 'kind': kind, 'label': lbl}])
        except Exception:
            pass

    def _ai_signal_trade(self, side: str):
        """One-click paper trade from selected AI signal."""
        try:
            sel = self.tree_signals.selection()
            if not sel:
                return
            vals = self.tree_signals.item(sel[0], 'values')
            if not vals:
                return
            # Columns: time, level, symbol, code, message
            symbol = str(vals[2]).strip().upper() if len(vals) > 2 else ''
            if not symbol:
                return
            if not hasattr(self, '_trade_exec') or not self._trade_exec:
                return
            if side == 'buy':
                self._trade_exec.buy_market(symbol)
            else:
                self._trade_exec.sell_market(symbol)
            # update activity
            self._update_at_activity()
            self.set_status(f"Paper {side.upper()} envoyé: {symbol}")
        except Exception:
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
        # Préfixer avec un horodatage court [HH:MM] et styliser le locuteur
        try:
            ts = datetime.now().strftime('%H:%M')
        except Exception:
            ts = ''
        has_nl = text.endswith('\n')
        raw = text[:-1] if has_nl else text
        self.txt_chat.configure(state=tk.NORMAL)
        try:
            if ts:
                self.txt_chat.insert(tk.END, f'[{ts}] ', 'ts')
            speaker_tag = None
            if raw.startswith('Vous: '):
                speaker_tag = 'speaker_user'
                self.txt_chat.insert(tk.END, 'Vous: ', speaker_tag)
                self.txt_chat.insert(tk.END, raw[len('Vous: ') :])
            elif raw.startswith('Agent: '):
                speaker_tag = 'speaker_agent'
                self.txt_chat.insert(tk.END, 'Agent: ', speaker_tag)
                self.txt_chat.insert(tk.END, raw[len('Agent: ') :])
            else:
                self.txt_chat.insert(tk.END, raw)
            if not has_nl:
                self.txt_chat.insert(tk.END, '\n')
            self.txt_chat.see(tk.END)
        finally:
            self.txt_chat.configure(state=tk.DISABLED)

    # Placeholder handlers pour le champ de chat
    def _on_chat_focus_in(self, _event=None):
        try:
            if getattr(self, '_chat_placeholder_active', False):
                if self.var_chat.get() == getattr(self, '_chat_placeholder', ''):
                    self.var_chat.set('')
                self._chat_placeholder_active = False
        except Exception:
            pass

    def _on_chat_focus_out(self, _event=None):
        try:
            if not (self.var_chat.get() or '').strip():
                self.var_chat.set(getattr(self, '_chat_placeholder', ''))
                self._chat_placeholder_active = True
        except Exception:
            pass

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
        menu.add_command(label='Copier ligne', command=lambda: self._copy_selected(tree))
        # Extra actions contextual to symbol/news
        menu.add_command(label='Copier symbole', command=lambda: self._copy_symbol_from_tree(tree))
        menu.add_command(
            label='Graphique rapide', command=lambda: self._quick_chart_from_tree(tree)
        )
        menu.add_command(
            label='Ajouter à la watchlist', command=lambda: self._add_watchlist_from_tree(tree)
        )
        menu.add_command(
            label='Ouvrir dans le navigateur', command=lambda: self._open_in_browser_from_tree(tree)
        )
        menu.add_separator()
        menu.add_command(
            label='Exporter la sélection…', command=lambda: self._export_tree_selection(tree)
        )

        def popup(ev):  # noqa
            iid = tree.identify_row(ev.y)
            if iid:
                tree.selection_set(iid)
                try:
                    menu.tk_popup(ev.x_root, ev.y_root)
                finally:
                    try:
                        menu.grab_release()
                    except Exception:
                        pass

        tree.bind('<Button-3>', popup)

    def _copy_selected(self, tree: ttk.Treeview):
        sel = tree.selection()
        if not sel:
            return
        vals = tree.item(sel[0], 'values')
        self.clipboard_clear()
        self.clipboard_append('\t'.join(str(v) for v in vals))
        self.update()

    def _copy_symbol_from_tree(self, tree: ttk.Treeview):
        sym = self._get_symbol_from_tree(tree)
        if not sym:
            return
        try:
            self.clipboard_clear()
            self.clipboard_append(sym)
            self.update()
            self.set_status(f"Symbole copié: {sym}")
        except Exception:
            pass

    def _get_symbol_from_tree(self, tree: ttk.Treeview) -> str | None:
        try:
            sel = tree.selection()
            if not sel:
                return None
            item = tree.item(sel[0])
            vals = item.get('values')
            cols = list(tree['columns'])
            # Prefer 'symbol' column if present
            if 'symbol' in cols:
                idx = cols.index('symbol')
                return str(vals[idx]) if vals and idx < len(vals) and vals[idx] else None
            # Next, try the tree text (#0) which we now use for logos + symbol label
            txt = item.get('text')
            if txt:
                return str(txt)
            # Fallback: first column often holds the symbol
            return str(vals[0]) if vals and vals[0] else None
        except Exception:
            return None

    def _quick_chart_from_tree(self, tree: ttk.Treeview):
        sym = self._get_symbol_from_tree(tree)
        if not sym:
            self.set_status('Aucun symbole sélectionné', error=True)
            return
        self._quick_chart_symbol(sym)

    def _quick_chart_symbol(self, symbol: str):
        symbol = (symbol or '').strip().upper()
        if not symbol:
            return
        # Prefer full analyzer when available
        if self.symbol_analyzer:
            try:
                self.symbol_analyzer.show_symbol_analysis(symbol)
                return
            except Exception:
                pass
        # Fallback: open Yahoo Finance in browser
        try:
            webbrowser.open_new_tab(f'https://finance.yahoo.com/quote/{symbol}')
            self.set_status(f'Ouverture du graphique pour {symbol} dans le navigateur')
        except Exception:
            pass

    def _add_watchlist_from_tree(self, tree: ttk.Treeview):
        sym = self._get_symbol_from_tree(tree)
        if not sym:
            return
        try:
            current = self._watchlist_read()
            s = sym.strip().upper()
            if s not in current:
                current.append(s)
                self._watchlist_save(current)
                if hasattr(self, 'list_watchlist'):
                    self._watchlist_load_from_config()
            self.set_status(f'Ajouté à la watchlist: {s}')
        except Exception:
            pass

    def _open_in_browser_from_tree(self, tree: ttk.Treeview):
        # News tree: open article URL
        if tree is getattr(self, 'tree_news', None):
            sel = tree.selection()
            if not sel:
                return
            try:
                iid = sel[0]
                url = None
                # Prefer robust iid mapping if available
                if isinstance(getattr(self, '_news_url_by_iid', None), dict):
                    url = self._news_url_by_iid.get(iid)
                # Fallback to index mapping
                if not url:
                    idx = tree.index(iid)
                    if isinstance(getattr(self, '_news_articles', None), list) and idx < len(
                        self._news_articles
                    ):
                        url = self._news_articles[idx].get('url')
                if url:
                    webbrowser.open_new_tab(url)
                    return
            except Exception:
                pass
        # Default: open finance page for symbol
        sym = self._get_symbol_from_tree(tree)
        if not sym:
            return
        try:
            webbrowser.open_new_tab(f'https://finance.yahoo.com/quote/{sym}')
        except Exception:
            pass

    def _export_tree_selection(self, tree: ttk.Treeview):
        try:
            sel = tree.selection()
            if not sel:
                return
            path = filedialog.asksaveasfilename(
                title='Exporter la sélection',
                defaultextension='.csv',
                filetypes=[('CSV', '*.csv')],
            )
            if not path:
                return
            # Write header and selected rows
            cols = list(tree['columns'])
            include_news_url = tree is getattr(self, 'tree_news', None)
            if include_news_url:
                cols = cols + ['url']
            with open(path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(cols)
                for iid in sel:
                    vals = list(tree.item(iid, 'values'))
                    if include_news_url:
                        try:
                            # Prefer iid mapping if available
                            url = ''
                            if isinstance(getattr(self, '_news_url_by_iid', None), dict):
                                url = self._news_url_by_iid.get(iid, '') or ''
                            if not url:
                                idx = tree.index(iid)
                                if isinstance(
                                    getattr(self, '_news_articles', None), list
                                ) and idx < len(self._news_articles):
                                    url = self._news_articles[idx].get('url') or ''
                            vals.append(url)
                        except Exception:
                            vals.append('')
                    writer.writerow(vals)
            self.set_status(f"Exporté: {path}")
        except Exception as e:
            self.set_status(f"Export: {e}", error=True)

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
                        # Use provider-aware quote (falls back to Yahoo/stale cache)
                        quote = self.api_manager.get_quote(symbol)
                        if quote:
                            price = float(quote.get('05. price', 0))
                            change = float(quote.get('09. change', 0))
                            change_pct = quote.get('10. change percent', '0%')
                            volume = quote.get('06. volume', 'N/A')

                            cur = self.base_currency
                            info_msg = f"""📊 Informations rapides pour {symbol}:

• Prix actuel: {format_money(price, cur, with_symbol=True)}
• Changement: {format_money(change, cur, with_symbol=True)} ({change_pct})
• Volume: {volume}
• Mise à jour: {quote.get('07. latest trading day', 'N/A')}

💡 Double-cliquez sur le symbole dans le tableau pour une analyse complète."""

                            self.after(
                                0,
                                lambda: messagebox.showinfo(f"Aperçu rapide - {symbol}", info_msg),
                            )
                        else:
                            self.after(
                                0,
                                lambda: messagebox.showwarning(
                                    "Aperçu rapide",
                                    f"Impossible de récupérer les données pour {symbol}",
                                ),
                            )
                    except Exception as e:
                        self.after(
                            0,
                            lambda err=e: self.set_status(
                                f"Erreur lors de la récupération: {err}", error=True
                            ),
                        )

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
                            # Use provider-aware quote and cached news to avoid noisy errors offline
                            quote = self.api_manager.get_quote(symbol)
                            news = self.api_manager.news.get_company_news(symbol, 3)

                            analysis_prompt = f"Analysez le symbole {symbol}:"
                            if quote:
                                price = float(quote.get('05. price', 0))
                                change = float(quote.get('09. change', 0))
                                change_pct = quote.get('10. change percent', '0%')
                                cur = self.base_currency
                                price_info = f"Prix: {price:.2f} {cur}"
                                change_info = f"Changement: {change:.2f} {cur} ({change_pct})"
                                analysis_prompt += f" {price_info}, {change_info}"

                            if news:
                                analysis_prompt += f", {len(news)} actualités récentes disponibles"

                            resp = self.agent.chat(analysis_prompt)
                            self.after(0, lambda: self._append_chat(f"Agent: {resp}\n"))
                        except Exception as e:
                            self.after(0, lambda err=e: self._append_chat(f"Erreur: {err}\n"))

                    threading.Thread(target=fetch_analysis, daemon=True).start()
                else:
                    resp = self.agent.chat(f"Donnez-moi une analyse générale du symbole {symbol}")
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

    def set_status(self, msg: str, error: bool = False, details: str | None = None):
        self.var_status.set(msg)
        self.update_idletasks()
        if error:
            self.log(f"❌ {msg}")
            try:
                # Si on a des détails et debug, ne pas timeout automatiquement
                debug = bool(app_config.get('app.debug', False))
                self._show_banner(
                    str(msg),
                    kind='error',
                    timeout_ms=(0 if (debug and details) else 8000),
                    details=details,
                )
            except Exception:
                pass

    # ------------------- Diagnostics (cache, circuits) -------------------
    # diagnostics helpers removed; handled by DiagnosticsPanel

    # ------------------- Bandeau d'information/erreur -------------------
    def _show_banner(
        self, text: str, kind: str = 'info', timeout_ms: int = 0, details: str | None = None
    ):
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

            # Configure ttk styles for banner (frame + label) to ensure 
            # background/foreground are applied
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

    def _set_last_error_details(self, details: str | None):
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
                    quote_v2 = r.get('quoteV2') or {}
                    norm.append(
                        {
                            'id': r.get('id'),
                            'symbol': stock.get('symbol'),
                            'name': stock.get('name'),
                            'exchange': stock.get('primaryExchange'),
                            'status': r.get('status'),
                            'buyable': r.get('buyable'),
                            'marketStatus': quote_v2.get('marketStatus'),
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

        # Helper to fill a given tree
        def _fill_tree(tree):
            try:
                for row in tree.get_children():
                    tree.delete(row)
                for i, r in enumerate(results):
                    tag = 'even' if i % 2 == 0 else 'odd'
                    iid = tree.insert(
                        '',
                        tk.END,
                        text=str(r.get('symbol') or ''),
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
                    try:
                        self._attach_logo_to_item(tree, iid, r.get('symbol') or '')
                    except Exception:
                        pass
            except Exception:
                pass

        _fill_tree(self.tree_search)
        try:
            if hasattr(self, 'tree_search2'):
                _fill_tree(self.tree_search2)
        except Exception:
            pass

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
        # Prepare order panel context
        try:
            sym = sec.get('symbol') or ''
            self.var_order_symbol.set(sym)
            self._selected_security = {'id': sec_id, 'symbol': sym}
        except Exception:
            pass
        self.set_status(f"Détails: {sec.get('symbol')} ...")
        self._busy(True)
        # Trigger async logo fetch (non-blocking)
        self._set_logo_image(sec.get('symbol'))

        def worker():
            try:
                md = self.api.get_security_market_data(sec_id)
                lines: list[str] = []
                stock = md.get('stock') or {}
                quote = md.get('quote') or {}
                fund = md.get('fundamentals') or {}
                lines.append(f"Nom: {stock.get('name')}")
                lines.append(f"Symbole: {stock.get('symbol')}")
                lines.append(f"Échange: {stock.get('primaryExchange')}")
                if quote:
                    lines.append(
                        'Prix: ' + str(quote.get('last')) + ' | Volume: ' + str(quote.get('volume'))
                    )
                    lines.append(
                        'High: '
                        + str(quote.get('high'))
                        + ' Low: '
                        + str(quote.get('low'))
                        + ' PrevClose: '
                        + str(quote.get('previousClose'))
                    )
                if fund:
                    lines.append(
                        '52w High: '
                        + str(fund.get('high52Week'))
                        + ' 52w Low: '
                        + str(fund.get('low52Week'))
                        + ' PE: '
                        + str(fund.get('peRatio'))
                        + ' Rendement: '
                        + str(fund.get('yield'))
                    )
                    lines.append(
                        'MarketCap: '
                        + str(fund.get('marketCap'))
                        + ' Devise: '
                        + str(fund.get('currency'))
                    )
                desc = fund.get('description')
                if desc:
                    lines.append('--- Description ---')
                    lines.append(desc)
                txt = '\n'.join(lines)
                self.after(0, lambda t=txt: self._set_search_details(t))
                # Update order subtypes (allowed types) in background
                try:

                    def _upd_types():
                        try:
                            sub = self.api.get_allowed_order_subtypes(sec_id)
                        except Exception:
                            sub = None
                        self.after(0, lambda s=sub: self._set_order_allowed_types(s))

                    threading.Thread(target=_upd_types, daemon=True).start()
                except Exception:
                    pass
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
    def _set_logo_image(self, symbol: str | None):
        symbol = (symbol or '').strip()
        if not symbol:
            self.lbl_search_logo.configure(text='[Logo]', image='')
            return

        def cb(img):
            try:
                self.after(0, lambda: self._apply_logo(symbol, img))
            except Exception:
                pass

        # Request a larger logo for the details pane
        try:
            self.media.get_logo_async(symbol, cb, large=True)
        except Exception:
            # Fallback: small logo
            try:
                self.media.get_logo_async(symbol, cb)
            except Exception:
                pass

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
            items = sorted(self._positions_cache, key=lambda p: p.get('value') or 0, reverse=True)[
                :20
            ]
            for row in self.tree_search.get_children():
                self.tree_search.delete(row)
            for i, p in enumerate(items):
                tag = 'even' if i % 2 == 0 else 'odd'
                sym = p.get('symbol') or ''
                iid = self.tree_search.insert(
                    '',
                    tk.END,
                    text=sym,
                    values=(sym, p.get('name'), '', 'Held', 'Oui', p.get('currency') or ''),
                    tags=(tag,),
                )
                try:
                    self._attach_logo_to_item(self.tree_search, iid, sym)
                except Exception:
                    pass
            self._set_search_details(
                "Suggestions par défaut: vos positions principales affichées. "
                "Lancez une recherche pour plus de titres."
            )
        except Exception:
            pass

    def _update_search_suggestions(self):
        query = (self.var_search_query.get() or '').strip().upper()
        # Cacher si vide
        if not query:
            try:
                if self.lst_search_suggestions.winfo_ismapped():
                    self.lst_search_suggestions.place_forget()
            except Exception:
                pass
            try:
                if (
                    hasattr(self, 'lst_search_suggestions2')
                    and self.lst_search_suggestions2.winfo_ismapped()
                ):
                    self.lst_search_suggestions2.place_forget()
            except Exception:
                pass
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
            try:
                if self.lst_search_suggestions.winfo_exists():
                    self.lst_search_suggestions.delete(0, tk.END)
                    for m in matches:
                        self.lst_search_suggestions.insert(tk.END, m)
            except Exception:
                pass
            try:
                if (
                    hasattr(self, 'lst_search_suggestions2')
                    and self.lst_search_suggestions2.winfo_exists()
                ):
                    self.lst_search_suggestions2.delete(0, tk.END)
                    for m in matches:
                        self.lst_search_suggestions2.insert(tk.END, m)
            except Exception:
                pass

        try:
            if hasattr(self, '_search_debounce_id') and self._search_debounce_id:
                self.after_cancel(self._search_debounce_id)
        except Exception:
            pass
        self._search_debounce_id = self.after(300, _apply_list)
        # Positionner sous le champ (approx) - placement simple
        try:
            self.lst_search_suggestions.place(x=200, y=0)
        except Exception:
            pass
        try:
            if hasattr(self, 'lst_search_suggestions2'):
                self.lst_search_suggestions2.place(x=200, y=0)
        except Exception:
            pass

    def _apply_search_suggestion(self):
        sel = None
        try:
            sel = self.lst_search_suggestions.curselection()
        except Exception:
            sel = None
        if not sel:
            try:
                sel = (
                    self.lst_search_suggestions2.curselection()
                    if hasattr(self, 'lst_search_suggestions2')
                    else None
                )
            except Exception:
                sel = None
        if not sel:
            return
        try:
            symbol = self.lst_search_suggestions.get(sel[0])
        except Exception:
            symbol = (
                self.lst_search_suggestions2.get(sel[0])
                if hasattr(self, 'lst_search_suggestions2')
                else ''
            )
        self.var_search_query.set(symbol)
        self.lst_search_suggestions.place_forget()
        try:
            if hasattr(self, 'lst_search_suggestions2'):
                self.lst_search_suggestions2.place_forget()
        except Exception:
            pass
        self.search_securities()

    # --------- Manual Order helpers ---------
    def _update_order_form_state(self):
        try:
            otype = (self.var_order_type.get() or '').lower()
            # Enable/disable price fields
            if otype == 'market':
                self.ent_order_limit.configure(state=tk.DISABLED)
                self.ent_order_stop.configure(state=tk.DISABLED)
            elif otype == 'limit':
                self.ent_order_limit.configure(state=tk.NORMAL)
                self.ent_order_stop.configure(state=tk.DISABLED)
            elif otype == 'stop':
                self.ent_order_limit.configure(state=tk.DISABLED)
                self.ent_order_stop.configure(state=tk.NORMAL)
            elif otype == 'stop_limit':
                self.ent_order_limit.configure(state=tk.NORMAL)
                self.ent_order_stop.configure(state=tk.NORMAL)
        except Exception:
            pass

    def _set_order_allowed_types(self, subtypes: list[str] | None):
        """Map WS allowedOrderSubtypes to our supported list and update combobox."""
        try:
            mapping = {
                'MARKET': 'market',
                'LIMIT': 'limit',
                'STOP': 'stop',
                'STOP_LIMIT': 'stop_limit',
                'STOPLIMIT': 'stop_limit',
                'TRAILING_STOP': None,  # not supported yet
            }
            allowed = ['market', 'limit', 'stop', 'stop_limit']
            if subtypes and isinstance(subtypes, list):
                vals = []
                for s in subtypes:
                    k = mapping.get(str(s).upper())
                    if k and k not in vals:
                        vals.append(k)
                if vals:
                    allowed = vals
            self.cb_order_type.configure(values=allowed)
            if (self.var_order_type.get() or '') not in allowed:
                self.var_order_type.set(allowed[0])
            self._update_order_form_state()
        except Exception:
            pass

    def _submit_manual_order(self):
        symbol = (self.var_order_symbol.get() or '').strip().upper()
        if not symbol:
            self.set_status("Ordre: symbole manquant.", error=True)
            return
        side = (self.var_order_side.get() or 'buy').lower()
        otype = (self.var_order_type.get() or 'market').lower()
        tif = (self.var_order_tif.get() or 'day').lower()
        # Parse numbers

        def _pfloat(v):
            try:
                vv = str(v).strip()
                return float(vv) if vv else None
            except Exception:
                return None

        qty = _pfloat(self.var_order_qty.get())
        notional = _pfloat(self.var_order_notional.get())
        limit_p = _pfloat(self.var_order_limit.get())
        stop_p = _pfloat(self.var_order_stop.get())
        # Ensure executor
        if not hasattr(self, '_trade_exec') or self._trade_exec is None:
            self._trade_exec = TradeExecutor(self.api_manager)
            try:
                self._trade_exec.configure_simple(
                    enabled=True, mode='paper', base_size=notional or 1000.0
                )
            except Exception:
                pass
        # Temporarily switch mode for this order if requested
        want_live = bool(self.var_order_live.get())
        prev_mode = getattr(self._trade_exec, 'mode', 'paper')
        try:
            if want_live:
                self._trade_exec.configure(mode='live', enabled=True)
            else:
                self._trade_exec.configure(mode='paper', enabled=True)
        except Exception:
            pass
        # Submit
        try:
            order = self._trade_exec.place_order(
                symbol=symbol,
                side=side,
                order_type=otype,
                qty=qty,
                notional=notional,
                limit_price=limit_p,
                stop_price=stop_p,
                time_in_force=tif,
            )
            status = order.get('status')
            if status == 'filled':
                filled_qty = order.get('filled_qty')
                avg_price = order.get('avg_fill_price')
                self.set_status(
                    f"Ordre exécuté: {side} {symbol} {filled_qty} @ {avg_price}"
                )
            elif status == 'open':
                self.set_status(f"Ordre en attente: {side} {otype} {symbol}")
            else:
                self.set_status(f"Ordre rejeté: {order.get('reason', 'inconnu')}", error=True)
        except Exception as e:
            self.set_status(f"Ordre erreur: {e}", error=True, details=repr(e))
        finally:
            # Restore previous mode
            try:
                self._trade_exec.configure(mode=prev_mode)
            except Exception:
                pass

    def _open_search_from_tree(self, tree: ttk.Treeview):
        try:
            sel = tree.selection()
            if not sel:
                return
            idx = tree.index(sel[0])
            if idx >= len(self._search_results):
                return
            # Temporarily point tree_search to the requested one for logo attach
            prev_tree = getattr(self, 'tree_search', None)
            self.tree_search = tree
            try:
                self.open_search_security_details()
            finally:
                if prev_tree is not None:
                    self.tree_search = prev_tree
        except Exception:
            pass

    # ------------------- Persistance UI divers -------------------
    def _on_tab_changed(self, _event=None):
        try:
            nb = self._main_notebook
            idx = nb.index(nb.select())
            app_config.set('ui.last_tab', int(idx))
        except Exception:
            pass

    # ---- Accessibility & theming helpers ----
    def _detect_system_theme(self) -> str:
        """Best-effort detection of system theme on Windows (defaults to light)."""
        try:
            import winreg  # type: ignore

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize",
            ) as key:
                # AppsUseLightTheme == 0 means dark
                val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
                return 'light' if int(val) == 1 else 'dark'
        except Exception:
            return 'light'

    def _apply_font_size(self):
        try:
            size = max(8, min(20, int(self._font_scale.get() or 10)))
            family = getattr(self, '_font_family', None)
            family_name = family.get() if family else None
            import tkinter.font as tkfont

            default_fonts = [
                'TkDefaultFont',
                'TkTextFont',
                'TkMenuFont',
                'TkHeadingFont',
                'TkTooltipFont',
            ]
            for fname in default_fonts:
                try:
                    f = tkfont.nametofont(fname)
                    if family_name:
                        f.configure(size=size, family=family_name)
                    else:
                        f.configure(size=size)
                except Exception:
                    pass
            app_config.set('ui.font.size', int(size))
            if family_name:
                app_config.set('ui.font.family', str(family_name))
        except Exception:
            pass

    # ---- Tree sorting and layout persistence ----
    def _on_tree_heading_click(self, tree: ttk.Treeview, col: str, numeric=False):
        # toggle sort and update header text with indicator
        try:
            descending = getattr(tree, f'_sort_desc_{col}', False)
            # Run sort
            self.sort_tree(tree, col, numeric=numeric)
            new_desc = not descending
            setattr(tree, f'_sort_desc_{col}', new_desc)
            # Update header labels to show arrow on active column
            for c in tree['columns']:
                txt = tree.heading(c, 'text')
                base = str(txt).replace(' ↑', '').replace(' ↓', '')
                if c == col:
                    base += ' ' + ('↑' if not new_desc else '↓')
                tree.heading(c, text=base)
        except Exception:
            self.sort_tree(tree, col, numeric=numeric)

    def _restore_tree_layout(self, tree: ttk.Treeview, key: str):
        try:
            widths = app_config.get(f'ui.tables.{key}.widths', {}) or {}
            for c in tree['columns']:
                w = widths.get(c)
                if isinstance(w, int) and w > 20:
                    tree.column(c, width=w)
        except Exception:
            pass

    def _save_tree_layouts(self):
        try:
            mapping = {
                'positions': getattr(self, 'tree_positions', None),
                'activities': getattr(self, 'tree_acts', None),
                'search': getattr(self, 'tree_search', None),
                'news': getattr(self, 'tree_news', None),
                'gainers': getattr(self, 'tree_gainers', None),
                'losers': getattr(self, 'tree_losers', None),
                'active': getattr(self, 'tree_active', None),
                'opps': getattr(self, 'tree_opps', None),
            }
            for key, tree in mapping.items():
                if not tree:
                    continue
                widths = {}
                for c in tree['columns']:
                    try:
                        widths[c] = int(tree.column(c, 'width'))
                    except Exception:
                        pass
                app_config.set(f'ui.tables.{key}.widths', widths)
        except Exception:
            pass

    def _bind_persist_notebook(self, nb: ttk.Notebook, key: str) -> None:
        """Bind a notebook to persist its selected tab index under ui.tabs.{key}.index."""
        try:

            def _on_change(_e=None, _nb=nb, _key=key):  # noqa
                try:
                    idx = _nb.index(_nb.select())
                    app_config.set(f'ui.tabs.{_key}.index', int(idx))
                except Exception:
                    pass

            nb.bind('<<NotebookTabChanged>>', _on_change)
        except Exception:
            pass

    def _restore_notebook_tab(self, nb: ttk.Notebook, key: str) -> None:
        """Restore the saved tab selection for a given notebook."""
        try:
            idx = int(app_config.get(f'ui.tabs.{key}.index', 0) or 0)
            tabs = nb.tabs()
            if 0 <= idx < len(tabs):
                nb.select(tabs[idx])
        except Exception:
            pass

    def _on_close(self):
        try:
            app_config.save_window_geometry(self.geometry())
        except Exception:
            pass
        try:
            self._save_tree_layouts()
        except Exception:
            pass
        self.destroy()

    def _apply_positions_quick_filter(self):
        try:
            q = (self.var_pos_quick.get() or '').strip().lower()
        except Exception:
            q = ''
        # if no cache yet, nothing to do
        if not isinstance(getattr(self, '_positions_cache', None), list):
            return
        # Clear and re-fill
        try:
            for row in self.tree_positions.get_children():
                self.tree_positions.delete(row)
        except Exception:
            return
        for pos in self._positions_cache:
            sym = str(pos.get('symbol') or '').lower()
            name = str(pos.get('name') or '').lower()
            if q and q not in sym and q not in name:
                continue
            val = pos.get('value') or 0.0
            pnl_pct = pos.get('pnlPct')
            avg = pos.get('avgPrice')
            arrow_pct = ''
            if isinstance(pnl_pct, (int, float)):
                arrow_pct = ('↑' if pnl_pct >= 0 else '↓') + f"{abs(pnl_pct):.2f}%"
                if pos.get('pnlIsDaily'):
                    arrow_pct += '*'
            idx = len(self.tree_positions.get_children())
            base_tag = 'even' if idx % 2 == 0 else 'odd'
            pnl_tag = None
            if isinstance(pnl_pct, (int, float)):
                pnl_tag = 'pnl_pos' if pnl_pct >= 0 else 'pnl_neg'
            tags = (base_tag,) + ((pnl_tag,) if pnl_tag else tuple())
            iid = self.tree_positions.insert(
                '',
                tk.END,
                text=str(pos.get('symbol') or ''),
                values=(
                    pos.get('symbol'),
                    pos.get('name'),
                    pos.get('quantity'),
                    (pos.get('lastPrice') if pos.get('lastPrice') is not None else ''),
                    f"{val:.2f}" if val else '',
                    pos.get('currency') or '',
                    f"{avg:.2f}" if isinstance(avg, (int, float)) else '',
                    arrow_pct,
                    (
                        f"{pos.get('pnlAbs'):,.2f}"
                        if isinstance(pos.get('pnlAbs'), (int, float))
                        else ''
                    ),
                ),
                tags=tags,
            )
            try:
                self._attach_logo_to_item(self.tree_positions, iid, pos.get('symbol') or '')
            except Exception:
                pass

    # ------------------- Paramètres: helpers -------------------
    def _refresh_profile_info(self):
        """Remplit les informations de profil dans l'onglet Paramètres."""
        try:
            name = None
            email = ''
            if self.api:
                try:
                    name = self.api.get_identity_display_name()
                except Exception:
                    name = None
                try:
                    tok = self.api.get_token_info() or {}
                    email = tok.get('email') or tok.get('username') or ''
                except Exception:
                    email = ''
            if not name:
                name = 'Non connecté'
            if hasattr(self, '_var_prof_name'):
                self._var_prof_name.set(name)
            if hasattr(self, '_var_prof_email'):
                self._var_prof_email.set(email)
        except Exception:
            pass

    def _logout(self):
        """Déconnexion manuelle: stop intégrations, efface session, réinitialise l'UI."""
        try:
            # Stop Telegram bridge if running
            try:
                self._stop_telegram_bridge()
            except Exception:
                pass
            # Effacer session.json (à la racine du projet)
            try:
                root = Path(__file__).resolve().parent.parent
                sess_path = root / 'session.json'
                if sess_path.exists():
                    sess_path.unlink(missing_ok=True)
            except Exception:
                pass
            # Reset API and caches
            self.api = None
            self.accounts = []
            self.current_account_id = None
            self._positions_cache = []
            self._activities_cache = []
            # Clear UI lists/trees
            try:
                self.list_accounts.delete(0, tk.END)
            except Exception:
                pass
            for tree_name in [
                'tree_positions',
                'tree_acts',
                'tree_gainers',
                'tree_losers',
                'tree_active',
                'tree_opps',
                'tree_search',
                'tree_news',
                'tree_signals',
            ]:
                try:
                    tree = getattr(self, tree_name, None)
                    if tree:
                        for iid in tree.get_children():
                            tree.delete(iid)
                except Exception:
                    pass
            # Reset greeting and show login button
            try:
                self.lbl_greeting.grid_remove()
                self.btn_connect.grid()
                self.var_greeting.set('')
            except Exception:
                pass
            # Update settings/profile
            self._refresh_profile_info()
            self.set_status('Déconnecté')
        except Exception as e:
            self.set_status(f"Déconnexion: {e}", error=True)

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
    def update_movers(self, top_n: int | None = None):
        """Remplit les tableaux gagnants / perdants / actifs / opportunités.

        Priorité:
          - Si API externe disponible: scan marché canadien (gainers/losers/actives) 
            via Yahoo screener
          - Sinon: fallback heuristique basé sur PnL des positions du portefeuille
        """
        # Ensure at least one movers tree exists
        if not hasattr(self, 'tree_gainers') and not hasattr(self, 'tree_gainers_compact'):
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
                                sym = (q.get('symbol') or '').strip().upper()
                                iid = tree.insert('', tk.END, text=sym, values=vals, tags=(tag,))
                                try:
                                    self._attach_logo_to_item(tree, iid, sym)
                                except Exception:
                                    pass

                        gainers = movers.get('gainers') or []
                        losers = movers.get('losers') or []
                        actives = movers.get('actives') or []
                        opps = movers.get('opportunities') or (losers[: max(1, top_n // 2)])
                        tgt_gainers = getattr(self, 'tree_gainers', None) or getattr(
                            self, 'tree_gainers_compact', None
                        )
                        tgt_losers = getattr(self, 'tree_losers', None) or getattr(
                            self, 'tree_losers_compact', None
                        )
                        fill_tree(
                            tgt_gainers,
                            gainers,
                            lambda q: (
                                q.get('symbol'),
                                f"{q.get('changePct', 0):.2f}",
                                f"{q.get('change', 0):.2f}",
                                f"{q.get('price', 0):.2f}",
                                q.get('volume'),
                            ),
                        )
                        fill_tree(
                            tgt_losers,
                            losers,
                            lambda q: (
                                q.get('symbol'),
                                f"{q.get('changePct', 0):.2f}",
                                f"{q.get('change', 0):.2f}",
                                f"{q.get('price', 0):.2f}",
                                q.get('volume'),
                            ),
                        )
                        fill_tree(
                            self.tree_active,
                            actives,
                            lambda q: (
                                q.get('symbol'),
                                f"{q.get('price', 0):.2f}",
                                f"{q.get('changePct', 0):.2f}",
                                f"{q.get('change', 0):.2f}",
                                q.get('volume'),
                            ),
                        )
                        fill_tree(
                            self.tree_opps,
                            opps,
                            lambda q: (
                                q.get('symbol'),
                                f"{q.get('changePct', 0):.2f}",
                                f"{q.get('change', 0):.2f}",
                                f"{q.get('price', 0):.2f}",
                                q.get('volume'),
                            ),
                        )
                        gainer_count = len(gainers)
                        loser_count = len(losers) 
                        active_count = len(actives)
                        status_msg = f"Mouvements (CA): +{gainer_count} / -{loser_count} / actifs {active_count}"
                        self.set_status(status_msg)
                        # Recolor according to Pct change
                        try:
                            pal = self._palettes[self._theme]
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
                                            str(cols[pnl_idx]).replace('%', '').replace('*', '')
                                        )
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
            p
            for p in losers
            if (
                pnl_pct(p) <= -5  # Forte baisse relative
                or pnl_abs(p) <= -100  # Perte absolue significative
                or (
                    pnl_pct(p) < 0 and val(p) > 500 and abs(pnl_pct(p)) <= 8
                )  # Baisse modérée sur grosse position
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
                    f"{pnl_pct(p):.2f}" if tree is not self.tree_active else f"{val(p):.2f}"
                )
                iid = tree.insert(
                    '',
                    tk.END,
                    text=str(p.get('symbol') or ''),
                    values=(
                        p.get('symbol'),
                        pnl_or_val,
                        f"{pnl_abs(p):.2f}",
                        f"{val(p):.2f}",
                        p.get('quantity'),
                    ),
                    tags=(tag,),
                )
                try:
                    self._attach_logo_to_item(tree, iid, p.get('symbol') or '')
                except Exception:
                    pass

        def fill_specific(tree, items, cols):
            for row in tree.get_children():
                tree.delete(row)
            for i, p in enumerate(items[:top_n]):
                tag = 'even' if i % 2 == 0 else 'odd'
                iid = tree.insert(
                    '', tk.END, text=str(p.get('symbol') or ''), values=cols(p), tags=(tag,)
                )
                try:
                    self._attach_logo_to_item(tree, iid, p.get('symbol') or '')
                except Exception:
                    pass

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
                    (
                        f"{p.get('symbol')} ({p.get('pnlPct'):.1f}%)"
                        if isinstance(p.get('pnlPct'), (int, float))
                        else p.get('symbol')
                    )
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
                        v = float(str(cols[pnl_idx]).replace('%', '').replace('*', ''))
                    except Exception:
                        v = 0.0
                    color = pal.get('success') if v >= 0 else pal.get('danger')
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
                    score = sum(1 for w in pos_words if w in text) - sum(
                        1 for w in neg_words if w in text
                    )
                    a['sentimentScore'] = score
                    enriched.append(a)
                articles = enriched
                self.after(0, lambda: self._update_news_tree(articles))
            except Exception as e:
                self.after(0, lambda e=e: self.set_status(f"Erreur actualités: {e}", error=True))

        threading.Thread(target=worker, daemon=True).start()

    def _schedule_news_auto(self):
        try:
            app_config.set('ui.news.auto', bool(self.var_news_auto.get()))
            app_config.set('ui.news.seconds', int(self.var_news_seconds.get()))
        except Exception:
            pass
        # Cancel previous if any
        try:
            if getattr(self, '_news_auto_id', None):
                self.after_cancel(self._news_auto_id)
        except Exception:
            pass
        if self.var_news_auto.get():
            # Trigger immediate refresh then schedule
            try:
                self.refresh_news()
            except Exception:
                pass
            try:
                secs = max(30, int(self.var_news_seconds.get()))
            except Exception:
                secs = 120
            self._news_auto_id = self.after(secs * 1000, self._news_auto_tick)

    def _news_auto_tick(self):
        if not self.var_news_auto.get():
            return
        try:
            self.refresh_news()
        except Exception:
            pass
        try:
            secs = max(30, int(self.var_news_seconds.get()))
        except Exception:
            secs = 120
        self._news_auto_id = self.after(secs * 1000, self._news_auto_tick)

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

    def _update_news_tree(self, articles: list[dict]):
        """Met à jour le TreeView des actualités."""
        # keep for URL open action
        try:
            self._news_articles = list(articles or [])
        except Exception:
            self._news_articles = list(articles or [])
        # Clear existing
        try:
            self._news_url_by_iid = {}
        except Exception:
            self._news_url_by_iid = {}
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
            iid = self.tree_news.insert('', tk.END, values=(source, title, published, sentiment))
            try:
                url = article.get('url') or ''
                if url:
                    self._news_url_by_iid[str(iid)] = url
            except Exception:
                pass

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

    def _display_market_overview(self, overview: dict):
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
                title = (
                    article.get('title', '')[:60] + '...'
                    if len(article.get('title', '')) > 60
                    else article.get('title', '')
                )
                lines.append(f"• {title}")

        self._append_output('\n'.join(lines))

    def _schedule_movers_auto(self):
        try:
            app_config.set('ui.movers.auto', bool(self.var_movers_auto.get()))
            app_config.set('ui.movers.seconds', int(self.var_movers_seconds.get()))
        except Exception:
            pass
        # Cancel previous
        try:
            if getattr(self, '_movers_auto_id', None):
                self.after_cancel(self._movers_auto_id)
        except Exception:
            pass
        if self.var_movers_auto.get():
            try:
                self.update_movers()
            except Exception:
                pass
            try:
                secs = max(30, int(self.var_movers_seconds.get()))
            except Exception:
                secs = 120
            self._movers_auto_id = self.after(secs * 1000, self._movers_auto_tick)

    def _movers_auto_tick(self):
        if not self.var_movers_auto.get():
            return
        try:
            self.update_movers()
        except Exception:
            pass
        try:
            secs = max(30, int(self.var_movers_seconds.get()))
        except Exception:
            secs = 120
        self._movers_auto_id = self.after(secs * 1000, self._movers_auto_tick)

    def _schedule_search_auto(self):
        try:
            app_config.set('ui.search.auto', bool(self.var_search_auto.get()))
            app_config.set('ui.search.seconds', int(self.var_search_seconds.get()))
        except Exception:
            pass
        try:
            if getattr(self, '_search_auto_id', None):
                self.after_cancel(self._search_auto_id)
        except Exception:
            pass
        if self.var_search_auto.get():
            try:
                self.search_securities()
            except Exception:
                pass
            try:
                secs = max(30, int(self.var_search_seconds.get()))
            except Exception:
                secs = 180
            self._search_auto_id = self.after(secs * 1000, self._search_auto_tick)

    def _search_auto_tick(self):
        if not self.var_search_auto.get():
            return
        try:
            self.search_securities()
        except Exception:
            pass
        try:
            secs = max(30, int(self.var_search_seconds.get()))
        except Exception:
            secs = 180
        self._search_auto_id = self.after(secs * 1000, self._search_auto_tick)

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
                total_pnl = sum(
                    float(p.get('pnlAbs', 0)) for p in self._positions_cache if p.get('pnlAbs')
                )
                positions_count = len(
                    [p for p in self._positions_cache if float(p.get('value', 0)) > 0]
                )

                success = self.api_manager.telegram.send_portfolio_summary(
                    total_value, total_pnl, positions_count
                )

                if success:
                    self.after(0, lambda: self.set_status("Notification Telegram envoyée"))
                else:
                    self.after(
                        0, lambda: self.set_status("Erreur envoi notification Telegram", error=True)
                    )

            except Exception as e:
                self.after(0, lambda e=e: self.set_status(f"Erreur notification: {e}", error=True))

        threading.Thread(target=worker, daemon=True).start()


# Fin de classe
__all__ = ["WSApp"]


if __name__ == '__main__':
    app = WSApp()
    app.mainloop()
