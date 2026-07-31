"""Main entry point for MCP Venus OS server."""

from mcp_venus_os.server import mcp


def main() -> None:
    """Main entry point."""
    mcp.run()


if __name__ == "__main__":
    main()
