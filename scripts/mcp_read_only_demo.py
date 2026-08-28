"""Read-only demo of the official Alpaca MCP Server (alpacahq/alpaca-mcp-server).

This script satisfies the hackathon requirement to use the Alpaca MCP Server
(or CLI) as part of the agent's workflow. It is a separate, human-facing
query/demo path: the autonomous trading loop (app/agents/workflow.py) never
depends on this process and always talks to Alpaca directly through
alpaca-py, so the deterministic Risk Engine remains the sole authority over
order submission regardless of whether the MCP server is running.

Setup (one-time, outside this repo):

    uv tool install alpaca-mcp-server
    # or: pipx install alpaca-mcp-server
    # or: git clone https://github.com/alpacahq/alpaca-mcp-server && uv sync

Then run this script with paper credentials already in .env:

    .\\.venv\\Scripts\\python.exe scripts\\mcp_read_only_demo.py

It launches the MCP server as a subprocess over stdio, lists the tools it
exposes, and calls two read-only tools (account info, then an option chain
lookup for the first watchlist symbol) to prove the integration works. It
never calls place_option_order or any other mutating tool.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config.settings import Settings

READ_ONLY_TOOL_ALLOWLIST = {
    "get_account_info",
    "get_account_config",
    "get_positions",
    "get_option_chain",
    "get_option_contracts",
    "get_stock_quote",
    "get_stock_latest_quote",
}


async def run(settings: Settings) -> int:
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError:
        print(
            "MCP CHECK SKIPPED: the 'mcp' package is not installed. "
            "Install it with 'pip install mcp' to enable this check.",
            file=sys.stderr,
        )
        return 1

    command = os.getenv("MCP_SERVER_COMMAND", "uvx")
    args = os.getenv("MCP_SERVER_ARGS", "alpaca-mcp-server").split()

    server_env = dict(os.environ)
    server_env["ALPACA_API_KEY"] = settings.api_key
    server_env["ALPACA_SECRET_KEY"] = settings.secret_key
    server_env["ALPACA_PAPER_TRADE"] = "true"

    server_params = StdioServerParameters(command=command, args=args, env=server_env)

    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                tools = await session.list_tools()
                tool_names = sorted(tool.name for tool in tools.tools)
                print(f"MCP SERVER OK tools={len(tool_names)}")
                for name in tool_names:
                    print(f"  - {name}")

                if "get_account_info" not in tool_names:
                    print("MCP CHECK FAILED: get_account_info tool not found", file=sys.stderr)
                    return 1

                account_result = await session.call_tool("get_account_info", arguments={})
                print("MCP get_account_info OK")
                for block in account_result.content:
                    text = getattr(block, "text", None)
                    if text:
                        print(f"  {text[:300]}")

                if settings.watchlist and "get_option_chain" in tool_names:
                    symbol = settings.watchlist[0]
                    chain_result = await session.call_tool(
                        "get_option_chain", arguments={"underlying_symbol": symbol}
                    )
                    print(f"MCP get_option_chain OK symbol={symbol}")
                    for block in chain_result.content:
                        text = getattr(block, "text", None)
                        if text:
                            print(f"  {text[:300]}")

        print("READ-ONLY MCP CHECK PASSED")
        return 0
    except FileNotFoundError:
        print(
            f"MCP CHECK FAILED: command '{command}' not found. "
            "Install the Alpaca MCP Server first (see script docstring).",
            file=sys.stderr,
        )
        return 1


def main() -> int:
    settings = Settings.from_env(PROJECT_ROOT / ".env")
    settings.require_paper_mode()
    settings.require_credentials()
    return asyncio.run(run(settings))


if __name__ == "__main__":
    raise SystemExit(main())
