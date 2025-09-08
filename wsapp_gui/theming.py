"""Module de gestion des thèmes pour l'application Wealthsimple.

Améliorations:
- Support de thèmes additionnels
- Gestion d'accessibilité
- Configuration dynamique des couleurs
- Système de thèmes extensible
"""

from __future__ import annotations

import logging
import tkinter as tk
from tkinter import ttk
from typing import Any

logger = logging.getLogger(__name__)

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
    # Blue theme (alternative cool tone)
    'blue': {
        'bg': '#f0f4f8',
        'panel': '#ffffff',
        'surface': '#e2e8f0',
        'border': '#a0aec0',
        'text': '#2d3748',
        'text_muted': '#4a5568',
        'accent': '#3182ce',
        'accent_hover': '#2c5282',
        'accent_bg': '#bee3f8',
        'sel': '#3182ce',
        'sel_text': '#ffffff',
        'success': '#38a169',
        'danger': '#e53e3e',
        'danger_bg': '#fed7d7',
        'pnl_pos': '#38a169',
        'pnl_neg': '#e53e3e',
    },
    # Green theme (nature-inspired)
    'green': {
        'bg': '#f0f7f0',
        'panel': '#ffffff',
        'surface': '#e8f5e8',
        'border': '#a7d6a7',
        'text': '#1a2e1a',
        'text_muted': '#4a5e4a',
        'accent': '#2e7d32',
        'accent_hover': '#1b5e20',
        'accent_bg': '#c8e6c9',
        'sel': '#2e7d32',
        'sel_text': '#ffffff',
        'success': '#1b5e20',
        'danger': '#c62828',
        'danger_bg': '#ffcdd2',
        'pnl_pos': '#1b5e20',
        'pnl_neg': '#c62828',
    },
}

class ThemeManager:
    """Gestionnaire avancé de thèmes avec fonctionnalités étendues."""

    def __init__(self):
        self.current_theme = 'light'
        self.custom_palettes: dict[str, dict[str, str]] = {}

    def register_custom_palette(self, name: str, palette: dict[str, str]) -> None:
        """Enregistre une palette personnalisée."""
        required_keys = {'bg', 'panel', 'text', 'accent'}
        if not required_keys.issubset(palette.keys()):
            missing = required_keys - palette.keys()
            raise ValueError(f"Palette incomplète. Clés manquantes: {missing}")

        self.custom_palettes[name] = palette
        logger.info(f"Palette personnalisée '{name}' enregistrée")

    def get_available_themes(self) -> list[str]:
        """Retourne la liste des thèmes disponibles."""
        return list(PALETTES.keys()) + list(self.custom_palettes.keys())

    def get_palette(self, name: str) -> dict[str, str]:
        """Récupère une palette par nom."""
        if name in self.custom_palettes:
            return self.custom_palettes[name]
        return PALETTES.get(name, PALETTES['light'])

    def is_dark_theme(self, name: str) -> bool:
        """Détermine si un thème est sombre."""
        palette = self.get_palette(name)
        # Analyse basée sur la luminosité du background
        bg_color = palette.get('bg', '#ffffff')
        # Simple heuristique: si le background est sombre
        if bg_color.startswith('#'):
            try:
                rgb_sum = sum(int(bg_color[i:i+2], 16) for i in (1, 3, 5))
                return rgb_sum < 384  # 128 * 3 / 2
            except ValueError:
                pass
        return name in ['dark', 'high']

    def adjust_palette_for_accessibility(self, palette: dict[str, str],
                                       high_contrast: bool = False) -> dict[str, str]:
        """Ajuste une palette pour l'accessibilité."""
        if not high_contrast:
            return palette.copy()

        # Version haute contraste
        adjusted = palette.copy()
        if self.is_dark_theme('_temp'):  # Utilise palette temporaire pour test
            adjusted.update({
                'text': '#ffffff',
                'bg': '#000000',
                'panel': '#000000',
                'accent': '#ffff00',
                'success': '#00ff00',
                'danger': '#ff0000'
            })
        else:
            adjusted.update({
                'text': '#000000',
                'bg': '#ffffff',
                'panel': '#ffffff',
                'accent': '#0000ff',
                'success': '#008000',
                'danger': '#ff0000'
            })
        return adjusted


def apply_palette(root: tk.Misc, name: str, high_contrast: bool = False) -> str:
    """Applique une palette de couleurs avec options d'accessibilité."""
    try:
        theme_manager = ThemeManager()
        base_palette = theme_manager.get_palette(name)

        if high_contrast:
            pal = theme_manager.adjust_palette_for_accessibility(base_palette, True)
        else:
            pal = base_palette

        style = ttk.Style()

        # Utiliser un thème qui permet la personnalisation des couleurs
        try:
            style.theme_use('clam')
        except Exception as e:
            logger.warning(f"Impossible d'utiliser le thème 'clam': {e}")

        _apply_root_styles(root, pal)
        _apply_widget_styles(style, pal)

        logger.info(f"Thème '{name}' appliqué" + (" (haute contraste)" if high_contrast else ""))
        return name if name in PALETTES else 'light'

    except Exception as e:
        logger.error(f"Erreur application thème '{name}': {e}")
        # Fallback vers le thème par défaut
        return apply_palette(root, 'light', False)


