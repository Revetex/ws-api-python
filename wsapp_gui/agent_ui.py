from __future__ import annotations
from typing import Iterable
from datetime import datetime
import tkinter as tk
from tkinter import ttk
from ai_agent import AIAgent, Signal


class AgentUI:
    def __init__(self, agent: AIAgent, tree: ttk.Treeview):
        self.agent = agent
        self.tree = tree

    def refresh_signals(self):
        if not self.tree:
            return
        for row in self.tree.get_children():
            self.tree.delete(row)
        signals: Iterable[Signal] = self.agent.get_signals()
        for sig in list(signals)[-100:]:
            level_tag = f"lvl_{sig.level.lower()}"
            symbol = sig.meta.get('symbol') if isinstance(sig.meta, dict) else ''
            self.tree.insert(
                '',
                tk.END,
                values=(
                    datetime.fromtimestamp(sig.ts).strftime('%H:%M:%S'),
                    sig.level,
                    symbol or '',
                    sig.code,
                    sig.message,
                ),
                tags=(level_tag,),
            )


__all__ = ["AgentUI"]
