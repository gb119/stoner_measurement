Writing sequence plugins
=========================

This is the implementation contract for an external Python package that adds
measurement steps to Stoner Measurement. It covers discovery, execution,
resource ownership, published data, configuration widgets and persistence.
It is also a checklist for coding assistants implementing those integrations.
Use :doc:`usage` and :doc:`data_workflows` for operating existing plugins.

Sequence plugins inherit ``BasePlugin``. Plot display factories have a
separate entry-point group and contract: see :doc:`plot_display_plugins` and
:doc:`plotting_contracts`. Instrument drivers implement device protocols;
sequence plugins orchestrate them or borrow application controller services.

.. contents:: On this page
   :local:
   :depth: 2

Discovery and identity
-----------------------

Install the external package into the same Python environment as the
application. Register no-argument plugin classes in your package's
``pyproject.toml``:

.. code-block:: toml

   [project.entry-points."stoner_measurement.plugins"]
   my_lab_record_value = "my_measurement_extras.record_value:RecordValueCommand"

``PluginManager.discover()`` loads each entry point and constructs its class.
The sequence editor creates separate instances for individual steps. Therefore:

* Modules and constructors must be inexpensive and work without connected
  hardware. Create widgets in UI hooks and open devices in lifecycle hooks.
* Accept ``parent=None`` and call ``super().__init__(parent)`` when the chosen
  base class supports Qt ownership.
* Use a distinctive entry-point name. Duplicate registry names can replace
  each other; discovery is not a collision-resolution service.
* Implement ``name`` as a human-readable plugin-type label. Use
  ``instance_name`` for the identity of a particular step and its namespace
  variable. Let the shared setter/editor validate identifiers and reserved
  names; do not assign the private backing attribute.
* Keep public module/class paths importable across releases. Saved sequences
  contain those paths, independently of the entry-point name.

Restart the application after installing or changing entry-point metadata.
Editable installs expose source edits, but an already running process retains
its imported classes. Discovery failures are logged and isolated from other
entry points.

Choose the execution contract
-------------------------------

Use the narrowest suitable base. These are the current interfaces, not the
older generator-based trace API or the compatibility ``state_control`` alias.

.. list-table:: Plugin families
   :header-rows: 1
   :widths: 25 40 35

   * - Import
     - Implement
     - Execution responsibility
   * - ``plugins.command.CommandPlugin``
     - ``name`` and ``execute()``
     - One action. Generated code calls ``instance()``; its callable delegates
       to ``execute()``. Lifecycle is off by default, but resource-owning
       commands can override ``has_lifecycle``.
   * - ``plugins.trace.TracePlugin``
     - ``name`` and ``_measure(parameters)``
     - Acquire complete trace tables. The public ``measure()`` wrapper owns
       status, result storage and optional channel statistics.
   * - ``plugins.state_scan.StateScanPlugin``
     - ``name``, ``state_name``, ``units``, ``set_state(value)``,
       ``get_state()`` and ``is_at_target()``
     - Move through discrete points and execute nested steps at those points.
   * - ``plugins.state_sweep.StateSweepPlugin``
     - ``name``, ``state_name`` and ``units``; override the relevant hardware
       hooks ``set_state``, ``get_state``, ``set_target``, ``set_rate`` and
       ``is_at_target``
     - Integrate a sweep generator with actual state/rate control. Default
       hardware hooks are no-ops and do not drive an instrument.
   * - ``plugins.monitor.MonitorPlugin``
     - ``name``, ``quantity_names``, ``units`` and ``read()``
     - Return a mapping of quantity names to scalar readings. ``units`` maps
       those names to unit strings. Use the base monitoring machinery.
   * - ``plugins.transform.TransformPlugin``
     - ``name``, ``required_inputs``, ``declared_outputs()`` and ``transform(data)``
     - Compute named outputs from existing data. The public ``run(data)``
       wrapper validates required inputs and stores results.
   * - ``plugins.sequence.SequencePlugin``
     - ``name`` and ``execute_sequence(sub_steps)``; define appropriate
       ``generate_action_code`` when execution changes child control flow
     - Own orchestration, not the sequence editor. Direct execution and
       generated-script execution must agree.

