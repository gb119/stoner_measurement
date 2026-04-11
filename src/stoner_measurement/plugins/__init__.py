"""Plugins package for stoner_measurement.

This package provides the abstract base class hierarchy for all measurement
plugins, along with built-in demonstration plugins.

The plugin classes are organised into type-specific sub-packages:

* :mod:`stoner_measurement.plugins.trace` — collects (x, y) data traces from
  instruments (:class:`~stoner_measurement.plugins.trace.base.TracePlugin`).
* :mod:`stoner_measurement.plugins.state_control` — controls experimental state
  (field, temperature, motor position, etc.)
  (:class:`~stoner_measurement.plugins.state_control.base.StateControlPlugin`).
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
  :class:`~stoner_measurement.plugins.command.plot_trace.PlotTraceCommand`).

Built-in example plugins:

* :class:`~stoner_measurement.plugins.trace.dummy.DummyPlugin` — hardware-free
  RSJ I-V model (in :mod:`stoner_measurement.plugins.trace`).
* :class:`~stoner_measurement.plugins.state_control.counter.CounterPlugin` —
  hardware-free counter (in :mod:`stoner_measurement.plugins.state_control`).
"""

from stoner_measurement.plugins.base_plugin import BasePlugin
from stoner_measurement.plugins.command import CommandPlugin, PlotTraceCommand, SaveCommand
from stoner_measurement.plugins.monitor import MonitorPlugin
from stoner_measurement.plugins.sequence import SequencePlugin, TopLevelSequence
from stoner_measurement.plugins.state_control import StateControlPlugin
from stoner_measurement.plugins.trace import TraceData, TracePlugin
from stoner_measurement.plugins.transform import TransformPlugin

__all__ = [
    "BasePlugin",
    "CommandPlugin",
    "MonitorPlugin",
    "PlotTraceCommand",
    "SaveCommand",
    "SequencePlugin",
    "StateControlPlugin",
    "TopLevelSequence",
    "TraceData",
    "TracePlugin",
    "TransformPlugin",
]

