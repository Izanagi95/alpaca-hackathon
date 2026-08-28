import os

import pytest


pytestmark = pytest.mark.integration


@pytest.mark.skipif(
    not os.getenv("ALPACA_API_KEY") or not os.getenv("ALPACA_SECRET_KEY"),
    reason="Alpaca paper credentials are not configured",
)
def test_read_only_integration_check() -> None:
    from scripts.integration_check import main

    assert main() == 0
