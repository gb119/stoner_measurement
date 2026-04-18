"""Tests for the scan generator class hierarchy."""

from __future__ import annotations

import numpy as np
import pytest
from PyQt6.QtWidgets import QWidget

from stoner_measurement.scan import (
    BaseScanGenerator,
    FunctionScanGenerator,
    FunctionScanWidget,
    WaveformType,
)


class TestBaseScanGenerator:
    # A minimal concrete subclass used to test the base class behaviours.
    class _Minimal(BaseScanGenerator):
        def generate(self) -> np.ndarray:
            return np.array([1.0, 2.0, 3.0])

        def measure_flags(self) -> np.ndarray:
            return np.array([True, True, True])

        def config_widget(self, parent=None) -> QWidget:
            return QWidget(parent)

        def to_json(self) -> dict:
            return {"type": "_Minimal"}

    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            BaseScanGenerator()  # type: ignore[abstract]

    def test_cannot_instantiate_missing_generate(self, qapp):
        """A subclass that only implements config_widget cannot be instantiated."""

        class _Partial(BaseScanGenerator):
            def measure_flags(self):
                return np.ones(5, dtype=bool)

            def config_widget(self, parent=None):
                return QWidget(parent)

            def to_json(self):
                return {"type": "_Partial"}

        with pytest.raises(TypeError):
            _Partial()

    def test_cannot_instantiate_missing_config_widget(self, qapp):
        """A subclass that only implements generate cannot be instantiated."""

        class _Partial(BaseScanGenerator):
            def generate(self):
                return np.zeros(5)

            def measure_flags(self):
                return np.ones(5, dtype=bool)

            def to_json(self):
                return {"type": "_Partial"}

        with pytest.raises(TypeError):
            _Partial()

    def test_cannot_instantiate_missing_measure_flags(self, qapp):
        """A subclass that does not implement measure_flags cannot be instantiated."""

        class _Partial(BaseScanGenerator):
            def generate(self):
                return np.zeros(5)

            def config_widget(self, parent=None):
                return QWidget(parent)

            def to_json(self):
                return {"type": "_Partial"}

        with pytest.raises(TypeError):
            _Partial()

    def test_values_returns_array(self, qapp):
        gen = self._Minimal()
        assert np.array_equal(gen.values, np.array([1.0, 2.0, 3.0]))

    def test_values_cached(self, qapp):
        gen = self._Minimal()
        assert gen.values is gen.values

    def test_flags_returns_boolean_array(self, qapp):
        gen = self._Minimal()
        assert np.array_equal(gen.flags, np.array([True, True, True]))

    def test_flags_cached(self, qapp):
        gen = self._Minimal()
        assert gen.flags is gen.flags

    def test_invalidate_cache_clears_cache(self, qapp):
        gen = self._Minimal()
        _ = gen.values
        _ = gen.flags
        gen._invalidate_cache()
        assert gen._cache is None
        assert gen._flags_cache is None

    def test_invalidate_cache_emits_signal(self, qapp):
        gen = self._Minimal()
        received: list[None] = []
        gen.values_changed.connect(lambda: received.append(None))
        gen._invalidate_cache()
        assert len(received) == 1

    def test_len(self, qapp):
        gen = self._Minimal()
        assert len(gen) == 3

    def test_iter_yields_all_values(self, qapp):
        gen = self._Minimal()
        assert list(gen) == [(0, 1.0, True), (1, 2.0, True), (2, 3.0, True)]

    def test_next_returns_tuple(self, qapp):
        gen = self._Minimal()
        it = iter(gen)
        result = next(it)
        assert isinstance(result, tuple)
        assert result == (0, 1.0, True)

    def test_next_raises_stop_iteration(self, qapp):
        gen = self._Minimal()
        it = iter(gen)
        next(it)
        next(it)
        next(it)
        with pytest.raises(StopIteration):
            next(it)

    def test_reset_restarts_iteration(self, qapp):
        gen = self._Minimal()
        list(gen)  # exhaust
        gen.reset()
        assert list(gen) == [(0, 1.0, True), (1, 2.0, True), (2, 3.0, True)]

    def test_current_value_changed_emitted_on_next(self, qapp):
        gen = self._Minimal()
        emitted: list[float] = []
        gen.current_value_changed.connect(emitted.append)
        it = iter(gen)
        next(it)
        next(it)
        assert emitted == [1.0, 2.0]

    def test_current_value_changed_all_values_emitted(self, qapp):
        gen = self._Minimal()
        emitted: list[float] = []
        gen.current_value_changed.connect(emitted.append)
        list(gen)
        assert emitted == [1.0, 2.0, 3.0]

    # ------------------------------------------------------------------
    # units property
    # ------------------------------------------------------------------

    def test_units_default_empty_string(self, qapp):
        gen = self._Minimal()
        assert gen.units == ""

    def test_units_setter_updates_value(self, qapp):
        gen = self._Minimal()
        gen.units = "V"
        assert gen.units == "V"

    def test_units_setter_emits_units_changed(self, qapp):
        gen = self._Minimal()
        emitted: list[str] = []
        gen.units_changed.connect(emitted.append)
        gen.units = "T"
        assert emitted == ["T"]

    def test_units_setter_does_not_invalidate_cache(self, qapp):
        """Changing units must not discard the value cache."""
        gen = self._Minimal()
        cached = gen.values
        gen.units = "A"
        assert gen._cache is not None
        assert gen._cache is cached

    def test_units_setter_coerces_to_str(self, qapp):
        gen = self._Minimal()
        gen.units = 42  # type: ignore[assignment]
        assert gen.units == "42"


