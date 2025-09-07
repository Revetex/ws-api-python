from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from ..config import app_config


class HelpersMixin:
    def apply_theme(self, name: str) -> None:
        from ..theming import apply_palette

        try:
            apply_palette(self, name)  # type: ignore[arg-type]
            setattr(self, "_theme", name)
            app_config.set("theme", name)
        except Exception:
            pass

    def toggle_theme(self) -> None:
        try:
            cur = getattr(self, "_theme", "light")
            self.apply_theme("dark" if cur == "light" else "light")
        except Exception:
            pass

    def sort_tree(self, tree: ttk.Treeview, col: str, numeric: bool = False) -> None:
        items = list(tree.get_children(""))
        idx = tree["columns"].index(col) if col in tree["columns"] else 0

        def _key(iid: Any) -> Any:
            val = tree.item(iid, "values")[idx]
            if not numeric:
                return str(val)
            try:
                return float(str(val).replace(",", "").replace("%", ""))
            except Exception:
                return 0.0

        items.sort(key=_key, reverse=True if numeric else False)
        for iid in items:
            tree.move(iid, "", "end")

    def _add_tree_context(self, tree: ttk.Treeview) -> None:
        menu = tk.Menu(tree, tearoff=0)
        menu.add_command(label="Copier ligne", command=lambda: self._copy_selected(tree))  # type: ignore[attr-defined]

        def popup(ev: Any) -> None:
            iid = tree.identify_row(ev.y)
            if iid:
                tree.selection_set(iid)
                menu.tk_popup(ev.x_root, ev.y_root)

        tree.bind("<Button-3>", popup)

    def _copy_selected(self, tree: ttk.Treeview) -> None:
        sel = tree.selection()
        if not sel:
            return
        vals = tree.item(sel[0], "values")
        try:
            cc = getattr(self, "clipboard_clear", None)
            ca = getattr(self, "clipboard_append", None)
            upd = getattr(self, "update", None)
            if callable(cc):
                cc()
            if callable(ca):
                ca("\t".join(str(v) for v in vals))
            if callable(upd):
                upd()
        except Exception:
            pass

    def set_status(self, msg: str, error: bool = False, details: str | None = None) -> None:
        try:
            var = getattr(self, "var_status", None)
            if var is not None:
                var.set(msg)
            if error and details:
                print(msg, "-", details)
        except Exception:
            pass

    def clear_all_caches(self) -> None:
        try:
            media = getattr(self, "media", None)
            if media and hasattr(media, "clear_cache"):
                media.clear_cache()
        except Exception:
            pass
        self.set_status("Caches vidés")

    def _apply_ai_prefs(self) -> None:
        import tkinter as _tk

        try:
            var = getattr(self, "var_ai_enhanced", _tk.BooleanVar(value=False))
            app_config.set("ai.enhanced", bool(var.get()))
            self.set_status("Préférences IA appliquées")
        except Exception:
            pass

    def toggle_tradingview_enabled(self) -> None:
        try:
            cur = bool(app_config.get("ui.tradingview.enabled", False))
            app_config.set("ui.tradingview.enabled", not cur)
            self.set_status("TradingView activé" if not cur else "TradingView désactivé")
        except Exception:
            pass

    def _append_chat(self, text: str) -> None:
        widget = getattr(self, "text_chat", None) or getattr(self, "txt_chat", None)
        if not widget:
            return
        try:
            state = str(widget.cget("state")) if "state" in widget.keys() else "normal"
        except Exception:
            state = "normal"
        try:
            if state != "normal":
                widget.configure(state="normal")
            widget.insert("end", text)
            widget.see("end")
        finally:
            try:
                if state != "normal":
                    widget.configure(state=state)
            except Exception:
                pass
