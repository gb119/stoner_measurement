"""Tests for PercentSliderWidget."""

from __future__ import annotations

import pytest

from stoner_measurement.ui.widgets import PercentSliderWidget


class TestPercentSliderWidget:
    def test_creates_widget(self, qapp):
        widget = PercentSliderWidget()
        assert widget is not None

    def test_initial_value_zero(self, qapp):
        widget = PercentSliderWidget()
        assert widget.value() == pytest.approx(0.0)

    def test_set_value_updates_spinbox(self, qapp):
        widget = PercentSliderWidget()
        widget.setValue(50.0)
        assert widget.value() == pytest.approx(50.0)

    def test_set_value_updates_slider(self, qapp):
        widget = PercentSliderWidget()
        widget.setValue(50.0)
        # Slider should be at midpoint (500 out of 1000 steps).
        assert widget._slider.value() == 500

    def test_set_value_100(self, qapp):
        widget = PercentSliderWidget()
        widget.setValue(100.0)
        assert widget.value() == pytest.approx(100.0)
        assert widget._slider.value() == 1000

    def test_set_value_does_not_emit_signal(self, qapp):
        widget = PercentSliderWidget()
        received: list[float] = []
        widget.valueChanged.connect(received.append)
        widget.setValue(75.0)
        assert received == []

    def test_slider_change_emits_signal(self, qapp):
        widget = PercentSliderWidget()
        received: list[float] = []
        widget.valueChanged.connect(received.append)
        widget._slider.setValue(500)
        assert len(received) == 1
        assert received[0] == pytest.approx(50.0)

    def test_spinbox_change_emits_signal(self, qapp):
        widget = PercentSliderWidget()
        received: list[float] = []
        widget.valueChanged.connect(received.append)
        widget._spinbox.setValue(25.0)
        assert len(received) == 1
        assert received[0] == pytest.approx(25.0)

    def test_slider_change_syncs_spinbox(self, qapp):
        widget = PercentSliderWidget()
        widget._slider.setValue(750)
        assert widget._spinbox.value() == pytest.approx(75.0)

    def test_spinbox_change_syncs_slider(self, qapp):
        widget = PercentSliderWidget()
        widget._spinbox.setValue(10.0)
        assert widget._slider.value() == 100

    def test_set_enabled_disables_both_controls(self, qapp):
        widget = PercentSliderWidget()
        widget.setEnabled(False)
        assert not widget._slider.isEnabled()
        assert not widget._spinbox.isEnabled()

    def test_set_enabled_enables_both_controls(self, qapp):
        widget = PercentSliderWidget()
        widget.setEnabled(False)
        widget.setEnabled(True)
        assert widget._slider.isEnabled()
        assert widget._spinbox.isEnabled()

    def test_set_tooltip_propagates(self, qapp):
        widget = PercentSliderWidget()
        widget.setToolTip("Test tip")
        assert widget._slider.toolTip() == "Test tip"
        assert widget._spinbox.toolTip() == "Test tip"

    def test_spinbox_suffix_is_percent(self, qapp):
        widget = PercentSliderWidget()
        assert "%" in widget._spinbox.suffix()

    def test_block_signals_on_container_prevents_emission(self, qapp):
        """blockSignals on the container suppresses valueChanged."""
        widget = PercentSliderWidget()
        received: list[float] = []
        widget.valueChanged.connect(received.append)
        widget.blockSignals(True)
        widget._slider.setValue(500)
        widget.blockSignals(False)
        assert received == []
