"""Tests for the Cerbo SSH toolset."""

import asyncio
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, Mock, patch

import pytest

from mcp_venus_os import server
from mcp_venus_os.config import MQTTConfig, ServerConfig
from mcp_venus_os.mqtt_client import MQTTClient
from mcp_venus_os.safety import SafetyCheckResult
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
async def test_concurrent_commands_share_connection_and_remain_parallel() -> None:
    with patch("mcp_venus_os.ssh_client.get_config", return_value=_ssh_cfg()):
        client = CerboSSHClient()
    connecting = asyncio.Event()
    allow_connection = asyncio.Event()
    all_commands_started = asyncio.Event()
    finish_commands = asyncio.Event()
    connections: list[Mock] = []
    commands: list[str] = []

    async def run_command(command: str) -> Mock:
        commands.append(command)
        if len(commands) == 4:
            all_commands_started.set()
        await finish_commands.wait()
        return Mock(exit_status=0, stdout=command, stderr="")

    async def connect(**kwargs: object) -> Mock:
        connection = Mock()
        connection.is_closed.return_value = False
        connection.run = AsyncMock(side_effect=run_command)
        connections.append(connection)
        connecting.set()
        await allow_connection.wait()
        return connection

    with patch("mcp_venus_os.ssh_client.asyncssh.connect", side_effect=connect):
        tasks = [asyncio.create_task(client.run(f"command-{i}")) for i in range(4)]
        try:
            await asyncio.wait_for(connecting.wait(), timeout=1)
            allow_connection.set()
            await asyncio.wait_for(all_commands_started.wait(), timeout=1)
        finally:
            allow_connection.set()
            finish_commands.set()
            results = await asyncio.gather(*tasks)
            await client.close()

    assert len(connections) == 1
    connections[0].close.assert_called_once_with()
    assert [result["stdout"] for result in results] == [f"command-{i}" for i in range(4)]
    assert all(result["success"] for result in results)


@pytest.mark.asyncio
async def test_close_waits_for_pending_connection_and_releases_it() -> None:
    with patch("mcp_venus_os.ssh_client.get_config", return_value=_ssh_cfg()):
        client = CerboSSHClient()
    connecting = asyncio.Event()
    allow_connection = asyncio.Event()
    connection = Mock()
    connection.is_closed.return_value = False

    async def connect(**kwargs: object) -> Mock:
        connecting.set()
        await allow_connection.wait()
        return connection

    with patch("mcp_venus_os.ssh_client.asyncssh.connect", side_effect=connect):
        opening = asyncio.create_task(client._ensure_conn())
        await asyncio.wait_for(connecting.wait(), timeout=1)
        closing = asyncio.create_task(client.close())
        await asyncio.sleep(0)
        close_was_pending = not closing.done()
        allow_connection.set()
        await asyncio.wait_for(asyncio.gather(opening, closing), timeout=1)

    assert close_was_pending
    connection.close.assert_called_once_with()
    assert client._conn is None


@pytest.mark.asyncio
async def test_cancelled_connection_does_not_block_next_command() -> None:
    with patch("mcp_venus_os.ssh_client.get_config", return_value=_ssh_cfg()):
        client = CerboSSHClient()
    connecting = asyncio.Event()
    connection = Mock()
    connection.is_closed.return_value = False
    connection.run = AsyncMock(return_value=Mock(exit_status=0, stdout="ready", stderr=""))
    attempts = 0

    async def connect(**kwargs: object) -> Mock:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            connecting.set()
            await asyncio.Event().wait()
        return connection

    with patch("mcp_venus_os.ssh_client.asyncssh.connect", side_effect=connect):
        opening = asyncio.create_task(client.run("cancelled"))
        await asyncio.wait_for(connecting.wait(), timeout=1)
        opening.cancel()
        with pytest.raises(asyncio.CancelledError):
            await opening
        result = await asyncio.wait_for(client.run("retry"), timeout=1)
        await client.close()

    assert attempts == 2
    assert result["success"]
    assert result["stdout"] == "ready"


@pytest.mark.asyncio
async def test_failed_handshake_does_not_close_another_callers_connection() -> None:
    with patch("mcp_venus_os.ssh_client.get_config", return_value=_ssh_cfg()):
        client = CerboSSHClient()
    connecting = asyncio.Event()
    fail_handshake = asyncio.Event()
    connection = Mock()
    connection.is_closed.return_value = False
    connection.run = AsyncMock(return_value=Mock(exit_status=0, stdout="ready", stderr=""))
    attempts = 0

    async def connect(**kwargs: object) -> Mock:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            connecting.set()
            await fail_handshake.wait()
            raise OSError("refused")
        return connection

    with patch("mcp_venus_os.ssh_client.asyncssh.connect", side_effect=connect):
        first = asyncio.create_task(client.run("first"))
        await asyncio.wait_for(connecting.wait(), timeout=1)
        second = asyncio.create_task(client.run("second"))
        await asyncio.sleep(0)
        fail_handshake.set()
        results = await asyncio.wait_for(asyncio.gather(first, second), timeout=1)
        connection.close.assert_not_called()
        assert client._conn is connection
        await client.close()

    assert not results[0]["success"]
    assert results[1]["success"]
    assert attempts == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["command", "password"])
