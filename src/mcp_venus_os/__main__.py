"""Main entry point for MCP Venus OS server."""

import argparse

from mcp_venus_os.config import get_config
from mcp_venus_os.server import mcp


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="MCP Venus OS server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default=None,
        help="Server transport (default: SERVER_TRANSPORT env or stdio)",
    )
    args = parser.parse_args()

    config = get_config()
    transport = args.transport or config.server_transport

    if transport == "http":
        mcp.run(transport="http", host=config.server_host, port=config.server_port)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
