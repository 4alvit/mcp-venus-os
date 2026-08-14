import pytest

from mcp_venus_os.safety import (
    ConfirmationRequiredError,
    SafetyCheckResult,
    SafetyValidator,
)


def test_validate_charge_current():
    validator = SafetyValidator()
    result = validator.validate_charge_current(0.0)
    assert result.allowed
    result = validator.validate_charge_current(10.0)
    assert isinstance(result, SafetyCheckResult)

def test_validate_discharge_current():
    validator = SafetyValidator()
    result = validator.validate_discharge_current(0.0)
    assert result.allowed
    result = validator.validate_discharge_current(10.0)
    assert isinstance(result, SafetyCheckResult)

def test_validate_soc_limit():
    validator = SafetyValidator()
    result = validator.validate_soc_limit(0)
    assert isinstance(result, SafetyCheckResult)
    result = validator.validate_soc_limit(100)
    assert isinstance(result, SafetyCheckResult)

def test_validate_mode():
    validator = SafetyValidator()
    result = validator.validate_mode("some_mode")
    assert isinstance(result, SafetyCheckResult)

def test_validate_write_operation():
    validator = SafetyValidator()
    result = validator.validate_write_operation("test_op", {}, confirmed=True)
    assert result.allowed

def test_confirmation_required_error():
    with pytest.raises(ConfirmationRequiredError) as exc_info:
        raise ConfirmationRequiredError("test", "test_op", {"key": "value"})
    assert exc_info.value.operation == "test_op"
    assert exc_info.value.params == {"key": "value"}
