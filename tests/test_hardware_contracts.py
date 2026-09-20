"""New targets and changed firmware/BMS cannot acquire write permission by echoing."""

from typing import Any
from unittest.mock import Mock, patch

import pytest
from pydantic import ValidationError

from mcp_venus_os.hardware_contracts import HardwareWriteContract, validate_hardware_write
from mcp_venus_os.server import _mqtt_write_and_verify


def validate(
    contracts: list[HardwareWriteContract], **changes: object
) -> tuple[HardwareWriteContract | None, str | None]:
    """Read only synthetic identity data from the reviewed fixture."""
    values = {(p.device_type, p.instance, p.path): (p.expected, 0.1) for p in contracts[0].identity}
    arguments: dict[str, Any] = {
        "contracts": contracts,
        "portal_id": "testportal",
        "device_type": "vebus",
        "instance": 256,
        "path": "Mode",
        "value": 1,
        "semantic_mode": "on",
        "read": lambda dtype, instance, path: values.get((dtype, instance, path)),
        "max_age": 60.0,
    }
    arguments.update(changes)
    return validate_hardware_write(**arguments)


def test_qualified_fixture_only_matches_its_exact_target(
    hardware_contracts: list[HardwareWriteContract],
) -> None:
    assert validate(hardware_contracts)[1] is None
    for changes in (
        {"portal_id": "new"},
        {"instance": 0},
        {"device_type": "inverter"},
        {"path": "Other"},
    ):
        assert validate(hardware_contracts, **changes)[0] is None


def test_all_identity_roles_must_be_present_fresh_and_exact(
    hardware_contracts: list[HardwareWriteContract],
) -> None:
    for missing in hardware_contracts[0].identity:
        for observed in (
            None,
            ("changed", 0.1),
            (missing.expected, 61),
            (missing.expected, float("nan")),
        ):
            values: dict[tuple[str, int, str], tuple[object, float] | None] = {
                (p.device_type, p.instance, p.path): (p.expected, 0.1)
                for p in hardware_contracts[0].identity
            }
            values[missing.device_type, missing.instance, missing.path] = observed
            assert (
                validate(hardware_contracts, read=lambda d, i, p, v=values: v.get((d, i, p)))[0]
                is None
            )


def test_mode_semantics_and_numeric_values_fail_closed(
    hardware_contracts: list[HardwareWriteContract],
) -> None:
    for changes in (
        {"value": 3},
        {"semantic_mode": "charger_only"},
        {"value": True},
        {"value": float("nan")},
        {"max_age": float("inf")},
    ):
        assert validate(hardware_contracts, **changes)[0] is None
    assert validate(hardware_contracts + [hardware_contracts[0]])[0] is None
    assert (
        validate_hardware_write([], "testportal", "vebus", 256, "Mode", 1, "on", Mock(), 60)[0]
        is None
    )


def test_soc_contract_requires_the_qualified_range(
    hardware_contracts: list[HardwareWriteContract],
) -> None:
    arguments = {
        "device_type": "battery",
        "instance": 512,
        "path": "SocLimit",
        "semantic_mode": None,
    }
    assert validate(hardware_contracts, **arguments, value=80)[1] is None
    for value in (-1, 101, float("inf")):
        assert validate(hardware_contracts, **arguments, value=value)[0] is None


def test_contract_schema_rejects_unqualified_or_wildcard_records(
    hardware_contracts: list[HardwareWriteContract],
) -> None:
    data = hardware_contracts[0].model_dump()
    for changes in (
        {"portal_id": "*"},
        {"identity": data["identity"][:4]},
        {"evidence_sha256": ""},
        {"unit": "percent"},
        {"instance": True},
    ):
        with pytest.raises(ValidationError):
            HardwareWriteContract.model_validate(data | changes)


@pytest.mark.asyncio
async def test_unqualified_target_never_publishes_or_starts_keepalive(enable_writes: None) -> None:
    client = Mock()
    client.config.portal_id = "new-target"
    client.config.stale_after_seconds = 60.0
    result = await _mqtt_write_and_verify(client, "vebus", 256, "Mode", 1, "on")
    assert not result["success"]
    client.publish.assert_not_called()
    client.start_keepalive.assert_not_called()


@pytest.mark.asyncio
async def test_old_matching_readback_is_not_a_fresh_ack(
    enable_writes: None, hardware_contracts: list[HardwareWriteContract]
) -> None:
    client = Mock()
    client.config.portal_id = "testportal"
    client.config.stale_after_seconds = 60.0
    client.write_prefix = "W/testportal"
    values = {
        (p.device_type, p.instance, p.path): (p.expected, 0.1)
        for p in hardware_contracts[0].identity
    }
    client.read_path.side_effect = lambda d, i, p: values.get((d, i, p))
    client.read_path_since.return_value = None
    with patch("mcp_venus_os.server.WRITE_VERIFY_TIMEOUT_S", 0.01):
        result = await _mqtt_write_and_verify(client, "vebus", 256, "Mode", 1, "on")
    assert not result["success"]
    assert "did not reflect" in result["error"]
