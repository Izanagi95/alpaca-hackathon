"""Vercel's Python runtime looks for an ASGI `app` under api/. This module
adds no logic of its own — it re-exports the same FastAPI app used locally
and in tests (app/dashboard/app.py), so nothing about the dashboard itself
changes between environments.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.dashboard.app import app  # noqa: E402,F401
