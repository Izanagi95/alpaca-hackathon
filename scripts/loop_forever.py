"""Runs the agent continuously for the multi-day competition window
(Monday 9:30 a.m. ET through Friday 9:30 a.m. ET): scan for new candidates,
then monitor and exit open positions, repeated on an interval, gated to
actual market hours via Alpaca's clock so it does not spam the API or
attempt trades while the market is closed.

Run with:

    .\\.venv\\Scripts\\python.exe scripts\\loop_forever.py

Stop with Ctrl+C. Intended to be left running (e.g. in a persistent terminal,
a scheduled task, or a small VM) for the whole scoring window; each iteration
is independent and safe to interrupt at any point, since every decision and
order is journaled immediately, not batched.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.alpaca.client import AlpacaClients
from app.config.settings import Settings

SCAN_INTERVAL_SECONDS = 15 * 60
MONITOR_INTERVAL_SECONDS = 5 * 60
CLOSED_MARKET_POLL_SECONDS = 5 * 60


def _run_subprocess(script_name: str) -> None:
    import subprocess

    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / script_name)],
        cwd=PROJECT_ROOT,
    )
    if result.returncode != 0:
        print(f"WARNING: {script_name} exited with code {result.returncode}", file=sys.stderr)


def main() -> int:
    settings = Settings.from_env(PROJECT_ROOT / ".env")
    settings.require_paper_mode()
    settings.require_credentials()
    clients = AlpacaClients(settings)

    last_scan = 0.0
    last_monitor = 0.0
    print("LOOP START — Ctrl+C to stop")

    while True:
        try:
            clock = clients.trading.get_clock()
        except Exception as error:
            print(f"CLOCK CHECK FAILED, will retry: {error}", file=sys.stderr)
            time.sleep(CLOSED_MARKET_POLL_SECONDS)
            continue

        if not clock.is_open:
            print(f"MARKET CLOSED next_open={clock.next_open}")
            time.sleep(CLOSED_MARKET_POLL_SECONDS)
            continue

        now = time.time()
        if now - last_monitor >= MONITOR_INTERVAL_SECONDS:
            print("RUNNING monitor_positions.py")
            _run_subprocess("monitor_positions.py")
            last_monitor = now

        if now - last_scan >= SCAN_INTERVAL_SECONDS:
            print("RUNNING run_agent.py")
            _run_subprocess("run_agent.py")
            last_scan = now

        time.sleep(30)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("LOOP STOPPED")
        raise SystemExit(0)
