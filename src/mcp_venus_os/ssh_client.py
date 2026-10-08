"""SSH access to the Cerbo GX for management operations.

One shared asyncssh client, lazily connected; every operation returns a
structured dict instead of raising so MCP tools never surface raw
exceptions. Key auth (``SSH_KEY_PATH``) takes precedence over password.
"""

import asyncio
import contextlib
import logging
import re
import time
from pathlib import Path
from typing import Any

import asyncssh
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed448, ed25519, rsa

from .config import get_config

logger = logging.getLogger(__name__)

# Cap stdout/stderr returned by tools (client-context protection)
_MAX_OUTPUT = 4096

# Firmware-update entry point moved between Venus releases
_SWUPDATE_CANDIDATES = (
    "/opt/victronenergy/swupdate-scripts/check-updates.sh",
    "/opt/victronenergy/swupdate-scripts/check-swupdate.sh",
)

# SetupHelper layout on the GX (verified on v3.75)
SETUPHELPER_DIR = "/data/SetupHelper"
PACKAGE_MANAGER_DIR = "/data/packageManager"


def valid_package_name(package: str) -> bool:
    """Only accept one literal directory name under /data."""
    return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", package))


def _truncate(text: str) -> str:
    return (
        text
        if len(text) <= _MAX_OUTPUT
        else text[:_MAX_OUTPUT] + f"… (+{len(text) - _MAX_OUTPUT}b)"
    )


def _strong_key(key: asyncssh.SSHKey) -> bool:
    """Check public parameters using the cryptographic library, never private data."""
    try:
        public = serialization.load_pem_public_key(key.export_public_key("pkcs8-pem"))
    except (ValueError, UnsupportedAlgorithm, asyncssh.KeyExportError):
        return False
    if isinstance(public, rsa.RSAPublicKey):
        return public.key_size >= 2048
    if isinstance(public, ec.EllipticCurvePublicKey):
        return isinstance(public.curve, (ec.SECP256R1, ec.SECP384R1, ec.SECP521R1))
    return isinstance(public, (ed25519.Ed25519PublicKey, ed448.Ed448PublicKey))


