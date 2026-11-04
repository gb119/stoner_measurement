Console and script reference
=============================

This reference is for experienced users inspecting results or developing Python
measurement scripts. The console on **Script Editor** shares the sequence
engine's live namespace. Examples below assume the named steps are present;
use the downloadable sequences in :doc:`usage` and :doc:`data_workflows`.
For implementing an external plugin, follow :doc:`third_party_plugins`.

Inspecting the active sequence
-------------------------------

The application exposes a live ``sequence`` view, not a snapshot:

.. code-block:: python

   sequence.steps              # nested plugin/(plugin, children) descriptors
   sequence.top_level_plugins  # root instances only
   sequence.plugins            # instances at every depth, in tree order
   [(p.instance_name, p.name) for p in sequence.plugins]

Instances are also bound by their names, for example ``iv_trace`` or
``curve_fit``. The first step may be Details or a command; do not assume
``sequence.plugins[0]`` is an instrument or has a scan generator.

Runtime names and expressions
------------------------------

The namespace contains ``np``/``numpy``, exported NumPy functions, ``log``,
plugin instance variables and the ``_traces``/``_values`` catalogues. A
catalogue maps a selectable identity to an expression rather than containing
the measurement itself. The ``sequence`` view is provided by the application;
a standalone SequenceEngine does not automatically have an editor tree.

.. code-block:: python

   _traces
   _values
   iv_trace.data['Dummy'].df.head()
   iv_trace.log.info("Inspecting the current trace")

Use actual instance names from the active sequence. A result is available only
after its producing step has completed, and a failed measurement/fit may expose
empty data or NaNs. Plot tables and scalar outputs are described in
:doc:`trace_data`.

Editing settings and refreshing controls
-----------------------------------------

Make configuration edits while execution is idle. A direct attribute edit can
affect the next execution without immediately rebuilding its cached widgets.
Use ``plugin.refresh()`` after edits, ``plugin.full_refresh()`` for that
container and its descendants, or ``sequence.full_refresh()`` for the tree.
These refreshes synchronise configuration UI; they do not acquire new data.

For the Function Scan Generator in the basic I-V example:

.. code-block:: python

   iv_trace.scan.amplitude = "5e-6"
   iv_trace.scan.num_points = 201
   iv_trace.refresh()

``scan`` is an alias for ``scan_generator`` only when the plugin has one.
Generator properties differ: a function generator has waveform parameters,
a list generator has ``stages``, and a stepped generator has its own stage
definition. Inspect the actual generator rather than assigning generic
``start``/``end`` fields to every type. For the Counter list in the workflow:

.. code-block:: python

   scan.scan.stages = [(0.0, True), (1.0, True), (2.0, True)]
   scan.refresh()

A state sweep uses ``sweep_generator`` instead. Preserve the boolean measurement
flag when editing stages. If settings change reported output names, refresh
data catalogues through the attached engine as described in
:doc:`third_party_plugins`.

Running code and lifecycle readiness
-------------------------------------

Console method calls are real actions on shared objects. They can move hardware
or write files. For a repeatable check with normal setup and cleanup, use
**Run Selection…**; for a modified full script, use **Generate Code** and run
the edited script on Script Editor. See :doc:`sequence_execution`.

After generated cleanup, a lifecycle-managed instance is no longer ready for
arbitrary action calls. Reconnecting begins a new session and may reset
per-run state. In particular, finish an incremental Save before cleanup if it
must retain the original destination; see :doc:`data_workflows`.

Selecting a plot display
-------------------------

The application injects a display-selection helper:

.. code-block:: python

   select_display_plugin('polar')

Selecting the current display preserves it. A different selection is dispatched
to the GUI and can clear incompatible plotted state; acquired tables remain
available. An unavailable requested display raises an error. Generated scripts
use this helper before plugin setup to select the sequence's preferred display.
Use :doc:`plot_displays` for coordinate forms and user controls, and
:doc:`plotting_contracts` for direct producer requests.

.. _temperature-console:

Temperature controller scripting
---------------------------------

The shared controller service is separate from the sequence engine. Obtain it
explicitly; ``engine`` is not an automatically injected controller variable:

.. code-block:: python

   from stoner_measurement.temperature_control.engine import TemperatureControllerEngine
   from stoner_measurement.temperature_control import LoopRef, ChannelRef

   temperature = TemperatureControllerEngine.instance()
   temperature.set_setpoint(1, 300.0)  # primary controller, native loop 1
   temperature.set_setpoint(LoopRef('secondary', 1), 275.0)
   temperature.set_input_channel(
       LoopRef('secondary', 1), ChannelRef('secondary', 'B')
   )
   state = temperature.get_engine_state()
   state.all_readings[ChannelRef('secondary', 'A')].value
   state.loop_values('setpoints')[LoopRef('secondary', 1)]

These examples require the corresponding connected controllers and supported
channels. ``temperature.controller('secondary')`` exposes controller-local
settings. Legacy integer-keyed state dictionaries and ``state.readings`` remain
primary views; ``state.secondary`` contains the secondary snapshot.
``cache_ages`` and ``controller_statuses`` distinguish freshness and status.

For a Set Temperature step and a temperature-monitor instance:

.. code-block:: python

   set_temperature.controller_id = 'secondary'
   set_temperature.control_loop = 1
   set_temperature.setpoint_expr = '275'
   temperature_monitor.temperature({'controller_id': 'secondary', 'channel': 'A'})

Use the actual step names and refresh their UI after edits. Do not close the
shared service as cleanup for a plugin that merely borrows it. The connection,
stability and migration controls are covered in :doc:`temperature_controllers`.
