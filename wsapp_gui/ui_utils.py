"""UI utility helpers for Tkinter/ttk widgets."""

from typing import Any, Optional
import tkinter as tk


def set_combobox_enabled(cmb: Any, enabled: bool) -> None:
    """Enable/disable a ttk.Combobox, using 'readonly' when enabled."""
    try:
        cmb.configure(state=('readonly' if enabled else 'disabled'))
    except Exception:
        pass


def set_widget_enabled(widget: Any, enabled: bool) -> None:
    """Best-effort enable/disable for common ttk widgets (Entry, Button, Checkbutton)."""
    try:
        state = 'normal' if enabled else 'disabled'
        widget.configure(state=state)
    except Exception:
        pass


class _ToolTip:
    """Lightweight tooltip shown on hover after a short delay."""

    def __init__(self, widget: Any, text: str, delay_ms: int = 500) -> None:
        self.widget = widget
        self.text = text
        self.delay = delay_ms
        self._after_id: Optional[str] = None
        self._tip: Optional[tk.Toplevel] = None
        try:
            widget.bind('<Enter>', self._on_enter)
            widget.bind('<Leave>', self._on_leave)
            widget.bind('<ButtonPress>', self._on_leave)
        except Exception:
            pass

    def _on_enter(self, _evt=None):
        try:
            self._after_id = self.widget.after(self.delay, self._show)
        except Exception:
            pass

    def _on_leave(self, _evt=None):
        try:
            if self._after_id:
                self.widget.after_cancel(self._after_id)
                self._after_id = None
            if self._tip is not None:
                self._tip.destroy()
                self._tip = None
        except Exception:
            pass

    def _show(self):
        try:
            if self._tip is not None:
                return
            x = self.widget.winfo_rootx() + 12
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 8
            tip = tk.Toplevel(self.widget)
            tip.wm_overrideredirect(True)
            tip.wm_geometry(f"+{x}+{y}")
            lbl = tk.Label(
                tip,
                text=self.text,
                justify='left',
                background='#ffffe0',
                relief='solid',
                borderwidth=1,
                padx=6,
                pady=4,
                wraplength=360,
            )
            lbl.pack()
            self._tip = tip
        except Exception:
            pass


def attach_tooltip(widget: Any, text: str, delay_ms: int = 500) -> None:
    """Attach a hover tooltip with given text to any widget (best-effort)."""
    try:
        _ToolTip(widget, text, delay_ms)
    except Exception:
        pass
