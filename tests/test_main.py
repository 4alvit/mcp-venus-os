"""Tests for the main entry point."""

import importlib.util
import runpy
from unittest.mock import patch

from mcp_venus_os.server import mcp


def test_main_runs_server() -> None:
    with patch.object(mcp, "run") as mock_run:
        from mcp_venus_os import __main__

        __main__.main()
    mock_run.assert_called_once()


def test_main_block() -> None:
    spec = importlib.util.find_spec("mcp_venus_os.__main__")
    assert spec is not None
    assert spec.origin is not None
    with patch.object(mcp, "run") as mock_run:
        runpy.run_path(spec.origin, run_name="__main__")
    mock_run.assert_called_once()
