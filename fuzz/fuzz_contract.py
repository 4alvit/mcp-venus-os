"""Fuzz reviewed hardware contracts without creating clients or issuing writes."""

import math
import struct
import sys
import types
from pathlib import Path

import atheris

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
# The initializer exports client implementations; only real pure contracts are
# loaded here, so fuzzing cannot construct a D-Bus/MQTT/SSH client.
package = types.ModuleType("mcp_venus_os")
package.__path__ = [str(Path(__file__).resolve().parents[1] / "src/mcp_venus_os")]
sys.modules[package.__name__] = package
with atheris.instrument_imports():
    from pydantic import ValidationError

    from mcp_venus_os.hardware_contracts import HardwareWriteContract, validate_hardware_write


def test_one_input(data: bytes) -> None:
    try:
        contract = HardwareWriteContract.model_validate_json(data)
    except ValidationError:
        return
    restored = HardwareWriteContract.model_validate_json(contract.model_dump_json())
    assert restored == contract  # nosec B101 - intentional test oracle
    identities = {
        (probe.device_type, probe.instance, probe.path): probe.expected
        for probe in contract.identity
    }

    def fresh_identity(device_type: str, instance: int, path: str) -> tuple[object, float]:
        return identities.get((device_type, instance, path)), 0.0

    values = [True, None, float("nan"), float("inf"), float("-inf")]
    if len(data) >= 8:
        values.append(struct.unpack("<d", data[:8])[0])
    if contract.minimum is not None:
        values.extend((contract.minimum, contract.maximum))
    for value in values:
        accepted, _ = validate_hardware_write(
            [contract],
            contract.portal_id,
            contract.device_type,
            contract.instance,
            contract.path,
            value,
            None,
            fresh_identity,
            30.0,
        )
        if isinstance(value, bool) or value is None or not math.isfinite(value):
            assert accepted is None  # nosec B101 - intentional test oracle
        if accepted is not None:
            assert contract.minimum <= value <= contract.maximum  # nosec B101 - intentional test oracle
    # Missing identity evidence must deny even a previously reviewed contract.
    accepted, _ = validate_hardware_write(
        [contract],
        contract.portal_id,
        contract.device_type,
        contract.instance,
        contract.path,
        0,
        None,
        lambda *_: None,
        30.0,
    )
    assert accepted is None  # nosec B101 - intentional test oracle


if __name__ == "__main__":
    atheris.Setup(sys.argv, atheris.instrument_func(test_one_input))
    atheris.Fuzz()
