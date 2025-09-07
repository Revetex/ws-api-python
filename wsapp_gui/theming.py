from __future__ import annotations

import tkinter as tk
from tkinter import ttk

PALETTES: dict[str, dict[str, str]] = {
    'light': {
        'bg': '#edf1f5',  # slightly darker for contrast
        'panel': '#ffffff',
        'surface': '#e2e8f0',  # darker surface
        'border': '#c3ccd6',
        'text': '#1e2530',
        'text_muted': '#5b6778',
        'accent': '#1d60d6',
        'accent_hover': '#184fae',
        # Info banner background (subtle)
        'accent_bg': '#dbeafe',
        'sel': '#1d60d6',
        'sel_text': '#ffffff',
        'success': '#047857',
        'danger': '#b91c1c',
        # Error banner background (subtle)
        'danger_bg': '#fee2e2',
        # PnL colors (allow color-blind adjustments via theme)
        'pnl_pos': '#047857',
        'pnl_neg': '#b91c1c',
    },
    'dark': {
        'bg': '#0d1320',  # deeper background
        'panel': '#1b2533',  # slightly lighter than before
        'surface': '#253244',
        'border': '#3a4a5e',
        'text': '#f2f6fa',
        'text_muted': '#8897ac',
        'accent': '#3d82f7',
        'accent_hover': '#2563eb',
        'accent_bg': '#1e3a8a',
        'sel': '#2f6dd9',
        'sel_text': '#f8fafc',
        'success': '#059669',
        'danger': '#dc2626',
        'danger_bg': '#3f1d1d',
        'pnl_pos': '#10b981',
        'pnl_neg': '#ef4444',
    },
    # High-contrast palette (accessibility)
    'high': {
        'bg': '#000000',
        'panel': '#000000',
        'surface': '#111111',
        'border': '#ffffff',
        'text': '#ffffff',
        'text_muted': '#e0e0e0',
        'accent': '#ffff00',
        'accent_hover': '#ffd400',
        'accent_bg': '#333300',
        'sel': '#00ffff',
        'sel_text': '#000000',
        'success': '#00ff00',
        'danger': '#ff3333',
        'danger_bg': '#330000',
        'pnl_pos': '#00ff00',
        'pnl_neg': '#ff3333',
    },
}


def apply_palette(root: tk.Misc, name: str) -> str:
    pal = PALETTES.get(name) or PALETTES['light']
    style = ttk.Style()
    # Use a theme that allows color customization
    # (native Windows theme ignores many color settings)
    try:
        style.theme_use('clam')
    except Exception:  # pragma: no cover
        pass
    root.configure(bg=pal['bg'])
    style.configure(
        '.',
        background=pal['panel'],
        foreground=pal['text'],
        bordercolor=pal['border'],
    )
    # Common label styles, including a muted variant used for helper texts
    style.configure('TLabel', background=pal['panel'], foreground=pal['text'])
    style.configure('Muted.TLabel', background=pal['panel'], foreground=pal['text_muted'])
    style.configure('TFrame', background=pal['panel'])
    style.configure('TNotebook', background=pal['panel'])
    style.configure('TNotebook.Tab', padding=(10, 4))
    style.map(
        'TNotebook.Tab',
        background=[('selected', pal['surface'])],
        foreground=[('disabled', pal['text_muted'])],
    )
    # Buttons: force high contrast foreground mapping for all states
    style.configure(
        'TButton',
        background=pal['accent'],
        foreground=pal['sel_text'],
        relief='flat',
        padding=(8, 4),
        focuscolor=pal['accent'],
        bordercolor=pal['accent'],
    )
    style.map(
        'TButton',
        background=[
            ('disabled', pal['panel']),
            ('pressed', pal['accent_hover']),
            ('active', pal['accent_hover']),
        ],
        foreground=[
            ('disabled', pal['text_muted']),
            ('pressed', pal['sel_text']),
            ('active', pal['sel_text']),
        ],
    )
    # Entry fields: stronger contrast
    style.configure(
        'TEntry',
        fieldbackground=pal['surface'],
        foreground=pal['text'],
        insertcolor=pal['text'],
        bordercolor=pal['border'],
        highlightcolor=pal['accent'],
    )
    # Combobox: improve readability especially in dark mode
    try:
        style.configure(
            'TCombobox',
            fieldbackground=pal['surface'],
            foreground=pal['text'],
            bordercolor=pal['border'],
            arrowsize=14,
        )
        style.map(
            'TCombobox',
            fieldbackground=[
                ('readonly', pal['surface']),
                ('!readonly', pal['surface']),
                ('focus', pal['surface']),
            ],
            foreground=[
                ('readonly', pal['text']),
                ('!readonly', pal['text']),
                ('focus', pal['text']),
            ],
        )
        # Drop-down list frame (best-effort; may vary by platform)
        style.configure('ComboboxPopdownFrame', background=pal['panel'], bordercolor=pal['border'])
    except Exception:
        pass
    style.configure(
        'Treeview',
        background=pal['panel'],
        fieldbackground=pal['panel'],
        foreground=pal['text'],
        bordercolor=pal['border'],
    )
    style.configure(
        'Treeview.Heading',
        background=pal['surface'],
        foreground=pal['text'],
    )
    style.map(
        'Treeview',
        background=[('selected', pal['sel'])],
        foreground=[('selected', pal['sel_text'])],
    )
    # Scrollbar colors for better visibility
    try:
        style.configure('Vertical.TScrollbar', background=pal['surface'], troughcolor=pal['panel'])
        style.configure(
            'Horizontal.TScrollbar', background=pal['surface'], troughcolor=pal['panel']
        )
    except Exception:
        pass
    # Progressbar
    try:
        style.configure(
            'Horizontal.TProgressbar', background=pal['accent'], troughcolor=pal['surface']
        )
    except Exception:
        pass
    return name if name in PALETTES else 'light'


__all__ = ["PALETTES", "apply_palette"]
