"""Lanceur minimal conservant le nom d'origine.

Exécution:
    python gui.py

La classe principale WSApp est définie dans wsapp_gui.app.
"""
from wsapp_gui import WSApp


def main() -> None:
    app = WSApp()
    app.mainloop()


if __name__ == '__main__':  # pragma: no cover
    main()
