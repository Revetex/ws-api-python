"""Telegram UI helper for wsapp GUI."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

from .config import app_config
from .ui_utils import set_combobox_enabled


class TelegramUI:
    """Encapsulates Telegram controls for the GUI."""

    def __init__(
        self,
        parent: tk.Widget,
        api_manager,
        agent,
        start_cb: Callable[[], None],
        stop_cb: Callable[[], None],
        test_cb: Callable[[], None],
    ) -> None:
        self.parent = parent
        self.api_manager = api_manager
        self.agent = agent
        self._start_cb = start_cb
        self._stop_cb = stop_cb
        self._test_cb = test_cb

        self._tg_connected = tk.BooleanVar(value=False)
        self._tg_msg_count = tk.IntVar(value=0)
        self.var_tg_chat = tk.StringVar(
            value=str(app_config.get('integrations.telegram.chat_id', ''))
        )
        self.var_tg_auto = tk.BooleanVar(
            value=bool(app_config.get('integrations.telegram.enabled', False))
        )
        self.var_tg_tech = tk.BooleanVar(
            value=bool(app_config.get('integrations.telegram.include_technical', True))
        )
        self.var_tg_tech_fmt = tk.StringVar(
            value=str(app_config.get('integrations.telegram.tech_format', 'plain') or 'plain')
        )
        self._cmb_fmt: ttk.Combobox | None = None

    def render(self) -> None:
        tab_tg = ttk.Frame(self.parent)
        self.parent.add(tab_tg, text='Telegram')
        ttop = ttk.Frame(tab_tg)
        ttop.pack(fill=tk.X, padx=6, pady=6)
        ttk.Label(ttop, text='Bot configuré:').pack(side=tk.LEFT)
        has_token = (
            bool(getattr(self.api_manager.telegram, 'bot_token', None))
            if self.api_manager
            else False
        )
        ttk.Label(
            ttop, text='Oui' if has_token else 'Non', foreground=('green' if has_token else 'red')
        ).pack(side=tk.LEFT, padx=4)
        ttk.Label(ttop, textvariable=self._tg_connected, foreground='gray').pack(
            side=tk.LEFT, padx=(8, 0)
        )
        ttk.Label(ttop, text='Msgs:').pack(side=tk.LEFT, padx=(12, 0))
        ttk.Label(ttop, textvariable=self._tg_msg_count).pack(side=tk.LEFT)

        ttk.Label(ttop, text='Chat ID:').pack(side=tk.LEFT, padx=(12, 2))
        ent_tg = ttk.Entry(ttop, width=18, textvariable=self.var_tg_chat)
        ent_tg.pack(side=tk.LEFT)

        def _save_tg_chat_id(*_):
            app_config.set('integrations.telegram.chat_id', (self.var_tg_chat.get() or '').strip())

        self.var_tg_chat.trace_add('write', _save_tg_chat_id)

        def _on_tg_enabled_toggle():
            app_config.set('integrations.telegram.enabled', bool(self.var_tg_auto.get()))
            set_combobox_enabled(self._cmb_fmt, self.var_tg_auto.get())

        ttk.Checkbutton(
            ttop, text='Auto démarrage', variable=self.var_tg_auto, command=_on_tg_enabled_toggle
        ).pack(side=tk.LEFT, padx=(12, 0))

        def _on_toggle_tech():
            val = bool(self.var_tg_tech.get())
            app_config.set('integrations.telegram.include_technical', val)
            try:
                self.agent.allow_technical_alerts = val
            except Exception:
                pass

        ttk.Checkbutton(
            ttop,
            text='Alertes techniques (SMA)',
            variable=self.var_tg_tech,
            command=_on_toggle_tech,
        ).pack(side=tk.LEFT, padx=(12, 0))

        ttk.Label(ttop, text='Format TECH_*:').pack(side=tk.LEFT, padx=(12, 4))
        self._cmb_fmt = ttk.Combobox(
            ttop,
            state='readonly',
            width=10,
            textvariable=self.var_tg_tech_fmt,
            values=('plain', 'emoji-rich'),
        )
        self._cmb_fmt.pack(side=tk.LEFT)
        set_combobox_enabled(
            self._cmb_fmt, bool(app_config.get('integrations.telegram.enabled', False))
        )

        def _on_fmt_change(_evt=None):
            app_config.set('integrations.telegram.tech_format', self.var_tg_tech_fmt.get())

        self._cmb_fmt.bind('<<ComboboxSelected>>', _on_fmt_change)

        btns = ttk.Frame(tab_tg)
        btns.pack(fill=tk.X, padx=6, pady=4)
        ttk.Button(btns, text='Démarrer chat', command=self._start_cb).pack(side=tk.LEFT)
        ttk.Button(btns, text='Arrêter', command=self._stop_cb).pack(side=tk.LEFT, padx=4)
        ttk.Button(btns, text='Message test', command=self._test_cb).pack(side=tk.LEFT, padx=4)
        ttk.Label(
            tab_tg,
            text="Contrôlez l'agent via Telegram lorsque le chat est actif (limité au chat ID).",
            foreground='gray',
        ).pack(fill=tk.X, padx=6)

    # Exposed setters for outer updates
    def set_connected(self, val: bool) -> None:
        try:
            self._tg_connected.set(val)
        except Exception:
            pass

    def inc_msg_count(self) -> None:
        try:
            self._tg_msg_count.set(self._tg_msg_count.get() + 1)
        except Exception:
            pass
