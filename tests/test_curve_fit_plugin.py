"""Tests for CurveFitPlugin — curve-fitting transform plugin."""

from __future__ import annotations

import json

import numpy as np
import pytest

from stoner_measurement.plugins.transform import CurveFitPlugin
from stoner_measurement.plugins.transform.curve_fit import (
    _has_p0_function,
    _parse_fit_params,
)

# ---------------------------------------------------------------------------
# Module-level helper tests
# ---------------------------------------------------------------------------


class TestParseFitParams:
    def test_basic_linear(self):
        code = "def fit(x, a, b): return a * x + b"
        assert _parse_fit_params(code) == ["a", "b"]

    def test_single_param(self):
        code = "def fit(x, k): return k * x"
        assert _parse_fit_params(code) == ["k"]

    def test_no_params_beyond_x(self):
        code = "def fit(x): return x"
        assert _parse_fit_params(code) == []

    def test_syntax_error_returns_empty(self):
        assert _parse_fit_params("not valid python !!!") == []

    def test_no_fit_function(self):
        assert _parse_fit_params("def helper(x): return x") == []

    def test_multiline(self):
        code = "def fit(x, amplitude, centre, width):\n    return amplitude"
        assert _parse_fit_params(code) == ["amplitude", "centre", "width"]


class TestHasP0Function:
    def test_p0_defined(self):
        assert _has_p0_function("def p0(x, y): return (1.0,)")

    def test_no_p0(self):
        assert not _has_p0_function("def fit(x, a): return a * x")

    def test_syntax_error_returns_false(self):
        assert not _has_p0_function("not valid !!!!")


# ---------------------------------------------------------------------------
# CurveFitPlugin construction
# ---------------------------------------------------------------------------


class TestCurveFitPluginInit:
    def test_name(self, qapp):
        assert CurveFitPlugin().name == "Curve Fit"

    def test_plugin_type(self, qapp):
        assert CurveFitPlugin().plugin_type == "transform"

    def test_required_inputs_empty(self, qapp):
        assert CurveFitPlugin().required_inputs == []

    def test_output_names_from_default_code(self, qapp):
        p = CurveFitPlugin()
        # Default code has fit(x, a, b)
        assert p.output_names == ["a", "a_err", "b", "b_err"]

    def test_default_fit_code_set(self, qapp):
        p = CurveFitPlugin()
        assert "def fit" in p.fit_code

    def test_param_names_from_default_code(self, qapp):
        p = CurveFitPlugin()
        assert p.param_names == ["a", "b"]


# ---------------------------------------------------------------------------
# CurveFitPlugin.transform — actual fitting
# ---------------------------------------------------------------------------


