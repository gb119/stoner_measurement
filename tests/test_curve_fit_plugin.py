"""Tests for CurveFitPlugin — curve-fitting transform plugin."""

from __future__ import annotations

import json

import numpy as np
import pytest

from stoner_measurement.plugins.transform import CurveFitPlugin
from stoner_measurement.plugins.transform.curve_fit import (
    _format_value_with_uncertainty,
    _has_p0_function,
    _ParamTableWidget,
    _parse_fit_params,
    _si_scale_and_prefix,
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


class TestSiScaleAndPrefix:
    def test_kilo(self):
        scale, prefix = _si_scale_and_prefix(1234.0)
        assert scale == pytest.approx(1000.0)
        assert prefix == "k"

    def test_milli(self):
        scale, prefix = _si_scale_and_prefix(0.00456)
        assert scale == pytest.approx(0.001)
        assert prefix == "m"

    def test_unity(self):
        scale, prefix = _si_scale_and_prefix(12.3)
        assert scale == pytest.approx(1.0)
        assert prefix == ""

    def test_zero(self):
        scale, prefix = _si_scale_and_prefix(0.0)
        assert scale == pytest.approx(1.0)
        assert prefix == ""

    def test_mega(self):
        scale, prefix = _si_scale_and_prefix(2.5e7)
        assert scale == pytest.approx(1e6)
        assert prefix == "M"

    def test_nano(self):
        scale, prefix = _si_scale_and_prefix(4.5e-8)
        assert scale == pytest.approx(1e-9)
        assert prefix == "n"

    def test_exact_kilo_boundary(self):
        # 1000.0 should resolve to tier=1 (kilo)
        scale, prefix = _si_scale_and_prefix(1000.0)
        assert scale == pytest.approx(1000.0)
        assert prefix == "k"

    def test_exact_milli_boundary(self):
        # 0.001 should resolve to tier=-1 (milli), mantissa=1.0, which is in [0.1, 1000)
        scale, prefix = _si_scale_and_prefix(0.001)
        assert scale == pytest.approx(0.001)
        assert prefix == "m"

    def test_sub_unity_stays_unscaled(self):
        # 0.5 is in [0.1, 1000), so no SI prefix should be applied
        scale, prefix = _si_scale_and_prefix(0.5)
        assert scale == pytest.approx(1.0)
        assert prefix == ""

    def test_lower_boundary_stays_unscaled(self):
        # 0.1 is exactly at the lower boundary, should stay at unity scale
        scale, prefix = _si_scale_and_prefix(0.1)
        assert scale == pytest.approx(1.0)
        assert prefix == ""

    def test_just_below_lower_boundary_uses_milli(self):
        # 0.099 < 0.1, so should scale to milli (mantissa ~99 m)
        scale, prefix = _si_scale_and_prefix(0.099)
        assert scale == pytest.approx(0.001)
        assert prefix == "m"

    def test_negative_value_same_prefix_as_positive(self):
        pos_scale, pos_prefix = _si_scale_and_prefix(1234.0)
        neg_scale, neg_prefix = _si_scale_and_prefix(-1234.0)
        assert neg_scale == pytest.approx(pos_scale)
        assert neg_prefix == pos_prefix


class TestFormatValueWithUncertainty:
    def test_formats_with_matching_precision(self):
        assert _format_value_with_uncertainty(12.345, 0.67) == "12.3 ± 0.7"

    def test_applies_si_prefix_for_large_values(self):
        assert _format_value_with_uncertainty(1234.0, 230.0) == "1.2 ± 0.2 k"

    def test_preserves_decimal_precision_when_rounding_to_one(self):
        assert _format_value_with_uncertainty(1.23, 0.96) == "1.2 ± 1.0"

    def test_applies_si_prefix_for_small_values(self):
        assert _format_value_with_uncertainty(0.00456, 0.00034) == "4.6 ± 0.3 m"

    def test_sub_unity_value_no_si_prefix(self):
        # 0.5 is in [0.1, 1000), so no prefix — value and uncertainty formatted at unity scale
        assert _format_value_with_uncertainty(0.5, 0.03) == "0.50 ± 0.03"

    def test_negative_value_uses_same_si_prefix(self):
        assert _format_value_with_uncertainty(-1234.0, 230.0) == "-1.2 ± 0.2 k"

    def test_returns_empty_for_non_finite_values(self):
        assert _format_value_with_uncertainty(np.nan, 0.1) == ""
        assert _format_value_with_uncertainty(1.0, np.nan) == ""


class TestParamTableWidget:
    def test_has_fitted_column(self, qapp):
        table = _ParamTableWidget()
        assert table._table.columnCount() == 5  # noqa: SLF001
        assert table._table.horizontalHeaderItem(4).text() == "Fitted"  # noqa: SLF001

    def test_updates_fitted_column_text(self, qapp):
        table = _ParamTableWidget()
        table.set_parameters(["a"])
        table.update_fitted_results({"a": 12.345, "a_err": 0.67})
        assert table._table.item(0, 4).text() == "12.3 ± 0.7"  # noqa: SLF001


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

    def test_stdout_from_user_fit_and_p0_is_forwarded_to_engine_output(self, qapp):
        from stoner_measurement.core.sequence_engine import SequenceEngine

        engine = SequenceEngine()
        plugin = CurveFitPlugin()
        engine.add_plugin("curve_fit", plugin)

        x = np.linspace(0.0, 1.0, 30)
        y = 4.0 * x + 0.0
        engine._namespace["_x"] = x
        engine._namespace["_y"] = y
        output_chunks: list[str] = []
        engine.output.connect(output_chunks.append)

        plugin.advanced_mode = True
        plugin.x_expr = "_x"
        plugin.y_expr = "_y"
        plugin.fit_code = (
            "fit_printed = False\n"
            "def fit(x, a, b):\n"
            "    global fit_printed\n"
            "    if not fit_printed:\n"
            "        print('fit debug line')\n"
            "        fit_printed = True\n"
            "    return a * x + b\n"
            "def p0(x, y):\n"
            "    print('p0 debug line 1')\n"
            "    print('p0 debug line 2')\n"
            "    return (1.0, 0.0)\n"
        )
        plugin.param_names = ["a", "b"]
        plugin.transform({})

        captured = "".join(output_chunks)
        assert "p0 debug line 1" in captured
        assert "p0 debug line 2" in captured
        assert "fit debug line" in captured
        assert captured.index("p0 debug line 1") < captured.index("p0 debug line 2")
        assert captured.index("p0 debug line 2") < captured.index("fit debug line")
        engine.shutdown()

    def test_user_fit_code_namespace_exposes_log_logger(self, qapp):
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
            "def fit(x, a, b):\n"
            "    log.debug('fit debug message')\n"
            "    return a * x + b\n"
            "def p0(x, y):\n"
            "    log.info('p0 info message')\n"
            "    return (1.0, 0.0)\n"
        )
        plugin.param_names = ["a", "b"]
        result = plugin.transform({})

        assert abs(result["a"] - 4.0) < 1e-5
        assert abs(result["b"] - 0.0) < 1e-5
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
            "column_key",
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

    def test_general_tab_not_present(self, qapp):
        p = CurveFitPlugin()
        tabs = p.config_tabs()
        tab_titles = [t for t, _ in tabs]
        assert "General" not in tab_titles

    def test_data_tab_contains_instance_name_editor(self, qapp):
        from PyQt6.QtWidgets import QLineEdit

        p = CurveFitPlugin()
        tabs = p.config_tabs()
        data_widget = dict(tabs)["Data"]
        # The Data tab must embed the instance-name editor from _general_config_widget.
        line_edits = data_widget.findChildren(QLineEdit)
        # At least one QLineEdit whose text matches the current instance_name.
        instance_name_edits = [w for w in line_edits if w.text() == p.instance_name]
        assert len(instance_name_edits) >= 1

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

    def test_fit_function_tab_shows_runtime_namespace_hint(self, qapp):
        from PyQt6.QtWidgets import QLabel

        p = CurveFitPlugin()
        tabs = p.config_tabs()
        fit_widget = dict(tabs)["Fit Function"]
        labels = [lbl.text().lower() for lbl in fit_widget.findChildren(QLabel)]
        assert any("numpy" in text and "np" in text for text in labels)

    def test_fit_function_editor_marks_syntax_error_line(self, qapp):
        from stoner_measurement.ui.editor_widget import EditorWidget

        p = CurveFitPlugin()
        tabs = p.config_tabs()
        fit_widget = dict(tabs)["Fit Function"]
        editor = fit_widget.findChildren(EditorWidget)[0]
        editor.set_text("def fit(x a):\n    return a")
        assert editor.syntax_error_line == 1
        assert editor.syntax_error_message
        editor.set_text("def fit(x, a):\n    return a")
        assert editor.syntax_error_line is None
        assert editor.syntax_error_message == ""

    def test_parameters_tab_is_qwidget_with_param_table(self, qapp):
        from PyQt6.QtWidgets import QWidget

        p = CurveFitPlugin()
        tabs = p.config_tabs()
        param_widget = dict(tabs)["Parameters"]
        assert isinstance(param_widget, QWidget)
        # The tab container holds a _ParamTableWidget as a child.
        tables = param_widget.findChildren(_ParamTableWidget)
        assert len(tables) == 1

    def test_config_tabs_cache_widgets(self, qapp):
        p = CurveFitPlugin()
        tabs1 = p.config_tabs()
        tabs2 = p.config_tabs()
        for (title1, widget1), (title2, widget2) in zip(tabs1, tabs2):
            assert title1 == title2
            assert widget1 is widget2

    def test_output_names_reflect_output_names_property(self, qapp):
        p = CurveFitPlugin()
        p.param_names = ["k", "c"]
        assert p.output_names == ["k", "k_err", "c", "c_err"]

    def test_parameters_table_updates_fitted_values_after_run(self, qapp):
        from stoner_measurement.core.sequence_engine import SequenceEngine

        engine = SequenceEngine()
        p = CurveFitPlugin()
        engine.add_plugin("curve_fit", p)
        engine._namespace["_x"] = np.linspace(0.0, 1.0, 30)
        engine._namespace["_y"] = 3.0 * engine._namespace["_x"] + 1.5
        p.advanced_mode = True
        p.x_expr = "_x"
        p.y_expr = "_y"
        p.fit_code = "def fit(x, a, b): return a * x + b"
        p.param_names = ["a", "b"]

        tabs = p.config_tabs()
        param_widget = dict(tabs)["Parameters"]
        table = param_widget.findChildren(_ParamTableWidget)[0]
        assert table._table.item(0, 4).text() == ""  # noqa: SLF001

        p.run({})
        qapp.processEvents()

        fitted_cell = table._table.item(0, 4).text()  # noqa: SLF001
        assert fitted_cell
        assert "±" in fitted_cell
        engine.shutdown()


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
        import pandas as pd

        from stoner_measurement.plugins.trace.base import TraceData

        plugin, _ = linear_plugin
        plugin.show_initial_trace = True
        result = plugin.transform({})
        assert "initial_fit" in result
        assert isinstance(result["initial_fit"], TraceData)
        assert len(result["initial_fit"].x) == 30
        assert len(result["initial_fit"].y) == 30
        assert isinstance(result["initial_fit"].df, pd.DataFrame)

    def test_best_fit_trace_computed_in_transform(self, linear_plugin):
        import pandas as pd

        from stoner_measurement.plugins.trace.base import TraceData

        plugin, _ = linear_plugin
        plugin.show_best_fit_trace = True
        result = plugin.transform({})
        assert "best_fit" in result
        assert isinstance(result["best_fit"], TraceData)
        assert len(result["best_fit"].x) == 30
        assert len(result["best_fit"].y) == 30
        assert isinstance(result["best_fit"].df, pd.DataFrame)

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


