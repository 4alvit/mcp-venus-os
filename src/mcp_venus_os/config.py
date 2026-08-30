"""Configuration management for MCP Venus OS."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class MissingPortalIdError(ValueError):
    """Raised when MQTT_PORTAL_ID is required but not configured."""


class DBusConfig(BaseSettings):
    """D-Bus connection configuration."""

    model_config = SettingsConfigDict(env_prefix="DBUS_")

    bus_type: str = Field(default="system", description="D-Bus type: system or session")
    service_name: str = Field(default="com.victronenergy", description="Base Victron service name")


class MQTTConfig(BaseSettings):
    """MQTT connection configuration."""

    model_config = SettingsConfigDict(env_prefix="MQTT_")

    host: str = Field(default="localhost", description="MQTT broker host")
    port: int = Field(default=1883, description="MQTT broker port")
    username: str | None = Field(default=None, description="MQTT username")
    password: str | None = Field(default=None, description="MQTT password")
    client_id: str = Field(default="mcp-venus-os", description="MQTT client ID")
    portal_id: str | None = Field(
        default=None,
        description="Venus OS portal ID (required when transport backend is mqtt)",
    )
    stale_after_seconds: float = Field(
        default=60.0, description="Mark cached readings older than this as stale"
    )
    tls: bool = Field(default=False, description="Use TLS for MQTT connection")

    @property
    def topic_prefix(self) -> str:
        """Base topic prefix for the Venus MQTT gateway (N/<portalId>)."""
        if not self.portal_id:
            raise MissingPortalIdError()
        return f"N/{self.portal_id}"


class SSHConfig(BaseSettings):
    """Cerbo GX SSH access configuration (management tools)."""

    model_config = SettingsConfigDict(env_prefix="SSH_")

    host: str | None = Field(
        default=None,
        description="Cerbo host for SSH tools; falls back to MQTT_HOST when unset",
    )
    port: int = Field(default=22, description="SSH port")
    user: str = Field(default="root", description="SSH user")
    key_path: str | None = Field(
        default=None, description="Private key path (preferred over password)"
    )
    password: str | None = Field(default=None, description="SSH password when no key configured")
    timeout_s: float = Field(default=15.0, description="SSH connect/command timeout")

    @property
    def effective_host(self) -> str:
        """Configured host or the MQTT broker host as default target."""
        return self.host or get_config().mqtt.host


class CerboRootConfig(BaseSettings):
    """Root-password provisioning for cerbo_enable_ssh."""

    model_config = SettingsConfigDict(env_prefix="CERBO_")

    root_password: str | None = Field(
        default=None,
        description="Password to set for root on the Cerbo (generated when unset)",
    )


class SafetyConfig(BaseSettings):
    """Safety constraints configuration.

    All write operations are deny-by-default: the killswitch
    ``enable_writes`` must be set to ``True`` (via ``SAFETY_ENABLE_WRITES=true``)
    before any tool will mutate device state, regardless of ``confirmed=True``
    or ``require_confirmation=False``. This is the single point that decides
    whether the control plane is live.
    """

    model_config = SettingsConfigDict(env_prefix="SAFETY_")

    enable_writes: bool = Field(
        default=False,
        description=(
            "Global killswitch: every write/control tool refuses to act when "
            "false, irrespective of the confirmed flag. Set true only on "
            "installs that are allowed to mutate Venus OS state."
        ),
    )
    require_confirmation: bool = Field(
        default=True, description="Require confirmation for write operations"
    )
    max_charge_current: float = Field(
        default=100.0, description="Maximum allowed charge current (A)"
    )
    max_discharge_current: float = Field(
        default=100.0, description="Maximum allowed discharge current (A)"
    )
    min_soc_limit: int = Field(default=10, description="Minimum allowed SoC limit (%)")
    max_soc_limit: int = Field(default=100, description="Maximum allowed SoC limit (%)")
    allowed_modes: list[str] = Field(
        default=["on", "off", "charger_only", "inverter_only", "eco"],
        description="Allowed inverter modes",
    )
    write_path_allowlist: dict[str, list[str]] = Field(
        default={
            # path-relative keys (device_type) → allowed W/… suffixes. A write
            # to any device_type / path outside this set is rejected even
            # when confirmed=True. Wildcards would invite target drift.
            "vebus": ["Mode", "Dc/0/MaxChargeCurrent", "Ac/ActiveIn/CurrentLimit"],
            "battery": ["SocLimit"],
            "solarcharger": ["Mode", "Dc/0/MaxChargeCurrent"],
        },
        description=("Map of write tool → allowed MQTT paths. Anything else is denied."),
    )
    ssh_command_deny_patterns: list[str] = Field(
        default=[
            # Anything that pivots out of the Cerbo shell or rewrites the box.
            # `rm -rf /` only (trailing whitespace/EOL) — `rm -rf /data/<pkg>`
            # used by setuphelper_remove_package stays allowed.
            r"\brm\s+-rf\s+/(?:\s|$)",
            r"\bmkfs",
            r"\bdd\s+if=",
            r"\bcurl\b.*\|\s*(?:ba)?sh",
            r"\bwget\b.*\|\s*(?:ba)?sh",
            r"\bshutdown\b",
            r"\breboot\b",
            r"\bhalt\b",
            r"\bpoweroff\b",
            r"\bflash\.sh\b",
            # firmware-update tools have their own gates; do not allow them
            # to be invoked by an arbitrary shell escape either.
        ],
        description=(
            "Regex patterns; if ANY matches the cerbo_ssh_exec command the "
            "request is denied, even with confirmed=True."
        ),
    )


class ServerConfig(BaseSettings):
    """Main server configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    dbus: DBusConfig = Field(default_factory=DBusConfig)
    mqtt: MQTTConfig = Field(default_factory=MQTTConfig)
    safety: SafetyConfig = Field(default_factory=SafetyConfig)
    ssh: SSHConfig = Field(default_factory=SSHConfig)
    cerbo: CerboRootConfig = Field(default_factory=CerboRootConfig)
    transport_backend: str = Field(
        default="mqtt", description="Transport backend: mqtt (default) or dbus (on-device)"
    )
    server_transport: str = Field(
        default="stdio", description="How Claude Code reaches the MCP server: stdio or http"
    )
    server_host: str = Field(
        default="127.0.0.1",
        description="HTTP bind address (use 0.0.0.0 in containers)",
    )
    server_port: int = Field(default=8000, description="HTTP port when server_transport=http")
    server_auth_token: str | None = Field(
        default=None, description="Bearer token required for HTTP mode (optional)"
    )
    log_level: str = Field(default="INFO", description="Logging level")


@lru_cache
def get_config() -> ServerConfig:
    """Get cached configuration instance."""
    return ServerConfig()