class TestCurveFitTransform:
    @pytest.fixture
    def linear_setup(self, qapp):
        """Return a CurveFitPlugin attached to an engine with linear x/y data."""
        from stoner_measurement.core.sequence_engine import SequenceEngine

        engine = SequenceEngine()
        plugin = CurveFitPlugin()
        engine.add_plugin("curve_fit", plugin)

        x = np.linspace(0.0, 1.0, 30)
        y = 3.0 * x + 1.5
        engine._namespace["_x"] = x
        engine._namespace["_y"] = y

        plugin.advanced_mode = True
        plugin.x_expr = "_x"
        plugin.y_expr = "_y"
        plugin.fit_code = "def fit(x, a, b): return a * x + b"
        plugin.param_names = ["a", "b"]

        yield plugin, engine
        engine.shutdown()

    def test_linear_fit_slope(self, linear_setup):
        plugin, _ = linear_setup
        result = plugin.transform({})
        assert abs(result["a"] - 3.0) < 1e-6

    def test_linear_fit_intercept(self, linear_setup):
        plugin, _ = linear_setup
        result = plugin.transform({})
        assert abs(result["b"] - 1.5) < 1e-6

    def test_uncertainties_close_to_zero_for_exact_data(self, linear_setup):
        plugin, _ = linear_setup
        result = plugin.transform({})
        assert result["a_err"] < 1e-6
        assert result["b_err"] < 1e-6

    def test_with_sigma(self, qapp):
        from stoner_measurement.core.sequence_engine import SequenceEngine

        engine = SequenceEngine()
        plugin = CurveFitPlugin()
        engine.add_plugin("curve_fit", plugin)

        rng = np.random.default_rng(0)
        x = np.linspace(0.0, 1.0, 50)
        noise = rng.normal(0, 0.05, size=50)
        y = 2.0 * x + 0.3 + noise
        sigma = np.full(50, 0.05)
        engine._namespace["_x"] = x
        engine._namespace["_y"] = y
        engine._namespace["_s"] = sigma

        plugin.advanced_mode = True
        plugin.x_expr = "_x"
        plugin.y_expr = "_y"
        plugin.y_error_expr = "_s"
        plugin.fit_code = "def fit(x, a, b): return a * x + b"
        plugin.param_names = ["a", "b"]

        result = plugin.transform({})
        assert abs(result["a"] - 2.0) < 0.3
        assert abs(result["b"] - 0.3) < 0.3
        engine.shutdown()

    def test_with_p0_function(self, qapp):
        from stoner_measurement.core.sequence_engine import SequenceEngine

        engine = SequenceEngine()
        plugin = CurveFitPlugin()
        engine.add_plugin("curve_fit", plugin)

        x = np.linspace(0.0, 1.0, 30)
        y = 4.0 * x + 0.0
        engine._namespace["_x"] = x
        engine._namespace["_y"] = y

        plugin.advanced_mode = True
        plugin.x_expr = "_x"
        plugin.y_expr = "_y"
        plugin.fit_code = (
            "def fit(x, a, b): return a * x + b\n"
            "def p0(x, y):\n"
            "    import numpy as np\n"
            "    return (float(np.polyfit(x, y, 1)[0]), 0.0)\n"
        )
        plugin.param_names = ["a", "b"]
        result = plugin.transform({})
        assert abs(result["a"] - 4.0) < 1e-5
        engine.shutdown()

    def test_with_bounds(self, qapp):
        from stoner_measurement.core.sequence_engine import SequenceEngine

        engine = SequenceEngine()
        plugin = CurveFitPlugin()
        engine.add_plugin("curve_fit", plugin)

        x = np.linspace(0.0, 1.0, 30)
        y = 2.0 * x + 0.5
        engine._namespace["_x"] = x
        engine._namespace["_y"] = y

        plugin.advanced_mode = True
        plugin.x_expr = "_x"
        plugin.y_expr = "_y"
        plugin.fit_code = "def fit(x, a, b): return a * x + b"
        plugin.param_names = ["a", "b"]
        plugin.param_settings = {
            "a": {"min": 0.0, "initial": None, "max": 10.0},
            "b": {"min": None, "initial": None, "max": None},
        }
        result = plugin.transform({})
        assert abs(result["a"] - 2.0) < 1e-5
        engine.shutdown()

    def test_returns_nan_on_empty_expressions(self, qapp):
        from stoner_measurement.core.sequence_engine import SequenceEngine

        engine = SequenceEngine()
        plugin = CurveFitPlugin()
        engine.add_plugin("curve_fit", plugin)
        plugin.advanced_mode = True
        plugin.x_expr = ""
        plugin.y_expr = ""
        plugin.fit_code = "def fit(x, a): return a * x"
        plugin.param_names = ["a"]
        result = plugin.transform({})
        assert np.isnan(result["a"])
        engine.shutdown()

    def test_returns_nan_on_missing_trace(self, qapp):
        from stoner_measurement.core.sequence_engine import SequenceEngine

        engine = SequenceEngine()
        plugin = CurveFitPlugin()
        engine.add_plugin("curve_fit", plugin)
        plugin.advanced_mode = False
        plugin.trace_key = "nonexistent"
        plugin.fit_code = "def fit(x, a): return a * x"
        plugin.param_names = ["a"]
        result = plugin.transform({})
        assert np.isnan(result["a"])
        engine.shutdown()

    def test_returns_nan_on_bad_fit_code(self, qapp):
        from stoner_measurement.core.sequence_engine import SequenceEngine

        engine = SequenceEngine()
        plugin = CurveFitPlugin()
        engine.add_plugin("curve_fit", plugin)

        x = np.linspace(0.0, 1.0, 10)
        y = x
        engine._namespace["_x"] = x
        engine._namespace["_y"] = y
        plugin.advanced_mode = True
        plugin.x_expr = "_x"
        plugin.y_expr = "_y"
        plugin.fit_code = "not valid python"
        plugin.param_names = ["a"]
        result = plugin.transform({})
        assert np.isnan(result["a"])
        engine.shutdown()

    def test_simple_mode_with_trace_data(self, qapp):
        from stoner_measurement.core.sequence_engine import SequenceEngine
        from stoner_measurement.plugins.trace import TraceData

        engine = SequenceEngine()
        plugin = CurveFitPlugin()
        engine.add_plugin("curve_fit", plugin)

        x = np.linspace(0.0, 1.0, 30)
        y = 5.0 * x + 2.0
        td = TraceData(x=x, y=y)
        engine._namespace["_td"] = td
        engine._namespace["_traces"] = {"dummy:ch": "_td"}

        plugin.advanced_mode = False
        plugin.trace_key = "dummy:ch"
        plugin.fit_code = "def fit(x, a, b): return a * x + b"
        plugin.param_names = ["a", "b"]
        result = plugin.transform({})
        assert abs(result["a"] - 5.0) < 1e-5
        assert abs(result["b"] - 2.0) < 1e-5
        engine.shutdown()