All imports in the table are relative to ``stoner_measurement``. See the
corresponding classes in :doc:`api/plugins` for detailed signatures. Use
``state_scan`` in new code; ``StateControlPlugin`` remains a compatibility alias.
The :ref:`example package <minimal-sequence-plugin-package>` has a runnable
example for each family.

These execution hooks and output declarations have separate responsibilities.
``declared_outputs()`` describes identities and metadata; ``execute()``,
``measure()``, ``run()`` and ``read()`` obtain or compute results. Inherit a
family's default declarations when they already describe the plugin correctly,
otherwise override the unified hook. Do not introduce additional publication
methods for individual channels.

Lifecycle and resource ownership
---------------------------------

``has_lifecycle`` determines participation in generated connection,
configuration and cleanup phases. It is a resource/setup decision, not a
synonym for the plugin family: some leaf commands need a lifecycle.

``validate()``
   Return ``True`` or raise
   ``stoner_measurement.core.validation.ValidationError`` with an actionable
   message. Generated scripts validate all enabled steps, including nested
   steps, after construction and before any connection. The default passes.
   The application's script-generation action also validates the prepared
   step instances before replacing editor content. Validation errors appear
   in a dialog and the log; the current script is preserved. Engine clients
   can call ``validate_generated_sequence()`` after generating source to run
   these checks without executing the generated script.
   Check numeric literals and relationships only when all operands are
   literals. Never evaluate expressions, access hardware or mutate settings.
   Use ``validate_expression(expression, namespace, label=...)`` from the same
   module to check syntax and warn about unknown names without execution.
   Missing names are warnings because earlier runtime scripts may define them;
   syntax errors block execution. Runtime type and range checks remain required.
   The engine also calls a scan generator's optional
   ``validate(namespace, label=...)`` hook. List scans implement this hook.

``connect()``
   Open or borrow the resources needed by this instance. Repeated calls must
   release this instance's previous resources before replacing them. The base
   wrapper invokes ``disconnect()`` before a repeated or partially failed
   connection attempt. Calls through ``super().connect()`` belong to the same
   attempt. Do not duplicate that tracking or clear its private state.

``configure()``
   Apply this instance's settings. Evaluate runtime setup expressions here,
   rather than while constructing the plugin or its configuration widgets.
   Propagate failed setup so the instance is not considered ready.

``disconnect()``
   Be idempotent after both successful and partial connection. Release owned
   handles, return owned outputs to the appropriate safe state, and clear
   references. Propagate cleanup failures. Never close another instance's
   resources or a borrowed shared controller service.

Generated sequences reset per-run state with ``start()`` and check meaningful
setup phases at runtime. Disconnection and failed setup invalidate readiness.
The checks also apply inside conditional branches and loops; do not substitute
static reachability assumptions or bypass ``require_ready()``.

An instance may be configured again during execution. Reconfigure derives
``delay_configuration`` from its sequence selections: do not add an editor
for that flag or persist it independently. A plugin must tolerate deferred
setup and reconnect through the same lifecycle hooks. User instructions for
placing Reconfigure belong in :ref:`sequence-reconfiguration`.

Keep transport commands and protocol details in instrument drivers. Plugins
using the shared temperature, magnet, motor, pressure or X-ray engines borrow
their sessions. For temperature selections, preserve controller-qualified
``LoopRef``/``ChannelRef`` identities; a loop's input choices belong to its
own controller. See :doc:`temperature_controllers` for the user-visible model.

Namespace, expressions and logging
-----------------------------------

