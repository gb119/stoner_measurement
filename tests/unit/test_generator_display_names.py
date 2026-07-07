"""Tests for human-friendly scan/sweep generator labels."""

from __future__ import annotations

from qtpy.QtWidgets import QWidget

from stoner_measurement.scan import BaseScanGenerator, FunctionScanGenerator, RampScanGenerator
from stoner_measurement.sweep import BaseSweepGenerator, MultiSegmentRampSweepGenerator


class _DisplayNamedScanGenerator(BaseScanGenerator):
    DISPLAY_NAME = "Custom Scan"

    def to_json(self):
        return {"type": "_DisplayNamedScanGenerator"}

    @classmethod
    def _from_json_data(cls, data, parent=None):
        return cls(parent=parent)

    def generate(self):
        return []

    def measure_flags(self):
        return []

    def config_widget(self, parent: QWidget | None = None) -> QWidget:
        return QWidget(parent)


class _DisplayNamedSweepGenerator(BaseSweepGenerator):
    DISPLAY_NAME = "Custom Sweep"

    def iter_points(self):
        yield from ()

    def config_widget(self, parent: QWidget | None = None) -> QWidget:
        return QWidget(parent)

    @classmethod
    def _from_json_data(cls, data, *, state_sweep=None, parent=None):
        return cls(state_sweep=state_sweep, parent=parent)


def test_scan_generator_display_name_splits_camel_case_and_numbers():
    assert FunctionScanGenerator.display_name() == "Function Scan Generator"
    assert RampScanGenerator.display_name() == "Ramp Scan Generator"


def test_sweep_generator_display_name_splits_camel_case_and_numbers():
    assert MultiSegmentRampSweepGenerator.display_name() == "Multi Segment Ramp Sweep Generator"


def test_scan_generator_display_name_honours_display_name_attribute():
    assert _DisplayNamedScanGenerator.display_name() == "Custom Scan"


def test_sweep_generator_display_name_honours_display_name_attribute():
    assert _DisplayNamedSweepGenerator.display_name() == "Custom Sweep"
