from unittest.mock import Mock, patch

import pytest

from mcp_venus_os.safety import SafetyCheckResult
from mcp_venus_os.server import (
    set_charge_current_limit,
    set_inverter_mode,
    set_soc_limit,
)


@pytest.mark.asyncio
async def test_set_inverter_mode_requires_confirmation():
    # When confirmed=False, safety validator returns not allowed and requires confirmation
    with patch("mcp_venus_os.server.get_safety_validator") as mock_get_validator:
        mock_validator = Mock()
        mock_get_validator.return_value = mock_validator
        mock_validator.validate_write_operation.return_value = SafetyCheckResult(
            allowed=False,
            requires_confirmation=True,
            reason="Test reason",
            confirmation_message="Please confirm",
        )

        result = await set_inverter_mode(mode="on", instance=0, confirmed=False)

        assert result["success"] is False
        assert result["requires_confirmation"] is True
        assert result["confirmation_message"] == "Please confirm"


@pytest.mark.asyncio
async def test_set_inverter_mode_not_allowed():
    with patch("mcp_venus_os.server.get_safety_validator") as mock_get_validator:
        mock_validator = Mock()
        mock_get_validator.return_value = mock_validator
        mock_validator.validate_write_operation.return_value = SafetyCheckResult(
            allowed=False,
            requires_confirmation=False,
            reason="Not allowed",
            confirmation_message="",
        )

        result = await set_inverter_mode(mode="on", instance=0, confirmed=True)

        assert result["success"] is False
        assert result["error"] == "Not allowed"


@pytest.mark.asyncio
async def test_set_inverter_mode_not_implemented():
    with patch("mcp_venus_os.server.get_safety_validator") as mock_get_validator:
        mock_validator = Mock()
        mock_get_validator.return_value = mock_validator
        mock_validator.validate_write_operation.return_value = SafetyCheckResult(
            allowed=True,
            requires_confirmation=False,
            reason="",
            confirmation_message="",
        )

        result = await set_inverter_mode(mode="on", instance=0, confirmed=True)

        assert result["success"] is False
        assert result["error"] == "Operation not implemented yet"


# Similar tests for set_charge_current_limit and set_soc_limit
@pytest.mark.asyncio
async def test_set_charge_current_limit_requires_confirmation():
    with patch("mcp_venus_os.server.get_safety_validator") as mock_get_validator:
        mock_validator = Mock()
        mock_get_validator.return_value = mock_validator
        mock_validator.validate_write_operation.return_value = SafetyCheckResult(
            allowed=False,
            requires_confirmation=True,
            reason="Test reason",
            confirmation_message="Please confirm",
        )

        result = await set_charge_current_limit(current=10.0, instance=0, confirmed=False)

        assert result["success"] is False
        assert result["requires_confirmation"] is True
        assert result["confirmation_message"] == "Please confirm"


@pytest.mark.asyncio
async def test_set_charge_current_limit_not_implemented():
    with patch("mcp_venus_os.server.get_safety_validator") as mock_get_validator:
        mock_validator = Mock()
        mock_get_validator.return_value = mock_validator
        mock_validator.validate_write_operation.return_value = SafetyCheckResult(
            allowed=True,
            requires_confirmation=False,
            reason="",
            confirmation_message="",
        )

        result = await set_charge_current_limit(current=10.0, instance=0, confirmed=True)

        assert result["success"] is False
        assert result["error"] == "Operation not implemented yet"


@pytest.mark.asyncio
async def test_set_soc_limit_requires_confirmation():
    with patch("mcp_venus_os.server.get_safety_validator") as mock_get_validator:
        mock_validator = Mock()
        mock_get_validator.return_value = mock_validator
        mock_validator.validate_write_operation.return_value = SafetyCheckResult(
            allowed=False,
            requires_confirmation=True,
            reason="Test reason",
            confirmation_message="Please confirm",
        )

        result = await set_soc_limit(soc_limit=80, instance=0, confirmed=False)

        assert result["success"] is False
        assert result["requires_confirmation"] is True
        assert result["confirmation_message"] == "Please confirm"


@pytest.mark.asyncio
async def test_set_soc_limit_not_implemented():
    with patch("mcp_venus_os.server.get_safety_validator") as mock_get_validator:
        mock_validator = Mock()
        mock_get_validator.return_value = mock_validator
        mock_validator.validate_write_operation.return_value = SafetyCheckResult(
            allowed=True,
            requires_confirmation=False,
            reason="",
            confirmation_message="",
        )

        result = await set_soc_limit(soc_limit=80, instance=0, confirmed=True)

        assert result["success"] is False
        assert result["error"] == "Operation not implemented yet"
