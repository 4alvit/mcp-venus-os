import pytest

from mcp_venus_os.safety import (
    ConfirmationRequiredError,
    SafetyCheckResult,
    SafetyValidator,
)


def test_validate_charge_current() -> None:
    validator = SafetyValidator()
    result = validator.validate_charge_current(0.0)
    assert result.allowed
    result = validator.validate_charge_current(10.0)
    assert isinstance(result, SafetyCheckResult)


def test_validate_discharge_current() -> None:
    validator = SafetyValidator()
    result = validator.validate_discharge_current(0.0)
    assert result.allowed
    result = validator.validate_discharge_current(10.0)
    assert isinstance(result, SafetyCheckResult)


def test_validate_soc_limit() -> None:
    validator = SafetyValidator()
    result = validator.validate_soc_limit(0)
    assert isinstance(result, SafetyCheckResult)
    result = validator.validate_soc_limit(100)
    assert isinstance(result, SafetyCheckResult)


def test_validate_mode() -> None:
    validator = SafetyValidator()
    result = validator.validate_mode("some_mode")
    assert isinstance(result, SafetyCheckResult)


def test_validate_write_operation() -> None:
    validator = SafetyValidator()
    result = validator.validate_write_operation("test_op", {}, confirmed=True)
    assert result.allowed


def test_confirmation_required_error() -> None:
    with pytest.raises(ConfirmationRequiredError) as exc_info:
        raise ConfirmationRequiredError("test", "test_op", {"key": "value"})
    assert exc_info.value.operation == "test_op"
    assert exc_info.value.params == {"key": "value"}


def test_validate_charge_current_negative() -> None:
    """Test charge current validation with negative value."""
    validator = SafetyValidator()
    result = validator.validate_charge_current(-1.0)
    assert not result.allowed
    assert "cannot be negative" in result.reason


def test_validate_charge_current_at_maximum() -> None:
    """Test charge current validation at maximum allowed value."""
    validator = SafetyValidator()
    result = validator.validate_charge_current(100.0)  # max_charge_current from config
    assert result.allowed


def test_validate_charge_current_over_maximum() -> None:
    """Test charge current validation with value over maximum."""
    validator = SafetyValidator()
    result = validator.validate_charge_current(100.1)  # Just over max_charge_current
    assert not result.allowed
    assert "exceeds maximum" in result.reason
    assert "100.1A" in result.reason
    assert "100.0A" in result.reason


def test_validate_discharge_current_negative() -> None:
    """Test discharge current validation with negative value."""
    validator = SafetyValidator()
    result = validator.validate_discharge_current(-1.0)
    assert not result.allowed
    assert "cannot be negative" in result.reason


def test_validate_discharge_current_at_maximum() -> None:
    """Test discharge current validation at maximum allowed value."""
    validator = SafetyValidator()
    result = validator.validate_discharge_current(100.0)  # max_discharge_current from config
    assert result.allowed


def test_validate_discharge_current_over_maximum() -> None:
    """Test discharge current validation with value over maximum."""
    validator = SafetyValidator()
    result = validator.validate_discharge_current(100.1)  # Just over max_discharge_current
    assert not result.allowed
    assert "exceeds maximum" in result.reason
    assert "100.1A" in result.reason
    assert "100.0A" in result.reason


def test_validate_soc_limit_below_minimum() -> None:
    """Test SoC limit validation with value below minimum."""
    validator = SafetyValidator()
    result = validator.validate_soc_limit(9)  # Just below min_soc_limit (10)
    assert not result.allowed
    assert "below minimum" in result.reason
    assert "9%" in result.reason
    assert "10%" in result.reason


def test_validate_soc_limit_at_minimum() -> None:
    """Test SoC limit validation at minimum allowed value."""
    validator = SafetyValidator()
    result = validator.validate_soc_limit(10)  # min_soc_limit from config
    assert result.allowed


def test_validate_soc_limit_at_maximum() -> None:
    """Test SoC limit validation at maximum allowed value."""
    validator = SafetyValidator()
    result = validator.validate_soc_limit(100)  # max_soc_limit from config
    assert result.allowed


def test_validate_soc_limit_over_maximum() -> None:
    """Test SoC limit validation with value over maximum."""
    validator = SafetyValidator()
    result = validator.validate_soc_limit(101)  # Just over max_soc_limit
    assert not result.allowed
    assert "exceeds maximum" in result.reason
    assert "101%" in result.reason
    assert "100%" in result.reason


def test_validate_mode_allowed() -> None:
    """Test mode validation with allowed mode."""
    validator = SafetyValidator()
    for mode in ["on", "off", "charger_only", "inverter_only", "eco"]:
        result = validator.validate_mode(mode)
        assert result.allowed


def test_validate_mode_not_allowed() -> None:
    """Test mode validation with not allowed mode."""
    validator = SafetyValidator()
    result = validator.validate_mode("invalid_mode")
    assert not result.allowed
    assert "not allowed" in result.reason
    assert "invalid_mode" in result.reason
    assert "on, off, charger_only, inverter_only, eco" in result.reason


