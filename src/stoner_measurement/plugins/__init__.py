"""Plugins package for stoner_measurement.

This package provides the abstract base class hierarchy for all measurement
plugins, along with a built-in demonstration plugin.

The following specialised sub-types are available:

* :class:`~stoner_measurement.plugins.trace.TracePlugin` — collects (x, y)
  data traces from instruments.
* :class:`~stoner_measurement.plugins.state_control.StateControlPlugin` —
  controls experimental state (field, temperature, motor position, etc.).
* :class:`~stoner_measurement.plugins.monitor.MonitorPlugin` — passively
  records auxiliary quantities at regular intervals.
* :class:`~stoner_measurement.plugins.transform.TransformPlugin` — performs
  pure-computation transforms or reductions on collected data.
* :class:`~stoner_measurement.plugins.sequence_plugin.SequencePlugin` —
  abstract mixin for plugins that may contain nested sub-steps in the
  sequence tree.
* :class:`~stoner_measurement.plugins.sequence_plugin.TopLevelSequence` —
  concrete root container for the entire measurement sequence.
"""

from stoner_measurement.plugins.base_plugin import BasePlugin
from stoner_measurement.plugins.monitor import MonitorPlugin
from stoner_measurement.plugins.sequence_plugin import SequencePlugin, TopLevelSequence
from stoner_measurement.plugins.state_control import StateControlPlugin
from stoner_measurement.plugins.trace import TracePlugin
from stoner_measurement.plugins.transform import TransformPlugin

__all__ = [
    "BasePlugin",
    "MonitorPlugin",
    "SequencePlugin",
    "StateControlPlugin",
    "TopLevelSequence",
    "TracePlugin",
    "TransformPlugin",
]
