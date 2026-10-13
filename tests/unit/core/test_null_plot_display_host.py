"""The shared null host preserves script selection and no-display completion."""

from threading import Event

import pytest

from stoner_measurement.core.plotting.contracts import ClearPlot, PlotRequest, ResultStatus


def test_generated_script_selects_without_rendering(engine, null_plot_display_host, qtbot):
    engine.preferred_display_plugin = "polar"
    code = engine.generate_sequence_code([], {})
    errors = []
    engine.error_output.connect(errors.append)
    with qtbot.waitSignal(engine.script_finished, timeout=5000):
        engine.run_script(code)
    assert not errors
    assert null_plot_display_host.factory_id == "polar"
    assert engine.preferred_display_plugin == "polar"
    assert engine.plot_client.capabilities() is None
    ticket = engine.plot_client.apply_now(PlotRequest(ClearPlot()))
    result = ticket.wait(timeout=0)
    assert result is not None
    assert result.status == ResultStatus.NO_DISPLAY


def test_missing_selection_preserves_current_display(engine, null_plot_display_host):
    with pytest.raises(RuntimeError, match="missing"):
        engine.select_display_plugin("missing")
    assert null_plot_display_host.factory_id == engine.preferred_display_plugin == "cartesian"


def test_cancelled_selection_preserves_current_display(null_plot_display_host):
    stopped = Event()
    stopped.set()
    with pytest.raises(RuntimeError, match="stopped"):
        null_plot_display_host.select_display("polar", stop_event=stopped)
    assert null_plot_display_host.factory_id == "cartesian"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
