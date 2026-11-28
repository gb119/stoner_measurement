"""Direct and generated state execution must collect the same measurements."""

from types import SimpleNamespace

import pandas as pd
import pytest

from stoner_measurement.core.sequence_hooks import defer_sequence_action
from stoner_measurement.core.trace_data import TraceData
from stoner_measurement.plugins.command import (
    BreakIfCommand,
    ContinueIfCommand,
    IfCommand,
    SaveCommand,
    SkipCollectionCommand,
)
from stoner_measurement.plugins.command.base import CommandPlugin
from stoner_measurement.plugins.state_scan import CounterPlugin
from stoner_measurement.plugins.state_sweep import StateSweepPlugin
from stoner_measurement.plugins.trace import DummyPlugin
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

    def __init__(self):
        super().__init__()
        self.callback = lambda: None

    @property
    def name(self):
        return "readback"

    def execute(self):
        self.callback()

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
    axis.collect_output_labels = {"readback:Measured": "Measured signal"}
    return axis, readback


@pytest.fixture
def state_case(engine, qtbot, null_plot_display_host, kind):
    """Supply an axis, its readback and both ways to run the sequence."""
    axis, readback = _axis(engine, kind)

    def execute(path, child, *, before=(), after=(), following=()):
        readback.callback = child
        if path == "direct":
            axis.execute_sequence([*before, readback, *after])
            return []

        source, line_map = engine.generate_sequence_code(
            [(axis, [*before, readback, *after]), *following], {}, return_line_map=True
        )
        errors = []
        engine.error_output.connect(errors.append)
        try:
            with qtbot.waitSignal(
                engine.status_changed,
                timeout=5000,
                check_params_cb=lambda status: status in {"Idle", "Error"},
            ):
                engine.run_script(source, customised=False, line_map=line_map)
            qtbot.waitUntil(lambda: not engine.is_running, timeout=5000)
        finally:
            engine.error_output.disconnect(errors.append)
        return errors

    return axis, readback, execute


@pytest.mark.parametrize("kind", ["scan", "sweep"])
@pytest.mark.parametrize("path", ["direct", "generated"])
@pytest.mark.parametrize("clear", [False, True])
@pytest.mark.parametrize("collect", [False, True])
def test_collection_flags_and_child_measurements_match(state_case, path, clear, collect):
    axis, readback, execute = state_case
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

    assert not execute(path, child)
    assert visited == [(0.0, False), (1.0, True), (2.0, True)]
    expected = ([] if clear else [-1.0]) + ([1.0, 2.0] if collect else [])
    assert axis.data.x.tolist() == expected
    if collect:
        assert axis.data.df["Measured signal"].tolist() == ([] if clear else [99.0]) + [
            10.0,
            20.0,
        ]


@pytest.mark.parametrize("kind", ["scan", "sweep"])
@pytest.mark.parametrize("path", ["direct", "generated"])
def test_failed_child_does_not_collect_and_disconnects(state_case, monkeypatch, kind, path):
    axis, _, execute = state_case
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

    if path == "direct":
        with pytest.raises(RuntimeError, match="child failed"):
            execute(path, child)
    else:
        errors = execute(path, child)
        assert len(errors) == 1
        assert "child failed" in errors[0]
    assert axis.data.df.empty
    assert disconnected == [True]
    if kind == "sweep":
        assert axis._previous_engine_polling_rate_hz is None
        assert rates == [10.0, 2.0]


@pytest.mark.parametrize("kind", ["scan", "sweep"])
@pytest.mark.parametrize("path", ["direct", "generated"])
@pytest.mark.parametrize("clear_filter", ["axis.value == 0", "False"])
def test_repeated_execution_resets_metadata_before_clear_filter(state_case, path, clear_filter):
    axis, readback, execute = state_case
    axis.clear_filter = clear_filter

    def child():
        readback.value = axis.value

    assert not execute(path, child)
    assert not execute(path, child)
    expected = [1.0, 2.0] if clear_filter != "False" else [1.0, 2.0, 1.0, 2.0]
    assert axis.data.x.tolist() == expected


