"""Environment loading utilities (simple .env parser).

Usage:
    from utils.env import load_dotenv_safe
    load_dotenv_safe()

Won't overwrite existing environment variables. Silent on errors.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path

DEFAULT_ENV_FILENAMES: Iterable[str] = ('.env', '.env.local')


def load_dotenv_safe(
    filenames: Iterable[str] = DEFAULT_ENV_FILENAMES, base: Path | None = None
) -> None:
    base = base or Path(__file__).resolve().parent.parent
    for name in filenames:
        path = base / name
        if not path.exists():
            continue
        try:
            for line in path.read_text(encoding='utf-8').splitlines():
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                k, v = line.split('=', 1)
                k = k.strip()
                raw = v.strip()
                if raw.startswith(('"', "'")) and len(raw) > 1:
                    q = raw[0]
                    closing = raw.find(q, 1)
                    if closing != -1:
                        raw = raw[1:closing]
                else:
                    if '#' in raw:
                        raw = raw.split('#', 1)[0].rstrip()
                if k not in os.environ:
                    os.environ[k] = raw
        except Exception:
            # fail silent
            pass
