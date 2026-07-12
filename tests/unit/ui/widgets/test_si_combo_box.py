"""Tests for the SIComboBox widget."""

from __future__ import annotations

import pytest

from stoner_measurement.ui.widgets import SIComboBox

# ---------------------------------------------------------------------------
# format_si static method
# ---------------------------------------------------------------------------

class TestFormatSI:
    def test_nano(self):
        assert SIComboBox.format_si(1e-9, "A") == "1 nA"

    def test_micro(self):
        assert SIComboBox.format_si(1e-6, "A") == "1 µA"

    def test_milli(self):
        assert SIComboBox.format_si(1e-3, "A") == "1 mA"

    def test_milli_volts(self):
        assert SIComboBox.format_si(100e-3, "V") == "100 mV"

    def test_pico(self):
        # siFormat rounds 1e-10 into the pico range: 100 pA
        assert SIComboBox.format_si(1e-10, "A") == "100 pA"

    def test_unity(self):
        assert SIComboBox.format_si(1.0, "V") == "1 V"

    def test_large(self):
        assert SIComboBox.format_si(120.0, "V") == "120 V"


# ---------------------------------------------------------------------------
# Construction and addValueItem
# ---------------------------------------------------------------------------

class TestAddValueItem:
    def test_label_auto_formatted(self, qapp):
        cb = SIComboBox(unit="A")
        cb.addValueItem(1e-9)
        assert cb.itemText(0) == "1 nA"

    def test_data_stored_as_float(self, qapp):
        cb = SIComboBox(unit="A")
        cb.addValueItem(1e-3)
        assert cb.itemData(0) == pytest.approx(1e-3)

    def test_custom_label_respected(self, qapp):
        cb = SIComboBox(unit="A")
        cb.addValueItem(1e-3, label="1 mA (custom)")
        assert cb.itemText(0) == "1 mA (custom)"

    def test_multiple_items(self, qapp):
        cb = SIComboBox(unit="V")
        for v in (0.01, 0.1, 1.0, 10.0, 100.0):
            cb.addValueItem(v)
        assert cb.count() == 5
        assert cb.itemText(0) == "10 mV"
        assert cb.itemText(2) == "1 V"


# ---------------------------------------------------------------------------
# addSpecialItem
# ---------------------------------------------------------------------------

class TestAddSpecialItem:
    def test_label_stored(self, qapp):
        cb = SIComboBox(unit="V")
        cb.addSpecialItem("Auto", 0.0)
        assert cb.itemText(0) == "Auto"

    def test_data_stored(self, qapp):
        cb = SIComboBox(unit="V")
        cb.addSpecialItem("Auto", 0.0)
        assert cb.itemData(0) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# currentFloatValue and setFloatValue
# ---------------------------------------------------------------------------

class TestValueAccessors:
    def test_current_float_value_returns_first(self, qapp):
        cb = SIComboBox(unit="V")
        cb.addValueItem(1.0)
        cb.addValueItem(10.0)
        assert cb.currentFloatValue() == pytest.approx(1.0)

    def test_set_float_value_selects_correct_item(self, qapp):
        cb = SIComboBox(unit="V")
        cb.addSpecialItem("Auto", 0.0)
        cb.addValueItem(1.0)
        cb.addValueItem(10.0)
        cb.setFloatValue(10.0)
        assert cb.currentFloatValue() == pytest.approx(10.0)

    def test_set_float_value_no_match_unchanged(self, qapp):
        cb = SIComboBox(unit="V")
        cb.addValueItem(1.0)
        cb.addValueItem(10.0)
        cb.setCurrentIndex(0)
        cb.setFloatValue(999.0)  # no match
        assert cb.currentIndex() == 0  # unchanged

    def test_set_float_value_zero_special_item(self, qapp):
        cb = SIComboBox(unit="V")
        cb.addSpecialItem("Auto", 0.0)
        cb.addValueItem(1.0)
        cb.setCurrentIndex(1)
        cb.setFloatValue(0.0)
        assert cb.currentIndex() == 0

    def test_current_float_value_non_float_data_raises(self, qapp):
        cb = SIComboBox(unit="V")
        cb.addItem("Mode A", "not_a_float")
        with pytest.raises((TypeError, ValueError)):
            cb.currentFloatValue()


# ---------------------------------------------------------------------------
# valueChanged signal
# ---------------------------------------------------------------------------

class TestValueChangedSignal:
    def test_signal_emitted_on_selection_change(self, qapp):
        cb = SIComboBox(unit="V")
        cb.addValueItem(1.0)
        cb.addValueItem(10.0)
        received = []
        cb.valueChanged.connect(received.append)
        cb.setCurrentIndex(1)
        assert received == [pytest.approx(10.0)]

    def test_signal_not_emitted_for_non_float_data(self, qapp):
        cb = SIComboBox(unit="V")
        cb.addItem("Mode A", "not_a_float")
        cb.addItem("Mode B", "also_not_a_float")
        received = []
        cb.valueChanged.connect(received.append)
        cb.setCurrentIndex(1)
        assert received == []


# ---------------------------------------------------------------------------
# Integration: mixed special + value items
# ---------------------------------------------------------------------------

class TestMixedItems:
    def test_voltage_range_combo(self, qapp):
        cb = SIComboBox(unit="V")
        cb.addSpecialItem("Auto", 0.0)
        for v in (0.01, 0.1, 1.0, 10.0, 100.0, 120.0):
            cb.addValueItem(v)
        assert cb.count() == 7
        assert cb.itemText(0) == "Auto"
        assert cb.itemText(1) == "10 mV"
        assert cb.itemText(3) == "1 V"
        cb.setFloatValue(0.1)
        assert cb.currentFloatValue() == pytest.approx(0.1)

    def test_current_range_combo(self, qapp):
        cb = SIComboBox(unit="A")
        for v in (1e-10, 1e-9, 1e-8, 1e-7, 1e-6, 1e-5, 1e-4, 1e-3, 1e-2, 1e-1):
            cb.addValueItem(v)
        assert cb.itemText(0) == "100 pA"
        assert cb.itemText(1) == "1 nA"
        assert cb.itemText(3) == "100 nA"
        assert cb.itemText(6) == "100 µA"
        assert cb.itemText(9) == "100 mA"


if __name__ == "__main__":

    raise SystemExit(pytest.main([__file__, "--pdb"]))
