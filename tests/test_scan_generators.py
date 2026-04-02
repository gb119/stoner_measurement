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
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            BaseScanGenerator()  # type: ignore[abstract]

    def test_cannot_instantiate_missing_generate(self, qapp):
        """A subclass that only implements config_widget cannot be instantiated."""

        class _Partial(BaseScanGenerator):
            def config_widget(self, parent=None):
                return QWidget(parent)

        with pytest.raises(TypeError):
            _Partial()

    def test_cannot_instantiate_missing_config_widget(self, qapp):
        """A subclass that only implements generate cannot be instantiated."""

        class _Partial(BaseScanGenerator):
            def generate(self):
                return np.zeros(5)

        with pytest.raises(TypeError):
            _Partial()


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

    def test_generate_cosine_starts_at_amplitude(self, qapp):
        gen = FunctionScanGenerator(waveform=WaveformType.COSINE, amplitude=2.0, offset=0.0)
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
        """Square wave values should be close to ±amplitude (ignoring zero crossings)."""
        gen = FunctionScanGenerator(
            waveform=WaveformType.SQUARE, amplitude=3.0, offset=0.0, num_points=100
        )
        arr = gen.generate()
        non_zero = arr[arr != 0.0]
        assert np.all(np.abs(np.abs(non_zero) - 3.0) < 1e-9)

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
        collected = list(gen)
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
        gen.waveform = WaveformType.COSINE
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
        cosine_index = list(WaveformType).index(WaveformType.COSINE)
        widget._waveform_combo.setCurrentIndex(cosine_index)
        assert gen.waveform is WaveformType.COSINE

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