async def test_old_transport_error_does_not_close_replacement(operation: str) -> None:
    with patch("mcp_venus_os.ssh_client.get_config", return_value=_ssh_cfg()):
        client = CerboSSHClient()
    started = asyncio.Event()
    fail_old_command = asyncio.Event()
    old_connection = Mock()
    old_connection.is_closed.return_value = False

    async def old_command(*args: object, **kwargs: object) -> None:
        started.set()
        await fail_old_command.wait()
        raise OSError("disconnected")

    old_connection.run = AsyncMock(side_effect=old_command)
    client._conn = old_connection
    replacement = Mock()
    replacement.is_closed.return_value = False
    replacement.run = AsyncMock(return_value=Mock(exit_status=0, stdout="ready", stderr=""))
    with patch("mcp_venus_os.ssh_client.asyncssh.connect", new=AsyncMock(return_value=replacement)):
        pending = asyncio.create_task(
            client.run("old")
            if operation == "command"
            else client.enable_root_password("test-password")
        )
        await asyncio.wait_for(started.wait(), timeout=1)
        await client.close()
        assert (await client.run("new"))["success"]
        fail_old_command.set()
        assert not (await asyncio.wait_for(pending, timeout=1))["success"]
        replacement.close.assert_not_called()
        assert client._conn is replacement
        await client.close()


@pytest.mark.asyncio
async def test_connect_timeout_covers_native_asyncssh_transport_setup() -> None:
    """Exercise AsyncSSH's timeout before TCP/login without opening a real socket."""
    with patch("mcp_venus_os.ssh_client.get_config", return_value=_ssh_cfg(timeout_s=0.01)):
        client = CerboSSHClient()
    transport_cancelled = asyncio.Event()

    async def stalled_transport(*args: object, **kwargs: object) -> None:
        try:
            await asyncio.Event().wait()
        finally:
            transport_cancelled.set()

    with patch("asyncssh.connection._connect", side_effect=stalled_transport):
        result = await asyncio.wait_for(client.run("probe"), timeout=1)

    assert not result["success"]
    assert result["error"].startswith("ssh failed:")
    assert transport_cancelled.is_set()
    assert client._conn is None


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
    """Without confirmed=True, the confirmation gate blocks execution."""
    mock_validator = Mock()
    mock_validator.validate_write_operation.return_value = SafetyCheckResult(
        allowed=False,
        requires_confirmation=True,
        confirmation_message="Confirm cerbo_ssh_exec?",
    )
    with patch("mcp_venus_os.server.get_safety_validator", return_value=mock_validator):
        result = await server.cerbo_ssh_exec(command="uname -a")
    assert result["success"] is False
    assert result["requires_confirmation"] is True


@pytest.mark.asyncio
async def test_cerbo_ssh_exec_runs_when_confirmed(enable_writes: None) -> None:  # noqa: ARG001
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
    assert 'cp -a "$stage/inverter-control-main/." /data/inverter-control/' in cmd
    assert "rm -rf /data/inverter-control" not in cmd
    assert 'wget -qO "$stage/release.tar.gz"' in cmd
    assert "setup install </dev/null" in cmd
    assert "scriptAction=INSTALL" in cmd
    assert "packageName=inverter-control" in cmd
    assert "</dev/null" in cmd


@pytest.mark.asyncio
@pytest.mark.parametrize("package", ["../SetupHelper", "bad;reboot", "", "/", "-rf"])
async def test_package_operations_reject_invalid_paths(package: str) -> None:
    client = _client()
    assert not (await client.setuphelper_install_package(package, "owner/repo"))["success"]
    assert not (await client.setuphelper_remove_package(package))["success"]
    cast(Any, client).run.assert_not_awaited()


@pytest.mark.asyncio
async def test_remove_package_has_no_recursive_delete_fallback() -> None:
    client = _client()
    await client.setuphelper_remove_package("dbus-ev")
    command = cast(Any, client).run.call_args.args[0]
    assert "rm -rf" not in command
    assert "setup uninstall </dev/null" in command


