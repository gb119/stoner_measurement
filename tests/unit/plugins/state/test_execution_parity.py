"""Direct and generated state execution must collect the same measurements."""

import logging
from types import SimpleNamespace

import pytest

from stoner_measurement.plugins.command.base import CommandPlugin
from stoner_measurement.plugins.state_scan import CounterPlugin
from stoner_measurement.plugins.state_sweep import StateSweepPlugin
from stoner_measurement.scan import ListScanGenerator
from stoner_measurement.sweep import BaseSweepGenerator


class _FiniteSweep(BaseSweepGenerator):
    def iter_points(self):
        yield from [(0, 0.0, 0, False), (1, 1.0, 0, True), (2, 2.0, 0, True)]

    def config_widget(self, parent=None):
        raise NotImplementedError


class _Sweep(StateSweepPlugin):
    _sweep_generator_class = _FiniteSweep

    @property
    def name(self):
        return "axis"

    @property
    def state_name(self):
        return "Value"

    @property
    def units(self):
        return "V"


class _Readback(CommandPlugin):
    value = 0.0

    @property
    def name(self):
        return "readback"

    def execute(self):
        pass

    def reported_values(self):
        return {"readback:Measured": "readback.value"}


def _axis(engine, kind):
    if kind == "scan":
        axis = CounterPlugin()
        axis.scan_generator = ListScanGenerator(stages=[(0.0, False), (1.0, True), (2.0, True)])
    else:
        axis = _Sweep()
    axis.instance_name = "axis"
    readback = _Readback()
    engine.add_plugin("axis", axis)
    engine.add_plugin("readback", readback)
    engine.update_step_plugin_catalog([axis, readback])
    axis.collect_outputs = ["readback:Measured"]
    return axis, readback


def _execute(axis, path, child):
    if path == "direct":
        axis.execute_sequence([child])
        return
    axis.connect()
    axis.configure()
    try:
        source = "\n".join(
            axis.generate_action_code(
                0, [child], lambda _step, indent: ["    " * indent + "child()"]
            )
        )
        exec(
            compile(source, "<state action>", "exec"),
            {
                "axis": axis,
                "child": child,
                "wait_for_plot_ready": lambda: None,
                "log": logging.getLogger(__name__),
            },
        )
    finally:
        axis.disconnect()


@pytest.mark.parametrize("kind", ["scan", "sweep"])
@pytest.mark.parametrize("path", ["direct", "generated"])
@pytest.mark.parametrize("clear", [False, True])
@pytest.mark.parametrize("collect", [False, True])
def test_collection_flags_and_child_measurements_match(engine, kind, path, clear, collect):
    axis, readback = _axis(engine, kind)
    axis.collect_data = True
    axis.value = -1.0
    axis.meas_flag = True
    readback.value = 99.0
    axis.collect()
    axis.clear_on_start = clear
    axis.collect_data = collect
    visited = []

    def child():
        visited.append((axis.value, axis.meas_flag))
        readback.value = axis.value * 10

    _execute(axis, path, child)
    assert visited == [(0.0, False), (1.0, True), (2.0, True)]
    expected = ([] if clear else [-1.0]) + ([1.0, 2.0] if collect else [])
    assert axis.data.x.tolist() == expected
    if collect:
        assert axis.data.df["readback:Measured"].tolist() == ([] if clear else [99.0]) + [
            10.0,
            20.0,
        ]


@pytest.mark.parametrize("kind", ["scan", "sweep"])
@pytest.mark.parametrize("path", ["direct", "generated"])
def test_failed_child_does_not_collect_and_disconnects(engine, monkeypatch, kind, path):
    axis, _readback = _axis(engine, kind)
    axis.collect_data = True
    disconnected = []
    monkeypatch.setattr(axis, "disconnect", lambda: disconnected.append(True))
    rates = []
    if kind == "sweep":
        controller = SimpleNamespace(polling_rate_hz=2.0, set_polling_rate=rates.append)
        monkeypatch.setattr(axis, "_engine", lambda: controller, raising=False)
        axis.engine_polling_rate_hz = 10.0

    def child():
        raise RuntimeError("child failed")

    with pytest.raises(RuntimeError, match="child failed"):
        _execute(axis, path, child)
    assert axis.data.df.empty
    assert disconnected == [True]
    if kind == "sweep":
        assert axis._previous_engine_polling_rate_hz is None
        assert rates == [10.0, 2.0]


@pytest.mark.parametrize("kind", ["scan", "sweep"])
@pytest.mark.parametrize("path", ["direct", "generated"])
@pytest.mark.parametrize("clear_filter", ["axis.value == 0", "False"])
def test_repeated_execution_resets_metadata_before_clear_filter(engine, kind, path, clear_filter):
    axis, readback = _axis(engine, kind)
    axis.collect_data = True
    axis.clear_filter = clear_filter

    def child():
        readback.value = axis.value

    _execute(axis, path, child)
    _execute(axis, path, child)
    expected = [1.0, 2.0] if clear_filter != "False" else [1.0, 2.0, 1.0, 2.0]
    assert axis.data.x.tolist() == expected


@pytest.mark.parametrize("kind", ["scan", "sweep"])
@pytest.mark.parametrize("path", ["direct", "generated"])
@pytest.mark.parametrize("collect_filter", ["False", "True"])
def test_collection_filter_controls_rows_on_both_paths(engine, kind, path, collect_filter):
    axis, readback = _axis(engine, kind)
    axis.collect_data = True
    axis.collect_filter = collect_filter

    def child():
        readback.value = axis.value

    _execute(axis, path, child)
    assert axis.data.x.tolist() == ([1.0, 2.0] if collect_filter == "True" else [])


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
