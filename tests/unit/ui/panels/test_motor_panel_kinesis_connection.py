"""Tests for Thorlabs Kinesis USB connection controls in the motor panel."""

from __future__ import annotations

import pytest
from qtpy.QtCore import Qt

from stoner_measurement.ui.motor_panel import MotorControlPanel
from stoner_measurement.ui.widgets import (
    restore_connection_address,
    selected_transport,
)


def _select_driver(panel: MotorControlPanel, name: str) -> None:
    index = panel._driver_combo.findData(  # noqa: SLF001
        name,
        role=Qt.ItemDataRole.UserRole + 1,
    )
    assert index >= 0
    panel._driver_combo.setCurrentIndex(index)  # noqa: SLF001


def test_selecting_thorlabs_driver_selects_kinesis_usb(qapp):
    """Thorlabs drivers should make their direct USB route immediately visible."""
    panel = MotorControlPanel()

    _select_driver(panel, "ThorlabsKDC101KPRMTE")

    assert panel._transport_combo.currentText() == "Kinesis USB"  # noqa: SLF001
    assert panel._kinesis_form_widget.isVisibleTo(panel)  # noqa: SLF001


def test_kinesis_serial_number_round_trips_through_connection_helpers(qapp):
    """The controller serial number should be selected and restored as the address."""
    panel = MotorControlPanel()
    _select_driver(panel, "ThorlabsHDR50")
    panel._kinesis_serial_edit.setText("  12345678  ")  # noqa: SLF001

    assert selected_transport(
        panel,
        panel._transport_combo.currentIndex(),  # noqa: SLF001
    ) == ("Kinesis USB", "12345678")

    panel._kinesis_serial_edit.clear()  # noqa: SLF001
    restore_connection_address(panel, "Kinesis USB", "87654321")
    assert panel._kinesis_serial_edit.text() == "87654321"  # noqa: SLF001


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