@pytest.mark.asyncio
async def test_install_shell_preserves_local_state_and_cleans_staging(tmp_path: Path) -> None:
    """Run the emitted shell command against a fake GX filesystem."""
    import os
    import subprocess
    import tarfile

    data = tmp_path / "data"
    package = data / "device-package"
    package.mkdir(parents=True)
    (package / "config.local").write_text("local settings")
    (package / ".venv").mkdir()
    (package / ".venv" / "sentinel").write_text("device dependencies")
    source = tmp_path / "source-repository-main"
    source.mkdir()
    (source / "setup").write_text('#!/bin/sh\ntest "$1" = install\n')
    archive = tmp_path / "release.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(source, arcname=source.name)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    wget = bin_dir / "wget"
    wget.write_text(f'#!/bin/sh\ncp "{archive}" "$2"\n')
    wget.chmod(0o755)
    client = _client()
    await client.setuphelper_install_package("device-package", "owner/source-repository")
    script = cast(Any, client).run.call_args.args[0].replace("/data/", f"{data}/")
    subprocess.run(
        ["sh", "-c", script],
        check=True,
        env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"},
    )
    assert (package / "config.local").read_text() == "local settings"
    assert (package / ".venv" / "sentinel").read_text() == "device dependencies"
    assert not list(data.glob(".mcp-package.*"))


@pytest.mark.asyncio
@pytest.mark.parametrize(("trusted", "legacy"), [(True, False), (False, False), (True, True)])
async def test_real_ssh_connection_rejects_untrusted_host_key(
    tmp_path: Path, trusted: bool, legacy: bool
) -> None:
    """A disposable local SSH handshake must enforce the configured host key."""
    import asyncssh

    class LocalServer(asyncssh.SSHServer):
        def begin_auth(self, username: str) -> bool:
            return False

    host_key = asyncssh.generate_private_key("ssh-ed25519")
    other_key = asyncssh.generate_private_key("ssh-ed25519")
    listener = await asyncssh.create_server(
        LocalServer,
        "127.0.0.1",
        0,
        server_host_keys=[host_key],
        kex_algs=["diffie-hellman-group14-sha1"] if legacy else ["curve25519-sha256"],
    )
    key = host_key if trusted else other_key
    known_hosts = tmp_path / "known_hosts"
    known_hosts.write_text(f"[127.0.0.1]:{listener.get_port()} " + key.export_public_key().decode())
    cfg = _ssh_cfg(host="127.0.0.1", port=listener.get_port(), known_hosts=str(known_hosts))
    with patch("mcp_venus_os.ssh_client.get_config", return_value=cfg):
        client = CerboSSHClient()
    try:
        if legacy:
            with pytest.raises(asyncssh.KeyExchangeFailed):
                await client._ensure_conn()
        elif trusted:
            connection = await client._ensure_conn()
            assert not connection.is_closed()
        else:
            with pytest.raises(asyncssh.HostKeyNotVerifiable):
                await client._ensure_conn()
    finally:
        await client.close()
        listener.close()
        await listener.wait_closed()


@pytest.mark.asyncio
@pytest.mark.parametrize(("trusted", "sha1_only"), [(True, False), (False, False), (True, True)])
async def test_real_ssh_selects_trusted_rsa_among_multiple_server_keys(
    tmp_path: Path, trusted: bool, sha1_only: bool
) -> None:
    """Keep trusted RSA/SHA-2 usable without accepting a SHA-1-only server."""
    import asyncssh

    class LocalServer(asyncssh.SSHServer):
        def begin_auth(self, username: str) -> bool:
            return False

    rsa = asyncssh.generate_private_key("ssh-rsa", key_size=2048)
    ed25519 = asyncssh.generate_private_key("ssh-ed25519")
    rsa_pair = asyncssh.load_keypairs([rsa])[0]
    if sha1_only:
        # Advertise a real legacy RSA/SHA-1 handshake, without altering the client.
        rsa_pair.host_key_algorithms = (b"ssh-rsa",)
    listener = await asyncssh.create_server(
        LocalServer,
        "127.0.0.1",
        0,
        server_host_keys=[rsa_pair] if sha1_only else [ed25519, rsa_pair],
        kex_algs=["curve25519-sha256"],
    )
    known_key = rsa if trusted else asyncssh.generate_private_key("ssh-rsa", key_size=2048)
    known_hosts = tmp_path / "known_hosts"
    known_hosts.write_text(
        f"[127.0.0.1]:{listener.get_port()} " + known_key.export_public_key().decode()
    )
    cfg = _ssh_cfg(host="127.0.0.1", port=listener.get_port(), known_hosts=str(known_hosts))
    with patch("mcp_venus_os.ssh_client.get_config", return_value=cfg):
        client = CerboSSHClient()
    try:
        if sha1_only:
            with pytest.raises(asyncssh.KeyExchangeFailed):
                await client._ensure_conn()
        elif trusted:
            connection = await client._ensure_conn()
            server_key = connection.get_server_host_key()
            assert server_key is not None
            assert server_key.export_public_key() == rsa.export_public_key()
        else:
            with pytest.raises(asyncssh.HostKeyNotVerifiable):
                await client._ensure_conn()
    finally:
        await client.close()
        listener.close()
        await listener.wait_closed()
