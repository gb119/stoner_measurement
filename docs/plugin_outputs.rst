Plugin output declarations
===========================

This is the publication contract for sequence plugins. Use
:doc:`third_party_plugins` for execution, lifecycle and packaging contracts,
:doc:`trace_data` for acquired table structure, and :doc:`data_workflows` for
selecting results in the application.

Declare outputs once
----------------------

Declare custom outputs through ``declared_outputs()`` and return a fresh
:class:`~stoner_measurement.core.plugin_outputs.PluginOutputs`, or inherit a
family declaration that already matches the plugin's results. Import the
declaration types from ``stoner_measurement.plugins`` or their defining module,
``stoner_measurement.core.plugin_outputs``.

``PluginOutputs.traces`` maps catalogue identifiers to ``TraceOutput`` objects.
``PluginOutputs.values`` maps scalar identifiers to ``ScalarOutput`` objects.
Both dictionaries preserve insertion order. They describe access to results;
they do not contain acquired arrays or scalar readings.

.. list-table:: Declaration fields
   :header-rows: 1
   :widths: 25 25 50

   * - Field
     - Applies to
     - Meaning
   * - Mapping key
     - Both output types
     - Fully qualified catalogue identifier, such as ``source:IV`` or
       ``scan.data``. Keep it stable for a given configuration.
   * - ``expression``
     - Both output types
     - Python expression resolving to the current result in the engine
       namespace. Consumers evaluate it when they need data.
   * - ``result_key``
     - Both output types
     - Optional local key in the plugin's result dictionary, such as ``IV``
       in ``source.data['IV']``. It is separate from the catalogue identifier.
   * - ``units``
     - Scalars
     - Physical unit string. ``""`` means unspecified or dimensionless.
   * - ``schema``
     - Traces
     - An empty ``TraceData`` declaring configured columns and metadata.
   * - ``schema_factory``
     - Traces
     - A zero-argument callable returning an empty ``TraceData`` or ``None``.
       Use this instead of ``schema`` when construction must be deferred.

Trace units belong to individual columns in the schema, not to one trace-wide
unit field. Omit ``result_key`` for outputs accessed through attributes, cached
monitor readings or statistics rather than a result-dictionary entry. A state
scan's ``scan.data`` is itself a table and has no local dictionary key.

Identifiers and expressions are independent. Do not reconstruct an expression
or local result key by splitting a label at ``:`` or ``.``. The trace and scalar
catalogues are separate: a legacy plugin may publish the same identifier in
both, and the resolver preserves that behaviour.

The complete scalar example in :doc:`third_party_plugins` uses this interface.
A plugin with an existing IV result and resistance attribute could declare::

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

This excerpt assumes ``_iv_schema()`` is the plugin's configuration-only schema
builder. A declaration may be queried before connection or acquisition. It
must not query hardware, evaluate runtime expressions or modify acquired data.
Changing a declaration does not itself change the instrument configuration.

Configured schemas and catalogue construction
----------------------------------------------

Schemas declare the complete expected table: column keys, roles, display names
and units. Include enabled auxiliary channels and configured axis transposition.
Share metadata construction with acquisition so declarations cannot drift from
the returned data. An empty schema for an IV table could be built with::

   import pandas as pd
   from stoner_measurement.core.trace_data import TraceData

   def _iv_schema(self):
       frame = pd.DataFrame({
           column: pd.Series(dtype=float)
           for column in ("x", "V", "R")
       })
       return TraceData(
           frame,
           column_roles={"x": "x", "V": "y", "R": "z"},
           names={"x": "Current", "V": "Voltage", "R": "Resistance"},
           units={"x": "A", "V": "V", "R": "Ω"},
       )

Supply either ``schema`` or ``schema_factory``, never both. Neither is required
when channels cannot yet be determined; a factory may also return ``None``.
An omitted schema means unknown metadata, whereas an empty ``TraceData`` is a
known schema with zero acquired rows. A populated table is not a valid schema.
Materialisation returns independent metadata snapshots.

The engine rebuilds catalogues in this order:

1. Resolve each sequence-step plugin's declarations and legacy overrides once.
2. Publish trace expressions as ``_traces`` and scalar expressions with units
   as ``_values``.
3. Materialise trace schemas into ``_trace_schemas``. Schema factories can now
   use the completed scalar catalogue to describe collected scan/sweep outputs.
4. Emit catalogue-change notifications, followed by the namespace update.

Factories follow the same configuration-only rules as declarations. In
particular, access scalar definitions and their units rather than evaluating
the expressions to discover columns. State scan and sweep bases already build
their collected-data schemas from selected scalar outputs.

Invalid schemas raise ``ValueError`` when requested directly. The engine logs
schema-construction failures while retaining expression catalogues. Selectors
prefer published configured schemas, then acquired metadata, then the existing
configured x/y fallback. Catalogue membership is not proof that data have been
acquired or that an access expression is currently evaluable.

Result names and ordering
--------------------------

For migrated trace plugins, ``trace_names`` is derived from trace declarations'
``result_key`` fields. For transforms:

* ``output_trace_names`` contains trace result keys.
* ``output_value_names`` contains scalar result keys.
* ``output_names`` contains all result keys, without duplicates.

Computed projections without a ``result_key`` do not appear in these lists.
The default combined order is scalar results followed by traces, respecting
each dictionary's insertion order. Set ``PluginOutputs.result_order`` to a
tuple of local result keys when a transform requires a different order.
Listed keys come first; newly added keys not in that tuple follow afterwards.
Unknown keys in the tuple do not create outputs.

``_measure()`` and ``transform()`` still return their normal result dictionaries.
``result_key`` describes those dictionaries; it does not move, rename or compute
their entries. Use ``measure()`` and ``run()`` respectively so the family bases
store results and manage their associated status or completion signals.

Compatibility and migration
-----------------------------

The old APIs remain available as dictionary views of resolved declarations:

.. list-table:: Compatibility views
   :header-rows: 1
   :widths: 40 60

   * - Method
     - Result
   * - ``reported_traces()``
     - Trace catalogue identifiers mapped to access expressions.
   * - ``configured_trace_data()``
     - Trace catalogue identifiers mapped to materialised empty schemas.
       Traces with unknown schemas are omitted.
   * - ``reported_values()``
     - Scalar catalogue identifiers mapped to access expressions.
   * - ``reported_value_units()``
     - Scalar catalogue identifiers mapped to physical unit strings.

The resolver distinguishes the following cases:

* ``declared_outputs()`` returning ``None`` selects adaptation of legacy
  publication hooks. This is ``BasePlugin``'s default.
* Returning ``PluginOutputs()`` explicitly declares no outputs. It does not
  request fallback to less-specific legacy declarations.
* A legacy subclass can override a publication hook inherited from a migrated
  parent. The more-specific override remains effective. Calling
  ``super().reported_*()`` supplies the parent's view; ordinary dictionary
  updates and removals continue to work.
* A unified declaration on a subclass supersedes legacy publication hooks on
  its ancestors. Old callers receive the unified views. A further legacy
  subclass can extend those views again.
* Defining a unified declaration and a legacy publication method on the same
  class is ambiguous. During resolution the unified declaration wins and a
  warning identifies the conflict. Implement one declaration style per class.

Legacy naming-property overrides remain supported by the trace and transform
family adapters. Old transform defaults are preserved: an old plugin that
overrides ``output_trace_names`` without restricting ``output_value_names``
can still publish a trace as a scalar too. New declarations classify outputs
explicitly and do not infer one category from the other.

To migrate a plugin:

1. Keep existing catalogue identifiers, access expressions and local result
   keys. Saved selections refer to those identifiers and expressions.
2. Combine scalar expressions and their units into ``ScalarOutput`` records.
3. Combine trace expressions, local keys and optional schema builders into
   ``TraceOutput`` records. Move the schema builder into a private helper;
   do not call ``configured_trace_data()`` from ``declared_outputs()``.
4. Return both mappings from ``declared_outputs()``. Remove the plugin's own
   legacy publication hooks and redundant naming-property overrides so the
   inherited compatibility views can serve existing callers.
5. Check outputs before acquisition, after configuration edits and after a
   previous run. Verify legacy subclasses as well as the migrated class.

To extend an already migrated parent, start with its declarations::

   def declared_outputs(self):
       outputs = super().declared_outputs()
       var = self.instance_name
       outputs.values[f"{var}:Temperature"] = ScalarOutput(
           f"{var}.temperature", units="K",
       )
       return outputs

This excerpt assumes the parent returns ``PluginOutputs`` and the subclass
provides a ``temperature`` attribute. Declaration records are frozen; replace
a record when changing its expression or units. The containing mappings support
extension. Do not build declarations by calling their own compatibility views.

Refresh and consumption
------------------------

After programmatic edits, ``plugin.refresh()`` refreshes the active scan
generator, rebuilds the attached engine's output catalogues, then refreshes
cached widgets that provide ``refresh()`` and requests their repaint. It does
not create a new configuration page or bind every raw editor to an attribute.
``plugin.full_refresh()`` additionally visits ``member_plugins()`` recursively;
``sequence.full_refresh()`` applies that operation to the sequence tree.

For a UI control that changes only published metadata, call
``self.sequence_engine.refresh_data_catalogs()`` when attached. Catalogue
consumers use the lifetime-scoped binding helpers in ``trace_catalog_ui`` so
open selectors react even when trace identifiers stay the same but channels
or units change. Refresh does not connect, configure or acquire instruments.

Framework consumers should call ``resolve_outputs(plugin)`` from
``stoner_measurement.core.plugin_outputs`` rather than merging individual
publication hooks themselves. Treat the returned mappings as a snapshot.
``engine.values_catalog`` entries remain string-compatible ``ValueCatalogEntry``
objects with a ``units`` attribute; trace entries remain expression strings.
Evaluate the selected expression against the live namespace when consuming its
data, for example with ``self.eval(expression)`` inside a plugin. A plugin's
``engine_namespace`` is live; ``engine.namespace`` is an inspection snapshot.
Do not persist declarations, schemas or factories in sequence JSON.
