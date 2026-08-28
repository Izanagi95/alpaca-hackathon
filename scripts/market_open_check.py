"""Prints 'true' or 'false' to stdout depending on whether the market is
currently open, per Alpaca's clock. Used by the GitHub Actions workflow to
skip a scheduled run entirely (no scan, no monitoring, no wasted API calls)
outside market hours, instead of guessing weekday/holiday rules locally.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.alpaca.client import AlpacaClients
from app.config.settings import Settings


def main() -> int:
    settings = Settings.from_env()
    settings.require_paper_mode()
    settings.require_credentials()
    clients = AlpacaClients(settings)
    clock = clients.trading.get_clock()
    print("true" if clock.is_open else "false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
