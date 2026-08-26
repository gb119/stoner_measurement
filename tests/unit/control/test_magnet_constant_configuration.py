"""Magnet-constant configuration synchronisation tests."""

from __future__ import annotations

import pytest

from stoner_measurement.instruments.oxford import OxfordIPS120
from stoner_measurement.instruments.transport import NullTransport
from stoner_measurement.magnet_control import engine as engine_module
from stoner_measurement.magnet_control.engine import MagnetControllerEngine


def test_ips120_connection_preserves_persisted_magnet_constant(monkeypatch, qapp):
    """A software-only IPS120 constant is not replaced by its constructor default."""
    _ = qapp
    monkeypatch.setattr(
        engine_module,
        "load_magnet_controller_config",
        lambda: {
            "limits": {
                "magnet_constant": 0.075,
                "max_current": 120.0,
                "max_field": 9.0,
                "max_ramp_rate": 0.8,
            }
        },
    )
    engine = MagnetControllerEngine()
    driver = OxfordIPS120(NullTransport(responses=[b"VIPS120-10 3.07\r"]))

    engine.connect_instrument(driver)

    assert driver.magnet_constant == pytest.approx(0.075)
    assert engine.configuration_dict()["limits"]["magnet_constant"] == pytest.approx(0.075)
    engine.shutdown()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
