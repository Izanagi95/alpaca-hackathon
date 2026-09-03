from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.alpaca.client import AlpacaClients
from app.config.settings import Settings


def main() -> int:
    settings = Settings.from_env(PROJECT_ROOT / ".env")
    settings.require_paper_mode()
    settings.require_credentials()

    account = AlpacaClients(settings).verify_account()
    # Two different identifiers, and submission forms ask for either: `id` is
    # the UUID the API uses, `account_number` is the PA... string the Alpaca
    # dashboard shows. Print both so there's nothing to look up elsewhere.
    print(f"account_id={account.id}")
    print(f"account_number={account.account_number}")
    print(f"status={account.status}")
    print(f"equity={account.equity}")
    print(f"buying_power={account.buying_power}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"FAILED: {error}", file=sys.stderr)
        raise SystemExit(1) from error
