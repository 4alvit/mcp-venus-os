"""Tests for the main entry point."""

import importlib.util
import runpy
from unittest.mock import Mock, patch

from mcp_venus_os.server import mcp


def test_main_runs_server() -> None:
    with (
        patch.object(mcp, "run") as mock_run,
        patch("sys.argv", ["mcp-venus-os"]),
    ):
        from mcp_venus_os import __main__

        __main__.main()
    mock_run.assert_called_once()


def test_main_block() -> None:
    spec = importlib.util.find_spec("mcp_venus_os.__main__")
    assert spec is not None
    assert spec.origin is not None
    with (
        patch.object(mcp, "run") as mock_run,
        patch("sys.argv", ["mcp-venus-os"]),
    ):
        runpy.run_path(spec.origin, run_name="__main__")
    mock_run.assert_called_once()


def test_http_auth_none_without_token() -> None:
    from mcp_venus_os.server import _http_auth

    cfg = Mock()
    cfg.server_auth_token = None
    with patch("mcp_venus_os.server.get_config", return_value=cfg):
        assert _http_auth() is None


def test_http_auth_verifier_with_token() -> None:
    from mcp_venus_os.server import _http_auth

    cfg = Mock()
    cfg.server_auth_token = "secret"
    with patch("mcp_venus_os.server.get_config", return_value=cfg):
        verifier = _http_auth()
    assert verifier is not None


def test_main_dispatches_http_with_host_and_port() -> None:
    from unittest.mock import MagicMock

    cfg = Mock()
    cfg.server_transport = "http"
    cfg.server_host = "0.0.0.0"
    cfg.server_port = 8000
    fake_mcp = MagicMock()
    with (
        patch("mcp_venus_os.__main__.mcp", fake_mcp),
        patch("mcp_venus_os.__main__.get_config", return_value=cfg),
        patch("sys.argv", ["mcp-venus-os"]),
    ):
        from mcp_venus_os.__main__ import main

        main()
    fake_mcp.run.assert_called_once_with(transport="http", host="0.0.0.0", port=8000)


def test_main_defaults_to_stdio() -> None:
    from unittest.mock import MagicMock

    cfg = Mock()
    cfg.server_transport = "stdio"
    fake_mcp = MagicMock()
    with (
        patch("mcp_venus_os.__main__.mcp", fake_mcp),
        patch("mcp_venus_os.__main__.get_config", return_value=cfg),
        patch("sys.argv", ["mcp-venus-os"]),
    ):
        from mcp_venus_os.__main__ import main

        main()
    fake_mcp.run.assert_called_once_with()