Use the attached ``sequence_engine`` and its public services. Access current
runtime state through ``self.engine_namespace``; it is an empty mapping while
detached. Do not retain a private copy of the engine namespace or inspect
sequence-tree widgets from execution code.

``engine.namespace`` and ``engine.namespace_snapshot()`` return copies for
inspection. Assigning a value to either snapshot does not define a runtime
variable. A plugin uses ``self.engine_namespace`` for live namespace access.

``self.eval(expression)`` and ``self.eval_float(expression)`` evaluate settings
against the live namespace. Keep expression text in configuration and evaluate
at the documented phase, so expressions can use the current loop value or an
upstream result. The namespace includes ``np``/``numpy``, exported NumPy names,
plugin instance variables, ``log``, and trace/value catalogue expressions.
The application also exposes a live ``sequence`` view; see :doc:`console_api`.

Use ``self.log`` for diagnostics. Let errors that prevent a valid action
propagate to the engine. When intentionally recovering, log the problem and
publish a defined invalid/empty result rather than leaving an earlier success
as though it were current. Do not catch ``KeyboardInterrupt`` or cancellation
indiscriminately. Bound hardware I/O and waits: stopping Python execution
cannot reliably interrupt an indefinitely blocked device call.

Built-in controller target commands, scans and sweeps abort on an error,
disconnection or shutdown snapshot instead of treating controller failure as
ordinary settling. Plugins implementing their own waits should apply
``core.controller_polling.raise_for_controller_failure`` before accepting a
target snapshot. Pass the selected temperature ``controller_id`` when using
the combined temperature service so that a failed peer does not mask the
selected controller's health. This status check cannot interrupt a native
driver call that has not returned; transports must also enforce I/O deadlines.

Sequence actions run on the engine worker. Create and update Qt widgets on the
GUI thread, using queued Qt signals or the application's service boundaries
for cross-thread requests. Import Qt through ``qtpy`` and signals through
``stoner_measurement.qt_compat``; do not force a particular Qt binding.

Publishing data for other steps
--------------------------------

The detailed reference is :doc:`plugin_outputs`, including all declaration
fields, schema timing, output ordering, inheritance rules and migration steps.

Implement ``declared_outputs()`` to describe trace identities, runtime access
expressions, configured channels and scalar units together. Return a fresh
``PluginOutputs`` containing two ordered mappings. Both mappings use the
existing fully qualified catalogue identifiers:

.. code-block:: python

   from stoner_measurement.plugins import (
       PluginOutputs, ScalarOutput, TraceOutput,
   )

   def declared_outputs(self):
       var = self.instance_name
       return PluginOutputs(
           traces={
               f"{var}:IV": TraceOutput(
                   f"{var}.data['IV']",
                   result_key="IV",
                   schema_factory=self._iv_schema,
               ),
           },
           values={
               f"{var}:Resistance": ScalarOutput(
                   f"{var}.resistance", units="Ω",
               ),
           },
       )

This example assumes the plugin produces ``data['IV']`` and a ``resistance``
attribute. Expressions are evaluated by consumers at runtime, not during
declaration. ``result_key`` identifies an entry in a plugin's result dictionary;
omit it for attribute access, monitor readings and calculated projections.
The trace and scalar mappings may independently use the same catalogue key.
Trace units belong to individual schema columns; scalar units live on each
``ScalarOutput``. Empty scalar units mean unspecified or dimensionless.

Common identities are ``instance:channel`` for acquired/transformed traces and
scalar quantities, and ``instance.data`` for a state scan/sweep's collected
table. Keep output keys stable for a configuration and ensure their expressions
resolve after execution. Do not infer local result keys by parsing identifiers.

