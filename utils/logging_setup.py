"""Central logging configuration.

Call setup_logging() early in application start.
"""
from __future__ import annotations
import logging
import sys

_DEF_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def setup_logging(level: int = logging.INFO) -> None:
    if logging.getLogger().handlers:
        return  # already configured
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_DEF_FORMAT))
    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)
