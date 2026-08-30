"""Safety constraints and validation for write operations."""

import logging
import re
from dataclasses import dataclass
from typing import Any

from .config import get_config

logger = logging.getLogger(__name__)


class SafetyError(Exception):
    """Base exception for safety violations."""

    pass


class ConfirmationRequiredError(SafetyError):
    """Raised when user confirmation is required for an operation."""

    def __init__(self, message: str, operation: str, params: dict[str, Any]):
        super().__init__(message)
        self.operation = operation
        self.params = params


class ParameterOutOfRangeError(SafetyError):
    """Raised when a parameter is outside allowed range."""

    pass


class InvalidModeError(SafetyError):
    """Raised when an invalid mode is requested."""

    pass


@dataclass
class SafetyCheckResult:
    """Result of a safety check."""

    allowed: bool
    reason: str | None = None
    requires_confirmation: bool = False
    confirmation_message: str | None = None


# Map of write operation → MQTT device type. Source of truth for what
# each control tool is allowed to touch; anything outside this map is
# considered unsafe by default.
_OPERATION_DEVICE_TYPE: dict[str, str] = {
    "set_inverter_mode": "vebus",
    "set_charge_current_limit": "vebus",
    "set_soc_limit": "battery",
}

# Map of write operation → the MQTT path the tool writes to. Used by the
# write-path allowlist check; this is the single source of truth that the
# W/… topic a tool publishes to is the one the SafetyConfig allowlist
# permits.
_OPERATION_DBUS_PATH: dict[str, str] = {
    "set_inverter_mode": "Mode",
    "set_charge_current_limit": "Dc/0/MaxChargeCurrent",
    "set_soc_limit": "SocLimit",
}


def _operation_device_type(operation: str) -> str | None:
    """Map write operation → MQTT device type."""
    return _OPERATION_DEVICE_TYPE.get(operation)


def _operation_dbus_path(operation: str) -> str | None:
    """Map write operation → MQTT path written to (the W/… suffix)."""
    return _OPERATION_DBUS_PATH.get(operation)


def _validate_write_path(operation: str, dbus_path: str | None) -> SafetyCheckResult:
    """Deny any write to a path not on the allowlist."""
    cfg = get_config().safety
    dtype = _operation_device_type(operation)
    if dtype is None:
        return SafetyCheckResult(True)  # unknown op — handled elsewhere
    allowed = cfg.write_path_allowlist.get(dtype, [])
    if dbus_path is not None and dbus_path not in allowed:
        return SafetyCheckResult(
            False,
            f"Path '{dbus_path}' is not in the write-path allowlist for "
            f"device type '{dtype}'. Allowed: {allowed}",
        )
    return SafetyCheckResult(True)


def _validate_ssh_command(command: str) -> SafetyCheckResult:
    """Deny commands matching any deny-pattern."""
    cfg = get_config().safety
    for pattern in cfg.ssh_command_deny_patterns:
        if re.search(pattern, command, re.IGNORECASE):
            return SafetyCheckResult(
                False,
                f"Command matches deny-pattern '{pattern}' and is rejected",
            )
    return SafetyCheckResult(True)