Supply ``schema=empty_trace`` or a zero-argument ``schema_factory`` to advertise
complete channels before acquisition. Factories are resolved after the scalar
catalogue has been built, allowing collected scan/sweep tables to describe
selected scalar outputs. For example::

   def _iv_schema(self):
       frame = pd.DataFrame({
           "x": pd.Series(dtype=float),
           "V": pd.Series(dtype=float),
           "R": pd.Series(dtype=float),
       })
       return TraceData(
           frame,
           column_roles={"x": "x", "V": "y", "R": "z"},
           names={"x": "Current", "V": "Voltage", "R": "Resistance"},
           units={"x": "A", "V": "V", "R": "Ω"},
       )

This example assumes ``import pandas as pd`` and
``from stoner_measurement.core.trace_data import TraceData``. Declarations
must use configuration state without hardware access, runtime expression
evaluation or changes to acquired results. Include optional channels only
when enabled. Keep declarations consistent with acquisition metadata and
configured transpose. State scan and sweep bases supply the single collected
table automatically when collection is enabled.

Configuration selectors prefer these schemas to previous results, then fall
back to acquired metadata and finally configured x/y labels. Omit both schema
fields when the columns cannot yet be determined. Configured schemas must be
empty; consumers receive independent metadata snapshots. The
engine publishes the schemas separately as ``_trace_schemas``; ``_traces``
continues to contain runtime access expressions. Schemas are derived rather
than serialised.

Existing plugins remain supported through the legacy methods:

* ``reported_traces()`` returns trace identifiers mapped to access expressions.
* ``configured_trace_data()`` returns configured empty tables by trace identifier.
* ``reported_values()`` returns scalar identifiers mapped to access expressions.
* ``reported_value_units()`` returns scalar units by identifier.

For migrated plugins these methods are derived compatibility views. The trace
``trace_names`` property and transform ``output_names``, ``output_trace_names``
and ``output_value_names`` properties derive from declared result keys.
``PluginOutputs.result_order`` optionally preserves an interleaved result order.
New transforms need not implement the old naming properties.

``BasePlugin.declared_outputs()`` returns ``None`` to select legacy adaptation.
An explicitly empty ``PluginOutputs`` declares no outputs. More-specific legacy
subclass overrides, including calls to ``super().reported_*()``, remain effective.
When one class defines both a unified declaration and a legacy method, the
unified declaration takes precedence during catalogue resolution and a warning
identifies the conflict. Avoid mixing both declaration styles on the same class.
Old transform classification defaults remain unchanged for legacy plugins.

Extend a migrated parent's ``super().declared_outputs()`` and update its typed
mappings. Do not build declarations by calling their own compatibility views.
Catalogue consumers should use ``resolve_outputs(plugin)`` from
``stoner_measurement.core.plugin_outputs`` to apply the shared compatibility
rules, rather than combining hooks independently. The engine resolves each
plugin once per catalogue rebuild, then materialises schemas and emits updates.

The ``_traces`` and ``_values`` catalogues describe steps in the current
sequence, not all installed plugin templates. ``engine.traces_catalog`` and
``engine.values_catalog`` and their change-signal arguments are snapshots.
Use snapshots to populate controls and evaluate the selected expression when
an action needs current data.

If a setting changes reported outputs, configured channels or units, call
``self.sequence_engine.refresh_data_catalogs()`` when attached. Consumers
should use ``bind_trace_catalog_updates`` or ``bind_value_catalog_updates``
from ``stoner_measurement.plugins.trace_catalog_ui`` to scope updates to a
widget's lifetime. Preserve valid selections, handle empty catalogues, and
refresh when a producer changes or is removed. The base
``remap_trace_reference`` handles common trace-key/expression attributes;
override it, calling ``super()``, when storing additional trace references.

Trace and transform result shapes
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A trace plugin's ``_measure(parameters)`` returns
``dict[str, TraceData]`` with keys matching ``trace_names``. Acquire each
instrument once per requested acquisition. Do not update ``status``, ``data``
or channel statistics inside ``_measure``: ``measure`` handles those duties.