@pytest.mark.parametrize("kind", ["scan", "sweep"])
@pytest.mark.parametrize("path", ["direct", "generated"])
@pytest.mark.parametrize("collect_filter", ["False", "True"])
def test_collection_filter_controls_rows_on_both_paths(state_case, path, collect_filter):
    axis, readback, execute = state_case
    axis.collect_data = True
    axis.collect_filter = collect_filter

    def child():
        readback.value = axis.value

    assert not execute(path, child)
    assert axis.data.x.tolist() == ([1.0, 2.0] if collect_filter == "True" else [])


@pytest.mark.parametrize("kind", ["scan", "sweep"])
@pytest.mark.parametrize(
    ("command_type", "visited", "later", "collected"),
    [(BreakIfCommand, [0, 1], [0], [1]), (ContinueIfCommand, [0, 1, 2], [0, 2], [1, 2])],
)
def test_loop_control_finishes_point_before_changing_flow(
    state_case, engine, command_type, visited, later, collected
):
    axis, _, execute = state_case
    control = command_type(condition="axis.value == 1")
    tail = _Readback()
    tail.instance_name = "tail"
    engine.add_plugin("tail", tail)
    reached = []
    ran_tail = []
    saved = []
    tail.callback = lambda: ran_tail.append(axis.value)

    def child():
        reached.append(axis.value)
        assert defer_sequence_action("iteration", lambda: saved.append(axis.data.x.tolist()))

    assert not execute("generated", child, after=[control, tail])
    assert reached == visited
    assert ran_tail == later
    assert axis.data.x.tolist() == collected
    assert saved == [[], *[collected[: index + 1] for index in range(len(collected))]]


@pytest.mark.parametrize("kind", ["scan", "sweep"])
@pytest.mark.parametrize("path", ["direct", "generated"])
def test_skip_collection_clears_live_flag_for_only_current_point(state_case, path):
    axis, _, execute = state_case
    skip = SkipCollectionCommand()
    flags = []

    def child():
        if path == "direct" and axis.value == 1:
            skip()
        flags.append(axis.meas_flag)

    reject = (IfCommand(condition="axis.value == 1"), [skip])
    assert not execute(path, child, before=[reject] if path == "generated" else [])
    assert flags == [False, False, True]
    assert axis.data.x.tolist() == [2.0]


@pytest.mark.parametrize("kind", ["scan", "sweep"])
@pytest.mark.parametrize("save_format", ["tdi", "nexus"])
@pytest.mark.parametrize("batch", [False, True])
def test_deferred_save_copies_only_new_rows_with_their_point_reading(
    state_case, engine, monkeypatch, tmp_path, save_format, batch
):
    axis, readback, execute = state_case
    dummy = DummyPlugin()
    save = SaveCommand()
    save.incremental_save = True
    save.save_format = save_format
    path = tmp_path / f"collected.{save_format}"
    save.path_expr = repr(str(path))
    engine.add_plugin("dummy", dummy)
    engine.add_plugin("save", save)
    engine.update_step_plugin_catalog([axis, readback, dummy, save])

    after_save = _Readback()
    after_save.instance_name = "after_save"
    engine.add_plugin("after_save", after_save)
    after_save.callback = lambda: setattr(dummy, "data", {"Dummy": TraceData.from_xy([0.0], [99.0])})
    condition = "axis.value == 2" if batch else "axis.meas_flag"

    copied = []
    original = pd.Series.to_numpy

    def spy(series, *args, **kwargs):
        if series.name == "Measured signal" and kwargs.get("copy"):
            copied.append(len(series))
        return original(series, *args, **kwargs)

    monkeypatch.setattr(pd.Series, "to_numpy", spy)

    def acquire():
        readback.value = axis.value * 10
        dummy.data = {"Dummy": TraceData.from_xy([0.0], [readback.value])}

    assert not execute("generated", acquire, after=[(IfCommand(condition=condition), [save]), after_save])
    assert copied == ([2] if batch else [1, 1])
    if save_format == "tdi":
        header, *rows = [line.split("\t") for line in path.read_text(encoding="utf-8").splitlines()]
        field = header.index("axis.data:Measured signal ()")
        signal = header.index("dummy:Dummy:y ()")
        measured = [float(row[field]) for row in rows if row[field]]
        short = [float(row[signal]) for row in rows if row[field]]
    else:
        h5py = pytest.importorskip("h5py")
        with h5py.File(path) as handle:
            columns = {ds.attrs["original_name"]: ds[:].tolist() for ds in handle["entry/data"].values()}
        measured = columns["axis.data:Measured signal ()"]
        short = columns["dummy:Dummy:y ()"]
    assert measured == [10.0, 20.0]
    assert short == pytest.approx([float("nan") if batch else 10.0, 20.0], nan_ok=True)