class SafetyValidator:
    """Validates operations against safety constraints."""

    def __init__(self) -> None:
        self.config = get_config().safety

    def validate_charge_current(self, current: float) -> SafetyCheckResult:
        """Validate charge current parameter."""
        if current < 0:
            return SafetyCheckResult(False, "Charge current cannot be negative")
        if current > self.config.max_charge_current:
            return SafetyCheckResult(
                False,
                f"Charge current {current}A exceeds maximum {self.config.max_charge_current}A",
            )
        return SafetyCheckResult(True)

    def validate_discharge_current(self, current: float) -> SafetyCheckResult:
        """Validate discharge current parameter."""
        if current < 0:
            return SafetyCheckResult(False, "Discharge current cannot be negative")
        if current > self.config.max_discharge_current:
            return SafetyCheckResult(
                False,
                f"Discharge current {current}A exceeds maximum "
                + f"{self.config.max_discharge_current}A",
            )
        return SafetyCheckResult(True)

    def validate_soc_limit(self, soc: int) -> SafetyCheckResult:
        """Validate state of charge limit."""
        if soc < self.config.min_soc_limit:
            return SafetyCheckResult(
                False, f"SoC limit {soc}% below minimum {self.config.min_soc_limit}%"
            )
        if soc > self.config.max_soc_limit:
            return SafetyCheckResult(
                False, f"SoC limit {soc}% exceeds maximum {self.config.max_soc_limit}%"
            )
        return SafetyCheckResult(True)

    def validate_mode(self, mode: str) -> SafetyCheckResult:
        """Validate inverter mode."""
        if mode not in self.config.allowed_modes:
            return SafetyCheckResult(
                False,
                f"Mode '{mode}' not allowed. Allowed: {', '.join(self.config.allowed_modes)}",
            )
        return SafetyCheckResult(True)

    # -------------------------------------------------------------------------
    # Write-path allowlist helpers
    # -------------------------------------------------------------------------
    # Main gate
    # -------------------------------------------------------------------------

    def validate_write_operation(
        self,
        operation: str,
        params: dict[str, Any],
        confirmed: bool = False,
        dbus_path: str | None = None,
    ) -> SafetyCheckResult:
        """Validate a write operation with all parameters.

        Checks (in order, first failure wins):
        1. Global killswitch (enable_writes).
        2. Write-path allowlist (dbus_path).
        3. Per-operation parameter range/enum validation.
        4. Confirmation gate.
        """
        logger.info("Validating write operation: %s with params: %s", operation, params)

        # 1. Killswitch — even confirmed=True is not enough.
        if not self.config.enable_writes:
            return SafetyCheckResult(
                False,
                reason=(
                    "Write operations are disabled. "
                    "Set SAFETY_ENABLE_WRITES=true to allow any writes."
                ),
            )

        # 2. Write-path allowlist.
        if operation != "cerbo_ssh_exec":
            path_result = _validate_write_path(operation, dbus_path)
            if not path_result.allowed:
                return path_result

        # 3. Operation-specific parameter checks.
        if "charge_current" in params:
            result = self.validate_charge_current(params["charge_current"])
            if not result.allowed:
                return result

        if "discharge_current" in params:
            result = self.validate_discharge_current(params["discharge_current"])
            if not result.allowed:
                return result

        if "soc_limit" in params:
            result = self.validate_soc_limit(params["soc_limit"])
            if not result.allowed:
                return result

        if "mode" in params:
            result = self.validate_mode(params["mode"])
            if not result.allowed:
                return result

        # 3b. SSH command deny-pattern check.
        if operation == "cerbo_ssh_exec":
            cmd_result = _validate_ssh_command(params.get("command", ""))
            if not cmd_result.allowed:
                return cmd_result

        # 4. Confirmation gate.
        if self.config.require_confirmation and not confirmed:
            return SafetyCheckResult(
                allowed=False,
                requires_confirmation=True,
                confirmation_message=(
                    f"Confirm {operation} with parameters: {params}? "
                    f"This will change device settings on Venus OS."
                ),
                reason="Confirmation required for write operation",
            )

        return SafetyCheckResult(True)


class ConfirmationManager:
    """Manages user confirmations for dangerous operations."""

    def __init__(self) -> None:
        self._pending: dict[str, dict[str, Any]] = {}

    def request_confirmation(self, operation: str, params: dict[str, Any], message: str) -> str:
        """Request confirmation for an operation. Returns confirmation ID."""
        import uuid

        confirmation_id = str(uuid.uuid4())[:8]
        self._pending[confirmation_id] = {
            "operation": operation,
            "params": params,
            "message": message,
            "confirmed": False,
        }
        return confirmation_id

    def confirm(self, confirmation_id: str) -> bool:
        """Confirm a pending operation."""
        if confirmation_id not in self._pending:
            return False
        self._pending[confirmation_id]["confirmed"] = True
        return True

    def get_pending(self, confirmation_id: str) -> dict[str, Any] | None:
        """Get pending confirmation details."""
        return self._pending.get(confirmation_id)

    def clear(self, confirmation_id: str) -> None:
        """Clear a confirmation."""
        self._pending.pop(confirmation_id, None)
