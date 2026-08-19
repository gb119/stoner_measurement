"""Curve-fit user-function logging and dynamic runtime access."""

from __future__ import annotations

import logging

import numpy as np
import pytest

from stoner_measurement.plugins.transform.curve_fit import CurveFitPlugin


def _attach_linear_data(plugin: CurveFitPlugin, engine) -> None:
    """Attach *plugin* to deterministic linear data in *engine*."""
    engine.add_plugin("cf_inst", plugin)
    x_data = np.linspace(0.0, 1.0, 30)
    engine._namespace.update({"_x": x_data, "_y": (2.0 * x_data) + 0.5})  # noqa: SLF001
    plugin.advanced_mode = True
    plugin.x_expr = "_x"
    plugin.y_expr = "_y"
    plugin.param_names = ["a", "b"]


def test_p0_warnings_are_logged_as_info(qapp, engine, caplog):
    plugin = CurveFitPlugin()
    _attach_linear_data(plugin, engine)
    plugin.fit_code = (
        "import warnings\n"
        "def fit(x, a, b): return a * x + b\n"
        "def p0(x, y):\n"
        "    warnings.warn('estimate warning', RuntimeWarning)\n"
        "    return (1.0, 0.0)\n"
    )

    with caplog.at_level(logging.INFO, logger="stoner_measurement.sequence"):
        result = plugin.run({})

    assert result["a"] == pytest.approx(2.0)
    record = next(record for record in caplog.records if "estimate warning" in record.message)
    assert record.levelno == logging.INFO
    assert "p0 function" in record.message


def test_p0_errors_are_logged_and_table_initials_are_used(qapp, engine, caplog):
    plugin = CurveFitPlugin()
    _attach_linear_data(plugin, engine)
    plugin.fit_code = (
        "def fit(x, a, b): return a * x + b\n"
        "def p0(x, y): raise ValueError('bad estimate')\n"
    )
    plugin.param_settings = {
        "a": {"min": None, "initial": 1.0, "max": None},
        "b": {"min": None, "initial": 0.0, "max": None},
    }

    with caplog.at_level(logging.ERROR, logger="stoner_measurement.sequence"):
        result = plugin.run({})

    assert result["a"] == pytest.approx(2.0)
    record = next(record for record in caplog.records if "bad estimate" in record.message)
    assert record.levelno == logging.ERROR
    assert "p0 function" in record.message


def test_initial_trace_warnings_are_logged_as_info(qapp, engine, caplog):
    plugin = CurveFitPlugin()
    _attach_linear_data(plugin, engine)
    plugin.show_initial_trace = True
    plugin.fit_code = (
        "import warnings\n"
        "first_call = True\n"
        "def fit(x, a, b):\n"
        "    global first_call\n"
        "    if first_call:\n"
        "        warnings.warn('initial trace warning', RuntimeWarning)\n"
        "        first_call = False\n"
        "    return a * x + b\n"
    )

    with caplog.at_level(logging.INFO, logger="stoner_measurement.sequence"):
        result = plugin.run({})

    assert "initial_fit" in result
    record = next(record for record in caplog.records if "initial trace warning" in record.message)
    assert record.levelno == logging.INFO
    assert "initial-parameter trace" in record.message


def test_initial_trace_errors_are_logged_and_fit_continues(qapp, engine, caplog):
    plugin = CurveFitPlugin()
    _attach_linear_data(plugin, engine)
    plugin.show_initial_trace = True
    plugin.fit_code = (
        "first_call = True\n"
        "def fit(x, a, b):\n"
        "    global first_call\n"
        "    if first_call:\n"
        "        first_call = False\n"
        "        raise ValueError('initial trace failed')\n"
        "    return a * x + b\n"
    )

    with caplog.at_level(logging.ERROR, logger="stoner_measurement.sequence"):
        result = plugin.run({})

    assert "initial_fit" not in result
    assert result["a"] == pytest.approx(2.0)
    record = next(record for record in caplog.records if "initial trace failed" in record.message)
    assert record.levelno == logging.ERROR


def test_compiled_fit_and_p0_are_callable_attributes(qapp):
    plugin = CurveFitPlugin()
    plugin.fit_code = (
        "def fit(x, a, b): return a * x + b\n"
        "def p0(x, y): return (3.0, 4.0)\n"
    )

    assert callable(plugin.fit)
    assert callable(plugin.p0)
    np.testing.assert_allclose(plugin.fit(np.array([0.0, 1.0]), 2.0, 0.5), [0.5, 2.5])
    assert plugin.p0(np.array([0.0]), np.array([0.5])) == (3.0, 4.0)


def test_latest_fitted_parameters_are_dynamic_attributes(qapp, engine):
    plugin = CurveFitPlugin()
    _attach_linear_data(plugin, engine)
    plugin.fit_code = "def fit(x, a, b): return a * x + b"

    with pytest.raises(AttributeError, match="attribute 'a'"):
        _ = plugin.a

    plugin.run({})

    assert plugin.a == pytest.approx(2.0)
    assert plugin.b == pytest.approx(0.5)


def test_missing_p0_and_unknown_attributes_raise_attribute_error(qapp):
    plugin = CurveFitPlugin()
    plugin.fit_code = "def fit(x, a): return a * x"

    with pytest.raises(AttributeError, match="attribute 'p0'"):
        _ = plugin.p0
    with pytest.raises(AttributeError, match="attribute 'unknown'"):
        _ = plugin.unknown


def test_existing_attributes_win_over_fitted_parameter_names(qapp):
    plugin = CurveFitPlugin()
    plugin.param_names = ["name", "data"]
    plugin.data = {"name": 12.0, "data": 34.0}

    assert plugin.name == "Curve Fit"
    assert plugin.data == {"name": 12.0, "data": 34.0}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