# ---------------------------------------------------------------------------
# column_key — multicolumn TraceData support
# ---------------------------------------------------------------------------


class TestCurveFitColumnKey:
    """Tests for CurveFitPlugin column_key attribute and multicolumn TraceData support."""

    def _make_engine_with_multicolumn_trace(self):
        """Return (engine, plugin) wired up with a two-y-column TraceData."""
        import pandas as pd

        from stoner_measurement.core.sequence_engine import SequenceEngine
        from stoner_measurement.plugins.trace.base import COLUMN_ROLE_Y, TraceData

        engine = SequenceEngine()
        plugin = CurveFitPlugin()
        engine.add_plugin("cf", plugin)

        x = np.linspace(0.0, 1.0, 20)
        df = pd.DataFrame(
            {"V": 3.0 * x + 1.0, "R": 2.0 * x + 0.5},
            index=pd.Index(x, name="x"),
        )
        td = TraceData(df=df, column_roles={"V": COLUMN_ROLE_Y, "R": COLUMN_ROLE_Y})
        engine._namespace["_td"] = td
        engine._namespace["_traces"] = {"src:IV": "_td"}

        plugin.advanced_mode = False
        plugin.trace_key = "src:IV"
        plugin.fit_code = "def fit(x, a, b): return a * x + b"
        plugin.param_names = ["a", "b"]
        return engine, plugin

    def _make_engine_with_multicolumn_error_trace(self):
        """Return (engine, plugin) for two y-columns with two y-error columns."""
        import pandas as pd

        from stoner_measurement.core.sequence_engine import SequenceEngine
        from stoner_measurement.plugins.trace.base import COLUMN_ROLE_E, COLUMN_ROLE_Y, TraceData

        engine = SequenceEngine()
        plugin = CurveFitPlugin()
        engine.add_plugin("cf", plugin)

        x = np.linspace(0.0, 1.0, 5)
        df = pd.DataFrame(
            {
                "V": 3.0 * x + 1.0,
                "R": 2.0 * x + 0.5,
                "e_V": np.full_like(x, 0.1),
                "e_R": np.full_like(x, 2.0),
            },
            index=pd.Index(x, name="x"),
        )
        td = TraceData(
            df=df,
            column_roles={
                "V": COLUMN_ROLE_Y,
                "R": COLUMN_ROLE_Y,
                "e_V": COLUMN_ROLE_E,
                "e_R": COLUMN_ROLE_E,
            },
        )
        engine._namespace["_td"] = td
        engine._namespace["_traces"] = {"src:IV": "_td"}
        plugin.advanced_mode = False
        plugin.trace_key = "src:IV"
        return engine, plugin

    def test_column_key_default_is_empty(self, qapp):
        assert CurveFitPlugin().column_key == ""

    def test_column_key_persisted_in_to_json(self, qapp):
        p = CurveFitPlugin()
        p.column_key = "V"
        assert p.to_json()["column_key"] == "V"

    def test_column_key_restored_from_json(self, qapp):
        from stoner_measurement.plugins.base_plugin import BasePlugin

        p = CurveFitPlugin()
        p.column_key = "R"
        restored = BasePlugin.from_json(p.to_json())
        assert isinstance(restored, CurveFitPlugin)
        assert restored.column_key == "R"

    def test_column_key_selects_specific_column(self, qapp):
        engine, plugin = self._make_engine_with_multicolumn_trace()
        plugin.column_key = "R"
        result = plugin.transform({})
        # R = 2.0 * x + 0.5
        assert abs(result["a"] - 2.0) < 1e-4
        assert abs(result["b"] - 0.5) < 1e-4
        engine.shutdown()

    def test_column_key_empty_uses_first_y_column(self, qapp):
        engine, plugin = self._make_engine_with_multicolumn_trace()
        plugin.column_key = ""
        result = plugin.transform({})
        # First COLUMN_ROLE_Y is "V": V = 3.0 * x + 1.0
        assert abs(result["a"] - 3.0) < 1e-4
        assert abs(result["b"] - 1.0) < 1e-4
        engine.shutdown()

    def test_initial_trace_uses_column_name_from_source(self, qapp):
        """_compute_initial_trace preserves source column name in output DataFrame."""
        engine, plugin = self._make_engine_with_multicolumn_trace()
        plugin.column_key = "V"
        plugin.show_initial_trace = True
        result = plugin.transform({})
        assert "initial_fit" in result
        trace = result["initial_fit"]
        assert "V" in trace.df.columns
        engine.shutdown()

    def test_best_fit_trace_uses_column_name_from_source(self, qapp):
        """_compute_best_fit_trace preserves source column name in output DataFrame."""
        engine, plugin = self._make_engine_with_multicolumn_trace()
        plugin.column_key = "R"
        plugin.show_best_fit_trace = True
        result = plugin.transform({})
        assert "best_fit" in result
        trace = result["best_fit"]
        assert "R" in trace.df.columns
        engine.shutdown()

    def test_initial_trace_generic_column_name_when_no_column_key(self, qapp):
        """_compute_initial_trace uses first COLUMN_ROLE_Y column name when column_key=''."""
        engine, plugin = self._make_engine_with_multicolumn_trace()
        plugin.column_key = ""
        plugin.show_initial_trace = True
        result = plugin.transform({})
        assert "initial_fit" in result
        # The first COLUMN_ROLE_Y column is "V"
        assert "V" in result["initial_fit"].df.columns
        engine.shutdown()

    def test_data_tab_has_column_combo(self, qapp):
        """_build_data_tab returns a widget with a Column combo box."""
        from PyQt6.QtWidgets import QComboBox

        engine, plugin = self._make_engine_with_multicolumn_trace()
        tabs = plugin.config_tabs()
        data_widget = dict(tabs)["Data"]
        combos = data_widget.findChildren(QComboBox)
        assert len(combos) >= 2  # at least trace_combo and column_combo
        engine.shutdown()

    def test_get_data_arrays_matches_sigma_to_selected_y_column(self, qapp):
        engine, plugin = self._make_engine_with_multicolumn_error_trace()
        plugin.column_key = "R"
        _, _, sigma, _, _, _ = plugin._get_data_arrays()
        assert sigma is not None
        np.testing.assert_allclose(sigma, [2.0, 2.0, 2.0, 2.0, 2.0])
        engine.shutdown()

    def test_data_tab_column_combo_repopulates_on_trace_change(self, qapp):
        import pandas as pd
        from PyQt6.QtWidgets import QComboBox

        from stoner_measurement.core.sequence_engine import SequenceEngine
        from stoner_measurement.plugins.trace.base import COLUMN_ROLE_Y, TraceData

        engine = SequenceEngine()
        plugin = CurveFitPlugin()
        engine.add_plugin("cf", plugin)

        td1 = TraceData(
            df=pd.DataFrame({"A": [1.0]}, index=pd.Index([0.0], name="x")),
            column_roles={"A": COLUMN_ROLE_Y},
        )
        td2 = TraceData(
            df=pd.DataFrame({"B": [2.0]}, index=pd.Index([0.0], name="x")),
            column_roles={"B": COLUMN_ROLE_Y},
        )
        engine._namespace["td1"] = td1
        engine._namespace["td2"] = td2
        engine._namespace["_traces"] = {"src:t1": "td1", "src:t2": "td2"}
        plugin.trace_key = "src:t1"

        tabs = plugin.config_tabs()
        data_widget = dict(tabs)["Data"]
        combos = data_widget.findChildren(QComboBox)
        trace_combo = next(c for c in combos if c.findText("src:t1") >= 0 and c.findText("src:t2") >= 0)
        column_combo = next(c for c in combos if c.findText("(default)") >= 0)

        assert column_combo.findText("A") >= 0
        assert column_combo.findText("B") == -1
        trace_combo.setCurrentText("src:t2")
        assert column_combo.findText("B") >= 0
        assert column_combo.findText("A") == -1
        engine.shutdown()
