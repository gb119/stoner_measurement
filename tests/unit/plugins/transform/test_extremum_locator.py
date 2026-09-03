"""Tests for noisy trace extremum location."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from qtpy.QtWidgets import QCheckBox, QComboBox, QLineEdit

from stoner_measurement.core import TraceData
from stoner_measurement.plugins.base_plugin import BasePlugin
from stoner_measurement.plugins.transform.extremum_locator import (
    MODE_MINIMUM,
    ExtremumLocatorPlugin,
)


def _attach(engine, plugin, x, y):
    trace = TraceData(
        pd.DataFrame({"field": x, "signal": y}),
        column_roles={"field": "x", "signal": "y"},
        units={"field": "T", "signal": "V"},
    )
    plugin.instance_name = "turn"
    engine.add_plugin("turn", plugin)
    engine._namespace["source"] = trace  # noqa: SLF001
    engine._namespace["_traces"] = {"measurement": "source"}  # noqa: SLF001
    plugin.trace_key = "measurement"
    return trace


def test_locates_broad_noisy_parabolic_maximum(engine):
    rng = np.random.default_rng(1234)
    x = np.linspace(-4.0, 6.0, 301)
    y = 10.0 - 0.3 * (x - 1.2) ** 2 + rng.normal(0.0, 0.12, len(x))
    plugin = ExtremumLocatorPlugin()
    plugin.smoothing_window = 31
    plugin.fit_window = 61
    _attach(engine, plugin, x, y)

    result = plugin.run({})

    assert result["extremum_x"] == pytest.approx(1.2, abs=0.08)
    assert result["extremum_y"] == pytest.approx(10.0, abs=0.08)
    assert plugin.extremum == (result["extremum_x"], result["extremum_y"])
    assert plugin.extremum_x == result["extremum_x"]
    with pytest.raises(AttributeError):
        plugin.extremum_x = 0.0


def test_locates_noisy_sinusoidal_minimum_with_advanced_inputs(engine):
    rng = np.random.default_rng(42)
    x = np.linspace(0.0, 2.0 * np.pi, 401)
    y = np.sin(x) + rng.normal(0.0, 0.04, len(x))
    plugin = ExtremumLocatorPlugin()
    plugin.mode = MODE_MINIMUM
    plugin.smoothing_window = 31
    plugin.fit_window = 51
    _attach(engine, plugin, x, np.zeros_like(x))
    engine._namespace.update({"fit_x": x, "fit_y": y})  # noqa: SLF001
    plugin.advanced_mode = True
    plugin.x_expr = "fit_x"
    plugin.y_expr = "fit_y"

    result = plugin.transform({})

    assert result["extremum_x"] == pytest.approx(1.5 * np.pi, abs=0.06)
    assert result["extremum_y"] == pytest.approx(-1.0, abs=0.04)


def test_x_range_selects_one_of_two_prominent_maxima(engine):
    x = np.linspace(-5.0, 5.0, 501)
    y = np.exp(-(((x + 2.0) / 0.6) ** 2)) + 2.0 * np.exp(-(((x - 2.0) / 0.6) ** 2))
    plugin = ExtremumLocatorPlugin()
    plugin.x_min_expr = "-4.0"
    plugin.x_max_expr = "0.0"
    plugin.smoothing_window = 15
    plugin.fit_window = 31
    _attach(engine, plugin, x, y)

    result = plugin.transform({})

    assert result["extremum_x"] == pytest.approx(-2.0, abs=0.03)
    assert result["extremum_y"] == pytest.approx(1.0, abs=0.03)


def test_prominence_rejects_shallow_turning_point(engine):
    x = np.linspace(0.0, 2.0 * np.pi, 201)
    plugin = ExtremumLocatorPlugin()
    plugin.turning_point_prominence = 2.0
    _attach(engine, plugin, x, np.sin(x))

    assert plugin.transform({}) == {}
    assert plugin.extremum is None


def test_reports_catalogue_values_and_source_units(engine):
    plugin = ExtremumLocatorPlugin()
    x = np.linspace(-1.0, 1.0, 51)
    _attach(engine, plugin, x, 2.0 - x**2)
    plugin.transform({})

    assert plugin.reported_values() == {
        "turn:extremum_x": "turn.extremum_x",
        "turn:extremum_y": "turn.extremum_y",
    }
    assert plugin.reported_value_units() == {
        "turn:extremum_x": "T",
        "turn:extremum_y": "V",
    }


def test_configuration_round_trip_and_tabs(qapp):
    plugin = ExtremumLocatorPlugin()
    plugin.mode = MODE_MINIMUM
    plugin.fit_window = 41
    plugin.x_min_expr = "lower"
    plugin.x_max_expr = "upper"
    plugin.turning_point_prominence = 0.15
    plugin.add_marker = True

    restored = BasePlugin.from_json(plugin.to_json())

    assert isinstance(restored, ExtremumLocatorPlugin)
    assert restored.mode == MODE_MINIMUM
    assert restored.fit_window == 41
    assert restored.x_min_expr == "lower"
    assert restored.x_max_expr == "upper"
    assert restored.turning_point_prominence == pytest.approx(0.15)
    assert restored.add_marker is True
    assert [title for title, _widget in restored.config_tabs()] == [
        "General",
        "Advanced",
        "About",
    ]


def test_mode_selector_is_on_general_page(qapp, managed_qt_widget):
    plugin = ExtremumLocatorPlugin()
    tabs = plugin.config_tabs()
    general = managed_qt_widget(tabs[0][1])
    advanced = tabs[1][1]
    mode = general.findChild(QComboBox, "extremum_mode")

    assert mode is not None
    assert advanced.findChild(QComboBox, "extremum_mode") is None
    mode.setCurrentIndex(mode.findData(MODE_MINIMUM))
    assert plugin.mode == MODE_MINIMUM


def test_range_and_marker_controls_are_on_general_page(qapp, managed_qt_widget):
    plugin = ExtremumLocatorPlugin()
    general = managed_qt_widget(plugin.config_tabs()[0][1])
    minimum = general.findChild(QLineEdit, "extremum_x_min")
    maximum = general.findChild(QLineEdit, "extremum_x_max")
    marker = general.findChild(QCheckBox, "extremum_add_marker")

    minimum.setText("-field_limit")
    minimum.editingFinished.emit()
    maximum.setText("field_limit")
    maximum.editingFinished.emit()
    marker.setChecked(True)

    assert plugin.x_min_expr == "-field_limit"
    assert plugin.x_max_expr == "field_limit"
    assert plugin.add_marker is True


def test_successful_result_can_add_marker_to_plot(engine, qapp, managed_qt_widget):
    from stoner_measurement.ui.plot_widget import PlotWidget

    plot = managed_qt_widget(PlotWidget())
    engine.plot_widget = plot
    plugin = ExtremumLocatorPlugin()
    plugin.add_marker = True
    x = np.linspace(-2.0, 2.0, 101)
    _attach(engine, plugin, x, 3.0 - (x - 0.4) ** 2)

    result = plugin.transform({})
    qapp.processEvents()

    assert len(plot._data_markers) == 1
    marker = plot._data_markers[0]
    assert marker.x == pytest.approx(result["extremum_x"])
    assert marker.y == pytest.approx(result["extremum_y"])


def test_about_documentation_describes_outputs_properties_and_advanced_options(qapp):
    html = ExtremumLocatorPlugin()._about_html()  # noqa: SLF001

    assert html is not None
    assert "extremum_x" in html
    assert "extremum_y" in html
    assert "Quadratic fit window" in html
    assert "smoothing_window" in html


def test_invalid_data_clears_previous_result(engine):
    plugin = ExtremumLocatorPlugin()
    _attach(engine, plugin, np.arange(5.0), -((np.arange(5.0) - 2.0) ** 2))
    assert plugin.transform({})
    engine._namespace["source"] = TraceData(  # noqa: SLF001
        pd.DataFrame({"x": [0.0, 1.0], "y": [1.0, 2.0]}),
        column_roles={"x": "x", "y": "y"},
    )

    assert plugin.transform({}) == {}
    assert plugin.extremum is None


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
