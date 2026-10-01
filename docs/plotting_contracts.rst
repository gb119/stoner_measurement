Plot display communications contract
============================================

The version-one records in ``stoner_measurement.core.plotting.contracts``
define how a producer describes a plot without depending on its renderer.
The main application routes plotting commands through ``PlotService`` and a
stable ``PlotDisplayHost``. The bundled Cartesian factory provides the default
display. ``PlotClient`` and ``PlotTicket`` define the producer interfaces.
Factories are discovered independently of sequence plugins. Idle replacement
validates and hydrates a candidate before committing it.
For a complete external factory example and packaging guidance, see
:doc:`plot_display_plugins`.

Generalised coordinates
-----------------------

Keep ``x``, ``y`` and ``z`` as coordinate slots. Their physical meaning is
specified separately:

* Cartesian: X, Y and optional Z.
* Polar: radius and angle, with no third coordinate.
* Cylindrical: radius, azimuth and axial position.
* Spherical: radius, theta and phi. The theta/phi convention is mandatory.

``CoordinateBinding.value`` is an independent intensity or colour channel.
It is not inferred from ``z`` or from an auxiliary ``TraceData`` column.
The coordinate system and the presentation (line, points, intensity or surface)
are separate. Coordinate arrays stay in source units; renderers later perform
projection and pointer-coordinate conversion.

Angular descriptors specify radians/degrees, azimuth origin and wrapping,
and clockwise/counterclockwise orientation. Spherical inclination is measured
from the positive polar axis; select explicitly whether theta or phi supplies
it. Wrapping applies to azimuth, not inclination. Angular channel metadata
may omit units and inherit the descriptor, but contradictory units are rejected.

Complete request examples
-------------------------

These examples construct real records; they do not require an attached display.
Imports used throughout:

>>> from stoner_measurement.core.plotting.contracts import (
...     AddMarker, AngularUnit, ChannelMetadata, ClearPlot,
...     CoordinateBinding, CoordinateDescriptor, CoordinateSystem,
...     PlotData, PlotRequest, Presentation, SeriesUpdate,
...     SphericalConvention, UpdateMode,
... )

Append a scalar point using a one-row sample table:

>>> point = PlotRequest(SeriesUpdate(
...     "sample:voltage",
...     PlotData({"field": [0.1], "voltage": [2.0]}),
...     CoordinateBinding("field", "voltage"),
...     mode=UpdateMode.APPEND,
...     axes={"x": "bottom", "y": "left"},
... ))
>>> point.payload.mode.value
'append'

Replace a trace, including uncertainties, physical labels, axes and style:

>>> trace = PlotRequest(SeriesUpdate(
...     "sample:voltage",
...     PlotData(
...         {"field": [0.1, 0.2], "voltage": [2.0, 3.0]},
...         metadata={"field": ChannelMetadata("Field", "T"),
...                   "voltage": ChannelMetadata("Voltage", "V")},
...         uncertainties={"voltage": [0.01, 0.02]},
...     ),
...     CoordinateBinding("field", "voltage"),
...     title="Voltage", axes={"x": "bottom", "y": "left"},
...     style={"colour": "red", "line_style": "solid"},
... ))
>>> trace.payload.data.uncertainties["voltage"].tolist()
[0.01, 0.02]

Clear and marker operations are requests too:

>>> clear = PlotRequest(ClearPlot())
>>> marker = PlotRequest(AddMarker(
...     {"x": 0.1, "y": 2.0},
...     axes={"x": "bottom", "y": "left"}, label="Reference",
... ))
>>> marker.payload.position["y"]
2.0

Describe a future cylindrical display while retaining the x/y/z slot names:

>>> samples = PlotData(
...     {"radius": [2.0], "angle": [90.0], "height": [4.0]},
...     metadata={"angle": ChannelMetadata("Azimuth", "deg")},
... )
>>> cylinder = SeriesUpdate(
...     "trajectory", samples,
...     CoordinateBinding(x="radius", y="angle", z="height"),
...     CoordinateDescriptor(CoordinateSystem.CYLINDRICAL,
...                          angular_unit=AngularUnit.DEGREES),
...     presentation=Presentation.POINTS,
... )
>>> cylinder.binding.z
'height'

