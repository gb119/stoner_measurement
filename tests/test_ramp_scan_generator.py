"""Tests for RampScanGenerator and RampScanWidget."""

from __future__ import annotations

import numpy as np
import pytest
from PyQt6.QtWidgets import QWidget

from stoner_measurement.scan import (
    BaseScanGenerator,
    RampMode,
    RampScanGenerator,
    RampScanWidget,
)


class TestRampScanGenerator:
    def test_generate_linear_endpoints(self, qapp):
        gen = RampScanGenerator(start=-2.0, end=3.0, num_points=11, mode=RampMode.LINEAR)
        values = gen.generate()
        assert len(values) == 11
        assert values[0] == -2.0
        assert values[-1] == 3.0

    def test_generate_endpoints_match_for_all_modes(self, qapp):
        for mode in RampMode:
            gen = RampScanGenerator(start=1.5, end=7.0, num_points=41, mode=mode, base=2.5)
            values = gen.generate()
            assert values[0] == pytest.approx(1.5)
            assert values[-1] == pytest.approx(7.0)

    def test_nonlinear_invalid_base_falls_back_to_linear(self, qapp):
        exp_gen = RampScanGenerator(start=0.0, end=4.0, num_points=10, mode=RampMode.EXPONENTIAL, base=1.0)
        log_gen = RampScanGenerator(start=0.0, end=4.0, num_points=10, mode=RampMode.LOGARITHMIC, base=1.0)
        pow_gen = RampScanGenerator(start=0.0, end=4.0, num_points=10, mode=RampMode.POWER, base=0.0)
        expected = np.linspace(0.0, 4.0, 10)
        assert np.allclose(exp_gen.generate(), expected)
        assert np.allclose(log_gen.generate(), expected)
        assert np.allclose(pow_gen.generate(), expected)

    def test_measure_flags_all_true(self, qapp):
        gen = RampScanGenerator(num_points=12)
        flags = gen.measure_flags()
        assert flags.dtype == bool
        assert flags.tolist() == [True] * 12

    def test_to_json_and_from_json_round_trip(self, qapp):
        gen = RampScanGenerator(
            start=-1.0,
            end=5.0,
            num_points=77,
            mode=RampMode.LOGARITHMIC,
            base=3.0,
        )
        restored = RampScanGenerator._from_json_data(gen.to_json())
        assert restored.start == gen.start
        assert restored.end == gen.end
        assert restored.num_points == gen.num_points
        assert restored.mode is gen.mode
        assert restored.base == gen.base

    def test_base_from_json_dispatch(self, qapp):
        gen = RampScanGenerator(mode=RampMode.POWER, base=2.2)
        restored = BaseScanGenerator.from_json(gen.to_json())
        assert isinstance(restored, RampScanGenerator)
        assert restored.mode is RampMode.POWER
        assert restored.base == 2.2

    def test_config_widget_returns_ramp_widget(self, qapp):
        gen = RampScanGenerator()
        widget = gen.config_widget()
        assert isinstance(widget, RampScanWidget)


class TestRampScanWidget:
    def test_is_qwidget(self, qapp):
        widget = RampScanWidget(generator=RampScanGenerator())
        assert isinstance(widget, QWidget)

    def test_start_spinbox_updates_generator(self, qapp):
        gen = RampScanGenerator(start=0.0)
        widget = RampScanWidget(generator=gen)
        widget._start_spin.setValue(4.2)
        assert gen.start == 4.2

    def test_end_spinbox_updates_generator(self, qapp):
        gen = RampScanGenerator(end=1.0)
        widget = RampScanWidget(generator=gen)
        widget._end_spin.setValue(-3.1)
        assert gen.end == -3.1

    def test_points_spinbox_updates_generator(self, qapp):
        gen = RampScanGenerator(num_points=10)
        widget = RampScanWidget(generator=gen)
        widget._points_spin.setValue(25)
        assert gen.num_points == 25

    def test_mode_combo_updates_generator(self, qapp):
        gen = RampScanGenerator(mode=RampMode.LINEAR)
        widget = RampScanWidget(generator=gen)
        power_index = list(RampMode).index(RampMode.POWER)
        widget._mode_combo.setCurrentIndex(power_index)
        assert gen.mode is RampMode.POWER

    def test_plot_curve_matches_generator_values(self, qapp):
        gen = RampScanGenerator(num_points=30)
        widget = RampScanWidget(generator=gen)
        widget._mode_combo.setCurrentIndex(list(RampMode).index(RampMode.EXPONENTIAL))
        widget._base_spin.setValue(3.0)
        _x, y = widget._curve.getData()
        assert np.allclose(y, gen.values)

    # ------------------------------------------------------------------
    # units — widget suffix propagation
    # ------------------------------------------------------------------

    def test_units_applied_to_start_and_end_spinboxes(self, qapp):
        gen = RampScanGenerator()
        widget = RampScanWidget(generator=gen)
        gen.units = "T"
        assert widget._start_spin.opts["suffix"] == "T"
        assert widget._end_spin.opts["suffix"] == "T"

    def test_units_not_applied_to_base_spinbox(self, qapp):
        gen = RampScanGenerator()
        widget = RampScanWidget(generator=gen)
        gen.units = "V"
        assert widget._base_spin.opts.get("suffix", "") != "V"

    def test_units_initialised_from_generator_at_construction(self, qapp):
        gen = RampScanGenerator()
        gen.units = "A"
        widget = RampScanWidget(generator=gen)
        assert widget._start_spin.opts["suffix"] == "A"
        assert widget._end_spin.opts["suffix"] == "A"

    def test_units_to_json_round_trip(self, qapp):
        gen = RampScanGenerator()
        gen.units = "V"
        d = gen.to_json()
        assert d["units"] == "V"
        restored = RampScanGenerator._from_json_data(d)
        assert restored.units == "V"

    def test_units_missing_from_json_defaults_empty(self, qapp):
        gen = RampScanGenerator()
        d = gen.to_json()
        d.pop("units", None)
        restored = RampScanGenerator._from_json_data(d)
        assert restored.units == ""
