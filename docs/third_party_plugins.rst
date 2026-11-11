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
     - ``name``, ``required_inputs``, ``output_names`` and ``transform(data)``
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

``reported_traces()`` and ``reported_values()`` return mappings of display keys
to expressions, not the current arrays or scalar values. The expressions
resolve in the engine namespace:

.. code-block:: python

   def reported_values(self):
       return {f"{self.instance_name}:Value": f"{self.instance_name}.value"}

   def reported_value_units(self):
       return {f"{self.instance_name}:Value": "V"}

Common identities are ``instance:channel`` for acquired/transformed traces and
scalar quantities, and ``instance.data`` for a state scan/sweep's collected
table. Keep output keys stable for a configuration and ensure their expressions
resolve after execution. Declare output units with matching keys.

The ``_traces`` and ``_values`` catalogues describe steps in the current
sequence, not all installed plugin templates. ``engine.traces_catalog`` and
``engine.values_catalog`` and their change-signal arguments are snapshots.
Use snapshots to populate controls and evaluate the selected expression when
an action needs current data.

If a setting changes reported outputs or units, call
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
names. Declare ``output_trace_names`` and ``output_value_names`` explicitly
when mixing tables and scalars. The default treats all output names as scalar
values; returning a table alone does not publish it as a trace. Use the base
``run`` path so input validation, result storage and completion signals remain
consistent. Trace selection can evaluate catalogue expressions inside a
transform with ``required_inputs=[]``; inputs declared there must instead be
supplied in the mapping passed to ``run``.

State scan/sweep bases already collect configured scalar outputs after their
child actions and publish their table as ``instance.data``. Reuse those hooks;
do not build a second collection table or assume a Save child sees the row
that will be collected after it. The execution-order example is in
:doc:`data_workflows`.

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

A complete minimal package
---------------------------

The downloadable :download:`record_value_plugin.py
<examples/record_value_plugin.py>` demonstrates a lifecycle-free command,
runtime expressions, a scalar output, a configuration page and persistence.
Copy it to ``src/my_measurement_extras/record_value.py`` in your package:

.. literalinclude:: examples/record_value_plugin.py
   :language: python

Include an ``__init__.py`` in ``src/my_measurement_extras/`` and this metadata:

.. code-block:: toml

   [build-system]
   requires = ["setuptools>=61"]
   build-backend = "setuptools.build_meta"

   [project]
   name = "my-measurement-extras"
   version = "0.1.0"
   requires-python = ">=3.12"
   dependencies = ["stoner_measurement"]

   [tool.setuptools.packages.find]
   where = ["src"]

   [project.entry-points."stoner_measurement.plugins"]
   my_lab_record_value = "my_measurement_extras.record_value:RecordValueCommand"

Declare the application-version range your package actually supports and test
against it. In the environment used to run the application, install with
``python -m pip install -e .``. For the repository's Conda environment this is
``conda run -n stoner_measurement python -m pip install -e .``.

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