def _apply_root_styles(root: tk.Misc, pal: dict[str, str]) -> None:
    """Applique les styles à la fenêtre racine."""
    root.configure(bg=pal['bg'])


def _apply_widget_styles(style: ttk.Style, pal: dict[str, str]) -> None:
    """Applique les styles aux widgets TTK."""
    # Styles de base
    style.configure(
        '.',
        background=pal['panel'],
        foreground=pal['text'],
        bordercolor=pal['border'],
    )

    # Labels
    style.configure('TLabel', background=pal['panel'], foreground=pal['text'])
    style.configure('Muted.TLabel', background=pal['panel'], foreground=pal['text_muted'])
    style.configure('TFrame', background=pal['panel'])

    # Notebook et onglets
    style.configure('TNotebook', background=pal['panel'])
    style.configure('TNotebook.Tab', padding=(10, 4))
    style.map(
        'TNotebook.Tab',
        background=[('selected', pal['surface'])],
        foreground=[('disabled', pal['text_muted'])],
    )

    # Boutons avec amélioration du contraste
    _configure_button_styles(style, pal)

    # Champs de saisie
    _configure_entry_styles(style, pal)

    # Combobox
    _configure_combobox_styles(style, pal)

    # Treeview
    _configure_treeview_styles(style, pal)

    # Scrollbars
    _configure_scrollbar_styles(style, pal)

    # Progressbar
    _configure_progressbar_styles(style, pal)


def _configure_button_styles(style: ttk.Style, pal: dict[str, str]) -> None:
    """Configure les styles des boutons."""
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


def _configure_entry_styles(style: ttk.Style, pal: dict[str, str]) -> None:
    """Configure les styles des champs de saisie."""
    style.configure(
        'TEntry',
        fieldbackground=pal['surface'],
        foreground=pal['text'],
        insertcolor=pal['text'],
        bordercolor=pal['border'],
        highlightcolor=pal['accent'],
    )


def _configure_combobox_styles(style: ttk.Style, pal: dict[str, str]) -> None:
    """Configure les styles des combobox."""
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
        style.configure('ComboboxPopdownFrame',
                       background=pal['panel'],
                       bordercolor=pal['border'])
    except Exception as e:
        logger.debug(f"Erreur configuration combobox: {e}")


def _configure_treeview_styles(style: ttk.Style, pal: dict[str, str]) -> None:
    """Configure les styles des treeview."""
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


def _configure_scrollbar_styles(style: ttk.Style, pal: dict[str, str]) -> None:
    """Configure les styles des scrollbars."""
    try:
        style.configure('Vertical.TScrollbar',
                       background=pal['surface'],
                       troughcolor=pal['panel'])
        style.configure('Horizontal.TScrollbar',
                       background=pal['surface'],
                       troughcolor=pal['panel'])
    except Exception as e:
        logger.debug(f"Erreur configuration scrollbar: {e}")


def _configure_progressbar_styles(style: ttk.Style, pal: dict[str, str]) -> None:
    """Configure les styles des progressbars."""
    try:
        style.configure(
            'Horizontal.TProgressbar',
            background=pal['accent'],
            troughcolor=pal['surface']
        )
    except Exception as e:
        logger.debug(f"Erreur configuration progressbar: {e}")


def get_theme_preview(theme_name: str) -> dict[str, Any]:
    """Génère un aperçu d'un thème pour l'interface utilisateur."""
    theme_manager = ThemeManager()
    palette = theme_manager.get_palette(theme_name)

    return {
        'name': theme_name,
        'display_name': theme_name.title(),
        'is_dark': theme_manager.is_dark_theme(theme_name),
        'colors': {
            'background': palette.get('bg'),
            'panel': palette.get('panel'),
            'text': palette.get('text'),
            'accent': palette.get('accent'),
        },
        'description': _get_theme_description(theme_name)
    }


def _get_theme_description(theme_name: str) -> str:
    """Retourne une description du thème."""
    descriptions = {
        'light': 'Thème clair par défaut, facile à lire',
        'dark': 'Thème sombre pour réduire la fatigue oculaire',
        'high': 'Thème haute contraste pour l\'accessibilité',
        'blue': 'Thème bleu apaisant pour une utilisation prolongée',
        'green': 'Thème vert nature pour un environnement relaxant',
    }
    return descriptions.get(theme_name, 'Thème personnalisé')

__all__ = ["PALETTES", "apply_palette", "ThemeManager", "get_theme_preview"]