Each ``TraceData`` is one shared-row table with an ordinary integer DataFrame
index. Independent coordinates are columns carrying the ``x`` role; multiple
simultaneously acquired channels sharing that coordinate belong in columns of
one table. Return separate tables for genuinely different coordinates.
Preserve column roles, names and units through transforms. See
:doc:`trace_data` for constructors and the full data contract.

A transform's ``transform(data)`` returns a mapping with its declared output
names. Classify each stored output through a ``TraceOutput`` or ``ScalarOutput``
with its ``result_key``. Returning a table alone does not publish it as a trace.
Legacy plugins may still declare ``output_trace_names`` and
``output_value_names``. Use the base
``run`` path so input validation, result storage and completion signals remain
consistent. Trace selection can evaluate catalogue expressions inside a
transform with ``required_inputs=[]``; inputs declared there must instead be
supplied in the mapping passed to ``run``.

State scan/sweep bases already collect configured scalar outputs after their
child actions and publish their table as ``instance.data``. Reuse those hooks;
do not build a second collection table or assume a Save child sees the row
that will be collected after it. The execution-order example is in
:doc:`data_workflows`.

Direct ``execute_sequence()`` calls and generated state loops reset iteration
metadata, honour ``clear_on_start`` and ``clear_filter``, and collect after
successful child actions when collection is enabled. The measurement flag and
``collect_filter`` both control collection; children still run at every point.

Monitor subclasses continue to implement ``read()``. The base class wraps
overrides so direct reads, generated actions and timer polls all cache the
last successful result and emit ``data_available`` once. Implementations
should acquire and return readings without updating ``_last_reading`` or
emitting ``data_available`` themselves. Calling ``super().read()`` does not
publish an intermediate result. Failed reads retain the last successful cache
and propagate; timer polling also emits ``read_error``. ``last_reading``
returns a copy and does not query hardware.

After programmatic configuration edits, call ``refresh()`` to update the scan
generator, output catalogues and cached widgets. ``full_refresh()`` also
refreshes member plugins recursively. These operations do not perform
instrument setup or acquisition. Configuration controls that change only
published metadata can still call ``engine.refresh_data_catalogs()`` directly.

Configuration UI and persistence
---------------------------------

``config_widget(parent=None)`` supplies a settings page.
``config_tabs(parent=None)`` supplies ``(title, QWidget)`` pairs. Prefer the
chosen base's tab hooks and caching instead of replacing its identity,
scan/sweep/data, or help pages. When constructing a complete custom tab set,
use ``self._get_cached_config_tabs(builder)`` and preserve the inherited
settings/persistence behavior. See :doc:`plugin_tab_ordering`.

Widgets edit plugin attributes; execution reads those attributes, not a live
widget. Bind pending edits with the usual editing signals so committing
configuration before generation captures them. Tolerate detached instances
and empty data catalogues. Use the shared ``stoner_measurement.ui`` widgets:
``FontAwareTabWidget``/``FontAwareTabBar`` for tabs and ``SISpinBox`` for
physical quantities supporting units or SI prefixes. Keep pages top-packed,
with one bottom stretch and explicit bounds for expanding controls.

Override ``to_json()`` to extend ``super().to_json()`` with JSON-compatible
settings. Override ``_restore_from_json(data)`` to call its superclass and
restore those settings with compatible defaults for older files. The inherited
loader constructs the concrete class named in the saved data, restores
identity and settings, then reapplies machine-only configuration where defined.
Keep device handles, widgets, engine references, acquired arrays and derived
readiness/deferred-setup flags out of the configuration payload.

Round-trip expressions as strings, selected output identities and roles as
configuration, and generator settings through their existing serializers.
Use ``BasePlugin.from_json`` for reconstruction; overriding that loader is
rarely necessary. Renaming a public class/module requires a compatibility
import or migration for previously saved sequences.

``monitor_widget(parent=None)`` optionally exposes a monitoring panel. Its
widget follows GUI ownership rules; it must not acquire an unmanaged second
session or keep polling callbacks connected after destruction.

