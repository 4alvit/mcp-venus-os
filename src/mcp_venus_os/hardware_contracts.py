"""Reviewed, target-specific write contracts. Read-back alone is not approval."""

import math
from collections.abc import Callable
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, model_validator

Number = StrictInt | StrictFloat
Role = Literal["venus_firmware", "target_product", "target_firmware", "bms_product", "bms_firmware"]


class IdentityProbe(BaseModel):
    """An exact, fresh MQTT identity value observed during device qualification."""

    model_config = ConfigDict(extra="forbid")
    role: Role
    device_type: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    instance: int = Field(strict=True, ge=0)
    path: str = Field(pattern=r"^[A-Za-z0-9_]+(?:/[A-Za-z0-9_]+)*$")
    expected: str | StrictInt


class HardwareWriteContract(BaseModel):
    """Operator-reviewed semantics for one portal, device instance and path."""

    model_config = ConfigDict(extra="forbid")
    contract_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
    portal_id: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    device_type: Literal["vebus", "battery"]
    instance: int = Field(strict=True, ge=0)
    path: Literal["Mode", "Dc/0/MaxChargeCurrent", "SocLimit"]
    identity: list[IdentityProbe] = Field(min_length=5, max_length=5)
    reviewed_by: str = Field(min_length=1)
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    semantics: str = Field(min_length=20)
    mode_codes: dict[str, StrictInt] = Field(default_factory=dict)
    unit: Literal["mode", "ampere", "percent"]
    minimum: Number | None = None
    maximum: Number | None = None

    @model_validator(mode="after")
    def validate_scope(self) -> Self:
        """No wildcard identities, partially specified bounds or unrelated target probes."""
        roles = {probe.role for probe in self.identity}
        expected = {
            "venus_firmware",
            "target_product",
            "target_firmware",
            "bms_product",
            "bms_firmware",
        }
        valid = roles == expected
        valid &= all(
            probe.device_type == self.device_type and probe.instance == self.instance
            for probe in self.identity
            if probe.role.startswith("target_")
        )
        valid &= all(
            probe.device_type == "battery"
            for probe in self.identity
            if probe.role.startswith("bms_")
        )
        if self.path == "Mode":
            valid &= self.device_type == "vebus" and self.unit == "mode" and bool(self.mode_codes)
            valid &= self.minimum is None and self.maximum is None
        else:
            expected_type, unit = (
                ("battery", "percent") if self.path == "SocLimit" else ("vebus", "ampere")
            )
            valid &= self.device_type == expected_type and self.unit == unit and not self.mode_codes
            valid &= (
                self.minimum is not None
                and self.maximum is not None
                and math.isfinite(self.minimum)
                and math.isfinite(self.maximum)
                and 0 <= self.minimum <= self.maximum
                and (self.unit != "percent" or self.maximum <= 100)
            )
        if not valid:
            message = (
                "Contract needs complete target/BMS/firmware identities and exact value semantics"
            )
            raise ValueError(message)
        return self


def validate_hardware_write(
    contracts: list[HardwareWriteContract],
    portal_id: str | None,
    device_type: str,
    instance: int,
    path: str,
    value: object,
    semantic_mode: str | None,
    read: Callable[[str, int, str], tuple[object, float] | None],
    max_age: float,
) -> tuple[HardwareWriteContract | None, str | None]:
    """Fail closed before publishing W/; never create contracts from an echo."""
    matches = [
        contract
        for contract in contracts
        if (contract.portal_id, contract.device_type, contract.instance, contract.path)
        == (portal_id, device_type, instance, path)
    ]
    if len(matches) != 1:
        return None, "Exactly one reviewed hardware contract is required for this target and path"
    contract = matches[0]
    if not math.isfinite(max_age) or max_age <= 0:
        return None, "Hardware identity freshness limit must be finite and positive"
    for probe in contract.identity:
        actual = read(probe.device_type, probe.instance, probe.path)
        if actual is None:
            return None, f"Hardware contract identity missing: {probe.role}"
        observed, age = actual
        if (
            type(observed) is not type(probe.expected)
            or observed != probe.expected
            or not math.isfinite(age)
            or not 0 <= age <= max_age
        ):
            return None, f"Hardware contract identity changed or stale: {probe.role}"
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None, "Contract requires a finite numeric hardware value"
    if path == "Mode":
        if semantic_mode not in contract.mode_codes or contract.mode_codes[semantic_mode] != value:
            return None, "Mode meaning/code has not been qualified for this hardware contract"
    elif (
        contract.minimum is None
        or contract.maximum is None
        or not contract.minimum <= value <= contract.maximum
    ):
        return None, "Value is outside the hardware-qualified range"
    return contract, None
