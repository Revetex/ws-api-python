"""GUI package refactor.

Expose WSApp and modular managers.
"""

from .agent_ui import AgentUI
from .app import WSApp
from .charts import ChartController
from .chat_manager import ChatManager
from .config import app_config
from .export_manager import ExportManager

# Gestionnaires modulaires
from .login_manager import LoginManager
from .news_manager import NewsManager
from .portfolio_manager import PortfolioManager
from .search_manager import SearchManager
from .theming import PALETTES, apply_palette
from .ui_builder import UIBuilder

__all__ = [
    "WSApp",
    "ChartController",
    "AgentUI",
    "PALETTES",
    "apply_palette",
    "app_config",
    "LoginManager",
    "PortfolioManager",
    "SearchManager",
    "NewsManager",
    "ChatManager",
    "UIBuilder",
    "ExportManager",
]
