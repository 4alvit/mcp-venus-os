"""Shared pytest fixtures for the MCP Venus OS test suite."""

from collections.abc import Generator
from unittest.mock import patch

import pytest

from mcp_venus_os.config import SafetyConfig, ServerConfig


@pytest.fixture
def enable_writes() -> Generator[None, None, None]:
    """Opt-in fixture: enables writes (killswitch off, confirmation off) for
    tests that exercise real write tool paths through the safety gate.

    Tests that verify killswitch, confirmation, or path-deny behaviour
    do NOT use this fixture and run against the real default config.
    """
    cfg = ServerConfig(
        safety=SafetyConfig(
            enable_writes=True,
            require_confirmation=False,
        )
    )
    with (
        patch("mcp_venus_os.safety.get_config", return_value=cfg),
        patch("mcp_venus_os.config.get_config", return_value=cfg),
    ):
        from mcp_venus_os.safety import SafetyValidator

        fresh_validator = SafetyValidator()
        with patch("mcp_venus_os.server.get_safety_validator", return_value=fresh_validator):
            yield
