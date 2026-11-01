"""Failed fits and missing plot outputs must not abort the sequence worker."""

from __future__ import annotations

import logging

import numpy as np
import pytest

from stoner_measurement.core.plotting.service import PlotService
from stoner_measurement.plugins.command import PlotPointsCommand, PlotTraceCommand
from stoner_measurement.plugins.transform import CurveFitPlugin


@pytest.mark.parametrize("failure", ["model", "data", "p0", "syntax"])
@pytest.mark.parametrize("trace_name", ["initial_fit", "best_fit"])
@pytest.mark.parametrize("plot_mode", ["simple", "advanced", "polar", "xyz"])
def test_failed_fit_and_plot_allow_later_script_steps(
    qapp, qtbot, engine, caplog, failure, trace_name, plot_mode
):
    fit = CurveFitPlugin()
    fit.advanced_mode = True
    fit.x_expr, fit.y_expr = "_x", "_y"
    fit.fit_code = "def fit(x, a): return a*x"
    fit.param_names = ["a"]
    fit.report_initial_values = True
    fit.show_initial_trace = fit.show_best_fit_trace = True
    engine.add_plugin("curve_fit", fit)
    fit.engine_namespace.update({"_x": np.arange(5.0), "_y": np.arange(5.0)})
    if failure == "model":
        fit.fit_code = "def fit(x, a): raise RuntimeError('model failed')"
    elif failure == "data":
        fit.engine_namespace["_x"] = ["bad"] * 5
    elif failure == "p0":
        fit.fit_code += "\ndef p0(x, y): return ['bad']"
    else:
        fit.fit_code = "def fit("

    plot = PlotTraceCommand()
    plot.trace_key = f"curve_fit:{trace_name}"
    plot.advanced_mode = plot_mode == "advanced"
    expression = f"curve_fit.data[{trace_name!r}]"
    plot.x_expr, plot.y_expr = expression + ".x", expression + ".y"
    if plot_mode == "polar":
        plot.plot_form = "polar"
        plot.polar_angle_expr, plot.polar_radius_expr = plot.x_expr, plot.y_expr
    elif plot_mode == "xyz":
        plot.plot_form = "xyz"
        plot.new_x_expr, plot.z_expr = plot.x_expr, plot.y_expr
        plot.fixed_y_expr = "0"
    engine.add_plugin("plot_fit", plot)
    plotted, errors = [], []
    plot.plot_update_queued.connect(lambda: plotted.append(True))
    engine.error_output.connect(errors.append)
    code = "\n".join(fit.generate_action_code(0, [], lambda *_: []))
    code += "\nplot_fit.execute()\ncontinued_after_fit = True"

    with caplog.at_level(logging.WARNING, logger="stoner_measurement.sequence"):
        with qtbot.waitSignal(engine.script_finished, timeout=5000):
            engine.run_script(code)

    assert engine.namespace["continued_after_fit"] is True
    assert not errors
    assert not plotted
    assert set(fit.data) == set(fit.output_value_names)
    assert all(np.isnan(value) for value in fit.data.values())
    assert trace_name not in fit.data
    assert any(
        record.levelno == logging.ERROR and "CurveFit:" in record.message
        for record in caplog.records
    )
    assert any(
        "PlotTrace:" in record.message and "skipping plot" in record.message
        for record in caplog.records
    )


@pytest.mark.parametrize("source", ["trace", "nan", "array_nan", "attribute", "runtime"])
@pytest.mark.parametrize(
    ("form", "target"),
    [
        ("polar", "polar_angle_expr"),
        ("polar", "polar_radius_expr"),
        ("polar", "polar_angle_error_expr"),
        ("polar", "polar_radius_error_expr"),
        ("polar", "polar_id_expr"),
        ("polar", "polar_title_expr"),
        ("xyz", "new_x_expr"),
        ("xyz", "coordinate_y_expr"),
        ("xyz", "z"),
        ("xyz", "error"),
        ("xyz", "identity"),
        ("xyz", "acquisition_id_expr"),
        ("xyz_value", "value_expr"),
        ("xy_intensity", "z"),
    ],
)
def test_failed_fit_points_skip_unavailable_inputs_and_continue(
    qapp, qtbot, engine, caplog, source, form, target
):
    fit = CurveFitPlugin()
    fit.advanced_mode = True
    fit.x_expr, fit.y_expr = "[0, 1, 2]", "[0, 1, 2]"
    fit.param_names = ["a"]
    fit.show_best_fit_trace = True
    fit.fit_code = "def fit(x, a): raise RuntimeError('fit failed')"
    engine.add_plugin("curve_fit", fit)
    points = PlotPointsCommand()
    points.plot_form = form
    points.polar_angle_expr, points.polar_radius_expr = "0", "1"
    points.new_x_expr, points.coordinate_y_expr, points.value_expr = "0", "1", "2"
    points.z_entries = [
        {"expr": "2", "surface_id_expr": "'first'"},
        {"expr": "3", "surface_id_expr": "'second'"},
    ]
    expression = {
        "trace": "curve_fit.data['best_fit'].y[0]",
        "nan": "curve_fit.a",
        "attribute": "curve_fit.unavailable",
        "array_nan": "np.array(curve_fit.a)",
        "runtime": "1 / 0",
    }[source]
    if target in {"z", "error", "identity"}:
        field = {"z": "expr", "error": "error_expr", "identity": "surface_id_expr"}[target]
        points.z_entries[1][field] = expression
    else:
        setattr(points, target, expression)
    engine.add_plugin("plot_points", points)
    service = PlotService()
    engine.plot_client = service
    results, errors = [], []
    service.result_ready.connect(results.append)
    engine.error_output.connect(errors.append)
    code = "\n".join(fit.generate_action_code(0, [], lambda *_: []))
    code += "\n" + "\n".join(points.generate_action_code(0, [], lambda *_: []))
    code += "\ncontinued_after_points = True"
    try:
        with caplog.at_level(logging.WARNING, logger="stoner_measurement.sequence"):
            with qtbot.waitSignal(engine.script_finished, timeout=5000):
                engine.run_script(code)
        assert engine.namespace["continued_after_points"] is True
        assert not errors
        assert not results  # A missing second Z series must not submit the first either.
        assert np.isnan(fit.data["a"])
        assert "best_fit" not in fit.data
        assert any(
            "PlotPoints:" in record.message
            and "skipping plot" in record.message
            and expression in record.message
            for record in caplog.records
        )
    finally:
        engine.plot_client = None
        service.shutdown()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
