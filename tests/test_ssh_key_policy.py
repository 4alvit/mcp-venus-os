"""Exercise key policy with disposable servers and synthetic credentials."""

import asyncio
import base64
import hashlib
import hmac
from pathlib import Path
from unittest.mock import patch

import asyncssh
import pytest

from mcp_venus_os.config import MQTTConfig, ServerConfig, SSHConfig
from mcp_venus_os.ssh_client import CerboSSHClient


def _client(port: int, known_hosts: Path, key_path: Path | None = None) -> CerboSSHClient:
    config = ServerConfig(
        mqtt=MQTTConfig(host="localhost", portal_id="test"),
        ssh=SSHConfig(
            host="127.0.0.1",
            port=port,
            known_hosts=str(known_hosts),
            key_path=str(key_path) if key_path else None,
            password="synthetic-password",
        ),
    )
    with patch("mcp_venus_os.ssh_client.get_config", return_value=config):
        return CerboSSHClient()


def _key(algorithm: str) -> asyncssh.SSHKey:
    if algorithm.startswith("rsa"):
        return asyncssh.generate_private_key("ssh-rsa", key_size=int(algorithm[3:]))
    return asyncssh.generate_private_key(algorithm)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("algorithm", "record", "accepted"),
    [
        ("rsa1024", "exact", False),
        ("rsa2048", "exact", True),
        ("ssh-ed25519", "exact", True),
        ("ssh-ed448", "exact", True),
        ("ecdsa-sha2-nistp256", "exact", True),
        ("rsa2048", "wrong-host", False),
        ("rsa2048", "revoked", False),
        ("rsa2048", "hashed", True),
        ("rsa2048", "wildcard", True),
        ("rsa1024", "hashed", False),
        ("rsa1024", "wildcard", False),
        ("rsa2048", "empty", False),
    ],
)
async def test_host_key_policy_before_password(
    tmp_path: Path, algorithm: str, record: str, accepted: bool
) -> None:
    passwords: list[str] = []

    class Server(asyncssh.SSHServer):
        def password_auth_supported(self) -> bool:
            return True

        def validate_password(self, username: str, password: str) -> bool:
            passwords.append(password)
            return True

    key = _key(algorithm)
    listener = await asyncssh.create_server(Server, "127.0.0.1", 0, server_host_keys=[key])
    host = f"[127.0.0.1]:{listener.get_port()}"
    if record == "wrong-host":
        host = "another.invalid"
    elif record == "wildcard":
        host = "127.0.0.*"
    elif record == "hashed":
        salt = b"synthetic-host-salt"
        digest = hmac.new(salt, host.encode(), hashlib.sha1).digest()
        host = "|1|" + base64.b64encode(salt).decode() + "|" + base64.b64encode(digest).decode()
    line = host + " " + key.export_public_key().decode()
    if record == "revoked":
        line += "@revoked " + line
    known_hosts = tmp_path / "known_hosts"
    known_hosts.write_text("" if record == "empty" else line)
    client = _client(listener.get_port(), known_hosts)
    try:
        if accepted:
            conn = await client._ensure_conn()
            assert not conn.is_closed()
            assert passwords == ["synthetic-password"]
        else:
            with pytest.raises(asyncssh.HostKeyNotVerifiable):
                await client._ensure_conn()
            assert passwords == []
    finally:
        await client.close()
        listener.close()
        await listener.wait_closed()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("algorithm", "accepted"),
    [("rsa1024", False), ("rsa2048", True), ("ssh-ed25519", True)],
)
async def test_client_key_policy_before_network(
    tmp_path: Path, algorithm: str, accepted: bool
) -> None:
    offered: list[bytes] = []
    connected: list[asyncssh.SSHServerConnection] = []
    key = _key(algorithm)

    class Server(asyncssh.SSHServer):
        def connection_made(self, conn: asyncssh.SSHServerConnection) -> None:
            connected.append(conn)

        def public_key_auth_supported(self) -> bool:
            return True

        def validate_public_key(self, username: str, public_key: asyncssh.SSHKey) -> bool:
            offered.append(public_key.public_data)
            return public_key.public_data == key.public_data

    host_key = _key("ssh-ed25519")
    listener = await asyncssh.create_server(Server, "127.0.0.1", 0, server_host_keys=[host_key])
    known_hosts = tmp_path / "known_hosts"
    known_hosts.write_text(
        f"[127.0.0.1]:{listener.get_port()} " + host_key.export_public_key().decode()
    )
    key_path = tmp_path / "identity"
    key.write_private_key(key_path)
    client = _client(listener.get_port(), known_hosts, key_path)
    try:
        if accepted:
            conn = await client._ensure_conn()
            assert not conn.is_closed()
            assert offered
            assert set(offered) == {key.public_data}
        else:
            with pytest.raises(asyncssh.KeyExchangeFailed, match="does not meet key policy"):
                await client._ensure_conn()
            assert offered == []
            assert connected == []
    finally:
        await client.close()
        listener.close()
        await listener.wait_closed()