def test_confirmation_manager() -> None:
    """Test ConfirmationManager class."""
    from mcp_venus_os.safety import ConfirmationManager
    
    manager = ConfirmationManager()
    
    # Test requesting confirmation
    confirmation_id = manager.request_confirmation(
        "test_operation",
        {"param1": "value1", "param2": 42},
        "Please confirm this operation"
    )
    
    assert isinstance(confirmation_id, str)
    assert len(confirmation_id) == 8  # First 8 chars of UUID
    
    # Test getting pending confirmation
    pending = manager.get_pending(confirmation_id)
    assert pending is not None
    assert pending["operation"] == "test_operation"
    assert pending["params"] == {"param1": "value1", "param2": 42}
    assert pending["message"] == "Please confirm this operation"
    assert pending["confirmed"] is False
    
    # Test confirming operation
    assert manager.confirm(confirmation_id) is True
    
    # Test getting pending confirmation after confirming
    pending_after = manager.get_pending(confirmation_id)
    assert pending_after is not None
    assert pending_after["confirmed"] is True
    
    # Test clearing confirmation
    manager.clear(confirmation_id)
    assert manager.get_pending(confirmation_id) is None
    
    # Test getting non-existent confirmation
    assert manager.get_pending("nonexistent") is None
    
    # Test confirming non-existent confirmation
    assert manager.confirm("nonexistent") is False


def test_validate_write_operation_with_charge_current() -> None:
    """Test write operation validation with charge current parameter."""
    validator = SafetyValidator()
    
    # Test with valid charge current
    result = validator.validate_write_operation(
        "set_charge_current",
        {"charge_current": 50.0},
        confirmed=True
    )
    assert result.allowed
    
    # Test with invalid charge current (too high)
    result = validator.validate_write_operation(
        "set_charge_current",
        {"charge_current": 150.0},  # Over max_charge_current (100.0)
        confirmed=True
    )
    assert not result.allowed
    assert "exceeds maximum" in result.reason


def test_validate_write_operation_with_discharge_current() -> None:
    """Test write operation validation with discharge current parameter."""
    validator = SafetyValidator()
    
    # Test with valid discharge current
    result = validator.validate_write_operation(
        "set_discharge_current",
        {"discharge_current": 50.0},
        confirmed=True
    )
    assert result.allowed
    
    # Test with invalid discharge current (too high)
    result = validator.validate_write_operation(
        "set_discharge_current",
        {"discharge_current": 150.0},  # Over max_discharge_current (100.0)
        confirmed=True
    )
    assert not result.allowed
    assert "exceeds maximum" in result.reason


def test_validate_write_operation_with_soc_limit() -> None:
    """Test write operation validation with SoC limit parameter."""
    validator = SafetyValidator()
    
    # Test with valid SoC limit
    result = validator.validate_write_operation(
        "set_soc_limit",
        {"soc_limit": 50},
        confirmed=True
    )
    assert result.allowed
    
    # Test with invalid SoC limit (too low)
    result = validator.validate_write_operation(
        "set_soc_limit",
        {"soc_limit": 5},  # Below min_soc_limit (10)
        confirmed=True
    )
    assert not result.allowed
    assert "below minimum" in result.reason
    
    # Test with invalid SoC limit (too high)
    result = validator.validate_write_operation(
        "set_soc_limit",
        {"soc_limit": 150},  # Over max_soc_limit (100)
        confirmed=True
    )
    assert not result.allowed
    assert "exceeds maximum" in result.reason


def test_validate_write_operation_with_mode() -> None:
    """Test write operation validation with mode parameter."""
    validator = SafetyValidator()
    
    # Test with valid mode
    result = validator.validate_write_operation(
        "set_inverter_mode",
        {"mode": "on"},
        confirmed=True
    )
    assert result.allowed
    
    # Test with invalid mode
    result = validator.validate_write_operation(
        "set_inverter_mode",
        {"mode": "invalid_mode"},
        confirmed=True
    )
    assert not result.allowed
    assert "not allowed" in result.reason


def test_validate_write_operation_confirmation_required() -> None:
    """Test write operation validation when confirmation is required but not provided."""
    validator = SafetyValidator()
    
    # Test with confirmed=False when require_confirmation is True (default)
    result = validator.validate_write_operation(
        "test_operation",
        {"some_param": "value"},
        confirmed=False
    )
    assert not result.allowed
    assert result.requires_confirmation is True
    assert "Confirmation required" in result.reason
    assert "test_operation" in result.confirmation_message
    
    # Test with confirmed=True when require_confirmation is True
    result = validator.validate_write_operation(
        "test_operation",
        {"some_param": "value"},
        confirmed=True
    )
    assert result.allowed




def test_main() -> None:
    """Test main entry point."""
    from mcp_venus_os import __main__
    
    # Test that main function exists and is callable
    assert callable(__main__.main)
    
    # We won't actually call mcp.run() as it would start the server
    # but we can verify the module imports correctly
    assert hasattr(__main__, 'mcp')
