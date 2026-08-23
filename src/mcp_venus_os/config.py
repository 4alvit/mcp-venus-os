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


class SafetyConfig(BaseSettings):
    """Safety constraints configuration."""

    model_config = SettingsConfigDict(env_prefix="SAFETY_")

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
    transport_backend: str = Field(
        default="mqtt", description="Transport backend: mqtt (default) or dbus (on-device)"
    )
    log_level: str = Field(default="INFO", description="Logging level")


@lru_cache
def get_config() -> ServerConfig:
    """Get cached configuration instance."""
    return ServerConfig()
