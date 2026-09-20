"""Shared pytest fixtures for the MCP Venus OS test suite."""

from collections.abc import Generator
from unittest.mock import patch

import pytest

from mcp_venus_os.config import SafetyConfig, ServerConfig
from mcp_venus_os.hardware_contracts import HardwareWriteContract


@pytest.fixture
def hardware_contracts() -> list[HardwareWriteContract]:
    """Synthetic lab records, never production approvals or default configuration."""
    contracts = []
    for dtype, instance, path, unit in (
        ("vebus", 256, "Mode", "mode"),
        ("vebus", 256, "Dc/0/MaxChargeCurrent", "ampere"),
        ("battery", 512, "SocLimit", "percent"),
    ):
        identities = [
            {
                "role": "venus_firmware",
                "device_type": "platform",
                "instance": 0,
                "path": "Firmware",
                "expected": "fixture-venus",
            },
            {
                "role": "target_product",
                "device_type": dtype,
                "instance": instance,
                "path": "ProductName",
                "expected": "fixture-" + dtype,
            },
            {
                "role": "target_firmware",
                "device_type": dtype,
                "instance": instance,
                "path": "FirmwareVersion",
                "expected": "fixture-fw",
            },
            {
                "role": "bms_product",
                "device_type": "battery",
                "instance": 512,
                "path": "ProductName",
                "expected": "fixture-battery",
            },
            {
                "role": "bms_firmware",
                "device_type": "battery",
                "instance": 512,
                "path": "FirmwareVersion",
                "expected": "fixture-fw",
            },
        ]
        contracts.append(
            HardwareWriteContract.model_validate(
                {
                    "contract_id": "fixture-" + unit,
                    "portal_id": "testportal",
                    "device_type": dtype,
                    "instance": instance,
                    "path": path,
                    "identity": identities,
                    "reviewed_by": "unit-test-only",
                    "evidence_sha256": "a" * 64,
                    "semantics": "Synthetic fixture, not a hardware qualification.",
                    "unit": unit,
                    "mode_codes": {"on": 1, "eco": 3, "off": 4} if unit == "mode" else {},
                    "minimum": None if unit == "mode" else 0,
                    "maximum": None if unit == "mode" else 100,
                }
            )
        )
    return contracts


@pytest.fixture
def enable_writes(hardware_contracts: list[HardwareWriteContract]) -> Generator[None, None, None]:
    """Opt-in fixture: enables writes (killswitch off, confirmation off) for
    tests that exercise real write tool paths through the safety gate.

    Tests that verify killswitch, confirmation, or path-deny behaviour
    do NOT use this fixture and run against the real default config.
    """
    cfg = ServerConfig(
        safety=SafetyConfig(
            enable_writes=True,
            require_confirmation=False,
            hardware_write_contracts=hardware_contracts,
        )
    )
    with (
        patch("mcp_venus_os.safety.get_config", return_value=cfg),
        patch("mcp_venus_os.config.get_config", return_value=cfg),
    ):
        from mcp_venus_os.safety import SafetyValidator

        fresh_validator = SafetyValidator()
        with patch("mcp_venus_os.server.get_safety_validator", return_value=fresh_validator):
            yield
