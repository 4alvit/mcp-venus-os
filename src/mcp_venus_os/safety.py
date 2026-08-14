"""Safety constraints and validation for write operations."""

import logging
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
                f"Discharge current {current}A exceeds maximum " +
                f"{self.config.max_discharge_current}A",
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
                False, f"Mode '{mode}' not allowed. Allowed: {', '.join(self.config.allowed_modes)}"
            )
        return SafetyCheckResult(True)

    def validate_write_operation(
        self, operation: str, params: dict[str, Any], confirmed: bool = False
    ) -> SafetyCheckResult:
        """Validate a write operation with all parameters."""
        logger.info("Validating write operation: %s with params: %s", operation, params)

        # Check individual parameters
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

        # Check if confirmation required
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
