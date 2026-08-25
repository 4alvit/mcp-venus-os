"""SSH access to the Cerbo GX for management operations.

One shared asyncssh client, lazily connected; every operation returns a
structured dict instead of raising so MCP tools never surface raw
exceptions. Key auth (``SSH_KEY_PATH``) takes precedence over password.
"""

import asyncio
import contextlib
import logging
import time
from typing import Any

import asyncssh

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


def _truncate(text: str) -> str:
    return (
        text
        if len(text) <= _MAX_OUTPUT
        else text[:_MAX_OUTPUT] + f"… (+{len(text) - _MAX_OUTPUT}b)"
    )


class CerboSSHClient:
    """Shared asyncssh connection with lazy connect and structured results."""

    def __init__(self) -> None:
        self.config = get_config().ssh
        self._conn: asyncssh.SSHClientConnection | None = None

    @property
    def configured(self) -> bool:
        """True when credentials exist (host defaults to MQTT_HOST)."""
        return bool(self.config.key_path or self.config.password)

    def _connect_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "host": self.config.effective_host,
            "port": self.config.port,
            "username": self.config.user,
            "known_hosts": None,  # LAN appliance; host key changes on reflash
            "login_timeout": self.config.timeout_s,
        }
        if self.config.key_path:
            kwargs["client_keys"] = [self.config.key_path]
        if self.config.password:
            kwargs["password"] = self.config.password
        return kwargs

    async def _ensure_conn(self) -> asyncssh.SSHClientConnection:
        if self._conn is None or self._conn.is_closed():
            self._conn = await asyncssh.connect(**self._connect_kwargs())
        return self._conn

    async def close(self) -> None:
        if self._conn is not None:
            with contextlib.suppress(Exception):
                self._conn.close()
            self._conn = None

    async def run(self, command: str, timeout_s: float | None = None) -> dict[str, Any]:
        """Run ``command``; never raises — returns success/stdout/stderr/exit_code."""
        started = time.monotonic()
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
            await self.close()  # dead connection must not poison later calls
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
        url = f"https://github.com/{repo}/archive/refs/heads/main.tar.gz"
        script = (
            f"wget -qO - {url} | tar -xzf - -C /data && "
            f"rm -rf /data/{package} && "
            f"mv /data/{package}-main /data/{package} && "
            f"cd /data/{package} && "
            f"scriptAction=INSTALL packageName={package} scriptDir=/data/{package} "
            f"/data/{package}/setup </dev/null"
        )
        return await self.run(script, timeout_s=300)

    async def enable_root_password(self, password: str) -> dict[str, Any]:
        """Set the root password so ssh login works (Venus superuser).

        Password goes over the channel via stdin to ``chpasswd`` — never in
        argv or shell-visible command line.
        """
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
            await self.close()
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
