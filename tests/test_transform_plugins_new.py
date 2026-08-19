"""Tests for new transform plugins: window, Savitzky–Golay, and Fourier."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from qtpy.QtWidgets import QComboBox, QWidget

from stoner_measurement.core import COLUMN_ROLE_Y, TraceData
from stoner_measurement.core.sequence_engine import SequenceEngine
from stoner_measurement.plugins.transform import (
    FourierTransformPlugin,
    SavitzkyGolayPlugin,
    WindowFilterPlugin,
    XOffsetRemovalPlugin,
)


def _set_transform_source(engine, plugin, length: int) -> TraceData:
    """Attach a multi-column source trace for array-input transform tests."""
    source = TraceData(
        df=pd.DataFrame(
            {
                "signal": np.zeros(length, dtype=float),
                "untouched": np.arange(length, dtype=float) + 100.0,
            },
            index=pd.Index(np.arange(length, dtype=float), name="source_x"),
        ),
        column_roles={"signal": COLUMN_ROLE_Y},
        names={"x": "Source X", "signal": "Signal", "untouched": "Untouched"},
        units={"x": "s", "signal": "V", "untouched": "A"},
    )
    engine._namespace["_transform_source"] = source
    engine._namespace["_traces"] = {"source": "_transform_source"}
    plugin.trace_key = "source"
    plugin.column_key = "signal"
    return source


@pytest.fixture
def engine(qapp):
    """Return a sequence engine that is always shut down after each test."""
    eng = SequenceEngine()
    yield eng
    eng.shutdown()


@pytest.mark.parametrize(
    ("plugin_cls", "expected_titles"),
    [
        (WindowFilterPlugin, ["Data", "Window"]),
        (SavitzkyGolayPlugin, ["Data", "Filter"]),
        (FourierTransformPlugin, ["Data", "Transform"]),
    ],
)
def test_transform_plugin_config_tabs_include_settings_tab(plugin_cls, expected_titles, qapp):
    """Each transform plugin returns data and settings tabs without raising errors."""
    plugin = plugin_cls()
    tabs = plugin.config_tabs()
    titles = [title for title, _ in tabs]
    assert titles[: len(expected_titles)] == expected_titles


@pytest.mark.parametrize(
    "plugin_cls",
    [WindowFilterPlugin, SavitzkyGolayPlugin, FourierTransformPlugin],
)
def test_transform_trace_combo_refreshes_when_catalog_changes(
    plugin_cls, engine, managed_qt_widget
):
    from stoner_measurement.plugins.state_scan import CounterPlugin

    plugin = plugin_cls()
    engine.add_plugin("transform", plugin)
    data_tab = managed_qt_widget(plugin.config_tabs()[0][1])
    trace_combo = next(
        combo
        for combo in data_tab.findChildren(QComboBox)
        if combo.findText("(no traces available)") >= 0
    )

    counter = CounterPlugin()
    counter.collect_data = True
    engine.update_step_plugin_catalog([counter])

    assert trace_combo.findText("counter.data") >= 0
    assert plugin.trace_key == "counter.data"


@pytest.mark.parametrize(
    "plugin_cls",
    [
        WindowFilterPlugin,
        SavitzkyGolayPlugin,
        FourierTransformPlugin,
        XOffsetRemovalPlugin,
    ],
)
def test_advanced_mode_keeps_source_trace_and_all_columns_active(
    plugin_cls, engine, managed_qt_widget
):
    plugin = plugin_cls()
    engine.add_plugin("transform", plugin)
    _set_transform_source(engine, plugin, 3)
    plugin.advanced_mode = True
    widget = managed_qt_widget(QWidget())
    ws = plugin._create_data_source_widgets(widget, engine._namespace["_traces"])
    plugin._wire_data_source_widgets(ws)

    assert ws["trace_combo"].isEnabled()
    assert ws["column_combo"].isEnabled()
    expected_columns = [
        "source:Source X (s)",
        "source:Signal (V)",
        "source:Untouched (A)",
    ]
    assert [
        ws["column_combo"].itemText(i) for i in range(ws["column_combo"].count())
    ] == expected_columns
    assert ws["x_combo"].isEnabled()
    assert ws["y_combo"].isEnabled()


class TestWindowFilterPlugin:
    def test_window_filter_advanced_mode_returns_filtered_trace(self, engine):
        plugin = WindowFilterPlugin()
        engine.add_plugin("window_filter", plugin)

        x = np.linspace(0.0, 1.0, 9)
        y = np.array([0.0, 0.0, 1.0, 1.0, 1.0, 1.0, 1.0, 0.0, 0.0], dtype=float)
        engine._namespace["_x"] = x
        engine._namespace["_y"] = y
        source = _set_transform_source(engine, plugin, len(x))

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
        np.testing.assert_allclose(td.x, source.x)
        np.testing.assert_allclose(td.y, expected)
        np.testing.assert_allclose(td.df["untouched"], source.df["untouched"])
        np.testing.assert_allclose(source.df["signal"], 0.0)

    def test_window_filter_simple_mode_honours_selected_column(self, engine):
        plugin = WindowFilterPlugin()
        engine.add_plugin("window_filter", plugin)

        x = np.arange(5, dtype=float)
        trace = TraceData(
            df=pd.DataFrame(
                {"y1": np.zeros(5), "y2": np.arange(5, dtype=float)}, index=pd.Index(x, name="x")
            ),
            column_roles={"y1": COLUMN_ROLE_Y, "y2": COLUMN_ROLE_Y},
        )
        engine._namespace["_trace_obj"] = trace
        engine._namespace["_traces"] = {"trace": "_trace_obj"}

        plugin.trace_key = "trace"
        plugin.column_key = "y2"
        plugin.window_name = "boxcar"
        plugin.window_length = 1

        result = plugin.transform({})
        np.testing.assert_allclose(
            result["filtered"].df["y2"], np.arange(5, dtype=float)
        )
        np.testing.assert_allclose(result["filtered"].df["y1"], 0.0)

    def test_window_filter_advanced_mode_replaces_selected_target_column(self, engine):
        plugin = WindowFilterPlugin()
        engine.add_plugin("window_filter", plugin)
        source = _set_transform_source(engine, plugin, 4)
        replacement = np.array([4.0, 3.0, 2.0, 1.0])
        engine._namespace["_advanced_x"] = np.arange(4, dtype=float)
        engine._namespace["_advanced_y"] = replacement
        plugin.column_key = "untouched"
        plugin.advanced_mode = True
        plugin.x_expr = "_advanced_x"
        plugin.y_expr = "_advanced_y"
        plugin.window_name = "boxcar"
        plugin.window_length = 1

        result = plugin.transform({})["filtered"]

        np.testing.assert_allclose(result.df["untouched"], replacement)
        np.testing.assert_allclose(result.df["signal"], source.df["signal"])
        np.testing.assert_allclose(source.df["untouched"], [100.0, 101.0, 102.0, 103.0])


class TestSavitzkyGolayPlugin:
    def test_savgol_smoothing_keeps_quadratic_shape(self, engine):
        plugin = SavitzkyGolayPlugin()
        engine.add_plugin("savgol_filter", plugin)

        x = np.linspace(-1.0, 1.0, 31)
        y = x**2
        engine._namespace["_x"] = x
        engine._namespace["_y"] = y
        source = _set_transform_source(engine, plugin, len(x))

        plugin.advanced_mode = True
        plugin.x_expr = "_x"
        plugin.y_expr = "_y"
        plugin.window_length = 9
        plugin.polyorder = 2
        plugin.derivative_order = 0

        result = plugin.transform({})
        td = result["savgol"]
        np.testing.assert_allclose(td.y, y, atol=1e-9)
        np.testing.assert_allclose(td.df["untouched"], source.df["untouched"])

    def test_savgol_first_derivative_of_quadratic(self, engine):
        plugin = SavitzkyGolayPlugin()
        engine.add_plugin("savgol_filter", plugin)

        x = np.linspace(-1.0, 1.0, 31)
        y = x**2
        engine._namespace["_x"] = x
        engine._namespace["_y"] = y
        _set_transform_source(engine, plugin, len(x))

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
        _set_transform_source(engine, plugin, len(x))

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
        _set_transform_source(engine, plugin, len(x))

        plugin.advanced_mode = True
        plugin.x_expr = "_x"
        plugin.y_expr = "_y"
        plugin.inverse = False

        result = plugin.transform({})
        td = result["fft"]

        assert {
            "signal_magnitude",
            "signal_real",
            "signal_imag",
            "signal_angle",
        }.issubset(set(td.df.columns))
        mid = len(td.x) // 2
        assert abs(td.x[mid]) < 1e-9
        peak_frequency = abs(td.x[int(np.argmax(td.y))])
        assert abs(peak_frequency - frequency) < 1.0
        magnitude = td.df["signal_magnitude"].to_numpy(dtype=float)
        complex_from_parts = td.df["signal_real"] + 1j * td.df["signal_imag"]
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
        _set_transform_source(engine, plugin, len(freq))

        plugin.advanced_mode = True
        plugin.x_expr = "_f"
        plugin.y_expr = "_spec"
        plugin.inverse = True

        result = plugin.transform({})
        td = result["fft"]

        assert {
            "signal_magnitude",
            "signal_real",
            "signal_imag",
            "signal_angle",
        }.issubset(set(td.df.columns))
        reconstructed = td.df["signal_real"].to_numpy(dtype=float)
        reconstructed = reconstructed / np.max(np.abs(reconstructed))
        expected = signal / np.max(np.abs(signal))
        corr = np.corrcoef(reconstructed, expected)[0, 1]
        assert corr > 0.99

    def test_inverse_fft_reciprocal_unit_simplifies_prefixed_unit(self, engine):
        plugin = FourierTransformPlugin()
        engine.add_plugin("fourier_transform", plugin)

        x = np.linspace(0.0, 1.0, 32)
        y = np.exp(1j * 2.0 * np.pi * x).real
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
        engine._namespace["_traces"] = {"dummy:Dummy": "_trace"}
        engine._namespace["_trace"] = TraceData(
            df=pd.DataFrame(
                {"V": np.arange(3, dtype=float), "R": np.arange(3, dtype=float) + 1.0},
                index=pd.Index(np.arange(3, dtype=float), name="x"),
            ),
            column_roles={"V": COLUMN_ROLE_Y},
            names={"x": "I", "V": "V", "R": "R"},
            units={"x": "A", "V": "V", "R": "Ω"},
        )

        widget = QWidget()
        ws = plugin._create_data_source_widgets(widget, engine._namespace["_traces"])

        assert ws["x_combo"].currentText() == "dummy:Dummy:I (A)"
        assert ws["y_combo"].currentText() == "dummy:Dummy:V (V)"
        assert ws["channel_items"] == {
            "dummy:Dummy:I (A)": "_trace.x",
            "dummy:Dummy:V (V)": "_trace.df['V'].to_numpy()",
            "dummy:Dummy:R (Ω)": "_trace.df['R'].to_numpy()",
        }
        assert plugin.eval(ws["channel_items"]["dummy:Dummy:R (Ω)"]).tolist() == [1.0, 2.0, 3.0]

    def test_data_source_widgets_use_configured_labels_before_acquisition(self, engine, qapp):
        from stoner_measurement.plugins.trace import DummyPlugin

        source = DummyPlugin()
        engine.add_plugin("dummy", source)
        engine.update_step_plugin_catalog([source])
        plugin = FourierTransformPlugin()
        engine.add_plugin("fourier_transform", plugin)

        widget = QWidget()
        ws = plugin._create_data_source_widgets(widget, engine.traces_catalog)

        assert list(ws["channel_items"]) == ["dummy:Dummy:I (A)", "dummy:Dummy:V (V)"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
