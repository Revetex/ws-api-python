"""UI utility helpers for Tkinter/ttk widgets.

Includes small helpers to toggle widget states, attach tooltips, and a
lightweight money formatter for consistent currency display.
"""

import tkinter as tk
from typing import Any

# Minimal currency symbol map; fallback to code at the end for clarity
_CURR_SYM = {
    'USD': '$',
    'CAD': 'C$',
    'EUR': '€',
    'GBP': '£',
    'JPY': '¥',
}


def format_money(
    value: float | int | None, currency: str | None = None, *, with_symbol: bool = False
) -> str:
    """Format a number with 2 decimals and append currency.

    - If ``with_symbol`` is True and a known mapping exists, prefix with the symbol (e.g., $).
    - Otherwise, append the currency code after the number (e.g., 123.45 CAD).
    - Returns an empty string for None values.
    """
    try:
        if value is None:
            return ''
        val = float(value)
        cur = (currency or '').upper() or 'CAD'
        if with_symbol and cur in _CURR_SYM:
            sym = _CURR_SYM[cur]
            return f"{sym}{val:,.2f}"
        # default: number followed by code for explicitness
        return f"{val:,.2f} {cur}"
    except Exception:
        return str(value) if value is not None else ''


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
        self._after_id: str | None = None
        self._tip: tk.Toplevel | None = None
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


__all__ = [
    'set_combobox_enabled',
    'set_widget_enabled',
    'attach_tooltip',
    'format_money',
]
