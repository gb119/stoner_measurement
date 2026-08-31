"""Unit tests for the lazy NI-DAQmx runtime trigger boundary."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from stoner_measurement.plugins.trace.daqmx_runtime import NidaqmxRuntime
from stoner_measurement.ui.widgets import (
    DaqmxInputTrigger,
    DaqmxInputTriggerMode,
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
    )
    return runtime


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


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