Generated execution and plotting
---------------------------------

The engine generates instantiation, startup setup, actions and final cleanup.
Usually inherit the action generator. If overriding
``generate_action_code(indent, sub_steps, render_sub_step)``, return Python
source lines with four spaces per indentation level, use the actual
``instance_name``, and render children through the supplied callback. Do not
duplicate whole-sequence setup/cleanup or assume neighbouring steps exist:
Run Selection can generate a script from only this subtree.

Overriding ``execute_sequence`` alone does not change the default transparent
``SequencePlugin`` action generator. A container that changes control flow
must implement generated actions with the same semantics as direct execution.
Use ``validate_sequence_position(sequence_steps)`` for genuine placement
constraints and ``is_loop_container`` for a container that generates a loop.

Plot producers submit portable requests through ``engine.plot_client`` and
negotiate capabilities. Keep renderer objects out of plugin execution code.
Use ``engine.wait_for_plot_ticket`` from workers when completion is required;
do not block the GUI on pending plot tickets. See :doc:`plotting_contracts`
for data ownership, cancellation, completion and surface assembly. The legacy
``engine.plot_widget`` facade is not a requirement for a new renderer.

.. _minimal-sequence-plugin-package:

A minimal package for all seven families
----------------------------------------

Each example runs without instruments. Create ``src/my_measurement_extras/``
with an empty ``__init__.py``. Copy the example files below into that
directory, saving ``record_value_plugin.py`` as ``record_value.py`` and keeping
the other filenames. Put this ``pyproject.toml`` in the package root. To
install only a subset, keep the corresponding entry-point lines and files.

.. code-block:: toml

   [build-system]
   requires = ["setuptools>=61"]
   build-backend = "setuptools.build_meta"

   [project]
   name = "my-measurement-extras"
   version = "0.1.0"
   requires-python = ">=3.12"
   dependencies = ["stoner_measurement", "numpy", "qtpy"]

   [tool.setuptools.packages.find]
   where = ["src"]

   [project.entry-points."stoner_measurement.plugins"]
   my_lab_record_value = "my_measurement_extras.record_value:RecordValueCommand"
   my_lab_demo_trace = "my_measurement_extras.demo_trace:DemoTracePlugin"
   my_lab_demo_scan = "my_measurement_extras.demo_scan:DemoScanPlugin"
   my_lab_demo_sweep = "my_measurement_extras.demo_sweep:DemoSweepPlugin"
   my_lab_demo_monitor = "my_measurement_extras.demo_monitor:DemoMonitorPlugin"
   my_lab_demo_mean = "my_measurement_extras.demo_transform:DemoTransformPlugin"
   my_lab_demo_group = "my_measurement_extras.demo_sequence:DemoSequencePlugin"

Declare the application-version range your package actually supports and test
against it. In the environment used to run the application, install with
``python -m pip install -e .``. For the repository's Conda environment this is
``conda run -n stoner_measurement python -m pip install -e .``.
Restart the application to discover the examples.

Command
~~~~~~~

:download:`Record Value <examples/record_value_plugin.py>` evaluates an
expression once per execution, logs the result and publishes a scalar with
configurable units. The **General** tab edits the expression and units, and
both settings survive saving and reopening the sequence.

.. literalinclude:: examples/record_value_plugin.py
   :language: python

Trace
~~~~~

:download:`Demo Trace <examples/demo_trace.py>` returns three fixed samples as
one ``TraceData`` table. The configured schema uses the same column names and
units as the acquisition. The inherited declaration helper applies the
configured transpose and includes statistics when enabled.

.. literalinclude:: examples/demo_trace.py
   :language: python

State scan
~~~~~~~~~~

:download:`Demo Scan <examples/demo_scan.py>` stores each setpoint immediately.
Choose points on the **Scan** tab and nest a **Record Value** step beneath it.
With the scan instance named ``demo_scan``, set the command's expression to
``demo_scan.value`` and its units to ``V`` to log the voltage at each point.
The inherited **Data** tab can collect the command's output after each point
marked for measurement.

