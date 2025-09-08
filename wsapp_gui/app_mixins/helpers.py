from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable

from ...utils.error_handler import handle_error
from ...utils.logging_setup import get_logger
from ..config import app_config

logger = get_logger('helpers_mixin')


class HelpersMixin:
    """Common small helpers mixed into the main app.

    All methods are fail-soft to avoid breaking the UI in headless or edge cases.
    """

    def apply_theme(self, name: str) -> None:
        """Apply a named theme palette and persist selection."""
        from ..theming import apply_palette

        try:
            apply_palette(self, name)  # type: ignore[arg-type]
            setattr(self, "_theme", name)
            app_config.set("theme", name)
        except Exception as e:
            logger.debug(f"apply_theme failed: {e}")

    def toggle_theme(self) -> None:
        """Toggle between light and dark themes."""
        try:
            cur = getattr(self, "_theme", "light")
            self.apply_theme("dark" if cur == "light" else "light")
        except Exception as e:
            logger.debug(f"toggle_theme failed: {e}")

    def sort_tree(self, tree: ttk.Treeview, col: str, numeric: bool = False) -> None:
        """Sort a Treeview by column. Numeric columns sort descending by default.

        Re-clicking the same column toggles the sort order for usability.
        """
        try:
            items = list(tree.get_children(""))
            columns = list(tree["columns"]) if "columns" in tree.keys() else []
            idx = columns.index(col) if col in columns else 0

            # Determine reverse order; numeric sorts desc by default
            base_reverse = True if numeric else False
            last_col = getattr(tree, "_last_sort_col", None)
            last_rev = getattr(tree, "_last_sort_reverse", base_reverse)
            reverse = (not last_rev) if last_col == col else base_reverse

            def _key(iid: Any) -> Any:
                vals = tree.item(iid, "values")
                val = vals[idx] if idx < len(vals) else ""
                if not numeric:
                    return str(val)
                try:
                    s = str(val).replace(",", "").replace("%", "").strip()
                    return float(s)
                except Exception:
                    return 0.0

            items.sort(key=_key, reverse=reverse)
            for iid in items:
                tree.move(iid, "", "end")

            setattr(tree, "_last_sort_col", col)
            setattr(tree, "_last_sort_reverse", reverse)
        except Exception as e:
            logger.debug(f"sort_tree failed: {e}")

    def _add_tree_context(self, tree: ttk.Treeview) -> None:
        """Attach a right-click context menu with copy action and Ctrl+C binding."""
        try:
            menu = tk.Menu(tree, tearoff=0)
            menu.add_command(
                label="Copier ligne",
                command=lambda: self._copy_selected(tree),  # type: ignore[attr-defined]
            )

            def popup(ev: Any) -> None:
                try:
                    iid = tree.identify_row(ev.y)
                    if iid:
                        tree.selection_set(iid)
                    menu.tk_popup(ev.x_root, ev.y_root)
                finally:
                    try:
                        menu.grab_release()
                    except Exception:
                        pass

            tree.bind("<Button-3>", popup)
            # Optional keyboard shortcut
            tree.bind("<Control-c>", lambda _e: self._copy_selected(tree))  # type: ignore[attr-defined]
        except Exception as e:
            logger.debug(f"_add_tree_context failed: {e}")

    def _copy_selected(self, tree: ttk.Treeview) -> None:
        """Copy the first selected row values to clipboard as TSV."""
        try:
            sel = tree.selection()
            if not sel:
                return
            vals = tree.item(sel[0], "values")
            txt = "\t".join(str(v) for v in vals)
            cc: Callable[[], None] | None = getattr(self, "clipboard_clear", None)
            ca: Callable[[str], None] | None = getattr(self, "clipboard_append", None)
            upd: Callable[[], None] | None = getattr(self, "update", None)
            if callable(cc):
                cc()
            if callable(ca):
                ca(txt)
            if callable(upd):
                upd()
        except Exception as e:
            logger.debug(f"_copy_selected failed: {e}")

    def set_status(self, msg: str, error: bool = False, details: str | None = None) -> None:
        """Set the inline status message and optionally log via error handler."""
        try:
            var = getattr(self, "var_status", None)
            if var is not None:
                var.set(msg)
            if error:
                handle_error(Exception(details or msg), context="status")
        except Exception as e:
            logger.debug(f"set_status failed: {e}")

    def clear_all_caches(self) -> None:
        """Clear media/API/sqlite caches when available and report status."""
        try:
            media = getattr(self, "media", None)
            if media and hasattr(media, "clear_cache"):
                media.clear_cache()
        except Exception as e:
            logger.debug(f"media.clear_cache failed: {e}")
        # API manager cache
        try:
            api = getattr(self, "api_manager", None)
            if api and hasattr(api, "clear_cache"):
                api.clear_cache()
        except Exception as e:
            logger.debug(f"api_manager.clear_cache failed: {e}")
        # Persistent SQLite cache
        try:
            from ...utils.sqlite_cache import PersistentCache

            pc = PersistentCache()
            stats = pc.stats() or {}
            for ns in list((stats.get('namespaces') or {}).keys()):
                try:
                    pc.clear_namespace(ns)
                except Exception:
                    pass
            pc.vacuum()
        except Exception as e:
            logger.debug(f"sqlite cache clear failed: {e}")
        self.set_status("Caches vidés")

    def _apply_ai_prefs(self) -> None:
        """Persist AI preferences from the UI toggle."""
        import tkinter as _tk

        try:
            var = getattr(self, "var_ai_enhanced", _tk.BooleanVar(value=False))
            app_config.set("ai.enhanced", bool(var.get()))
            self.set_status("Préférences IA appliquées")
        except Exception as e:
            logger.debug(f"_apply_ai_prefs failed: {e}")

    def toggle_tradingview_enabled(self) -> None:
        """Toggle embedded TradingView chart integration flag."""
        try:
            cur = bool(app_config.get("ui.tradingview.enabled", False))
            app_config.set("ui.tradingview.enabled", not cur)
            self.set_status("TradingView activé" if not cur else "TradingView désactivé")
        except Exception as e:
            logger.debug(f"toggle_tradingview_enabled failed: {e}")

    def _append_chat(self, text: str) -> None:
        """Append text to chat widget safely, preserving state."""
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
