"""Tests for the refreshable Thorlabs APT controller selector."""

from __future__ import annotations

import pytest

from stoner_measurement.instruments.thorlabs.hdr50 import AptControllerInfo
from stoner_measurement.ui.widgets.apt_controller_widget import AptControllerComboBox


def _controller(serial: str, model: str = "BSC201") -> AptControllerInfo:
    return AptControllerInfo(
        serial_number=serial,
        model=model,
        software_version="APT 3.21",
        hardware_notes="Benchtop stepper",
        hardware_type=11,
    )


def test_widget_populates_discovered_controllers(qapp):
    widget = AptControllerComboBox(
        discover=lambda: [_controller("70001234")], auto_refresh=True
    )

    assert widget.combo.count() == 1
    assert widget.combo.itemText(0) == "70001234 — BSC201"
    widget.combo.setCurrentIndex(0)
    assert widget.current_serial() == "70001234"


def test_refresh_preserves_manual_serial_number(qapp):
    controllers = [_controller("70001234")]
    widget = AptControllerComboBox(discover=lambda: controllers)
    widget.set_serial("70009999")

    controllers.append(_controller("70005678"))
    widget.refresh()

    assert widget.current_serial() == "70009999"


def test_refresh_preserves_discovered_selection(qapp):
    controllers = [_controller("70001234"), _controller("70005678")]
    widget = AptControllerComboBox(discover=lambda: controllers)
    widget.set_serial("70005678")

    widget.refresh()

    assert widget.current_serial() == "70005678"


def test_editing_a_discovered_selection_returns_manual_text(qapp):
    widget = AptControllerComboBox(
        discover=lambda: [_controller("70001234")], auto_refresh=True
    )
    widget.combo.setCurrentIndex(0)

    widget.combo.setEditText("70009999")

    assert widget.current_serial() == "70009999"


def test_refresh_logs_discovery_error_and_keeps_manual_entry(qapp, caplog):
    def fail():
        raise RuntimeError("APT unavailable")

    widget = AptControllerComboBox(discover=lambda: [])
    widget.set_serial("70009999")
    with caplog.at_level("ERROR"):
        widget._discover = fail  # noqa: SLF001
        widget.refresh()

    assert widget.current_serial() == "70009999"
    assert "APT unavailable" in caplog.text


def test_construction_defers_hardware_discovery_until_refresh(qapp):
    calls = []
    widget = AptControllerComboBox(discover=lambda: calls.append(True) or [])

    assert calls == []

    widget.refresh()

    assert calls == [True]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
