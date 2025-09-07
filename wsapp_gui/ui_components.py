"""Enhanced UI components for consistent styling and modern design."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable


class WSFrame(ttk.Frame):
    """Enhanced frame with consistent styling."""

    def __init__(self, master=None, **kwargs):
        super().__init__(master, **kwargs)
        self.configure(style='Card.TFrame')


class WSCard(ttk.Frame):
    """Card-style container for grouping related content."""

    def __init__(self, master=None, title: str = "", **kwargs):
        super().__init__(master, style='Card.TFrame', **kwargs)

        if title:
            title_label = ttk.Label(self, text=title, style='CardTitle.TLabel')
            title_label.pack(anchor='w', padx=10, pady=(10, 5))

        # Content container
        self.content = ttk.Frame(self, style='CardContent.TFrame')
        self.content.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))


class WSButton(ttk.Button):
    """Enhanced button with consistent styling and hover effects."""

    def __init__(self, master=None, **kwargs):
        super().__init__(master, **kwargs)
        self.configure(style='WS.TButton')


class WSLabel(ttk.Label):
    """Enhanced label with consistent styling."""

    def __init__(self, master=None, **kwargs):
        super().__init__(master, **kwargs)
        self.configure(style='WS.TLabel')


class WSEntry(ttk.Entry):
    """Enhanced entry with validation and consistent styling."""

    def __init__(self, master=None, validator: Callable[[str], bool] | None = None, **kwargs):
        super().__init__(master, **kwargs)
        self.configure(style='WS.TEntry')
        self.validator = validator

        if validator:
            self.bind('<KeyRelease>', self._on_validate)

    def _on_validate(self, event=None):
        """Validate input on key release."""
        if self.validator:
            text = self.get()
            if not self.validator(text):
                self.configure(style='WSError.TEntry')
            else:
                self.configure(style='WS.TEntry')


class WSCombobox(ttk.Combobox):
    """Enhanced combobox with consistent styling."""

    def __init__(self, master=None, **kwargs):
        super().__init__(master, **kwargs)
        self.configure(style='WS.TCombobox')


class WSTreeview(ttk.Treeview):
    """Enhanced treeview with consistent styling and better UX."""

    def __init__(self, master=None, **kwargs):
        super().__init__(master, **kwargs)
        self.configure(style='WS.Treeview')

        # Enable alternating row colors
        self.tag_configure('oddrow', background='#f8f9fa')
        self.tag_configure('evenrow', background='#ffffff')

    def insert(self, parent, index, iid=None, **kwargs):
        """Override insert to add alternating row colors."""
        result = super().insert(parent, index, iid=iid, **kwargs)

        # Apply alternating colors
        children = self.get_children()
        for i, child in enumerate(children):
            if i % 2 == 0:
                self.item(child, tags=('evenrow',))
            else:
                self.item(child, tags=('oddrow',))

        return result


class WSNotebook(ttk.Notebook):
    """Enhanced notebook with better tab styling."""

    def __init__(self, master=None, **kwargs):
        super().__init__(master, **kwargs)
        self.configure(style='WS.TNotebook')


class WSProgressBar(ttk.Progressbar):
    """Enhanced progress bar with better styling."""

    def __init__(self, master=None, **kwargs):
        super().__init__(master, **kwargs)
        self.configure(style='WS.Horizontal.TProgressbar')


class WSStatusBar(ttk.Frame):
    """Status bar component for displaying application status."""

    def __init__(self, master=None, **kwargs):
        super().__init__(master, **kwargs)

        self.status_label = WSLabel(self, text="Prêt")
        self.status_label.pack(side=tk.LEFT, padx=5)

        # Progress bar (hidden by default)
        self.progress = WSProgressBar(self, mode='indeterminate')
        self.progress.pack(side=tk.RIGHT, padx=5)
        self.progress.pack_forget()

        self.progress_visible = False

    def set_status(self, text: str, error: bool = False):
        """Set status text."""
        self.status_label.configure(text=text)
        if error:
            self.status_label.configure(foreground='red')
        else:
            self.status_label.configure(foreground='black')

    def show_progress(self):
        """Show progress bar."""
        if not self.progress_visible:
            self.progress.pack(side=tk.RIGHT, padx=5)
            self.progress.start()
            self.progress_visible = True

    def hide_progress(self):
        """Hide progress bar."""
        if self.progress_visible:
            self.progress.stop()
            self.progress.pack_forget()
            self.progress_visible = False


class WSBanner(ttk.Frame):
    """Banner component for notifications and alerts."""

    def __init__(self, master=None, message: str = "", kind: str = "info", **kwargs):
        super().__init__(master, **kwargs)

        # Color mapping for different kinds
        colors = {'info': '#dbeafe', 'success': '#d1fae5', 'warning': '#fef3c7', 'error': '#fee2e2'}

        self.configure(style='Banner.TFrame')
        self.configure(bg=colors.get(kind, colors['info']))

        self.message_label = tk.Label(
            self,
            text=message,
            bg=colors.get(kind, colors['info']),
            fg='#1f2937',
            font=('TkDefaultFont', 10),
        )
        self.message_label.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10, pady=5)

        # Close button
        self.close_button = tk.Button(
            self,
            text='×',
            bg=colors.get(kind, colors['info']),
            fg='#6b7280',
            font=('TkDefaultFont', 12, 'bold'),
            bd=0,
            command=self.destroy,
        )
        self.close_button.pack(side=tk.RIGHT, padx=5)

    def set_message(self, message: str):
        """Update banner message."""
        self.message_label.configure(text=message)


def apply_modern_styles():
    """Apply modern styles to ttk widgets."""
    style = ttk.Style()

    # Card styles
    style.configure('Card.TFrame', background='#ffffff', relief='raised', borderwidth=1)
    style.configure('CardTitle.TLabel', font=('TkHeadingFont', 12, 'bold'), foreground='#1f2937')
    style.configure('CardContent.TFrame', background='#ffffff')

    # Button styles
    style.configure(
        'WS.TButton',
        font=('TkDefaultFont', 10),
        padding=(10, 5),
        relief='flat',
        background='#3b82f6',
        foreground='white',
    )
    style.map('WS.TButton', background=[('active', '#2563eb'), ('pressed', '#1d4ed8')])

    # Label styles
    style.configure('WS.TLabel', font=('TkDefaultFont', 10), foreground='#1f2937')

    # Entry styles
    style.configure(
        'WS.TEntry', font=('TkDefaultFont', 10), padding=(5, 2), relief='flat', borderwidth=1
    )
    style.configure(
        'WSError.TEntry',
        font=('TkDefaultFont', 10),
        padding=(5, 2),
        relief='flat',
        borderwidth=1,
        fieldbackground='#fef2f2',
    )

    # Combobox styles
    style.configure('WS.TCombobox', font=('TkDefaultFont', 10), padding=(5, 2))

    # Treeview styles
    style.configure(
        'WS.Treeview',
        font=('TkDefaultFont', 10),
        rowheight=25,
        background='#ffffff',
        fieldbackground='#ffffff',
    )
    style.configure(
        'WS.Treeview.Heading',
        font=('TkHeadingFont', 10, 'bold'),
        background='#f3f4f6',
        foreground='#1f2937',
    )

    # Notebook styles
    style.configure('WS.TNotebook', tabmargins=(2, 5, 2, 0))
    style.configure(
        'WS.TNotebook.Tab',
        font=('TkDefaultFont', 10),
        padding=(10, 5),
        background='#f3f4f6',
        foreground='#6b7280',
    )
    style.map(
        'WS.TNotebook.Tab',
        background=[('selected', '#ffffff')],
        foreground=[('selected', '#1f2937')],
    )

    # Progressbar styles
    style.configure(
        'WS.Horizontal.TProgressbar',
        background='#3b82f6',
        troughcolor='#e5e7eb',
        borderwidth=0,
        lightcolor='#3b82f6',
        darkcolor='#3b82f6',
    )

    # Banner styles
    style.configure('Banner.TFrame', relief='flat', borderwidth=0)


# Initialize modern styles when module is imported
apply_modern_styles()
