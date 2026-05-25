"""Tests for new transform plugins: window, Savitzky–Golay, and Fourier."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from PyQt6.QtWidgets import QWidget

from stoner_measurement.core.sequence_engine import SequenceEngine
from stoner_measurement.plugins.trace.base import COLUMN_ROLE_Y, TraceData
from stoner_measurement.plugins.transform import (
    FourierTransformPlugin,
    SavitzkyGolayPlugin,
    WindowFilterPlugin,
)


@pytest.fixture
def engine(qapp):
    """Return a sequence engine that is always shut down after each test."""
    eng = SequenceEngine()
    yield eng
    eng.shutdown()


class TestWindowFilterPlugin:
    def test_window_filter_advanced_mode_returns_filtered_trace(self, engine):
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

    def test_window_filter_simple_mode_honours_selected_column(self, engine):
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


class TestSavitzkyGolayPlugin:
    def test_savgol_smoothing_keeps_quadratic_shape(self, engine):
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

    def test_savgol_first_derivative_of_quadratic(self, engine):
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

    def test_savgol_clamps_and_persists_polyorder_and_derivative(self, engine):
        plugin = SavitzkyGolayPlugin()
        engine.add_plugin("savgol_filter", plugin)

        x = np.linspace(-1.0, 1.0, 11)
        y = x**2
        engine._namespace["_x"] = x
        engine._namespace["_y"] = y

        plugin.advanced_mode = True
        plugin.x_expr = "_x"
        plugin.y_expr = "_y"
        plugin.window_length = 5
        plugin.polyorder = 9
        plugin.derivative_order = 7

        result = plugin.transform({})
        assert "savgol" in result
        assert plugin.polyorder == 4
        assert plugin.derivative_order == 4


class TestFourierTransformPlugin:
    def test_forward_fft_resamples_non_uniform_data_and_shifts_frequency(self, engine):
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

        result = plugin.transform({})
        td = result["fft"]

        assert {"y_magnitude", "y_real", "y_imag", "y_angle"}.issubset(set(td.df.columns))
        mid = len(td.x) // 2
        assert abs(td.x[mid]) < 1e-9
        peak_frequency = abs(td.x[int(np.argmax(td.y))])
        assert abs(peak_frequency - frequency) < 1.0
        magnitude = td.df["y_magnitude"].to_numpy(dtype=float)
        complex_from_parts = td.df["y_real"] + 1j * td.df["y_imag"]
        np.testing.assert_allclose(magnitude, np.abs(complex_from_parts))

    def test_inverse_fft_recovers_signal_shape(self, engine):
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

        result = plugin.transform({})
        td = result["fft"]

        assert {"y_magnitude", "y_real", "y_imag", "y_angle"}.issubset(set(td.df.columns))
        reconstructed = td.df["y_real"].to_numpy(dtype=float)
        reconstructed = reconstructed / np.max(np.abs(reconstructed))
        expected = signal / np.max(np.abs(signal))
        corr = np.corrcoef(reconstructed, expected)[0, 1]
        assert corr > 0.99

    def test_inverse_fft_reciprocal_unit_simplifies_prefixed_unit(self, engine):
        plugin = FourierTransformPlugin()
        engine.add_plugin("fourier_transform", plugin)

        x = np.linspace(0.0, 1.0, 32)
        y = np.exp(1j * 2.0 * np.pi * x)
        trace = TraceData(
            df=pd.DataFrame({"spec": y}, index=pd.Index(x, name="x")),
            column_roles={"spec": COLUMN_ROLE_Y},
            units={"x": "1/s"},
        )
        engine._namespace["_fft_trace"] = trace
        engine._namespace["_traces"] = {"fft": "_fft_trace"}

        plugin.trace_key = "fft"
        plugin.column_key = "spec"
        plugin.inverse = True

        result = plugin.transform({})
        assert result["fft"].units["x"] == "s"

    def test_data_source_widgets_default_y_expression_uses_y_channel(self, engine, qapp):
        plugin = FourierTransformPlugin()
        engine.add_plugin("fourier_transform", plugin)
        engine._namespace["_traces"] = {"trace": "_trace"}
        engine._namespace["_trace"] = TraceData(
            df=pd.DataFrame({"y": np.arange(3, dtype=float)}, index=pd.Index(np.arange(3, dtype=float), name="x")),
            column_roles={"y": COLUMN_ROLE_Y},
        )

        widget = QWidget()
        ws = plugin._create_data_source_widgets(widget, engine._namespace["_traces"])

        assert ws["y_combo"].currentText().endswith(" (y)")