.. literalinclude:: examples/demo_scan.py
   :language: python

State sweep
~~~~~~~~~~~

:download:`Demo Sweep <examples/demo_sweep.py>` simulates a continuous voltage
ramp. The inherited **Sweep** tab starts with a segment from 0 to 1 V at
5 V/s. Nest a **Record Value** step with expression ``demo_sweep.value`` and
units ``V`` to log the sampled voltage as it changes. Use ``demo_sweep`` as
the sweep instance name. The generator polls the simulated state and the
sweep runs its children at each yielded point.

.. literalinclude:: examples/demo_sweep.py
   :language: python

Monitor
~~~~~~~

:download:`Demo Monitor <examples/demo_monitor.py>` returns one simulated
temperature reading. The base class caches it in ``last_reading`` and
publishes the temperature with its units. Running it as a sequence step
performs one read. The example sets ``has_lifecycle`` to ``False`` because it
needs no instrument setup.

.. literalinclude:: examples/demo_monitor.py
   :language: python

Transform
~~~~~~~~~

:download:`Demo Mean Voltage <examples/demo_transform.py>` uses the completed
``Demo Trace`` table. Add a **Demo Trace** step named ``demo_trace`` before
the transform. The transform reads that fixed source from the live namespace
and publishes **Mean Voltage**, which is 2 V for the three example samples.
The inherited ``run({})`` call stores the result in ``data``.

.. literalinclude:: examples/demo_transform.py
   :language: python

Sequence container
~~~~~~~~~~~~~~~~~~

:download:`Demo Group <examples/demo_sequence.py>` logs the start of the group
and then runs the nested steps in order. Try nesting **Demo Trace** followed
by **Demo Mean Voltage**. The generated action emits the same log call as the
direct execution method and delegates child rendering to the base class.

.. literalinclude:: examples/demo_sequence.py
   :language: python

For the renderer extension point, see the independent downloadable example in
:doc:`plot_display_plugins`.

Verification checklist
------------------------

Before distributing a plugin, verify:

* Entry-point metadata loads the class, and construction needs neither
  widgets nor hardware. A clean environment can import the saved class path.
* Two instances keep independent configuration, identity and owned resources.
* Every editable setting survives JSON reconstruction, including defaults for
  older data, without persisting runtime state.
* Generated Python compiles and actually runs through the engine. Test the
  plugin inside loops/branches and as a one-off selected subtree where valid.
* Published keys, units, data shapes and failed-result behavior match the
  declared contract. Downstream Plot Points/Plot Trace/Save can consume them.
* Configured schemas work before acquisition and after changing optional
  channels, units or transpose. Schema builders return empty tables and do not
  evaluate result expressions. Refresh updates any already open selectors.
* Migrated declarations retain existing identifiers and expressions. Legacy
  callers and subclass overrides, including ``super()`` updates, still work.
* Direct and generated state execution agree on clearing, collection filters,
  point metadata and child-action order. Generated Break/Continue still act
  on the intended loop.
* Direct, generated and timer-driven monitor reads update ``last_reading``
  and publish one completed result. Failed reads retain the last successful
  cache; only timer polling converts the error to ``read_error``.
* Owned-resource cleanup works after partial setup, failed configuration,
  repeated connection and stop. Borrowed controller sessions remain open.
* Configuration pages survive selection changes, missing catalogues and
  producer renames/removal, and release signal connections on destruction.
* Supported Qt bindings and rendering backends work in your deployment.
  Fake drivers verify software behavior; they do not establish bench behavior.

Use the repository's managed widget/configuration fixtures when contributing
tests here, following :doc:`contributing`. A coding assistant should identify
the relevant base contract, the closest current implementation, resource
ownership and persistence requirements before writing a new plugin.