For spherical coordinates the angle convention is explicit:

>>> sphere = CoordinateDescriptor(
...     CoordinateSystem.SPHERICAL,
...     spherical_convention=SphericalConvention.THETA_INCLINATION,
... )
>>> sphere.spherical_convention.value
'theta_inclination_phi_azimuth'

>>> spherical_series = SeriesUpdate(
...     "orientation",
...     PlotData({"radius": [2.0], "theta": [1.57], "phi": [3.14]}),
...     CoordinateBinding(x="radius", y="theta", z="phi"), sphere,
...     presentation=Presentation.POINTS,
... )
>>> spherical_series.binding.dimensions
3

Snapshots and capability checks
-------------------------------

``PlotData`` copies arrays, metadata and uncertainty mappings. Arrays have
immutable backing storage, including when producers supplied writable NumPy
views. Empty tables and NaN samples are supported. Columns must be one-dimensional
and equally sized; uncertainties must reference an existing channel, have matching
length and be nonnegative. Map topology and interpolation are deferred.

``PlotCapabilities.unsupported_reasons(request)`` checks operations, coordinate
system/dimension pairs, rendering intent, named axes, uncertainties and independent
value channels. An empty tuple indicates structural support. The Cartesian bridge
must also validate style values, axis domains and existing state before applying
the request. The current bridge supports Cartesian two-coordinate line and point
plots with uncertainties and named axes. Other layouts terminate as unsupported.

Submission and completion
-------------------------

``PlotService.submit(request)`` returns a ``CompletionTicket``. Each accepted
request receives exactly one terminal ``PlotResult`` with request identity,
display target and generation, and one of ``applied``, ``unsupported``, ``failed``,
``cancelled`` or ``no_display``. Errors and cancellations include a diagnostic.
An applied marker can return its assigned ID. ``no_display`` preserves headless
acquisition without claiming that graphics were drawn.

Workers may use ``ticket.wait(timeout)``. It returns ``None`` when the wait expires;
that does not cancel the request. ``SequenceEngine.wait_for_plot_ticket`` honours
pause and stop. Stop cancels queued work; an operation already applying may finish.
GUI callers use result notifications or the synchronous ``apply_now`` path;
blocking on a pending ticket from the GUI raises an error.
Completion acknowledges application of the whole logical operation, including
axes and styles; it does not mean a repaint or graphics-buffer swap has occurred.

Public ``axes()``, ``series()`` and ``capabilities()`` queries return descriptions
without exposing renderer objects. Ownership, compatibility and migration gates
are recorded in ``notes/2026-10-01-plot-contract-stage1.md`` and
``notes/2026-10-01-plot-service-stage2.md`` in the source tree.

The application's host owns the service and selected display, including the
Cartesian widget's graphics lifecycle.
``engine.plot_client`` is the stable producer endpoint; ``engine.plot_widget``
provides an allowlisted legacy facade. Legacy GUI calls retain immediate return
values; worker calls are dispatched to the GUI and wait on their own tickets.
Legacy plotting signals remain observable without a second rendering connection.
Standalone engines with no client retain their previous signal-based behaviour.

The pending queue is bounded (128 requests by default); a full queue rejects a
submission before accepting it. Duplicate request IDs are rejected. Each accepted
request terminates once, including renderer exceptions, cancellation and headless
execution. Completion covers data, labels, axis assignment and styles, rather
than repaint timing. ``data_snapshot(series_id)`` assembles an immutable copy of
the plotted data; point append retains chunks without copying the whole series
on each submission. Acquisition data remains owned by the measurement plugins.

Display factories and host
--------------------------

``stoner_measurement.ui.plotting.interfaces`` defines the version-one
``PlotDisplayFactory`` and ``PlotDisplay`` protocols. Display factories do not
inherit ``BasePlugin``. A factory exposes ``factory_id``, ``name``,
``contract_version`` (currently 1), ``capabilities`` and ``create(parent)``.
Loading a factory must not construct widgets or connect instruments.