def test_password_configuration_does_not_load_ambient_keys(tmp_path: Path) -> None:
    client = _client(22, tmp_path / "known_hosts")
    options = asyncssh.SSHClientConnectionOptions(**client._connect_kwargs())
    assert options.client_keys is None
    assert options.agent_path is None
    assert options.pkcs11_provider is None
    assert not options.gss_auth
    assert not options.gss_kex
    assert not options.host_based_auth


@pytest.mark.asyncio
async def test_rekey_rejects_weak_key_even_when_listed_in_known_hosts(tmp_path: Path) -> None:
    connections: list[asyncssh.SSHServerConnection] = []
    errors: list[Exception | None] = []

    class Server(asyncssh.SSHServer):
        def connection_made(self, conn: asyncssh.SSHServerConnection) -> None:
            connections.append(conn)

        def connection_lost(self, exc: Exception | None) -> None:
            errors.append(exc)

        def begin_auth(self, username: str) -> bool:
            return False

    strong, weak = _key("rsa2048"), _key("rsa1024")
    listener = await asyncssh.create_server(Server, "127.0.0.1", 0, server_host_keys=[strong])
    known_hosts = tmp_path / "known_hosts"
    known_hosts.write_text(
        "".join(
            f"[127.0.0.1]:{listener.get_port()} " + key.export_public_key().decode()
            for key in (strong, weak)
        )
    )
    client = _client(listener.get_port(), known_hosts)
    try:
        conn = await client._ensure_conn()
        assert not conn.is_closed()
        peer = connections[0]
        pair = asyncssh.load_keypairs([weak])[0]
        # Change only the disposable server's rekey offering, leaving the client
        # and real key-exchange/verification implementation untouched.
        for algorithm in peer._server_host_keys:
            peer._server_host_keys[algorithm] = pair
        peer._rekey_bytes_sent = peer._rekey_bytes
        peer.send_debug("synthetic rekey fixture")
        await asyncio.wait_for(conn.wait_closed(), timeout=3)
        await asyncio.wait_for(peer.wait_closed(), timeout=3)
        assert conn.is_closed()
        assert errors
        error = errors[-1]
        assert isinstance(error, asyncssh.Error)
        assert error.code == asyncssh.DISC_HOST_KEY_NOT_VERIFIABLE
    finally:
        await client.close()
        listener.close()
        await listener.wait_closed()


@pytest.mark.asyncio
async def test_trusted_certificate_cannot_bypass_raw_key_policy(tmp_path: Path) -> None:
    key = _key("rsa1024")
    ca = _key("ssh-ed25519")
    certificate = ca.generate_host_certificate(key, "test", principals=["127.0.0.1"])
    pair = asyncssh.load_keypairs([(key, certificate)])[0]
    pair.host_key_algorithms = (b"rsa-sha2-256-cert-v01@openssh.com",)
    listener = await asyncssh.create_server(
        asyncssh.SSHServer, "127.0.0.1", 0, server_host_keys=[pair]
    )
    known_hosts = tmp_path / "known_hosts"
    known_hosts.write_text(
        f"@cert-authority [127.0.0.1]:{listener.get_port()} " + ca.export_public_key().decode()
    )
    client = _client(listener.get_port(), known_hosts)
    try:
        with pytest.raises(asyncssh.KeyExchangeFailed):
            await client._ensure_conn()
    finally:
        await client.close()
        listener.close()
        await listener.wait_closed()