class TestFunctionScanGenerator:
    # ------------------------------------------------------------------
    # generate() — array shape
    # ------------------------------------------------------------------

    @pytest.mark.parametrize("waveform", list(WaveformType))
    def test_generate_length(self, qapp, waveform):
        gen = FunctionScanGenerator(waveform=waveform, num_points=20)
        arr = gen.generate()
        assert isinstance(arr, np.ndarray)
        assert len(arr) == 20

    def test_generate_default_num_points(self, qapp):
        gen = FunctionScanGenerator()
        assert len(gen.generate()) == 100

    def test_generate_sine_starts_at_zero(self, qapp):
        gen = FunctionScanGenerator(waveform=WaveformType.SINE, amplitude=1.0, phase=0.0)
        arr = gen.generate()
        assert abs(arr[0]) < 1e-9

    def test_generate_cosine_via_phase_shift(self, qapp):
        """SINE at 90° phase gives cosine behaviour: first sample = amplitude."""
        gen = FunctionScanGenerator(waveform=WaveformType.SINE, amplitude=2.0, offset=0.0, phase=90.0)
        arr = gen.generate()
        assert abs(arr[0] - 2.0) < 1e-9

    def test_generate_triangle_range(self, qapp):
        gen = FunctionScanGenerator(
            waveform=WaveformType.TRIANGLE, amplitude=1.0, offset=0.0, num_points=200
        )
        arr = gen.generate()
        assert arr.max() <= 1.0 + 1e-9
        assert arr.min() >= -1.0 - 1e-9

    def test_generate_square_values(self, qapp):
        """Square wave values should be strictly ±amplitude (no zero crossings)."""
        gen = FunctionScanGenerator(
            waveform=WaveformType.SQUARE, amplitude=3.0, offset=0.0, num_points=100
        )
        arr = gen.generate()
        assert np.all(np.abs(np.abs(arr) - 3.0) < 1e-9)

    def test_generate_sawtooth_range(self, qapp):
        gen = FunctionScanGenerator(
            waveform=WaveformType.SAWTOOTH, amplitude=1.0, offset=0.0, num_points=200
        )
        arr = gen.generate()
        assert arr.max() <= 1.0 + 1e-9
        assert arr.min() >= -1.0 - 1e-9

    def test_generate_applies_amplitude(self, qapp):
        # Use a phase of 90° so the first sample lands exactly at the peak
        # (sin(π/2) = 1), giving an exact value without relying on dense sampling.
        gen = FunctionScanGenerator(waveform=WaveformType.SINE, amplitude=5.0, offset=0.0, phase=90.0)
        arr = gen.generate()
        assert abs(arr[0] - 5.0) < 1e-9

    def test_generate_applies_offset(self, qapp):
        gen = FunctionScanGenerator(
            waveform=WaveformType.SINE, amplitude=1.0, offset=10.0, num_points=100
        )
        arr = gen.generate()
        # All values shifted up by 10
        assert arr.min() >= 10.0 - 1.0 - 1e-9
        assert arr.max() <= 10.0 + 1.0 + 1e-9

    def test_generate_applies_phase(self, qapp):
        """A 90° phase shifts sine into cosine behaviour."""
        gen_sin = FunctionScanGenerator(waveform=WaveformType.SINE, phase=0.0, num_points=100)
        gen_cos = FunctionScanGenerator(waveform=WaveformType.SINE, phase=90.0, num_points=100)
        assert abs(gen_cos.generate()[0] - 1.0) < 1e-9  # sin(0 + π/2) = 1
        assert abs(gen_sin.generate()[0]) < 1e-9  # sin(0) = 0

    def test_generate_applies_exponent_before_scaling(self, qapp):
        gen = FunctionScanGenerator(
            waveform=WaveformType.SINE,
            amplitude=2.0,
            offset=1.0,
            phase=-90.0,
            exponent=2.0,
            num_points=100,
        )
        arr = gen.generate()
        # sin(-π/2) = -1 -> sign(-1)*|-1|^2 = -1 -> 2*(-1) + 1 = -1
        assert abs(arr[0] - (-1.0)) < 1e-9

    # ------------------------------------------------------------------
    # Boundary conditions
    # ------------------------------------------------------------------

    def test_generate_num_points_two(self, qapp):
        gen = FunctionScanGenerator(num_points=2)
        arr = gen.generate()
        assert len(arr) == 2

    def test_num_points_below_minimum_clamped(self, qapp):
        gen = FunctionScanGenerator(num_points=0)
        assert gen.num_points == 2

    def test_amplitude_zero_gives_constant_offset(self, qapp):
        gen = FunctionScanGenerator(amplitude=0.0, offset=3.5, num_points=10)
        arr = gen.generate()
        assert np.allclose(arr, 3.5)

    # ------------------------------------------------------------------
    # Iterator interface
    # ------------------------------------------------------------------

    def test_iter_yields_num_points_values(self, qapp):
        gen = FunctionScanGenerator(num_points=7)
        values = list(gen)
        assert len(values) == 7

    def test_iter_raises_stop_iteration(self, qapp):
        gen = FunctionScanGenerator(num_points=3)
        it = iter(gen)
        next(it)
        next(it)
        next(it)
        with pytest.raises(StopIteration):
            next(it)

    def test_iter_values_match_generate(self, qapp):
        gen = FunctionScanGenerator(num_points=10)
        expected = gen.generate()
        collected = [value for _, value, _ in gen]
        assert np.allclose(collected, expected)

    def test_len(self, qapp):
        gen = FunctionScanGenerator(num_points=15)
        assert len(gen) == 15

    # ------------------------------------------------------------------
    # reset()
    # ------------------------------------------------------------------

    def test_reset_allows_reiteration(self, qapp):
        gen = FunctionScanGenerator(num_points=5)
        first_pass = list(gen)
        gen.reset()
        second_pass = list(gen)
        assert first_pass == second_pass

    def test_reset_sets_index_to_zero(self, qapp):
        gen = FunctionScanGenerator(num_points=5)
        list(gen)  # exhaust iterator
        gen.reset()
        assert gen._index == 0

    # ------------------------------------------------------------------
    # Value caching
    # ------------------------------------------------------------------

    def test_values_cached_on_repeated_access(self, qapp):
        gen = FunctionScanGenerator(num_points=10)
        first = gen.values
        second = gen.values
        assert first is second  # same object — not recomputed

    def test_parameter_change_invalidates_cache(self, qapp):
        gen = FunctionScanGenerator(num_points=10)
        first = gen.values
        gen.amplitude = 2.0
        second = gen.values
        assert first is not second

    def test_waveform_change_invalidates_cache(self, qapp):
        gen = FunctionScanGenerator()
        _ = gen.values
        gen.waveform = WaveformType.TRIANGLE
        assert gen._cache is None

    def test_offset_change_invalidates_cache(self, qapp):
        gen = FunctionScanGenerator()
        _ = gen.values
        gen.offset = 5.0
        assert gen._cache is None

    def test_phase_change_invalidates_cache(self, qapp):
        gen = FunctionScanGenerator()
        _ = gen.values
        gen.phase = 45.0
        assert gen._cache is None

    def test_num_points_change_invalidates_cache(self, qapp):
        gen = FunctionScanGenerator()
        _ = gen.values
        gen.num_points = 50
        assert gen._cache is None

    def test_values_changed_signal_emitted(self, qapp):
        gen = FunctionScanGenerator()
        _ = gen.values
        received: list[None] = []
        gen.values_changed.connect(lambda: received.append(None))
        gen.amplitude = 3.0
        assert len(received) == 1

    # ------------------------------------------------------------------
    # periods parameter
    # ------------------------------------------------------------------

    def test_default_periods_is_one(self, qapp):
        gen = FunctionScanGenerator()
        assert gen.periods == 1.0

    def test_default_exponent_is_one(self, qapp):
        gen = FunctionScanGenerator()
        assert gen.exponent == 1.0

    def test_generate_half_period(self, qapp):
        """0.5 periods of sine: starts at 0, peaks at midpoint, ends near 0."""
        gen = FunctionScanGenerator(
            waveform=WaveformType.SINE, amplitude=1.0, offset=0.0, phase=0.0,
            periods=0.5, num_points=101
        )
        arr = gen.generate()
        assert len(arr) == 101
        assert abs(arr[0]) < 1e-9         # sin(0) = 0
        assert abs(arr[50] - 1.0) < 1e-9  # peak at midpoint: sin(π/2) = 1
        assert abs(arr[-1]) < 1e-9        # sin(π) ≈ 0

    def test_generate_two_periods_length(self, qapp):
        gen = FunctionScanGenerator(num_points=50, periods=2.0)
        arr = gen.generate()
        assert len(arr) == 50

    def test_generate_two_periods_sine_symmetry(self, qapp):
        """Two periods of sine: the midpoint and endpoint are both ≈ 0."""
        gen = FunctionScanGenerator(
            waveform=WaveformType.SINE, amplitude=1.0, offset=0.0, phase=0.0,
            periods=2.0, num_points=201
        )
        arr = gen.generate()
        # Midpoint is at 2π (start of second period): sin(2π) = 0
        assert abs(arr[100]) < 1e-9
        # Endpoint is at 4π: sin(4π) ≈ 0
        assert abs(arr[-1]) < 1e-9

    def test_periods_change_invalidates_cache(self, qapp):
        gen = FunctionScanGenerator()
        _ = gen.values
        gen.periods = 2.0
        assert gen._cache is None

    def test_exponent_change_invalidates_cache(self, qapp):
        gen = FunctionScanGenerator()
        _ = gen.values
        gen.exponent = 2.0
        assert gen._cache is None

    def test_periods_below_minimum_clamped(self, qapp):
        gen = FunctionScanGenerator(periods=0.0)
        assert gen.periods > 0.0

    def test_periods_signal_emitted(self, qapp):
        gen = FunctionScanGenerator()
        received: list[None] = []
        gen.values_changed.connect(lambda: received.append(None))
        gen.periods = 3.0
        assert len(received) == 1

    def test_exponent_signal_emitted(self, qapp):
        gen = FunctionScanGenerator()
        received: list[None] = []
        gen.values_changed.connect(lambda: received.append(None))
        gen.exponent = 2.0
        assert len(received) == 1

    # ------------------------------------------------------------------
    # measure_flags()
    # ------------------------------------------------------------------

    def test_measure_flags_returns_all_true(self, qapp):
        gen = FunctionScanGenerator(num_points=10)
        flags = gen.measure_flags()
        assert isinstance(flags, np.ndarray)
        assert flags.dtype == bool
        assert flags.tolist() == [True] * 10

    def test_measure_flags_length_matches_num_points(self, qapp):
        gen = FunctionScanGenerator(num_points=7)
        assert len(gen.measure_flags()) == 7

    def test_flags_property_cached(self, qapp):
        gen = FunctionScanGenerator(num_points=5)
        assert gen.flags is gen.flags

    def test_flags_cache_invalidated_on_num_points_change(self, qapp):
        gen = FunctionScanGenerator(num_points=5)
        _ = gen.flags
        gen.num_points = 10
        assert gen._flags_cache is None

    def test_iter_yields_tuples_with_true_measure(self, qapp):
        gen = FunctionScanGenerator(num_points=3)
        results = list(gen)
        assert all(isinstance(r, tuple) and len(r) == 3 for r in results)
        assert all(r[2] is True for r in results)

    def test_current_value_changed_emitted_during_iteration(self, qapp):
        gen = FunctionScanGenerator(num_points=4)
        emitted: list[float] = []
        gen.current_value_changed.connect(emitted.append)
        list(gen)
        assert len(emitted) == 4
        expected_values = gen.values.tolist()
        assert emitted == pytest.approx(expected_values)

    # ------------------------------------------------------------------
    # config_widget()
    # ------------------------------------------------------------------

    def test_config_widget_returns_function_scan_widget(self, qapp):
        gen = FunctionScanGenerator()
        widget = gen.config_widget()
        assert isinstance(widget, FunctionScanWidget)

    def test_config_widget_bound_to_generator(self, qapp):
        gen = FunctionScanGenerator()
        widget = gen.config_widget()
        assert widget.get_generator() is gen


