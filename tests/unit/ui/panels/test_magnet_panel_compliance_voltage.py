"""Compliance-voltage controls in the magnet panel."""

from __future__ import annotations

import pytest

from stoner_measurement.magnet_control.engine import MagnetControllerEngine
from stoner_measurement.ui.magnet_panel import MagnetControlPanel


@pytest.fixture(autouse=True)
def cleanup_magnet_engine():
    """Keep the singleton engine isolated between panel tests."""
    engine = MagnetControllerEngine._singleton  # noqa: SLF001
    if engine is not None:
        engine.shutdown()
    yield
    engine = MagnetControllerEngine._singleton  # noqa: SLF001
    if engine is not None:
        engine.shutdown()


def test_panel_restores_and_applies_cached_compliance(managed_qt_widget):
    """The persisted value appears in the panel and participates in Apply."""
    engine = MagnetControllerEngine.instance()
    engine._compliance_voltage = 4.5  # noqa: SLF001
    panel = managed_qt_widget(MagnetControlPanel())

    assert panel._compliance_voltage_spin.value() == pytest.approx(4.5)  # noqa: SLF001

    panel._compliance_voltage_spin.setValue(6.0)  # noqa: SLF001
    panel._on_apply_limits()  # noqa: SLF001

    assert engine.compliance_voltage == pytest.approx(6.0)


def test_panel_read_limits_refreshes_compliance(monkeypatch, managed_qt_widget):
    """Read refreshes the compliance control alongside magnet limits."""
    panel = managed_qt_widget(MagnetControlPanel())
    monkeypatch.setattr(panel._engine, "refresh_magnet_constant", lambda: None)  # noqa: SLF001
    monkeypatch.setattr(panel._engine, "get_limits", lambda: None)  # noqa: SLF001
    monkeypatch.setattr(panel._engine, "refresh_compliance_voltage", lambda: 7.25)  # noqa: SLF001

    panel._on_read_limits()  # noqa: SLF001

    assert panel._compliance_voltage_spin.value() == pytest.approx(7.25)  # noqa: SLF001


def test_panel_save_persists_compliance(monkeypatch, managed_qt_widget, tmp_path):
    """Save transfers the panel value into the engine YAML mapping."""
    panel = managed_qt_widget(MagnetControlPanel())
    panel._compliance_voltage_spin.setValue(8.5)  # noqa: SLF001
    monkeypatch.setattr(
        "stoner_measurement.ui.magnet_panel.selected_transport",
        lambda *_args, **_kwargs: ("Null (test)", ""),
    )
    monkeypatch.setattr(panel._engine, "save_configuration", lambda: tmp_path / "magnet_controller.yaml")  # noqa: SLF001
    monkeypatch.setattr(
        "stoner_measurement.ui.magnet_panel.QMessageBox.information",
        lambda *_args, **_kwargs: 0,
    )

    panel._on_save_configuration()  # noqa: SLF001

    assert panel._engine.configuration_dict()["limits"]["compliance_voltage"] == pytest.approx(8.5)  # noqa: SLF001


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
