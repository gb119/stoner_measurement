"""Unit propagation tests for CurveFitPlugin fitted parameters."""

from __future__ import annotations

import pytest

from stoner_measurement.plugins.base_plugin import BasePlugin
from stoner_measurement.plugins.transform.curve_fit import CurveFitPlugin, _ParamTableWidget


def _row_by_label(table: _ParamTableWidget, label: str) -> int:
    """Return a table row index from its vertical header text."""
    for row in range(table._table.rowCount()):  # noqa: SLF001
        if table._table.verticalHeaderItem(row).text() == label:  # noqa: SLF001
            return row
    raise AssertionError(f"No row labelled {label!r}")


def test_parameter_table_reads_and_preserves_si_units(qapp, managed_qt_widget):
    table = managed_qt_widget(_ParamTableWidget())
    table.set_parameters(["amplitude"])
    units_row = _row_by_label(table, "Units")
    table._table.item(units_row, 0).setText("m/s")  # noqa: SLF001

    settings = table.read_settings()
    table.set_parameters(["amplitude", "offset"])

    assert settings["amplitude"]["units"] == "m/s"
    assert table._table.item(units_row, 0).text() == "m/s"  # noqa: SLF001
    assert table._table.item(units_row, 1).text() == ""  # noqa: SLF001


def test_fitted_value_uncertainty_and_initial_share_parameter_unit(qapp):
    plugin = CurveFitPlugin()
    plugin.param_names = ["amplitude"]
    plugin.param_settings = {
        "amplitude": {"min": None, "initial": None, "max": None, "units": "V"}
    }
    plugin.report_initial_values = True

    assert plugin.reported_value_units() == {
        "curve_fit:amplitude": "V",
        "curve_fit:amplitude_err": "V",
        "curve_fit:amplitude_initial": "V",
    }


def test_editing_units_refreshes_live_values_catalogue(
    qapp, engine, managed_qt_widget
):
    plugin = CurveFitPlugin()
    plugin.param_names = ["a", "b"]
    plugin.report_initial_values = True
    engine.add_plugin("curve_fit", plugin)
    engine.update_step_plugin_catalog([plugin])
    tabs = plugin.config_tabs()
    for _title, widget in tabs:
        managed_qt_widget(widget)
    parameter_tab = dict(tabs)["Parameters"]
    table = parameter_tab.findChild(_ParamTableWidget)
    assert table is not None

    units_row = _row_by_label(table, "Units")
    table._table.item(units_row, 0).setText("A")  # noqa: SLF001

    assert engine.values_catalog["curve_fit:a"].units == "A"
    assert engine.values_catalog["curve_fit:a_err"].units == "A"
    assert engine.values_catalog["curve_fit:a_initial"].units == "A"
    assert engine.values_catalog["curve_fit:b"].units == ""


def test_parameter_units_round_trip_and_legacy_default(qapp):
    plugin = CurveFitPlugin()
    plugin.param_names = ["frequency"]
    plugin.param_settings = {
        "frequency": {"min": 0.0, "initial": 1.0, "max": None, "units": "Hz"}
    }

    restored = BasePlugin.from_json(plugin.to_json())

    assert restored.param_settings["frequency"]["units"] == "Hz"

    legacy = plugin.to_json()
    legacy["param_settings"]["frequency"].pop("units")
    restored_legacy = BasePlugin.from_json(legacy)

    assert restored_legacy.param_settings["frequency"]["units"] == ""


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
