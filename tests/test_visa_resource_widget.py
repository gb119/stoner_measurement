"""Tests for the VisaResourceComboBox widget and related helpers."""

from __future__ import annotations

import pytest

from stoner_measurement.ui.widgets.visa_resource_widget import (
    FILTER_ALL,
    FILTER_GPIB,
    FILTER_SERIAL,
    VisaResourceComboBox,
    VisaResourceStatus,
    list_visa_resources,
)


class TestListVisaResources:
    def test_returns_list(self):
        result = list_visa_resources()
        assert isinstance(result, list)

    def test_returns_list_with_filter(self):
        result = list_visa_resources(FILTER_GPIB)
        assert isinstance(result, list)

    def test_returns_list_serial_filter(self):
        result = list_visa_resources(FILTER_SERIAL)
        assert isinstance(result, list)

    def test_all_items_are_strings(self):
        for item in list_visa_resources():
            assert isinstance(item, str)


class TestVisaResourceStatus:
    def test_values(self):
        assert VisaResourceStatus.DISCONNECTED.value == "disconnected"
        assert VisaResourceStatus.CONNECTING.value == "connecting"
        assert VisaResourceStatus.CONNECTED.value == "connected"
        assert VisaResourceStatus.ERROR.value == "error"


class TestVisaResourceComboBox:
    def test_creates_widget(self, qapp):
        w = VisaResourceComboBox()
        assert w is not None

    def test_default_status_is_disconnected(self, qapp):
        w = VisaResourceComboBox()
        assert w.status is VisaResourceStatus.DISCONNECTED

    def test_combo_property_returns_qcombobox(self, qapp):
        from PyQt6.QtWidgets import QComboBox

        w = VisaResourceComboBox()
        assert isinstance(w.combo, QComboBox)

    def test_extra_resources_appear_in_combo(self, qapp):
        w = VisaResourceComboBox(extra_resources=["GPIB0::2::INSTR", "GPIB0::3::INSTR"])
        items = [w.combo.itemText(i) for i in range(w.combo.count())]
        assert "GPIB0::2::INSTR" in items
        assert "GPIB0::3::INSTR" in items

    def test_set_resource_selects_existing(self, qapp):
        w = VisaResourceComboBox(extra_resources=["GPIB0::5::INSTR"])
        w.set_resource("GPIB0::5::INSTR")
        assert w.current_resource() == "GPIB0::5::INSTR"

    def test_set_resource_adds_if_absent(self, qapp):
        w = VisaResourceComboBox()
        w.set_resource("GPIB0::22::INSTR")
        assert w.current_resource() == "GPIB0::22::INSTR"

    def test_current_resource_strips_whitespace(self, qapp):
        w = VisaResourceComboBox()
        w.combo.setEditText("  GPIB0::7::INSTR  ")
        assert w.current_resource() == "GPIB0::7::INSTR"

    def test_set_status_connected(self, qapp):
        w = VisaResourceComboBox()
        w.set_status(VisaResourceStatus.CONNECTED)
        assert w.status is VisaResourceStatus.CONNECTED
        assert "90ee90" in w.combo.styleSheet().lower()

    def test_set_status_connecting(self, qapp):
        w = VisaResourceComboBox()
        w.set_status(VisaResourceStatus.CONNECTING)
        assert w.status is VisaResourceStatus.CONNECTING
        assert "ffd580" in w.combo.styleSheet().lower()

    def test_set_status_error(self, qapp):
        w = VisaResourceComboBox()
        w.set_status(VisaResourceStatus.ERROR)
        assert w.status is VisaResourceStatus.ERROR
        assert "ffaaaa" in w.combo.styleSheet().lower()

    def test_set_status_disconnected_clears_stylesheet(self, qapp):
        w = VisaResourceComboBox()
        w.set_status(VisaResourceStatus.CONNECTED)
        w.set_status(VisaResourceStatus.DISCONNECTED)
        assert w.status is VisaResourceStatus.DISCONNECTED
        assert w.combo.styleSheet() == ""

    def test_refresh_preserves_selection(self, qapp):
        w = VisaResourceComboBox(extra_resources=["GPIB0::5::INSTR"])
        w.set_resource("GPIB0::5::INSTR")
        w.refresh()
        assert w.current_resource() == "GPIB0::5::INSTR"

    def test_refresh_signal_emitted(self, qapp):
        w = VisaResourceComboBox()
        received = []
        w.refresh_requested.connect(lambda: received.append(True))
        w.refresh()
        assert len(received) == 1

    def test_resource_changed_signal_on_set(self, qapp):
        w = VisaResourceComboBox()
        received = []
        w.resource_changed.connect(received.append)
        w.set_resource("GPIB0::9::INSTR")
        assert any("GPIB0::9::INSTR" in r for r in received)

    def test_filter_all_constant(self):
        assert FILTER_ALL == "?*::INSTR"

    def test_filter_serial_constant(self):
        assert FILTER_SERIAL == "ASRL*::INSTR"

    def test_filter_gpib_constant(self):
        assert FILTER_GPIB == "GPIB*::*::INSTR"

    def test_widget_has_refresh_button(self, qapp):
        from PyQt6.QtWidgets import QPushButton

        w = VisaResourceComboBox()
        buttons = w.findChildren(QPushButton)
        assert any(b.text() == "Refresh" for b in buttons)

    def test_combo_is_editable(self, qapp):
        w = VisaResourceComboBox()
        assert w.combo.isEditable()

    def test_placeholder_text_set(self, qapp):
        w = VisaResourceComboBox(placeholder="test placeholder")
        assert w.combo.placeholderText() == "test placeholder"
