"""Compliance-voltage configuration tests for the magnet engine."""

from __future__ import annotations

import pytest

from stoner_measurement.magnet_control import engine as engine_module
from stoner_measurement.magnet_control.engine import MagnetControllerEngine


class _ComplianceDriver:
    """Narrow connected driver double with optional compliance support."""

    def __init__(self) -> None:
        self.is_connected = True
        self.applied: list[float] = []
        self._compliance_voltage = 4.0

    def confirm_identity(self) -> None:
        """Accept the fake identity."""

    def refresh_magnet_constant(self) -> float:
        """Return a fixed software magnet constant."""
        return 0.1

    def set_compliance_voltage(self, voltage: float) -> None:
        """Record and apply a compliance voltage."""
        self.applied.append(voltage)
        self._compliance_voltage = voltage

    @property
    def compliance_voltage(self) -> float:
        """Return the fake hardware compliance value."""
        return self._compliance_voltage

    def return_to_local(self) -> None:
        """No-op local handoff."""

    def disconnect(self) -> None:
        """Mark the fake connection closed."""
        self.is_connected = False


def test_engine_loads_persists_and_applies_compliance_voltage(monkeypatch, qapp):
    """A YAML compliance value is retained and applied on connection."""
    _ = qapp
    monkeypatch.setattr(
        engine_module,
        "load_magnet_controller_config",
        lambda: {"limits": {"compliance_voltage": 3.5}},
    )
    engine = MagnetControllerEngine()
    driver = _ComplianceDriver()

    engine.connect_instrument(driver)  # type: ignore[arg-type]

    assert engine.compliance_voltage == pytest.approx(3.5)
    assert driver.applied == [pytest.approx(3.5)]
    assert engine.configuration_dict()["limits"]["compliance_voltage"] == pytest.approx(3.5)
    engine.shutdown()


def test_engine_sets_and_refreshes_capable_driver_compliance(qapp):
    """The public engine API writes and refreshes driver compliance."""
    _ = qapp
    engine = MagnetControllerEngine()
    driver = _ComplianceDriver()
    engine.connect_instrument(driver)  # type: ignore[arg-type]

    engine.set_compliance_voltage(6.25)
    driver._compliance_voltage = 5.75  # noqa: SLF001

    assert engine.refresh_compliance_voltage() == pytest.approx(5.75)
    assert engine.compliance_voltage == pytest.approx(5.75)
    engine.shutdown()


@pytest.mark.parametrize("value", [0.0, -1.0, float("nan"), float("inf")])
def test_engine_rejects_invalid_compliance_voltage(value, qapp):
    """Invalid cached safety limits are rejected before reaching a driver."""
    _ = qapp
    engine = MagnetControllerEngine()
    with pytest.raises(ValueError, match="positive and finite"):
        engine.set_compliance_voltage(value)
    engine.shutdown()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
