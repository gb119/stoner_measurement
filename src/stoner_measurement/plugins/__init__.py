"""Plugins package for stoner_measurement.

This package provides the abstract base class hierarchy for all measurement
plugins, along with built-in demonstration plugins.

The plugin classes are organised into type-specific sub-packages:

* :mod:`stoner_measurement.plugins.trace` — collects (x, y) data traces from
  instruments (:class:`~stoner_measurement.plugins.trace.base.TracePlugin`).
* :mod:`stoner_measurement.plugins.state` — shared abstract ancestor for both
  state-scan and state-sweep plugin families
  (:class:`~stoner_measurement.plugins.state.base.StatePlugin`).
* :mod:`stoner_measurement.plugins.state_scan` — controls experimental state
  (field, temperature, motor position, etc.) via discrete-step scanning
  (:class:`~stoner_measurement.plugins.state_scan.base.StateScanPlugin`).
* :mod:`stoner_measurement.plugins.state_sweep` — executes sub-sequences in a
  generator-driven sweep loop
  (:class:`~stoner_measurement.plugins.state_sweep.base.StateSweepPlugin`).
* :mod:`stoner_measurement.plugins.monitor` — passively records auxiliary
  quantities at regular intervals
  (:class:`~stoner_measurement.plugins.monitor.base.MonitorPlugin`).
* :mod:`stoner_measurement.plugins.transform` — performs pure-computation
  transforms or reductions on collected data
  (:class:`~stoner_measurement.plugins.transform.base.TransformPlugin`).
* :mod:`stoner_measurement.plugins.sequence` — abstract mixin for plugins that
  may contain nested sub-steps in the sequence tree
  (:class:`~stoner_measurement.plugins.sequence.base.SequencePlugin`,
  :class:`~stoner_measurement.plugins.sequence.base.TopLevelSequence`).
* :mod:`stoner_measurement.plugins.command` — executes a single action in the
  sequence without instrument lifecycle steps
  (:class:`~stoner_measurement.plugins.command.base.CommandPlugin`,
  :class:`~stoner_measurement.plugins.command.save.SaveCommand`,
  :class:`~stoner_measurement.plugins.command.plot_trace.PlotTraceCommand`,
  :class:`~stoner_measurement.plugins.command.details.DetailsCommand`).

Built-in example plugins:

* :class:`~stoner_measurement.plugins.trace.dummy.DummyPlugin` — hardware-free
  RSJ I-V model (in :mod:`stoner_measurement.plugins.trace`).
* :class:`~stoner_measurement.plugins.state_scan.counter.CounterPlugin` —
  hardware-free counter (in :mod:`stoner_measurement.plugins.state_scan`).

Legacy aliases:

* :class:`~stoner_measurement.plugins.state_control.StateControlPlugin` —
  alias for :class:`~stoner_measurement.plugins.state_scan.StateScanPlugin`
  (in :mod:`stoner_measurement.plugins.state_control`).
"""

from stoner_measurement.plugins.base_plugin import BasePlugin
from stoner_measurement.plugins.command import (
    CommandPlugin,
    DetailsCommand,
    PlotTraceCommand,
    SaveCommand,
)
from stoner_measurement.plugins.monitor import MonitorPlugin
from stoner_measurement.plugins.sequence import SequencePlugin, TopLevelSequence
from stoner_measurement.plugins.state import StatePlugin
from stoner_measurement.plugins.state_control import StateControlPlugin
from stoner_measurement.plugins.state_scan import CounterPlugin, StateScanPlugin
from stoner_measurement.plugins.state_sweep import StateSweepPlugin, SweepTimePlugin
from stoner_measurement.plugins.trace import TraceData, TracePlugin
from stoner_measurement.plugins.transform import TransformPlugin

__all__ = [
    "BasePlugin",
    "CommandPlugin",
    "CounterPlugin",
    "DetailsCommand",
    "MonitorPlugin",
    "PlotTraceCommand",
    "SaveCommand",
    "SequencePlugin",
    "StateControlPlugin",
    "StatePlugin",
    "StateScanPlugin",
    "StateSweepPlugin",
    "SweepTimePlugin",
    "TopLevelSequence",
    "TraceData",
    "TracePlugin",
    "TransformPlugin",
]