# ---------------------------------------------------------------------------
# JSON round-trip
# ---------------------------------------------------------------------------


class TestCurveFitSerialization:
    def test_to_json_has_required_keys(self, qapp):
        p = CurveFitPlugin()
        d = p.to_json()
        for key in (
            "type",
            "class",
            "instance_name",
            "trace_key",
            "advanced_mode",
            "x_expr",
            "y_expr",
            "y_error_expr",
            "fit_code",
            "param_names",
            "param_settings",
        ):
            assert key in d, f"Missing key: {key}"

    def test_to_json_type_is_transform(self, qapp):
        assert CurveFitPlugin().to_json()["type"] == "transform"

    def test_round_trip(self, qapp):
        from stoner_measurement.plugins.base_plugin import BasePlugin

        p = CurveFitPlugin()
        p.advanced_mode = True
        p.x_expr = "my_x"
        p.y_expr = "my_y"
        p.y_error_expr = "my_e"
        p.fit_code = "def fit(x, amp, freq): return amp * x + freq"
        p.param_names = ["amp", "freq"]
        p.param_settings = {
            "amp": {"min": 0.0, "initial": 1.0, "max": 10.0},
            "freq": {"min": None, "initial": 0.5, "max": None},
        }

        data = p.to_json()
        # Ensure it's JSON-serialisable.
        json_str = json.dumps(data)
        restored_data = json.loads(json_str)

        restored = BasePlugin.from_json(restored_data)
        assert isinstance(restored, CurveFitPlugin)
        assert restored.advanced_mode is True
        assert restored.x_expr == "my_x"
        assert restored.y_expr == "my_y"
        assert restored.y_error_expr == "my_e"
        assert "def fit" in restored.fit_code
        assert restored.param_names == ["amp", "freq"]
        assert restored.param_settings["amp"]["min"] == 0.0
        assert restored.param_settings["freq"]["initial"] == 0.5

    def test_instance_name_preserved(self, qapp):
        from stoner_measurement.plugins.base_plugin import BasePlugin

        p = CurveFitPlugin()
        p.instance_name = "my_fit"
        restored = BasePlugin.from_json(p.to_json())
        assert restored.instance_name == "my_fit"


# ---------------------------------------------------------------------------
# Config tabs
# ---------------------------------------------------------------------------