@pytest.mark.parametrize("kind", ["scan"])
def test_save_flushes_earlier_rows_on_a_point_rejected_by_collection(state_case, engine, tmp_path):
    axis, _, execute = state_case
    save = SaveCommand()
    save.incremental_save = True
    path = tmp_path / "batch.txt"
    save.path_expr = repr(str(path))
    engine.add_plugin("save", save)
    final_batch = IfCommand(condition="axis.value == 2")

    assert not execute(
        "generated", lambda: None, after=[(final_batch, [save, SkipCollectionCommand()])]
    )
    assert axis.data.x.tolist() == [1.0]
    data = [line.split("\t") for line in path.read_text(encoding="utf-8").splitlines()]
    field = data[0].index("axis.data:Value ()")
    assert [row[field] for row in data[1:] if row[field]] == ["1.0"]


@pytest.mark.parametrize("kind", ["scan"])
@pytest.mark.parametrize("select_outer_in_inner", [False, True])
def test_nested_save_uses_its_position_and_root_drains_before_disconnect(
    state_case, engine, monkeypatch, tmp_path, select_outer_in_inner
):
    outer, readback, execute = state_case
    inner = CounterPlugin()
    inner.instance_name = "inner"
    inner.scan_generator = ListScanGenerator(stages=[(10.0, True)])
    inner.collect_outputs = []
    inner_save, outer_save = SaveCommand(), SaveCommand()
    inner_path, outer_path = tmp_path / "inner.txt", tmp_path / "outer.txt"
    for plugin, name, path in [(inner_save, "inner_save", inner_path), (outer_save, "outer_save", outer_path)]:
        plugin.instance_name = name
        plugin.path_expr = repr(str(path))
        plugin.incremental_save = True
        use_inner_table = name == "inner_save" and not select_outer_in_inner
        plugin.trace_selection = {"inner.data": use_inner_table, "axis.data": not use_inner_table}
        engine.add_plugin(name, plugin)
    inner_tail, join, root_step = _Readback(), _Readback(), _Readback()
    inner_tail.instance_name = "inner_tail"
    join.instance_name, root_step.instance_name = "join", "root_step"
    for plugin in (inner, inner_tail, join, root_step):
        engine.add_plugin(plugin.instance_name, plugin)
    engine.update_step_plugin_catalog([outer, inner, readback, inner_save, outer_save])
    events = []

    def before_inner_collection():
        assert not inner_path.exists()

    def at_join():
        assert inner_path.exists()
        assert not outer_path.exists()
        events.append("joined")

    def at_root():
        assert outer_path.exists()
        assert defer_sequence_action("iteration", lambda: events.append("root iteration"))
        assert defer_sequence_action("sequence", lambda: events.append("root sequence"))
        events.append("root body")

    inner_tail.callback, join.callback, root_step.callback = before_inner_collection, at_join, at_root
    monkeypatch.setattr(outer, "disconnect", lambda: events.append("disconnected"))
    measure = IfCommand(condition="axis.value == 1")
    assert not execute(
        "generated", lambda: None,
        after=[(measure, [(inner, [inner_save, inner_tail]), join, outer_save])], following=[root_step],
    )
    assert events == ["joined", "root body", "root iteration", "root sequence", "disconnected"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
