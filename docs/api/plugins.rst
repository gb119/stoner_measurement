Plugin modules
==============

.. automodule:: stoner_measurement.plugins.base_plugin
   :members:
   :undoc-members:
   :show-inheritance:

Sequence sub-package
--------------------

.. automodule:: stoner_measurement.plugins.sequence
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: stoner_measurement.plugins.sequence.base
   :members:
   :undoc-members:
   :show-inheritance:

Trace sub-package
-----------------

.. automodule:: stoner_measurement.plugins.trace
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: stoner_measurement.plugins.trace.base
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: stoner_measurement.plugins.trace.dummy
   :members:
   :undoc-members:
   :show-inheritance:

State-control sub-package
--------------------------

.. automodule:: stoner_measurement.plugins.state_control
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: stoner_measurement.plugins.state_control.base
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: stoner_measurement.plugins.state_control.counter
   :members:
   :undoc-members:
   :show-inheritance:

Monitor sub-package
-------------------

.. automodule:: stoner_measurement.plugins.monitor
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: stoner_measurement.plugins.monitor.base
   :members:
   :undoc-members:
   :show-inheritance:

Transform sub-package
---------------------

.. automodule:: stoner_measurement.plugins.transform
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: stoner_measurement.plugins.transform.base
   :members:
   :undoc-members:
   :show-inheritance:

Command sub-package
-------------------

.. automodule:: stoner_measurement.plugins.command
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: stoner_measurement.plugins.command.base
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: stoner_measurement.plugins.command.save
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: stoner_measurement.plugins.command.plot_trace
   :members:
   :undoc-members:
   :show-inheritance:

Plugin type overview
--------------------

The plugin hierarchy consists of one abstract root class and five specialised
sub-types:

* :class:`~stoner_measurement.plugins.base_plugin.BasePlugin` — abstract root
  shared by all plugins.  Provides :attr:`~stoner_measurement.plugins.base_plugin.BasePlugin.name`,
  :attr:`~stoner_measurement.plugins.base_plugin.BasePlugin.instance_name`,
  :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.config_tabs`,
  :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.monitor_widget`, and
  :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.generate_action_code`.
* :class:`~stoner_measurement.plugins.trace.TracePlugin` — acquires ``(x, y)``
  data traces from instruments.
* :class:`~stoner_measurement.plugins.state_control.StateControlPlugin` —
  controls experimental state (field, temperature, motor position, etc.) and
  acts as a scan loop over a
  :class:`~stoner_measurement.scan.BaseScanGenerator`.  Inherits from
  :class:`~stoner_measurement.plugins.sequence.base.SequencePlugin` so that
  other steps can be nested beneath it in the sequence tree.
* :class:`~stoner_measurement.plugins.monitor.MonitorPlugin` — passively
  records auxiliary quantities (temperature, pressure, etc.) by polling
  hardware at a configurable interval.
* :class:`~stoner_measurement.plugins.transform.TransformPlugin` — performs
  pure-computation transforms or reductions on collected data without accessing
  hardware.
* :class:`~stoner_measurement.plugins.sequence.base.SequencePlugin` —
  abstract base for any plugin that acts as a container in the sequence tree.
  :class:`~stoner_measurement.plugins.state_control.StateControlPlugin`
  inherits from this class.

Generated sequence code structure
----------------------------------

The sequence engine's
:meth:`~stoner_measurement.core.sequence_engine.SequenceEngine.generate_sequence_code`
method produces a three-phase script:

1. **Connect phase** — :meth:`connect` is called on every unique plugin
   instance in the tree, in depth-first order.
2. **Configure phase** — :meth:`configure` is called on every unique plugin
   instance in the same order.
3. **Action phase** — each step's action code is rendered inside a single
   ``try`` block; a ``finally`` clause calls :meth:`disconnect` on every
   plugin in reverse order to ensure resources are always released.

For a single :class:`~stoner_measurement.plugins.trace.TracePlugin` named
``instrument`` the generated script looks like:

.. code-block:: python

    # Sequence script — auto-generated from sequence tree.
    # Edit as needed, then click Run.

    # Connect and initialise all plugins.
    instrument.connect()

    # Configure all plugins.
    instrument.configure()

    try:
        data = instrument.measure({})
        for channel, x, y in data:
            print(f"{channel}: x={x:.4g}, y={y:.4g}")
    finally:
        instrument.disconnect()

For a :class:`~stoner_measurement.plugins.state_control.StateControlPlugin`
named ``field`` containing a nested
:class:`~stoner_measurement.plugins.trace.TracePlugin` named ``instrument``,
the generated script looks like:

.. code-block:: python

    # Sequence script — auto-generated from sequence tree.
    # Edit as needed, then click Run.

    # Connect and initialise all plugins.
    field.connect()
    instrument.connect()

    # Configure all plugins.
    field.configure()
    instrument.configure()

    try:
        for _setpoint in field.scan_generator.generate():
            field.ramp_to(float(_setpoint))
            print(f"Field: {field.get_state():.4g} T")
            data = instrument.measure({})
            for channel, x, y in data:
                print(f"{channel}: x={x:.4g}, y={y:.4g}")
    finally:
        instrument.disconnect()
        field.disconnect()

TracePlugin lifecycle
---------------------

All :class:`~stoner_measurement.plugins.trace.TracePlugin` subclasses share a
four-step lifecycle:

1. **connect()** — open instrument connections and verify the instrument
   identity.
2. **configure()** — push plugin settings to the instrument.
3. **measure(parameters)** — trigger and collect the complete multipoint trace,
   returning a dict mapping channel names to
   :class:`~stoner_measurement.plugins.trace.TraceData` objects.  The default
   implementation delegates to
   :meth:`~stoner_measurement.plugins.trace.TracePlugin.execute_multichannel`
   (and thence to
   :meth:`~stoner_measurement.plugins.trace.TracePlugin.execute`).
4. **disconnect()** — cleanly release all reserved resources.

Status during these operations is reported via the
:attr:`~stoner_measurement.plugins.trace.TracePlugin.status` property (a
:class:`~stoner_measurement.plugins.trace.TraceStatus` value) and the
:attr:`~stoner_measurement.plugins.trace.TracePlugin.status_changed` signal.

Plotting acquired trace data is the responsibility of
:class:`~stoner_measurement.plugins.command.PlotTraceCommand`; add it as a
command step in the sequence immediately after a trace step.

Implementing a trace plugin
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Subclass :class:`~stoner_measurement.plugins.trace.TracePlugin` and implement:

* :attr:`~stoner_measurement.plugins.base_plugin.BasePlugin.name` — unique
  string identifier.
* :meth:`~stoner_measurement.plugins.trace.TracePlugin.execute` — generator
  that yields ``(x, y)`` pairs for each measured point.  The active
  :attr:`~stoner_measurement.plugins.trace.TracePlugin.scan_generator` provides
  the x-values.

Optionally override:

* :meth:`~stoner_measurement.plugins.trace.TracePlugin.connect` — open hardware
  connections.
* :meth:`~stoner_measurement.plugins.trace.TracePlugin.configure` — push
  settings to the instrument.
* :meth:`~stoner_measurement.plugins.trace.TracePlugin.disconnect` — close
  hardware connections.
* :meth:`~stoner_measurement.plugins.trace.TracePlugin.execute_multichannel` —
  yield ``(channel, x, y)`` triples when the plugin supports simultaneous
  multi-channel acquisition.
* :meth:`~stoner_measurement.plugins.trace.TracePlugin._plugin_config_tabs` —
  return a :class:`~PyQt6.QtWidgets.QWidget` for the *Settings* configuration
  tab.
* :meth:`~stoner_measurement.plugins.trace.TracePlugin._about_html` — return an
  HTML string for the *About* tab; omit the tab by returning ``None``
  (the default).

The configuration panel automatically shows three tabs for each
:class:`~stoner_measurement.plugins.trace.TracePlugin`:

1. **{name} – Scan** — instance-name editor, optional scan-generator type
   selector, and the active generator's own configuration widget.
2. **{name} – Settings** — populated by
   :meth:`~stoner_measurement.plugins.trace.TracePlugin._plugin_config_tabs`;
   a blank widget is shown if the method returns ``None``.
3. **{name} – About** *(optional)* — shown only when
   :meth:`~stoner_measurement.plugins.trace.TracePlugin._about_html` returns a
   non-``None`` HTML string.

StateControlPlugin lifecycle
-----------------------------

A :class:`~stoner_measurement.plugins.state_control.StateControlPlugin`
commands hardware to move to a series of set-points defined by a
:class:`~stoner_measurement.scan.BaseScanGenerator`.  Its lifecycle is:

1. **connect()** — open instrument connections.
2. **configure()** — push settings to the instrument.
3. **For each set-point** in :attr:`~stoner_measurement.plugins.state_control.StateControlPlugin.scan_generator`:

   a. :meth:`~stoner_measurement.plugins.state_control.StateControlPlugin.ramp_to`
      — command the hardware to the set-point and block until settled (or a
      timeout is exceeded).
   b. Execute all nested sub-steps (other plugins nested beneath this node in
      the sequence tree).

4. **disconnect()** — release instrument resources (always called, even after
   an error).

Because :class:`~stoner_measurement.plugins.state_control.StateControlPlugin`
inherits from
:class:`~stoner_measurement.plugins.sequence.base.SequencePlugin`, it can
act as a branch node in the sequence tree and hold nested sub-steps.

Implementing a state-control plugin
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Subclass
:class:`~stoner_measurement.plugins.state_control.StateControlPlugin` and
implement:

* :attr:`~stoner_measurement.plugins.base_plugin.BasePlugin.name` — unique
  string identifier.
* :attr:`~stoner_measurement.plugins.state_control.StateControlPlugin.state_name`
  — human-readable name of the controlled quantity (e.g. ``"Magnetic Field"``).
* :attr:`~stoner_measurement.plugins.state_control.StateControlPlugin.units`
  — physical unit string (e.g. ``"T"``, ``"K"``, ``"V"``).
* :meth:`~stoner_measurement.plugins.state_control.StateControlPlugin.set_state`
  — command the hardware to move towards the supplied value.
* :meth:`~stoner_measurement.plugins.state_control.StateControlPlugin.get_state`
  — return the current measured value of the controlled quantity.
* :meth:`~stoner_measurement.plugins.state_control.StateControlPlugin.is_at_target`
  — return ``True`` when the hardware has settled at the commanded target.

Optionally override:

* :meth:`~stoner_measurement.plugins.state_control.StateControlPlugin.connect`
  — open hardware connections.
* :meth:`~stoner_measurement.plugins.state_control.StateControlPlugin.configure`
  — push settings to the instrument.
* :meth:`~stoner_measurement.plugins.state_control.StateControlPlugin.disconnect`
  — close hardware connections.
* :attr:`~stoner_measurement.plugins.state_control.StateControlPlugin.limits`
  — ``(min, max)`` tuple restricting the allowed set-point range; defaults to
  ``(-inf, inf)``.
* :attr:`~stoner_measurement.plugins.state_control.StateControlPlugin.settle_timeout`
  — maximum seconds to wait for the state to settle; defaults to ``60.0``.
* :meth:`~stoner_measurement.plugins.state_control.StateControlPlugin._plugin_config_tabs`
  — return a :class:`~PyQt6.QtWidgets.QWidget` for the *Settings* tab.
* :meth:`~stoner_measurement.plugins.state_control.StateControlPlugin._about_html`
  — return an HTML string for the *About* tab.

The configuration panel automatically shows up to three tabs:

1. **{name} – Scan** — instance-name editor, optional scan-generator type
   selector, and the active generator's configuration widget.
2. **{name} – Settings** — populated by ``_plugin_config_tabs()``.
3. **{name} – About** *(optional)* — shown when ``_about_html()`` returns a
   non-``None`` string.

MonitorPlugin lifecycle
------------------------

A :class:`~stoner_measurement.plugins.monitor.MonitorPlugin` passively records
auxiliary quantities by polling hardware at a configurable interval.

* **read()** — perform a single synchronous hardware read and return a
  ``{quantity_name: value}`` dict.
* **start_monitoring(interval_ms)** — start the internal
  :class:`~PyQt6.QtCore.QTimer`; calls :meth:`read` every *interval_ms*
  milliseconds (default: :attr:`~stoner_measurement.plugins.monitor.MonitorPlugin.monitor_interval`,
  which defaults to 1000 ms).
* **stop_monitoring()** — stop the polling timer.
* :attr:`~stoner_measurement.plugins.monitor.MonitorPlugin.last_reading` — the
  cached result of the most recent successful :meth:`read` call.

Signals emitted by the polling loop:

* :attr:`~stoner_measurement.plugins.monitor.MonitorPlugin.data_available` —
  emitted with the reading dict after each successful poll.
* :attr:`~stoner_measurement.plugins.monitor.MonitorPlugin.read_error` —
  emitted with a descriptive message if :meth:`read` raises an exception.

Implementing a monitor plugin
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Subclass :class:`~stoner_measurement.plugins.monitor.MonitorPlugin` and
implement:

* :attr:`~stoner_measurement.plugins.base_plugin.BasePlugin.name` — unique
  string identifier.
* :attr:`~stoner_measurement.plugins.monitor.MonitorPlugin.quantity_names` —
  ordered list of quantity identifiers returned by :meth:`read`.
* :attr:`~stoner_measurement.plugins.monitor.MonitorPlugin.units` — mapping of
  quantity name to unit string.
* :meth:`~stoner_measurement.plugins.monitor.MonitorPlugin.read` — perform a
  single synchronous hardware read and return a ``{quantity: value}`` dict.

Optionally override:

* :attr:`~stoner_measurement.plugins.monitor.MonitorPlugin.monitor_interval` —
  default polling interval in milliseconds.

TransformPlugin lifecycle
--------------------------

A :class:`~stoner_measurement.plugins.transform.TransformPlugin` accepts a
dictionary of named input arrays/scalars, validates that all required keys are
present, and returns a dictionary of output arrays/scalars.  It performs pure
computation and does not access hardware.

* **run(data)** — validate *data* (raising :exc:`ValueError` on missing keys),
  call :meth:`~stoner_measurement.plugins.transform.TransformPlugin.transform`,
  emit :attr:`~stoner_measurement.plugins.transform.TransformPlugin.transform_complete`,
  and return the result dict.  This is the preferred entry point.
* **transform(data)** — implement the actual computation.

Implementing a transform plugin
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Subclass :class:`~stoner_measurement.plugins.transform.TransformPlugin` and
implement:

* :attr:`~stoner_measurement.plugins.base_plugin.BasePlugin.name` — unique
  string identifier.
* :attr:`~stoner_measurement.plugins.transform.TransformPlugin.required_inputs`
  — ordered list of required input key names.
* :attr:`~stoner_measurement.plugins.transform.TransformPlugin.output_names` —
  ordered list of output key names.
* :meth:`~stoner_measurement.plugins.transform.TransformPlugin.transform` —
  perform the computation and return the result dict.

Optionally override:

* :attr:`~stoner_measurement.plugins.transform.TransformPlugin.description` —
  human-readable summary of the computation.

SequencePlugin
--------------

:class:`~stoner_measurement.plugins.sequence.base.SequencePlugin` is an
abstract base class for any plugin that acts as a container (branch node) in
the sequence tree.  Concrete subclasses must implement
:attr:`~stoner_measurement.plugins.base_plugin.BasePlugin.name` (inherited from
:class:`~stoner_measurement.plugins.base_plugin.BasePlugin`) and
:meth:`~stoner_measurement.plugins.sequence.base.SequencePlugin.execute_sequence`.

:class:`~stoner_measurement.plugins.sequence.base.TopLevelSequence` is the
concrete root container for the entire measurement sequence.  It transparently
passes through all nested sub-steps without any additional action.

:class:`~stoner_measurement.plugins.state_control.StateControlPlugin` inherits
from :class:`~stoner_measurement.plugins.sequence.base.SequencePlugin` to
gain sub-sequence container behaviour while retaining its full instrument
lifecycle API.