class TestCurveFitConfigTabs:
    def test_has_three_content_tabs(self, qapp):
        p = CurveFitPlugin()
        tabs = p.config_tabs()
        tab_titles = [t for t, _ in tabs]
        assert "Data" in tab_titles
        assert "Fit Function" in tab_titles
        assert "Parameters" in tab_titles

    def test_general_tab_present(self, qapp):
        p = CurveFitPlugin()
        tabs = p.config_tabs()
        tab_titles = [t for t, _ in tabs]
        assert "General" in tab_titles

    def test_first_tab_is_data(self, qapp):
        p = CurveFitPlugin()
        tabs = p.config_tabs()
        assert tabs[0][0] == "Data"

    def test_second_tab_is_fit_function(self, qapp):
        p = CurveFitPlugin()
        tabs = p.config_tabs()
        assert tabs[1][0] == "Fit Function"

    def test_third_tab_is_parameters(self, qapp):
        p = CurveFitPlugin()
        tabs = p.config_tabs()
        assert tabs[2][0] == "Parameters"

    def test_data_tab_is_qwidget(self, qapp):
        from PyQt6.QtWidgets import QWidget

        p = CurveFitPlugin()
        tabs = p.config_tabs()
        data_widget = dict(tabs)["Data"]
        assert isinstance(data_widget, QWidget)

    def test_fit_function_tab_contains_editor(self, qapp):
        from stoner_measurement.ui.editor_widget import EditorWidget

        p = CurveFitPlugin()
        tabs = p.config_tabs()
        fit_widget = dict(tabs)["Fit Function"]
        editors = fit_widget.findChildren(EditorWidget)
        assert len(editors) == 1

    def test_parameters_tab_is_qwidget_with_param_table(self, qapp):
        from PyQt6.QtWidgets import QWidget

        from stoner_measurement.plugins.transform.curve_fit import _ParamTableWidget

        p = CurveFitPlugin()
        tabs = p.config_tabs()
        param_widget = dict(tabs)["Parameters"]
        assert isinstance(param_widget, QWidget)
        # The tab container holds a _ParamTableWidget as a child.
        tables = param_widget.findChildren(_ParamTableWidget)
        assert len(tables) == 1

    def test_output_names_reflect_output_names_property(self, qapp):
        p = CurveFitPlugin()
        p.param_names = ["k", "c"]
        assert p.output_names == ["k", "k_err", "c", "c_err"]


# ---------------------------------------------------------------------------
# _update_param_names
# ---------------------------------------------------------------------------


class TestUpdateParamNames:
    def test_updates_param_names(self, qapp):
        p = CurveFitPlugin()
        p._update_param_names("def fit(x, k): return k")
        assert p.param_names == ["k"]

    def test_handles_syntax_error_gracefully(self, qapp):
        p = CurveFitPlugin()
        p._update_param_names("not valid !!")
        assert p.param_names == []

    def test_updates_fit_code(self, qapp):
        p = CurveFitPlugin()
        new_code = "def fit(x, k): return k"
        p._update_param_names(new_code)
        assert p.fit_code == new_code


# ---------------------------------------------------------------------------
# Code generation
# ---------------------------------------------------------------------------


class TestCurveFitCodeGeneration:
    def test_has_lifecycle_false(self, qapp):
        """CurveFitPlugin (and TransformPlugin) must not participate in the
        connect/configure/disconnect lifecycle."""
        assert CurveFitPlugin().has_lifecycle is False

    def test_generate_action_code_calls_run(self, qapp):
        p = CurveFitPlugin()
        p.instance_name = "my_fit"
        lines = p.generate_action_code(1, [], lambda s, i: [])
        assert any("my_fit.run({})" in line for line in lines)

    def test_generate_action_code_not_commented(self, qapp):
        p = CurveFitPlugin()
        lines = p.generate_action_code(1, [], lambda s, i: [])
        code_lines = [ln for ln in lines if ln.strip()]
        assert all(not ln.strip().startswith("#") for ln in code_lines)


# ---------------------------------------------------------------------------
# Optional trace outputs
# ---------------------------------------------------------------------------