class CerboSSHClient:
    """Shared asyncssh connection with lazy connect and structured results."""

    def __init__(self) -> None:
        self.config = get_config().ssh
        self._conn: asyncssh.SSHClientConnection | None = None
        self._connection_lock = asyncio.Lock()

    @property
    def configured(self) -> bool:
        """True when credentials exist (host defaults to MQTT_HOST)."""
        return bool(self.config.key_path or self.config.password)

    def _known_hosts(
        self, host: str, addr: str, port: int | None
    ) -> tuple[list[asyncssh.SSHKey], list[asyncssh.SSHKey], list[asyncssh.SSHKey]]:
        """Keep host matching and revocations; trust only strong raw host keys."""
        path = Path(self.config.known_hosts or "~/.ssh/known_hosts").expanduser()
        source = str(path) if self.config.known_hosts or path.is_file() else b""
        trusted, _, revoked, *_ = asyncssh.match_known_hosts(source, host, addr, port)
        return [key for key in trusted if _strong_key(key)], [], list(revoked)

    def _connect_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "host": self.config.effective_host,
            "port": self.config.port,
            "username": self.config.user,
            "kex_algs": [
                "curve25519-sha256",
                "curve25519-sha256@libssh.org",
                "ecdh-sha2-nistp256",
                "ecdh-sha2-nistp384",
                "ecdh-sha2-nistp521",
                "diffie-hellman-group14-sha256",
                "diffie-hellman-group16-sha512",
            ],
            # Filter AsyncSSH's known_hosts-derived preference order. A fixed
            # allowlist can select an offered key which the operator never trusted.
            "server_host_key_algs": "-*ssh-rsa*,*ssh-dss*,*-cert-*",
            "signature_algs": "-*ssh-rsa*,*ssh-dss*",
            "known_hosts": self._known_hosts,
            # Only the documented raw key/password credentials may authenticate.
            # Ambient identities and certificate chains would bypass this policy.
            "client_keys": None,
            "client_certs": [],
            "agent_path": None,
            "agent_forwarding": False,
            "pkcs11_provider": None,
            "gss_kex": False,
            "gss_auth": False,
            "host_based_auth": False,
            "x509_trusted_certs": None,
            "mac_algs": [
                "hmac-sha2-256-etm@openssh.com",
                "hmac-sha2-512-etm@openssh.com",
                "hmac-sha2-256",
                "hmac-sha2-512",
            ],
            "connect_timeout": self.config.timeout_s,
            "login_timeout": self.config.timeout_s,
        }
        if self.config.key_path:
            try:
                key = asyncssh.read_private_key(Path(self.config.key_path).expanduser())
            except (OSError, asyncssh.KeyImportError):
                message = "Unable to load configured SSH client key"
                raise asyncssh.KeyExchangeFailed(message) from None
            if not _strong_key(key):
                message = "Configured SSH client key does not meet key policy"
                raise asyncssh.KeyExchangeFailed(message)
            # Pass the checked object, so the connection cannot reload another key.
            kwargs["client_keys"] = [key]
        if self.config.password:
            kwargs["password"] = self.config.password
        return kwargs

    async def _ensure_conn(self) -> asyncssh.SSHClientConnection:
        async with self._connection_lock:
            if self._conn is None or self._conn.is_closed():
                self._conn = await asyncssh.connect(**self._connect_kwargs())
            return self._conn

    async def close(self) -> None:
        await self._close_connection()

    async def _close_connection(self, expected: asyncssh.SSHClientConnection | None = None) -> None:
        async with self._connection_lock:
            if self._conn is not None and (expected is None or self._conn is expected):
                with contextlib.suppress(Exception):
                    self._conn.close()
                self._conn = None

    async def run(self, command: str, timeout_s: float | None = None) -> dict[str, Any]:
        """Run ``command``; never raises — returns success/stdout/stderr/exit_code."""
        started = time.monotonic()
        conn = None
        try:
            conn = await self._ensure_conn()
            result = await asyncio.wait_for(conn.run(command), timeout_s or self.config.timeout_s)
            return {
                "success": bool(result.exit_status == 0),
                "exit_code": result.exit_status,
                "stdout": _truncate(str(result.stdout or "")),
                "stderr": _truncate(str(result.stderr or "")),
                "elapsed_s": round(time.monotonic() - started, 2),
            }
        except asyncssh.PermissionDenied:
            return {"success": False, "error": "ssh permission denied — check key/password"}
        except (OSError, TimeoutError, asyncssh.Error) as exc:
            if conn is not None:
                await self._close_connection(conn)
            return {"success": False, "error": f"ssh failed: {exc}"}

    async def available(self) -> dict[str, Any]:
        """Cheap reachability probe: TCP connect, no auth, no command."""
        host = self.config.effective_host
        started = time.monotonic()
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(host, self.config.port), timeout=3.0
            )
            writer.close()
            return {
                "success": True,
                "host": host,
                "port": self.config.port,
                "reachable": True,
                "latency_ms": round((time.monotonic() - started) * 1000),
            }
        except OSError as exc:
            return {"success": True, "host": host, "reachable": False, "error": str(exc)}
        except TimeoutError:
            return {"success": True, "host": host, "reachable": False, "error": "timeout"}

    # --- curated operations -------------------------------------------------

    async def firmware_version(self) -> dict[str, Any]:
        out = await self.run("cat /opt/victronenergy/version")
        if not out.get("success"):
            return out
        lines = [ln for ln in out["stdout"].splitlines() if ln.strip()]
        return {"success": True, "version": lines[0] if lines else None, "raw": out["stdout"]}

    async def check_updates(self) -> dict[str, Any]:
        script = await self._swupdate_script()
        if script is None:
            return {"success": False, "error": "no swupdate check script found on device"}
        return await self.run(script)

    async def apply_updates(self) -> dict[str, Any]:
        script = await self._swupdate_script()
        if script is None:
            return {"success": False, "error": "no swupdate check script found on device"}
        # long-running: firmware download + install
        return await self.run(f"{script} -force -update", timeout_s=900)

    async def _swupdate_script(self) -> str | None:
        for candidate in _SWUPDATE_CANDIDATES:
            probe = await self.run(f"[ -f {candidate} ] && echo y")
            if probe.get("success"):
                return candidate
        return None

    async def setuphelper_status(self) -> dict[str, Any]:
        installed = await self.run(f"[ -d {SETUPHELPER_DIR} ] && echo y")
        if not installed.get("success"):
            return {
                "success": True,
                "installed": False,
                "hint": "install via wget of SetupHelper archive + /data/SetupHelper/setup",
            }
        version = await self.run(
            f"grep -m1 '^version' {SETUPHELPER_DIR}/PackageManager.py 2>/dev/null"
        )
        packages = await self.run(f"ls {PACKAGE_MANAGER_DIR} 2>/dev/null")
        installed_packages = [
            ln.strip() for ln in packages.get("stdout", "").splitlines() if ln.strip()
        ]
        return {
            "success": True,
            "installed": True,
            "version_line": version.get("stdout", "").strip() or None,
            "packages": installed_packages,
        }

    async def setuphelper_install_package(self, package: str, repo: str) -> dict[str, Any]:
        """Install a package via the documented wget+tar+setup pattern.

        Two hazards this method guards against (both bit us on 2026-08-24):
        - ``archive/latest.tar.gz`` resolves to the *tag* ``latest``, which
          can be months old. Always fetch ``refs/heads/main``.
        - Running ``setup`` without ``scriptAction`` drops it into
          standardActionPrompt, which blocks forever reading stdin over a
          headless SSH channel. Set the env PackageManager would set and
          redirect stdin from /dev/null so any stray read gets EOF.
        """
        if not valid_package_name(package):
            return {"success": False, "error": "invalid SetupHelper package name"}
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
            return {"success": False, "error": "repo must be owner/repository"}
        repo_name = repo.split("/")[1]
        url = f"https://github.com/{repo}/archive/refs/heads/main.tar.gz"
        # Download and validate before touching the installed package. Keep
        # its virtualenv, configuration and live supervise directory inodes.
        # A pipe hid wget failures, and rm -rf discarded all device-local state.
        script = (
            "set -eu; "
            "stage=$(mktemp -d /data/.mcp-package.XXXXXX); "
            "trap 'rm -rf \"$stage\"' EXIT HUP INT TERM; "
            f'wget -qO "$stage/release.tar.gz" {url}; '
            'tar -xzf "$stage/release.tar.gz" -C "$stage"; '
            f'test -f "$stage/{repo_name}-main/setup"; '
            f"mkdir -p /data/{package}; "
            f'cp -a "$stage/{repo_name}-main/." /data/{package}/; '
            f"cd /data/{package}; "
            f"scriptAction=INSTALL packageName={package} scriptDir=/data/{package} "
            f"bash /data/{package}/setup install </dev/null"
        )
        return await self.run(script, timeout_s=300)

    async def setuphelper_remove_package(self, package: str) -> dict[str, Any]:
        """Run package-owned uninstall; never delete arbitrary package data."""
        if not valid_package_name(package):
            return {"success": False, "error": "invalid SetupHelper package name"}
        return await self.run(
            f"test -f /data/{package}/setup && bash /data/{package}/setup uninstall </dev/null",
            timeout_s=300,
        )

    async def enable_root_password(self, password: str) -> dict[str, Any]:
        """Set the root password so ssh login works (Venus superuser).

        Password goes over the channel via stdin to ``chpasswd`` — never in
        argv or shell-visible command line.
        """
        conn = None
        try:
            conn = await self._ensure_conn()
            result = await conn.run("chpasswd 2>&1", input=f"root:{password}\n")
            ok = result.exit_status == 0 and "password" not in (result.stderr or "").lower()
            return {
                "success": bool(ok),
                "password_set": bool(ok),
                "stderr": _truncate(str(result.stderr or result.stdout or "")),
            }
        except (OSError, TimeoutError, asyncssh.Error) as exc:
            if conn is not None:
                await self._close_connection(conn)
            return {"success": False, "error": f"ssh failed: {exc}"}


_client: CerboSSHClient | None = None


def get_ssh_client() -> CerboSSHClient:
    global _client
    if _client is None:
        _client = CerboSSHClient()
    return _client


async def close_ssh_client() -> None:
    global _client
    if _client is not None:
        await _client.close()
        _client = None
