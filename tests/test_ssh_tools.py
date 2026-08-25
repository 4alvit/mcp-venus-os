"""Tests for the Cerbo SSH toolset."""

from typing import Any, cast
from unittest.mock import AsyncMock, Mock, patch

import pytest

from mcp_venus_os import server
from mcp_venus_os.config import MQTTConfig, ServerConfig
from mcp_venus_os.mqtt_client import MQTTClient
from mcp_venus_os.ssh_client import CerboSSHClient


def _mqtt_read_client(entries: dict[str, object]) -> MQTTClient:
    """Cold-cache MQTT client fixture (same shape as test_server's helper)."""
    import json as _json
    from unittest.mock import patch as _patch

    from mcp_venus_os.mqtt_client import MQTTClient

    def _feed(topic: str, payload: bytes) -> None:
        import paho.mqtt.client as paho_mqtt

        msg = paho_mqtt.MQTTMessage()
        msg._topic = topic.encode()
        msg.payload = payload
        MQTTClient._on_message(cast(Any, client), cast(Any, Mock()), None, msg)
        client._drain_inbox()

    cfg = ServerConfig(mqtt=MQTTConfig(host="localhost", portal_id="testportal"))
    with (
        _patch.object(server, "_mqtt_client", None),
        _patch("mcp_venus_os.mqtt_client.get_config", return_value=cfg),
    ):
        client = server.get_mqtt_client()
    for topic, value in entries.items():
        _feed(topic.replace("<portal>", "testportal"), _json.dumps(value).encode())
    return client


def _ssh_cfg(**overrides: object) -> ServerConfig:
    ssh_kwargs: dict[str, Any] = {"host": "10.0.0.5", "password": "secret"}
    ssh_kwargs.update(overrides)
    return ServerConfig(mqtt=MQTTConfig(host="localhost", portal_id="p"), ssh=ssh_kwargs)  # type: ignore[arg-type]


def _client() -> CerboSSHClient:
    with patch("mcp_venus_os.ssh_client.get_config", return_value=_ssh_cfg()):
        c = CerboSSHClient()
    cast(Any, c).run = AsyncMock(return_value={"success": True, "stdout": "", "stderr": ""})
    return c


@pytest.mark.asyncio
async def test_firmware_version_parses_first_line() -> None:
    c = _client()
    cast(Any, c).run = AsyncMock(
        return_value={"success": True, "stdout": "v3.75\nVictron Energy\n20260624", "stderr": ""}
    )
    out = await c.firmware_version()
    assert out["version"] == "v3.75"


def test_configured_requires_credentials() -> None:
    with patch("mcp_venus_os.ssh_client.get_config", return_value=_ssh_cfg(password=None)):
        assert not CerboSSHClient().configured
    with patch("mcp_venus_os.ssh_client.get_config", return_value=_ssh_cfg()):
        assert CerboSSHClient().configured


@pytest.mark.asyncio
async def test_run_reports_transport_error_without_raising() -> None:
    with patch("mcp_venus_os.ssh_client.get_config", return_value=_ssh_cfg()):
        c = CerboSSHClient()
    with patch("mcp_venus_os.ssh_client.asyncssh.connect", side_effect=OSError("refused")):
        out = await c.run("echo hi")
    assert out["success"] is False
    assert "refused" in out["error"]


@pytest.mark.asyncio
async def test_setuphelper_status_lists_packages() -> None:
    c = _client()

    async def _run(cmd: str, timeout_s: float | None = None) -> dict[str, Any]:
        if "[ -d" in cmd:
            return {"success": True, "stdout": "y"}
        if "PackageManager.py" in cmd:
            return {"success": True, "stdout": 'version = "9.1"', "stderr": ""}
        return {"success": True, "stdout": "dbus-mqtt-battery\ndbus-pump\n", "stderr": ""}

    cast(Any, c).run = AsyncMock(side_effect=_run)
    out = await c.setuphelper_status()
    assert out == {
        "success": True,
        "installed": True,
        "version_line": 'version = "9.1"',
        "packages": ["dbus-mqtt-battery", "dbus-pump"],
    }


