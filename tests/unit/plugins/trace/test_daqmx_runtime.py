"""Unit tests for the lazy NI-DAQmx runtime trigger boundary."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from stoner_measurement.plugins.trace.daqmx_runtime import (
    DaqmxRuntimeError,
    NidaqmxRuntime,
    validate_task_definition,
)
from stoner_measurement.ui.widgets import (
    DaqmxChannelFamily,
    DaqmxInputRange,
    DaqmxInputTrigger,
    DaqmxInputTriggerMode,
    DaqmxSelectionMode,
    DaqmxTaskDefinition,
    DaqmxTaskKind,
    DaqmxTerminalConfiguration,
    DaqmxTriggerEdge,
)


class _StartTrigger:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def disable_start_trig(self) -> None:
        self.calls.append(("disable",))

    def cfg_dig_edge_start_trig(self, source, *, trigger_edge) -> None:
        self.calls.append(("digital", source, trigger_edge))

    def cfg_anlg_edge_start_trig(self, *, trigger_source, trigger_slope, trigger_level) -> None:
        self.calls.append(("analog", trigger_source, trigger_slope, trigger_level))


def _runtime() -> NidaqmxRuntime:
    runtime = object.__new__(NidaqmxRuntime)
    runtime._constants = SimpleNamespace(
        Edge=SimpleNamespace(RISING="edge-rising", FALLING="edge-falling"),
        Slope=SimpleNamespace(RISING="slope-rising", FALLING="slope-falling"),
        LineGrouping=SimpleNamespace(CHAN_PER_LINE="channel-per-line"),
        VoltageUnits=SimpleNamespace(FROM_CUSTOM_SCALE="custom-scale"),
        TerminalConfiguration=SimpleNamespace(
            RSE="rse", NRSE="nrse", DIFF="differential"
        ),
        TaskMode=SimpleNamespace(
            TASK_VERIFY="verify", TASK_UNRESERVE="unreserve", TASK_COMMIT="commit"
        ),
        AcquisitionType=SimpleNamespace(FINITE="finite"),
    )
    return runtime


def _definition(
    *,
    kind: DaqmxTaskKind = DaqmxTaskKind.ACQUISITION,
    channels: tuple[str, ...] = ("Dev1/ai0",),
    scale: str = "",
    terminal_configuration: DaqmxTerminalConfiguration = DaqmxTerminalConfiguration.DEFAULT,
) -> DaqmxTaskDefinition:
    return DaqmxTaskDefinition(
        task_kind=kind,
        device="Dev1",
        physical_channels=channels,
        custom_scale=scale,
        terminal_configuration=terminal_configuration,
    )


def test_input_start_trigger_maps_immediate_digital_and_analog_modes():
    runtime = _runtime()
    start_trigger = _StartTrigger()
    task = SimpleNamespace(triggers=SimpleNamespace(start_trigger=start_trigger))

    runtime.configure_input_start_trigger(task, DaqmxInputTrigger())
    runtime.configure_input_start_trigger(
        task,
        DaqmxInputTrigger(
            mode=DaqmxInputTriggerMode.DIGITAL,
            edge=DaqmxTriggerEdge.FALLING,
            terminal="/Dev1/PFI0",
        ),
    )
    runtime.configure_input_start_trigger(
        task,
        DaqmxInputTrigger(
            mode=DaqmxInputTriggerMode.ANALOG,
            edge=DaqmxTriggerEdge.RISING,
            terminal="/Dev1/APFI0",
            analog_level=0.125,
        ),
    )

    assert start_trigger.calls == [
        ("disable",),
        ("digital", "/Dev1/PFI0", "edge-falling"),
        ("analog", "/Dev1/APFI0", "slope-rising", 0.125),
    ]


def test_digital_output_task_uses_one_channel_per_line():
    runtime = _runtime()
    calls = []
    task = SimpleNamespace(
        do_channels=SimpleNamespace(
            add_do_chan=lambda line, *, line_grouping: calls.append((line, line_grouping))
        ),
        number_of_channels=1,
        close=lambda: calls.append(("close",)),
    )
    runtime._nidaqmx = SimpleNamespace(Task=lambda: task)

    result = runtime.create_digital_output_task("Dev1/port0/line0")

    assert result is task
    assert calls == [("Dev1/port0/line0", "channel-per-line")]


@pytest.mark.parametrize(
    ("definition", "message"),
    [
        (DaqmxTaskDefinition(), "Select a DAQmx device"),
        (DaqmxTaskDefinition(device="Dev1"), "Select at least one physical channel"),
        (
            DaqmxTaskDefinition(device="Dev1", physical_channels=("Dev2/ai0",)),
            "selected device",
        ),
        (_definition(channels=("Dev1/ai0", "Dev1/di0")), "cannot mix"),
        (_definition(channels=("Dev1/ao0",)), "not valid for a acquisition"),
        (_definition(channels=("Dev1/ctr0",)), "Counter channels"),
        (_definition(channels=("Dev1/di0",), scale="scaled"), "analog channels"),
        (
            DaqmxTaskDefinition(selection_mode=DaqmxSelectionMode.GLOBAL_CHANNELS),
            "MAX global channel",
        ),
        (
            DaqmxTaskDefinition(selection_mode=DaqmxSelectionMode.SAVED_TASK),
            "MAX saved task",
        ),
    ],
)
def test_task_definition_validation_rejects_inconsistent_sources(definition, message):
    with pytest.raises(ValueError, match=message):
        validate_task_definition(definition)


@pytest.mark.parametrize(
    "definition",
    [
        _definition(),
        _definition(kind=DaqmxTaskKind.OUTPUT, channels=("Dev1/ao0",)),
        _definition(channels=("Dev1/port0/line0",)),
        _definition(kind=DaqmxTaskKind.OUTPUT, channels=("Dev1/port0/line0",)),
        DaqmxTaskDefinition(
            selection_mode=DaqmxSelectionMode.GLOBAL_CHANNELS,
            global_channels=("global",),
        ),
        DaqmxTaskDefinition(
            selection_mode=DaqmxSelectionMode.SAVED_TASK,
            saved_task="saved",
        ),
    ],
)
def test_task_definition_validation_accepts_supported_sources(definition):
    validate_task_definition(definition)


def test_analogue_plugin_validation_rejects_digital_physical_channels():
    with pytest.raises(ValueError, match="Select analog channels"):
        validate_task_definition(
            _definition(channels=("Dev1/di0",)), DaqmxChannelFamily.ANALOG
        )


@pytest.mark.parametrize(
    ("input_range", "message"),
    [
        (DaqmxInputRange("Dev1/ai0", float("nan")), "must be finite"),
        (DaqmxInputRange("Dev1/ai0", 0.0), "must be positive"),
        (DaqmxInputRange("Dev1/ai0", -2.0), "must be positive"),
    ],
)
def test_task_definition_validation_rejects_invalid_input_ranges(input_range, message):
    definition = DaqmxTaskDefinition(
        device="Dev1",
        physical_channels=("Dev1/ai0",),
        input_ranges=(input_range,),
    )

    with pytest.raises(ValueError, match=message):
        validate_task_definition(definition)


def test_digital_output_task_closes_when_line_expands_to_multiple_channels():
    runtime = _runtime()
    calls = []
    task = SimpleNamespace(
        do_channels=SimpleNamespace(add_do_chan=lambda *_args, **_kwargs: None),
        number_of_channels=2,
        close=lambda: calls.append("close"),
    )
    runtime._nidaqmx = SimpleNamespace(Task=lambda: task)

    with pytest.raises(DaqmxRuntimeError, match="exactly one"):
        runtime.create_digital_output_task("Dev1/port0")

    assert calls == ["close"]


def test_create_task_loads_saved_task_without_creating_a_new_one():
    runtime = _runtime()
    loaded = object()
    runtime._system = SimpleNamespace(tasks={"saved": SimpleNamespace(load=lambda: loaded)})
    runtime._nidaqmx = SimpleNamespace(Task=lambda: pytest.fail("unexpected new task"))
    definition = DaqmxTaskDefinition(
        selection_mode=DaqmxSelectionMode.SAVED_TASK,
        saved_task="saved",
    )

    assert runtime.create_task(definition) is loaded


def test_create_task_adds_global_channels_and_closes_on_failure():
    runtime = _runtime()
    calls = []

    def fail_add(channels):
        calls.append(channels)
        raise RuntimeError("MAX refused channel")

    task = SimpleNamespace(
        add_global_channels=fail_add,
        close=lambda: calls.append("close"),
    )
    runtime._nidaqmx = SimpleNamespace(Task=lambda: task)
    runtime._system = SimpleNamespace(global_channels={"g1": "one", "g2": "two"})
    definition = DaqmxTaskDefinition(
        selection_mode=DaqmxSelectionMode.GLOBAL_CHANNELS,
        global_channels=("g1", "g2"),
    )

    with pytest.raises(RuntimeError, match="MAX refused"):
        runtime.create_task(definition)

    assert calls == [["one", "two"], "close"]


@pytest.mark.parametrize(
    ("definition", "collection", "method", "expected_kwargs"),
    [
        (
            _definition(
                scale="gain",
                terminal_configuration=DaqmxTerminalConfiguration.DIFFERENTIAL,
            ),
            "ai_channels",
            "add_ai_voltage_chan",
            {
                "terminal_config": "differential",
                "min_val": -10.0,
                "max_val": 10.0,
                "units": "custom-scale",
                "custom_scale_name": "gain",
            },
        ),
        (
            _definition(kind=DaqmxTaskKind.OUTPUT, channels=("Dev1/ao0",)),
            "ao_channels",
            "add_ao_voltage_chan",
            {},
        ),
        (_definition(channels=("Dev1/di0",)), "di_channels", "add_di_chan", {}),
        (
            _definition(kind=DaqmxTaskKind.OUTPUT, channels=("Dev1/do0",)),
            "do_channels",
            "add_do_chan",
            {},
        ),
    ],
)
def test_create_task_adds_each_supported_physical_channel_family(
    definition, collection, method, expected_kwargs
):
    runtime = _runtime()
    calls = []
    channel_collection = SimpleNamespace(
        **{method: lambda channel, **kwargs: calls.append((channel, kwargs))}
    )
    task = SimpleNamespace(close=lambda: None, **{collection: channel_collection})
    runtime._nidaqmx = SimpleNamespace(Task=lambda: task)

    assert runtime.create_task(definition) is task
    assert calls == [(definition.physical_channels[0], expected_kwargs)]


@pytest.mark.parametrize(
    ("configuration", "expected_constant"),
    [
        (DaqmxTerminalConfiguration.RSE, "rse"),
        (DaqmxTerminalConfiguration.NRSE, "nrse"),
        (DaqmxTerminalConfiguration.DIFFERENTIAL, "differential"),
    ],
)
def test_analogue_input_terminal_configuration_maps_to_nidaqmx(
    configuration, expected_constant
):
    runtime = _runtime()
    calls = []
    task = SimpleNamespace(
        ai_channels=SimpleNamespace(
            add_ai_voltage_chan=lambda channel, **kwargs: calls.append((channel, kwargs))
        ),
        close=lambda: None,
    )
    runtime._nidaqmx = SimpleNamespace(Task=lambda: task)

    runtime.create_task(_definition(terminal_configuration=configuration))

    assert calls == [
        (
            "Dev1/ai0",
            {
                "min_val": -10.0,
                "max_val": 10.0,
                "terminal_config": expected_constant,
            },
        )
    ]


def test_analogue_input_ranges_are_applied_per_channel():
    runtime = _runtime()
    calls = []
    task = SimpleNamespace(
        ai_channels=SimpleNamespace(
            add_ai_voltage_chan=lambda channel, **kwargs: calls.append((channel, kwargs))
        ),
        close=lambda: None,
    )
    runtime._nidaqmx = SimpleNamespace(Task=lambda: task)
    definition = DaqmxTaskDefinition(
        device="Dev1",
        physical_channels=("Dev1/ai0", "Dev1/ai1"),
        input_ranges=(
            DaqmxInputRange("Dev1/ai0", 0.1),
            DaqmxInputRange("Dev1/ai1", 5.0),
        ),
    )

    runtime.create_task(definition)

    assert calls == [
        ("Dev1/ai0", {"min_val": -0.1, "max_val": 0.1}),
        ("Dev1/ai1", {"min_val": -5.0, "max_val": 5.0}),
    ]


@pytest.mark.parametrize(
    ("kind", "actual"),
    [
        (DaqmxTaskKind.ACQUISITION, "ANALOG_INPUT"),
        (DaqmxTaskKind.ACQUISITION, "DIGITAL_INPUT"),
        (DaqmxTaskKind.OUTPUT, "ANALOG_OUTPUT"),
        (DaqmxTaskKind.OUTPUT, "DIGITAL_OUTPUT"),
    ],
)
def test_verify_task_accepts_matching_channel_direction(kind, actual):
    runtime = _runtime()
    calls = []
    task = SimpleNamespace(
        channels=SimpleNamespace(chan_type=SimpleNamespace(name=actual)),
        control=lambda mode: calls.append(mode),
    )

    runtime.verify_task(task, kind)

    assert calls == ["verify"]


def test_verify_task_rejects_opposite_channel_direction():
    runtime = _runtime()
    task = SimpleNamespace(
        channels=SimpleNamespace(chan_type=SimpleNamespace(name="ANALOG_OUTPUT")),
        control=lambda _mode: pytest.fail("invalid task should not be verified"),
    )

    with pytest.raises(DaqmxRuntimeError, match="analog output channels"):
        runtime.verify_task(task, DaqmxTaskKind.ACQUISITION)


def test_verify_task_rejects_wrong_channel_family():
    runtime = _runtime()
    task = SimpleNamespace(
        channels=SimpleNamespace(chan_type=SimpleNamespace(name="DIGITAL_INPUT")),
        control=lambda _mode: pytest.fail("invalid task should not be verified"),
    )

    with pytest.raises(DaqmxRuntimeError, match="digital channels; expected analog"):
        runtime.verify_task(task, DaqmxTaskKind.ACQUISITION, DaqmxChannelFamily.ANALOG)


def test_prepare_timing_and_commit_use_expected_task_modes():
    runtime = _runtime()
    calls = []

    def stop():
        calls.append("stop")
        raise RuntimeError("already stopped")

    task = SimpleNamespace(
        stop=stop,
        control=lambda mode: calls.append(mode),
        timing=SimpleNamespace(
            cfg_samp_clk_timing=lambda *args, **kwargs: calls.append((args, kwargs))
        ),
    )

    runtime.prepare_for_configuration(task)
    runtime.configure_finite_timing(task, 2500.0, 64, source="/Dev1/ai/SampleClock")
    runtime.commit_task(task)

    assert calls == [
        "stop",
        "unreserve",
        (
            (2500.0,),
            {
                "source": "/Dev1/ai/SampleClock",
                "sample_mode": "finite",
                "samps_per_chan": 64,
            },
        ),
        "commit",
    ]


@pytest.mark.parametrize(
    ("channel_type", "subsystem"),
    [("ANALOG_INPUT", "ai"), ("DIGITAL_INPUT", "di")],
)
def test_input_clock_and_output_start_routes_follow_acquisition_subsystem(
    channel_type, subsystem
):
    runtime = _runtime()
    calls = []
    input_task = SimpleNamespace(
        devices=[SimpleNamespace(name="Dev1")],
        channels=SimpleNamespace(chan_type=SimpleNamespace(name=channel_type)),
    )
    output_task = SimpleNamespace(
        triggers=SimpleNamespace(
            start_trigger=SimpleNamespace(
                cfg_dig_edge_start_trig=lambda source: calls.append(source)
            )
        )
    )

    assert runtime.input_sample_clock_source(input_task) == f"/Dev1/{subsystem}/SampleClock"
    assert runtime.configure_output_start_from_input(output_task, input_task) == (
        f"/Dev1/{subsystem}/StartTrigger"
    )
    assert calls == [f"/Dev1/{subsystem}/StartTrigger"]


@pytest.mark.parametrize("method", ["input_sample_clock_source", "configure_output_start_from_input"])
def test_automatic_routing_rejects_multiple_devices(method):
    runtime = _runtime()
    input_task = SimpleNamespace(
        devices=[SimpleNamespace(name="Dev1"), SimpleNamespace(name="Dev2")]
    )
    args = (
        (input_task,)
        if method == "input_sample_clock_source"
        else (SimpleNamespace(), input_task)
    )

    with pytest.raises(
        DaqmxRuntimeError, match="requires the acquisition task to use one device"
    ):
        getattr(runtime, method)(*args)


@pytest.mark.parametrize("method", ["input_sample_clock_source", "configure_output_start_from_input"])
def test_automatic_routing_rejects_unsupported_channel_type(method):
    runtime = _runtime()
    input_task = SimpleNamespace(
        devices=[SimpleNamespace(name="Dev1")],
        channels=SimpleNamespace(chan_type=SimpleNamespace(name="COUNTER_INPUT")),
    )
    args = (
        (input_task,)
        if method == "input_sample_clock_source"
        else (SimpleNamespace(), input_task)
    )

    with pytest.raises(DaqmxRuntimeError, match="no supported"):
        getattr(runtime, method)(*args)


@pytest.mark.parametrize(
    ("channel_type", "count", "values", "expected"),
    [
        ("ANALOG_OUTPUT", 1, [0.0, 1.5], [0.0, 1.5]),
        ("ANALOG_OUTPUT", 2, [0.0, 1.5], [[0.0, 1.5], [0.0, 1.5]]),
        ("DIGITAL_OUTPUT", 1, [0.0, -2.0], [False, True]),
    ],
)
def test_write_output_shapes_and_converts_data(channel_type, count, values, expected):
    calls = []
    task = SimpleNamespace(
        number_of_channels=count,
        channels=SimpleNamespace(chan_type=SimpleNamespace(name=channel_type)),
        write=lambda data, *, auto_start: calls.append((data, auto_start)),
    )

    NidaqmxRuntime.write_output(task, np.asarray(values))

    assert calls == [(expected, False)]


def test_simple_task_operations_and_read_shape_normalisation():
    calls = []
    task = SimpleNamespace(
        channel_names=["first", 2],
        start=lambda: calls.append("start"),
        read=lambda **kwargs: calls.append(kwargs) or [1.0, 2.0],
        wait_until_done=lambda timeout: calls.append(("wait", timeout)),
        stop=lambda: calls.append("stop"),
        close=lambda: calls.append("close"),
    )

    assert NidaqmxRuntime.channel_names(task) == ("first", "2")
    NidaqmxRuntime.start(task)
    values = NidaqmxRuntime.read(task, 2, 0.75)
    NidaqmxRuntime.wait_until_done(task, 1.25)
    NidaqmxRuntime.stop(task)
    NidaqmxRuntime.close(task)

    np.testing.assert_array_equal(values, [[1.0, 2.0]])
    assert calls == [
        "start",
        {"number_of_samples_per_channel": 2, "timeout": 0.75},
        ("wait", 1.25),
        "stop",
        "close",
    ]


def test_stop_tolerates_already_cleared_task():
    def fail_stop():
        raise RuntimeError("already cleared")

    NidaqmxRuntime.stop(SimpleNamespace(stop=fail_stop))


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
