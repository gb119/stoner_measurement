"""Tests for new transform plugins: window, Savitzky–Golay, and Fourier."""

from __future__ import annotations

import numpy as np
import pandas as pd

from stoner_measurement.core.sequence_engine import SequenceEngine
from stoner_measurement.plugins.trace.base import COLUMN_ROLE_Y, TraceData
from stoner_measurement.plugins.transform import (
    FourierTransformPlugin,
    SavitzkyGolayPlugin,
    WindowFilterPlugin,
)


class TestWindowFilterPlugin:
    def test_window_filter_advanced_mode_returns_filtered_trace(self, qapp):
        engine = SequenceEngine()
        plugin = WindowFilterPlugin()
        engine.add_plugin("window_filter", plugin)

        x = np.linspace(0.0, 1.0, 9)
        y = np.array([0.0, 0.0, 1.0, 1.0, 1.0, 1.0, 1.0, 0.0, 0.0], dtype=float)
        engine._namespace["_x"] = x
        engine._namespace["_y"] = y

        plugin.advanced_mode = True
        plugin.x_expr = "_x"
        plugin.y_expr = "_y"
        plugin.window_name = "boxcar"
        plugin.window_length = 3
        plugin.window_parameters = ""

        result = plugin.transform({})
        assert "filtered" in result
        td = result["filtered"]

        expected = np.convolve(y, np.ones(3) / 3.0, mode="same")
        np.testing.assert_allclose(td.x, x)
        np.testing.assert_allclose(td.y, expected)

        engine.shutdown()

    def test_window_filter_simple_mode_honours_selected_column(self, qapp):
        engine = SequenceEngine()
        plugin = WindowFilterPlugin()
        engine.add_plugin("window_filter", plugin)

        x = np.arange(5, dtype=float)
        trace = TraceData(
            df=pd.DataFrame({"y1": np.zeros(5), "y2": np.arange(5, dtype=float)}, index=pd.Index(x, name="x")),
            column_roles={"y1": COLUMN_ROLE_Y, "y2": COLUMN_ROLE_Y},
        )
        engine._namespace["_trace_obj"] = trace
        engine._namespace["_traces"] = {"trace": "_trace_obj"}

        plugin.trace_key = "trace"
        plugin.column_key = "y2"
        plugin.window_name = "boxcar"
        plugin.window_length = 1

        result = plugin.transform({})
        np.testing.assert_allclose(result["filtered"].y, np.arange(5, dtype=float))

        engine.shutdown()


class TestSavitzkyGolayPlugin:
    def test_savgol_smoothing_keeps_quadratic_shape(self, qapp):
        engine = SequenceEngine()
        plugin = SavitzkyGolayPlugin()
        engine.add_plugin("savgol_filter", plugin)

        x = np.linspace(-1.0, 1.0, 31)
        y = x**2
        engine._namespace["_x"] = x
        engine._namespace["_y"] = y

        plugin.advanced_mode = True
        plugin.x_expr = "_x"
        plugin.y_expr = "_y"
        plugin.window_length = 9
        plugin.polyorder = 2
        plugin.derivative_order = 0

        result = plugin.transform({})
        td = result["savgol"]
        np.testing.assert_allclose(td.y, y, atol=1e-9)

        engine.shutdown()

    def test_savgol_first_derivative_of_quadratic(self, qapp):
        engine = SequenceEngine()
        plugin = SavitzkyGolayPlugin()
        engine.add_plugin("savgol_filter", plugin)

        x = np.linspace(-1.0, 1.0, 31)
        y = x**2
        engine._namespace["_x"] = x
        engine._namespace["_y"] = y

        plugin.advanced_mode = True
        plugin.x_expr = "_x"
        plugin.y_expr = "_y"
        plugin.window_length = 9
        plugin.polyorder = 3
        plugin.derivative_order = 1

        result = plugin.transform({})
        td = result["savgol"]
        np.testing.assert_allclose(td.y, 2.0 * x, atol=0.15)

        engine.shutdown()


class TestFourierTransformPlugin:
    def test_forward_fft_resamples_non_uniform_data_and_shifts_frequency(self, qapp):
        engine = SequenceEngine()
        plugin = FourierTransformPlugin()
        engine.add_plugin("fourier_transform", plugin)

        rng = np.random.default_rng(123)
        x = np.sort(rng.uniform(0.0, 1.0, size=128))
        frequency = 7.0
        y = np.sin(2.0 * np.pi * frequency * x)
        engine._namespace["_x"] = x
        engine._namespace["_y"] = y

        plugin.advanced_mode = True
        plugin.x_expr = "_x"
        plugin.y_expr = "_y"
        plugin.inverse = False
        plugin.output_component = "magnitude"

        result = plugin.transform({})
        td = result["fft"]

        mid = len(td.x) // 2
        assert abs(td.x[mid]) < 1e-9
        peak_frequency = abs(td.x[int(np.argmax(td.y))])
        assert abs(peak_frequency - frequency) < 1.0

        engine.shutdown()

    def test_inverse_fft_recovers_signal_shape(self, qapp):
        engine = SequenceEngine()
        plugin = FourierTransformPlugin()
        engine.add_plugin("fourier_transform", plugin)

        n_points = 128
        dt = 0.01
        t = np.arange(n_points) * dt
        signal = np.cos(2.0 * np.pi * 5.0 * t)
        freq = np.fft.fftshift(np.fft.fftfreq(n_points, d=dt))
        spec = np.fft.fftshift(np.fft.fft(signal))

        engine._namespace["_f"] = freq
        engine._namespace["_spec"] = spec

        plugin.advanced_mode = True
        plugin.x_expr = "_f"
        plugin.y_expr = "_spec"
        plugin.inverse = True
        plugin.output_component = "real"

        result = plugin.transform({})
        td = result["fft"]

        reconstructed = td.y / np.max(np.abs(td.y))
        expected = signal / np.max(np.abs(signal))
        corr = np.corrcoef(reconstructed, expected)[0, 1]
        assert corr > 0.99

        engine.shutdown()
