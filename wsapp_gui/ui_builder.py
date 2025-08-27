"""Module de construction de l'interface utilisateur pour l'application Wealthsimple."""

from __future__ import annotations
import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .app import WSApp

# Constantes pour les symboles de découverte
DISCOVER_SYMBOLS = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "AMD", "INTC", "ORCL",
    "SHOP", "BN", "BNS", "RY", "TD", "ENB", "SU", "CNQ", "WEED", "BTC", "ETH",
]


class UIBuilder:
    """Constructeur de l'interface utilisateur."""

    def __init__(self, app: WSApp):
        self.app = app

    def build_ui(self) -> None:
        """Construit l'interface utilisateur complète."""
        # Menu principal
        self._build_menu_bar()

        # Barre de statut
        self._build_status_bar()

        # Notebook principal
        self.notebook = ttk.Notebook(self.app)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        # Construction des onglets
        self._build_login_tab()
        self._build_positions_tab()
        self._build_search_tab()
        self._build_news_tab()
        self._build_chat_tab()

        # Raccourcis clavier
        self._setup_keyboard_shortcuts()

    def _build_menu_bar(self) -> None:
        """Construit la barre de menu."""
        menubar = tk.Menu(self.app)
        self.app.config(menu=menubar)

        # Menu Fichier
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Fichier", menu=file_menu)
        file_menu.add_command(label="Exporter positions...", command=self.app.export_manager.export_positions_csv)
        file_menu.add_command(label="Exporter activités...", command=self.app.export_manager.export_activities_csv)
        file_menu.add_command(label="Exporter résultats recherche...", command=self.app.export_manager.export_search_results_csv)
        file_menu.add_command(label="Rapport de portefeuille...", command=self.app.export_manager.generate_portfolio_report)
        file_menu.add_separator()
        file_menu.add_command(label="Quitter", command=self.app.quit)

        # Menu Affichage
        view_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Affichage", menu=view_menu)
        view_menu.add_command(label="Basculer thème", command=self.app.toggle_theme)
        view_menu.add_command(label="Vider les caches", command=self.app.clear_all_caches)

        # Menu Aide
        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Aide", menu=help_menu)
        help_menu.add_command(label="À propos", command=self._show_about)

    def _setup_keyboard_shortcuts(self) -> None:
        """Configure les raccourcis clavier."""
        self.app.bind('<Control-r>', lambda e: self.app.portfolio_manager.refresh_accounts())
        self.app.bind('<Control-t>', lambda e: self.app.toggle_theme())
        self.app.bind('<Control-q>', lambda e: self.app.quit())
        # Focus rapide sur la recherche si disponible
        self.app.bind('<Control-f>', lambda e: getattr(self.app, 'entry_search', None) and self.app.entry_search.focus_set())
        self.app.bind('<F5>', lambda e: self.app.portfolio_manager.refresh_accounts())

    def _show_about(self) -> None:
        """Affiche la boîte de dialogue À propos."""
        # Utiliser la bannière d'information non bloquante plutôt qu'une popup
        self.app.set_status(
            "Wealthsimple Assistant — Application de gestion de portefeuille avec IA (version refactorisée et modulaire)",
            error=False,
        )

    def _build_status_bar(self) -> None:
        """Construit la barre de statut."""
        status = ttk.Label(self.app, textvariable=self.app.var_status, anchor=tk.W)
        status.pack(fill=tk.X, side=tk.BOTTOM)

    def _build_login_tab(self) -> None:
        """Construit l'onglet de connexion."""
        tab_login = ttk.Frame(self.notebook)
        self.notebook.add(tab_login, text="Connexion")

        # Frame principal
        frame = ttk.Frame(tab_login, padding=10)
        frame.pack(anchor=tk.NW)

        # Champs de connexion
        ttk.Label(frame, text="Email").grid(row=0, column=0, sticky=tk.W, pady=2)
        self.app.entry_email = ttk.Entry(frame, textvariable=self.app.var_email, width=32)
        self.app.entry_email.grid(row=0, column=1, pady=2)

        ttk.Label(frame, text="Mot de passe").grid(row=1, column=0, sticky=tk.W, pady=2)
        self.app.entry_password = ttk.Entry(frame, textvariable=self.app.var_password, width=32, show="*")
        self.app.entry_password.grid(row=1, column=1, pady=2)

        ttk.Label(frame, text="Code OTP").grid(row=2, column=0, sticky=tk.W, pady=2)
        self.app.entry_otp = ttk.Entry(frame, textvariable=self.app.var_otp, width=16)
        self.app.entry_otp.grid(row=2, column=1, sticky=tk.W, pady=2)

        # Boutons
        self.app.btn_login = ttk.Button(frame, text="Se connecter", command=self.app.login_manager.login_clicked)
        self.app.btn_login.grid(row=3, column=0, columnspan=2, pady=10)

        # Entrée pour valider avec Entrée
        for w in (self.app.entry_email, self.app.entry_password, self.app.entry_otp):
            w.bind('<Return>', lambda e: self.app.login_manager.login_clicked())

        ttk.Button(frame, text="Basculer thème", command=self.app.toggle_theme).grid(row=4, column=0, columnspan=2, pady=5)

    def _build_positions_tab(self) -> None:
        """Construit l'onglet des positions."""
        tab_positions = ttk.Frame(self.notebook)
        self.notebook.add(tab_positions, text="Positions")

        # Frame principal
        main_frame = ttk.Frame(tab_positions, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Sélection de compte
        account_frame = ttk.Frame(main_frame)
        account_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(account_frame, text="Compte:").pack(side=tk.LEFT)
        self.app.combo_accounts = ttk.Combobox(account_frame, state="readonly", width=40)
        self.app.combo_accounts.pack(side=tk.LEFT, padx=(5, 10))
        self.app.combo_accounts.bind('<<ComboboxSelected>>', self.app.portfolio_manager.on_account_selected)

        ttk.Button(account_frame, text="Actualiser", command=self.app.portfolio_manager.refresh_accounts).pack(side=tk.LEFT)

        # Boutons d'export
        export_frame = ttk.Frame(main_frame)
        export_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Button(export_frame, text="Exporter positions", command=self.app.export_manager.export_positions_csv).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(export_frame, text="Exporter activités", command=self.app.export_manager.export_activities_csv).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(export_frame, text="Rapport complet", command=self.app.export_manager.generate_portfolio_report).pack(side=tk.LEFT)

        # Notebook pour positions et activités
        details_nb = ttk.Notebook(main_frame)
        details_nb.pack(fill=tk.BOTH, expand=True)

        # Onglet positions
        pos_frame = ttk.Frame(details_nb)
        details_nb.add(pos_frame, text="Positions")

        self.app.tree_positions = ttk.Treeview(pos_frame, columns=("Symbol", "Name", "Quantity", "Value"), show="headings")
        self.app.tree_positions.heading("Symbol", text="Symbole", command=lambda: self.app.sort_tree(self.app.tree_positions, "Symbol"))
        self.app.tree_positions.heading("Name", text="Nom", command=lambda: self.app.sort_tree(self.app.tree_positions, "Name"))
        self.app.tree_positions.heading("Quantity", text="Quantité", command=lambda: self.app.sort_tree(self.app.tree_positions, "Quantity", True))
        self.app.tree_positions.heading("Value", text="Valeur", command=lambda: self.app.sort_tree(self.app.tree_positions, "Value", True))
        self.app.tree_positions.pack(fill=tk.BOTH, expand=True)

        # Onglet activités
        act_frame = ttk.Frame(details_nb)
        details_nb.add(act_frame, text="Activités")

        self.app.tree_activities = ttk.Treeview(act_frame, columns=("Date", "Type", "Description", "Amount"), show="headings")
        self.app.tree_activities.heading("Date", text="Date", command=lambda: self.app.sort_tree(self.app.tree_activities, "Date"))
        self.app.tree_activities.heading("Type", text="Type", command=lambda: self.app.sort_tree(self.app.tree_activities, "Type"))
        self.app.tree_activities.heading("Description", text="Description", command=lambda: self.app.sort_tree(self.app.tree_activities, "Description"))
        self.app.tree_activities.heading("Amount", text="Montant", command=lambda: self.app.sort_tree(self.app.tree_activities, "Amount", True))
        self.app.tree_activities.pack(fill=tk.BOTH, expand=True)

    def _build_search_tab(self) -> None:
        """Construit l'onglet de recherche."""
        tab_search = ttk.Frame(self.notebook)
        self.notebook.add(tab_search, text="Recherche")

        # Frame principal
        main_frame = ttk.Frame(tab_search, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Frame de recherche
        search_frame = ttk.Frame(main_frame)
        search_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(search_frame, text="Rechercher:").pack(side=tk.LEFT)
        self.app.entry_search = ttk.Entry(search_frame, textvariable=self.app.var_search, width=20)
        self.app.entry_search.pack(side=tk.LEFT, padx=(5, 5))
        self.app.entry_search.bind('<Return>', lambda e: self.app.search_manager.search_securities())
        ttk.Button(search_frame, text="Rechercher", command=self.app.search_manager.search_securities).pack(side=tk.LEFT)

        # Boutons de découverte
        discover_frame = ttk.LabelFrame(main_frame, text="Symboles populaires", padding=5)
        discover_frame.pack(fill=tk.X, pady=(0, 10))

        for i, symbol in enumerate(DISCOVER_SYMBOLS[:10]):  # Afficher seulement les 10 premiers
            ttk.Button(discover_frame, text=symbol, width=8,
                       command=lambda s=symbol: self.app.search_manager._discover_click(s)).grid(
                row=i // 5, column=i % 5, padx=2, pady=2)

        # Frame de résultats
        results_frame = ttk.Frame(main_frame)
        results_frame.pack(fill=tk.BOTH, expand=True)

        # Tableau de résultats
        left_frame = ttk.Frame(results_frame)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.app.tree_search = ttk.Treeview(left_frame, columns=("Symbol", "Name", "Exchange", "Buyable"), show="headings")
        self.app.tree_search.heading("Symbol", text="Symbole")
        self.app.tree_search.heading("Name", text="Nom")
        self.app.tree_search.heading("Exchange", text="Bourse")
        self.app.tree_search.heading("Buyable", text="Achetable")
        self.app.tree_search.pack(fill=tk.BOTH, expand=True)
        self.app.tree_search.bind('<Double-1>', lambda e: self.app.search_manager.open_search_security_details())

        # Zone de détails
        right_frame = ttk.Frame(results_frame)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, padx=(10, 0))

        ttk.Label(right_frame, text="Détails du titre").pack(anchor=tk.W)
        self.app.text_search_details = tk.Text(right_frame, width=40, height=20)
        self.app.text_search_details.pack(fill=tk.BOTH, expand=True)

    def _build_news_tab(self) -> None:
        """Construit l'onglet actualités et données intraday."""
        tab_news = ttk.Frame(self.notebook)
        self.notebook.add(tab_news, text="Marché & Actualités")

        # Frame principal
        main_frame = ttk.Frame(tab_news, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Notebook pour intraday et actualités
        news_nb = ttk.Notebook(main_frame)
        news_nb.pack(fill=tk.BOTH, expand=True)

        # Onglet intraday
        intraday_frame = ttk.Frame(news_nb)
        news_nb.add(intraday_frame, text="Données intraday")

        # Controls intraday
        controls_frame = ttk.Frame(intraday_frame)
        controls_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(controls_frame, text="Symbole:").pack(side=tk.LEFT)
        self.app.entry_intraday = ttk.Entry(controls_frame, textvariable=self.app.var_intraday_symbol, width=10)
        self.app.entry_intraday.pack(side=tk.LEFT, padx=(5, 5))
        self.app.entry_intraday.bind('<Return>', lambda e: self.app.news_manager.load_intraday())
        ttk.Button(controls_frame, text="Charger", command=self.app.news_manager.load_intraday).pack(side=tk.LEFT)

        # Zone pour le graphique (sera utilisée par ChartController)
        self.app.chart_frame = ttk.Frame(intraday_frame)
        self.app.chart_frame.pack(fill=tk.BOTH, expand=True)

        # Onglet actualités
        news_frame = ttk.Frame(news_nb)
        news_nb.add(news_frame, text="Actualités")

        # Controls actualités
        news_controls = ttk.Frame(news_frame)
        news_controls.pack(fill=tk.X, pady=(0, 10))

        ttk.Button(news_controls, text="Actualiser actualités", command=self.app.news_manager.load_news).pack(side=tk.LEFT)

        # Tableau d'actualités
        self.app.tree_news = ttk.Treeview(news_frame, columns=("Title", "Source", "Date"), show="headings")
        self.app.tree_news.heading("Title", text="Titre")
        self.app.tree_news.heading("Source", text="Source")
        self.app.tree_news.heading("Date", text="Date")
        self.app.tree_news.pack(fill=tk.BOTH, expand=True)
        self.app.tree_news.bind('<Double-1>', lambda e: self.app.news_manager.open_news_url())

    def _build_chat_tab(self) -> None:
        """Construit l'onglet de chat et signaux IA."""
        tab_chat = ttk.Frame(self.notebook)
        self.notebook.add(tab_chat, text="Chat & Signaux")

        # Frame principal
        main_frame = ttk.Frame(tab_chat, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Notebook pour chat et signaux
        chat_nb = ttk.Notebook(main_frame)
        chat_nb.pack(fill=tk.BOTH, expand=True)

        # Onglet chat
        chat_frame = ttk.Frame(chat_nb)
        chat_nb.add(chat_frame, text="Chat IA")

        # Zone de chat
        self.app.text_chat = tk.Text(chat_frame, height=15, state=tk.NORMAL)
        self.app.text_chat.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # Zone de saisie
        input_frame = ttk.Frame(chat_frame)
        input_frame.pack(fill=tk.X)

        self.app.entry_chat = ttk.Entry(input_frame, textvariable=self.app.var_chat)
        self.app.entry_chat.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        self.app.entry_chat.bind('<Return>', lambda e: self.app.chat_manager._chat_send())
        ttk.Button(input_frame, text="Envoyer", command=self.app.chat_manager._chat_send).pack(side=tk.RIGHT)

        # Onglet signaux/mouvements
        signals_frame = ttk.Frame(chat_nb)
        chat_nb.add(signals_frame, text="Mouvements du marché")

        # Controls
        signals_controls = ttk.Frame(signals_frame)
        signals_controls.pack(fill=tk.X, pady=(0, 10))

        ttk.Button(signals_controls, text="Actualiser mouvements", command=self.app.chat_manager.update_movers).pack(side=tk.LEFT)

        # Tableau des mouvements
        self.app.tree_gainers = ttk.Treeview(signals_frame, columns=("Symbol", "Price", "Change"), show="headings")
        self.app.tree_gainers.heading("Symbol", text="Symbole")
        self.app.tree_gainers.heading("Price", text="Prix")
        self.app.tree_gainers.heading("Change", text="Variation")
        self.app.tree_gainers.pack(fill=tk.BOTH, expand=True)

        # Onglet préférences
        prefs_frame = ttk.Frame(chat_nb)
        chat_nb.add(prefs_frame, text="Préférences")

        # Options de notification
        notify_frame = ttk.LabelFrame(prefs_frame, text="Notifications", padding=10)
        notify_frame.pack(fill=tk.X, pady=10)

        ttk.Checkbutton(notify_frame, text="Notifications d'information", variable=self.app.notify_info).pack(anchor=tk.W)
        ttk.Checkbutton(notify_frame, text="Notifications d'avertissement", variable=self.app.notify_warn).pack(anchor=tk.W)
        ttk.Checkbutton(notify_frame, text="Notifications d'alerte", variable=self.app.notify_alert).pack(anchor=tk.W)
        ttk.Button(
            notify_frame,
            text="Sauvegarder préférences",
            command=self.app.chat_manager._update_notify_prefs,
        ).pack(pady=(10, 0))

        # Options IA améliorée
        ai_frame = ttk.LabelFrame(prefs_frame, text="Intelligence Artificielle", padding=10)
        ai_frame.pack(fill=tk.X, pady=10)
        # Backed by app_config setting
        try:
            import tkinter as tk
            from .config import app_config
            self.app.var_ai_enhanced = tk.BooleanVar(value=bool(app_config.get('ai.enhanced', False)))
        except Exception:
            # Fallback if config not available during tests
            import tkinter as tk
            self.app.var_ai_enhanced = tk.BooleanVar(value=False)
        ttk.Checkbutton(ai_frame, text="Activer le Conseiller (Enhanced AI)", variable=self.app.var_ai_enhanced).pack(anchor=tk.W)
        ttk.Button(
            ai_frame,
            text="Appliquer",
            command=lambda: self.app._apply_ai_prefs(),
        ).pack(pady=(10, 0))