class TestFunctionScanWidget:
    def test_instantiates(self, qapp):
        gen = FunctionScanGenerator()
        widget = FunctionScanWidget(generator=gen)
        assert widget is not None

    def test_is_qwidget(self, qapp):
        gen = FunctionScanGenerator()
        widget = FunctionScanWidget(generator=gen)
        assert isinstance(widget, QWidget)

    def test_get_generator(self, qapp):
        gen = FunctionScanGenerator()
        widget = FunctionScanWidget(generator=gen)
        assert widget.get_generator() is gen

    def test_amplitude_spinbox_updates_generator(self, qapp):
        gen = FunctionScanGenerator(amplitude=1.0)
        widget = FunctionScanWidget(generator=gen)
        widget._amplitude_spin.setValue(3.5)
        assert abs(gen.amplitude - 3.5) < 1e-9

    def test_offset_spinbox_updates_generator(self, qapp):
        gen = FunctionScanGenerator(offset=0.0)
        widget = FunctionScanWidget(generator=gen)
        widget._offset_spin.setValue(2.0)
        assert abs(gen.offset - 2.0) < 1e-9

    def test_phase_spinbox_updates_generator(self, qapp):
        gen = FunctionScanGenerator(phase=0.0)
        widget = FunctionScanWidget(generator=gen)
        widget._phase_spin.setValue(90.0)
        assert abs(gen.phase - 90.0) < 1e-9

    def test_points_spinbox_updates_generator(self, qapp):
        gen = FunctionScanGenerator(num_points=100)
        widget = FunctionScanWidget(generator=gen)
        widget._points_spin.setValue(50)
        assert gen.num_points == 50

    def test_waveform_combo_updates_generator(self, qapp):
        gen = FunctionScanGenerator(waveform=WaveformType.SINE)
        widget = FunctionScanWidget(generator=gen)
        triangle_index = list(WaveformType).index(WaveformType.TRIANGLE)
        widget._waveform_combo.setCurrentIndex(triangle_index)
        assert gen.waveform is WaveformType.TRIANGLE

    def test_plot_curve_data_matches_generator_after_change(self, qapp):
        gen = FunctionScanGenerator(num_points=20)
        widget = FunctionScanWidget(generator=gen)
        widget._amplitude_spin.setValue(2.0)
        _x, y = widget._curve.getData()
        assert np.allclose(y, gen.values)

    def test_initial_plot_curve_data_matches_generator(self, qapp):
        gen = FunctionScanGenerator(num_points=10)
        widget = FunctionScanWidget(generator=gen)
        _x, y = widget._curve.getData()
        assert np.allclose(y, gen.values)

    def test_external_generator_change_refreshes_plot(self, qapp):
        """Changing a generator parameter from outside still updates the plot."""
        gen = FunctionScanGenerator(num_points=10)
        widget = FunctionScanWidget(generator=gen)
        gen.amplitude = 5.0  # triggers values_changed → _refresh_plot
        _x, y = widget._curve.getData()
        assert np.allclose(y, gen.values)

    def test_periods_spinbox_updates_generator(self, qapp):
        gen = FunctionScanGenerator(periods=1.0)
        widget = FunctionScanWidget(generator=gen)
        widget._periods_spin.setValue(2.5)
        assert abs(gen.periods - 2.5) < 1e-9

    def test_periods_spinbox_initial_value(self, qapp):
        gen = FunctionScanGenerator(periods=0.5)
        widget = FunctionScanWidget(generator=gen)
        assert abs(widget._periods_spin.value() - 0.5) < 1e-9

    def test_exponent_spinbox_updates_generator(self, qapp):
        gen = FunctionScanGenerator(exponent=1.0)
        widget = FunctionScanWidget(generator=gen)
        widget._exponent_spin.setValue(3.0)
        assert abs(gen.exponent - 3.0) < 1e-9

    def test_exponent_spinbox_initial_value(self, qapp):
        gen = FunctionScanGenerator(exponent=2.0)
        widget = FunctionScanWidget(generator=gen)
        assert abs(widget._exponent_spin.value() - 2.0) < 1e-9

    # ------------------------------------------------------------------
    # units — widget suffix propagation
    # ------------------------------------------------------------------

    def test_units_applied_to_amplitude_and_offset_spinboxes(self, qapp):
        gen = FunctionScanGenerator()
        widget = FunctionScanWidget(generator=gen)
        gen.units = "V"
        assert widget._amplitude_spin.opts["suffix"] == "V"
        assert widget._offset_spin.opts["suffix"] == "V"

    def test_units_not_applied_to_phase_or_exponent_spinboxes(self, qapp):
        gen = FunctionScanGenerator()
        widget = FunctionScanWidget(generator=gen)
        gen.units = "T"
        assert widget._phase_spin.opts.get("suffix", "") != "T"
        assert widget._exponent_spin.opts.get("suffix", "") != "T"

    def test_units_initialised_from_generator_at_construction(self, qapp):
        gen = FunctionScanGenerator()
        gen.units = "A"
        widget = FunctionScanWidget(generator=gen)
        assert widget._amplitude_spin.opts["suffix"] == "A"

    def test_units_to_json_round_trip(self, qapp):
        gen = FunctionScanGenerator()
        gen.units = "V"
        d = gen.to_json()
        assert d["units"] == "V"
        restored = FunctionScanGenerator._from_json_data(d)
        assert restored.units == "V"

    def test_units_missing_from_json_defaults_empty(self, qapp):
        gen = FunctionScanGenerator()
        d = gen.to_json()
        d.pop("units", None)
        restored = FunctionScanGenerator._from_json_data(d)
        assert restored.units == ""