Register a no-argument factory class in a separate entry-point group, using the
same entry-point name as its ``factory_id``:

.. code-block:: toml

   [project.entry-points."stoner_measurement.plot_displays"]
   example = "example_package.displays:ExampleDisplayFactory"

``PlotDisplayRegistry`` discovers factory metadata and isolates import, version
and ID errors. Its ``factories`` and ``diagnostics`` properties return snapshots.
The bundled ``cartesian`` factory remains available when installed entry-point
metadata is absent and cannot be overridden by another package.

``create(parent)`` returns an adapter with a ``widget`` owned by the supplied
parent, matching ``capabilities``, a no-argument Qt ``changed`` signal, and these
methods:

* ``validate(payload)`` rejects invalid operations before mutation.
* ``apply(payload)`` applies the complete operation synchronously on the GUI
  thread and returns a marker ID or None.
* ``descriptions()`` returns tuples of ``AxisDescription`` and
  ``SeriesDescription`` records. Emit ``changed`` when those descriptions change.
* ``close()`` releases owned resources and is safe to call repeatedly.
* ``export_state()`` returns immutable ``DisplayState``; ``import_state(state)``
  hydrates the complete snapshot into a hidden candidate.
* ``export_settings()`` and ``import_settings(settings)`` handle versioned JSON
  preferences without measurement arrays.

Only the selected factory creates a display. The host validates its interface
and falls back to Cartesian for unavailable or broken startup selections. Failed
creation must release non-widget resources itself; widgets created under the
supplied parent are closed by the host on failure. ``diagnostics`` records the
reason for fallback and the application logs it.

``MainWindow.plot_display_host`` exposes the stable host and its ``service``.
``host.display`` exposes the GUI adapter; ``host.display_widget`` and the retained
``MainWindow.plot_widget`` accessor expose the concrete GUI widget. Cartesian
``pg_widget`` inspection belongs here, outside ``PlotClient``. A different display
need not implement any legacy Cartesian methods; those calls terminate as
unsupported while portable requests use the standard interface.

Startup selection is available through ``MainWindow(display_factory_id=...)``
or ``PlotDisplayHost(factory_id=...)``. The application restores its saved factory
and preferences through QSettings, with Cartesian fallback when unavailable.
Embedded controller plots retain their standalone ``PlotWidget`` API.

Switching display
-----------------

Choose **View → Plot display** to select an installed display factory. The current
selection is checked. Cartesian traces are the only bundled rendering option;
installed third-party factories add choices to this menu. A refused replacement
shows its diagnostic and retains the previous selection.

``host.switch_display(factory_id)`` returns True on success or False with a
diagnostic. Replacement requires both an idle engine (including queued scripts
and console commands) and an empty plot queue. The GUI creates and hydrates a
hidden candidate, verifies its capabilities and descriptions, then changes the
active display. Failure before commit leaves the original display and generation
unchanged. The stable producer service stays attached throughout; a successful
commit advances its generation once, disconnects the old display and explicitly
closes its graphics before deferred deletion. New submissions during hydration
are rejected before acceptance rather than applied to either renderer.

``DisplayState`` contains immutable series/data bindings, axes, visibility,
resolved marker IDs/anchors and renderer preferences. Cartesian public
``export_plot_state``/``import_plot_state`` methods preserve data, uncertainties,
labels, styles, active axes, mappings/ranges, marker anchors and legend sizing.
They capture the current UI controls, so replay respects edits made after the
original producer request. Source channel metadata remains owned by the service.

Factories may declare ``supported_styles`` as a set of portable style keys. A
replacement can retain unsupported keys for switching back, with status-bar
feedback; incompatible required coordinates, series or marker/axis operations
refuse the replacement. This never changes a coordinate system implicitly.

The application stores the selected factory and versioned per-factory renderer
preferences at ``plotDisplay/preferences`` in QSettings. Measurements and plotted
arrays are excluded; restarting restores preferences without restoring acquired
series. Unsupported or malformed saved settings fall back to Cartesian defaults.
``host.save_preferences()`` persists current controls; close and successful
replacement also save them. Shared plots remain application-wide across sequence
documents.