class TestCurveFitOptionalTraces:
    @pytest.fixture
    def linear_plugin(self, qapp):
        from stoner_measurement.core.sequence_engine import SequenceEngine

        engine = SequenceEngine()
        plugin = CurveFitPlugin()
        engine.add_plugin("curve_fit", plugin)
        x = np.linspace(0.0, 1.0, 30)
        y = 3.0 * x + 1.5
        engine._namespace["_x"] = x
        engine._namespace["_y"] = y
        plugin.advanced_mode = True
        plugin.x_expr = "_x"
        plugin.y_expr = "_y"
        plugin.fit_code = "def fit(x, a, b): return a * x + b"
        plugin.param_names = ["a", "b"]
        yield plugin, engine
        engine.shutdown()

    def test_output_trace_names_empty_by_default(self, qapp):
        assert CurveFitPlugin().output_trace_names == []

    def test_output_value_names_excludes_traces(self, qapp):
        p = CurveFitPlugin()
        p.param_names = ["a", "b"]
        p.show_initial_trace = True
        p.show_best_fit_trace = True
        assert p.output_value_names == ["a", "a_err", "b", "b_err"]

    def test_output_names_includes_traces_when_enabled(self, qapp):
        p = CurveFitPlugin()
        p.param_names = ["a", "b"]
        p.show_initial_trace = True
        p.show_best_fit_trace = True
        assert "initial_fit" in p.output_names
        assert "best_fit" in p.output_names

    def test_output_trace_names_initial_only(self, qapp):
        p = CurveFitPlugin()
        p.show_initial_trace = True
        assert p.output_trace_names == ["initial_fit"]

    def test_output_trace_names_best_fit_only(self, qapp):
        p = CurveFitPlugin()
        p.show_best_fit_trace = True
        assert p.output_trace_names == ["best_fit"]

    def test_output_trace_names_both(self, qapp):
        p = CurveFitPlugin()
        p.show_initial_trace = True
        p.show_best_fit_trace = True
        assert p.output_trace_names == ["initial_fit", "best_fit"]

    def test_reported_traces_empty_by_default(self, qapp):
        p = CurveFitPlugin()
        assert p.reported_traces() == {}

    def test_reported_traces_initial_when_enabled(self, qapp):
        p = CurveFitPlugin()
        p.instance_name = "fit1"
        p.show_initial_trace = True
        traces = p.reported_traces()
        assert "fit1:initial_fit" in traces
        assert traces["fit1:initial_fit"] == "fit1.data['initial_fit']"

    def test_reported_traces_best_fit_when_enabled(self, qapp):
        p = CurveFitPlugin()
        p.instance_name = "fit1"
        p.show_best_fit_trace = True
        traces = p.reported_traces()
        assert "fit1:best_fit" in traces
        assert traces["fit1:best_fit"] == "fit1.data['best_fit']"

    def test_initial_trace_computed_in_transform(self, linear_plugin):
        from stoner_measurement.plugins.trace.base import TraceData

        plugin, _ = linear_plugin
        plugin.show_initial_trace = True
        result = plugin.transform({})
        assert "initial_fit" in result
        assert isinstance(result["initial_fit"], TraceData)
        assert len(result["initial_fit"].x) == 30
        assert len(result["initial_fit"].y) == 30

    def test_best_fit_trace_computed_in_transform(self, linear_plugin):
        from stoner_measurement.plugins.trace.base import TraceData

        plugin, _ = linear_plugin
        plugin.show_best_fit_trace = True
        result = plugin.transform({})
        assert "best_fit" in result
        assert isinstance(result["best_fit"], TraceData)
        assert len(result["best_fit"].x) == 30
        assert len(result["best_fit"].y) == 30

    def test_best_fit_trace_matches_optimal_params(self, linear_plugin):
        plugin, _ = linear_plugin
        plugin.show_best_fit_trace = True
        result = plugin.transform({})
        # For exact linear data the best-fit y should be close to original y.
        x = np.linspace(0.0, 1.0, 30)
        expected_y = 3.0 * x + 1.5
        np.testing.assert_allclose(result["best_fit"].y, expected_y, atol=1e-6)

    def test_no_traces_when_flags_disabled(self, linear_plugin):
        plugin, _ = linear_plugin
        result = plugin.transform({})
        assert "initial_fit" not in result
        assert "best_fit" not in result

    def test_to_json_includes_trace_flags(self, qapp):
        p = CurveFitPlugin()
        p.show_initial_trace = True
        p.show_best_fit_trace = False
        d = p.to_json()
        assert d["show_initial_trace"] is True
        assert d["show_best_fit_trace"] is False

    def test_round_trip_preserves_trace_flags(self, qapp):
        from stoner_measurement.plugins.base_plugin import BasePlugin

        p = CurveFitPlugin()
        p.show_initial_trace = True
        p.show_best_fit_trace = True
        restored = BasePlugin.from_json(p.to_json())
        assert isinstance(restored, CurveFitPlugin)
        assert restored.show_initial_trace is True
        assert restored.show_best_fit_trace is True

    def test_parameters_tab_has_trace_checkboxes(self, qapp):
        from PyQt6.QtWidgets import QCheckBox

        p = CurveFitPlugin()
        tabs = p.config_tabs()
        param_widget = dict(tabs)["Parameters"]
        checkboxes = param_widget.findChildren(QCheckBox)
        labels = {cb.text() for cb in checkboxes}
        assert any("initial" in lbl.lower() for lbl in labels)
        assert any("best" in lbl.lower() for lbl in labels)