@pytest.mark.asyncio
async def test_enable_root_password_sends_stdin_not_argv() -> None:
    with patch("mcp_venus_os.ssh_client.get_config", return_value=_ssh_cfg()):
        c = CerboSSHClient()
    conn = Mock()
    conn.is_closed = Mock(return_value=False)
    conn.run = AsyncMock(return_value=Mock(exit_status=0, stdout="", stderr=""))
    cast(Any, c)._conn = conn
    out = await c.enable_root_password("s3cret")
    assert out["success"] is True
    args, kwargs = conn.run.call_args
    assert "s3cret" not in str(args[0])
    assert kwargs["input"] == "root:s3cret\n"


# --- MCP tool wiring --------------------------------------------------------


@pytest.mark.asyncio
async def test_ssh_tools_register_when_configured() -> None:
    client = _mqtt_read_client({})
    with (
        patch.object(server, "_registered_capabilities", set()),
        patch.object(server.mcp, "add_tool") as mock_add,
        patch("mcp_venus_os.server.get_ssh_client") as mock_ssh,
    ):
        mock_ssh.return_value.configured = True
        server._apply_capability_tools(client)
    names = [c.args[0].__name__ for c in mock_add.call_args_list]
    assert names.count("cerbo_ssh_exec") == 1
    assert "cerbo_version" in names


@pytest.mark.asyncio
async def test_ssh_tools_skipped_when_unconfigured() -> None:
    client = _mqtt_read_client({})
    with (
        patch.object(server, "_registered_capabilities", set()),
        patch.object(server.mcp, "add_tool") as mock_add,
        patch("mcp_venus_os.server.get_ssh_client") as mock_ssh,
    ):
        mock_ssh.return_value.configured = False
        server._apply_capability_tools(client)
    names = [c.args[0].__name__ for c in mock_add.call_args_list]
    assert not any(n.startswith(("cerbo_", "setuphelper_")) for n in names)


@pytest.mark.asyncio
async def test_cerbo_ssh_exec_gated_without_confirmation() -> None:
    with patch.object(server, "_safety_validator", None):
        result = await server.cerbo_ssh_exec(command="uname -a")
    assert result["success"] is False
    assert result["requires_confirmation"] is True


@pytest.mark.asyncio
async def test_cerbo_ssh_exec_runs_when_confirmed() -> None:
    fake = Mock()
    fake.configured = True
    fake.run = AsyncMock(return_value={"success": True, "stdout": "Linux cerbo", "exit_code": 0})
    with patch("mcp_venus_os.server.get_ssh_client", return_value=fake):
        result = await server.cerbo_ssh_exec(command="uname -a", confirmed=True)
    assert result["success"] is True
    fake.run.assert_awaited_once_with("uname -a", timeout_s=30.0)


@pytest.mark.asyncio
async def test_setuphelper_install_uses_main_branch_and_no_stdin_hang() -> None:
    """Regression: 2026-08-24 prod incident.

    - archive/latest.tar.gz resolves to the *tag* latest (months old), not main
    - setup without scriptAction blocks forever on stdin over headless SSH
    """
    c = _client()
    captured: dict[str, Any] = {}

    async def _run(cmd: str, timeout_s: float | None = None) -> dict[str, Any]:
        captured["cmd"] = cmd
        return {"success": True, "stdout": "", "stderr": ""}

    cast(Any, c).run = AsyncMock(side_effect=_run)
    await c.setuphelper_install_package("inverter-control", "victron-venus/inverter-control")

    cmd = captured["cmd"]
    assert "archive/refs/heads/main.tar.gz" in cmd
    assert "/archive/latest.tar.gz" not in cmd
    assert "mv /data/inverter-control-main /data/inverter-control" in cmd
    assert "scriptAction=INSTALL" in cmd
    assert "packageName=inverter-control" in cmd
    assert "</dev/null" in cmd
