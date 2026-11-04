Writing a plot display plugin
=============================

This is the developer integration guide for an external renderer package.
For choosing and operating an installed display, use :doc:`plot_displays`.

The measurement display is replaceable through a factory and a GUI adapter.
Start with :doc:`plotting_contracts` for the request records, coordinates and
completion semantics. Display plugins are independent of sequence plugins:
they do not inherit ``BasePlugin`` or acquire instrument sessions.

Registering a factory
---------------------

Put a no-argument factory class in your installed Python package and register it
in that package's ``pyproject.toml``:

.. code-block:: toml

   [project.entry-points."stoner_measurement.plot_displays"]
   summary = "your_package.summary_display:SummaryDisplayFactory"

The entry name must match ``factory_id``. Give the factory a human-readable
``name``, ``contract_version = 1`` and immutable ``PlotCapabilities`` metadata.
Discovery constructs factory metadata, so keep it inexpensive and free of
widgets, graphics contexts and instrument connections. Construct the renderer
only in ``create(parent)`` on the GUI thread. Optional rendering dependencies
can be imported there; unavailable dependencies then produce an isolated
creation failure instead of breaking other displays.

Install your package into the application's Python environment and restart the
application to discover it. Select it through **View → Plot display**. Bundled
choices are described in :doc:`plot_displays`. A missing or broken saved
selection falls back to Cartesian. Installation adds the menu choice without
editing ``MainWindow``, ``SequenceEngine`` or plotting commands.

The user-facing controls for bundled renderers belong in
:doc:`plot_displays`. This page describes the factory and adapter integration
that external display packages must implement.

A complete independent example
------------------------------

The downloadable :download:`summary_display.py <examples/summary_display.py>`
implements a diagnostic sample-count display using Qt alone. Copy it into your
package under the module path above. It accepts Cartesian line/point requests
and displays sample counts; it intentionally does not draw curves, markers or
error bars. It demonstrates append/replace, public descriptions, axis records,
state replay, preferences and idempotent cleanup without Cartesian widget APIs.
The integration tests load this exact example, discover its factory, run an
existing plotting command on the engine worker and switch back to Cartesian.

.. literalinclude:: examples/summary_display.py
   :language: python

The example concatenates accumulated data for clarity. For a production display
with long point streams, retain append chunks or extend renderer buffers rather
than copying every earlier sample on each update. The service already retains
canonical append chunks and does not copy the full acquisition catalogue.

Adapter responsibilities
------------------------

``PlotDisplay`` and ``PlotDisplayFactory`` in
``stoner_measurement.ui.plotting.interfaces`` specify the public interface.
An adapter can be a QWidget itself, as above, or own a separate ``widget``.
Its widget must belong to the supplied parent; factory and adapter capabilities
must agree. The host owns and closes the selected adapter. If creation fails,
release partial non-widget resources before raising. Never close a borrowed
service or another display's resources.

Implement ``validate(payload)`` without mutation. Declare only operations,
coordinate layouts and presentations you accept. Structural capability checks
do not validate a renderer's styles, axis domains, resource limits or current
series state. Raise ``UnsupportedDisplayOperation`` for unsupported features;
raise an ordinary exception for malformed requests or rendering failures.
These become terminal results and wake the waiting producer.

``apply(payload)`` runs on the GUI thread and must finish the complete logical
operation before returning. Do not acknowledge data before applying its axes,
labels and styles. Return a positive marker ID only for a successful marker
operation, otherwise None. Completion does not promise a repaint. Rendering
errors do not promise rollback of partially changed graphics; canonical service
data remains available for explicit recovery. Do not queue another service
operation synchronously from inside ``apply``.

Return immutable ``AxisDescription`` and ``SeriesDescription`` tuples from
``descriptions()``. Emit the no-argument ``changed`` Qt signal when public state
changes, including user edits to titles, visibility or axes. Keep graphics
objects inside the adapter. Ordinary producers use ``engine.plot_client``;
they must never inspect adapter members or graphics scenes.

How commands discover supported dimensions
------------------------------------------

Commands can query the active display through the stable producer endpoint:

.. code-block:: python

   from stoner_measurement.core.plotting.contracts import CoordinateSystem

   client = command.sequence_engine.plot_client
   capabilities = client.capabilities() if client is not None else None
   supports_xyz = (
       capabilities is not None
       and (CoordinateSystem.CARTESIAN, 3) in capabilities.layouts
   )

Inspect ``layouts`` for coordinate system/dimension pairs, ``presentations`` for
line, points, intensity or surface support, and ``value_channel`` for independent
intensity binding. Use ``unsupported_reasons(PlotRequest(update))`` to check a
complete proposed request; dimensions alone do not establish support. The GUI
host's ``factory_id`` identifies the selected renderer, but producer behaviour
should depend on capabilities rather than particular renderer names.

Plot Points and Plot Trace default to Cartesian XY, preserving old sequences.
Their **Plot form** controls additionally offer **Polar (angle, radius)**,
**XYZ**, **XY intensity**, and
**XYZ + value** when the complete layout, presentation and optional assembly
extension are supported. They explicitly select ``x``, ``y``, ``z`` and optional
``value`` sources and coordinate conventions. No auxiliary acquisition role
implies Z, and display selection never converts XY into angular coordinates.

Plot Trace captures ``Z(X, Y=fixed)`` slices: X/Z arrays and a scalar Y evaluated
once on each execution. Plot Points captures scalar X/Y and multiple measured
Z entries inside nested loops. Each measured channel has its own stable surface
identity, independent of its label. Both commands persist the additional fields
and evaluate expressions when the generated action executes.

To accept these forms, advertise ``surface_versions=frozenset({1})`` alongside
the layouts, operations and presentations you support. Trace XYZ uses
``Presentation.SURFACE``; point XYZ uses ``Presentation.POINTS``. XY intensity
requires a two-coordinate layout, ``value_channel=True`` and
``Presentation.INTENSITY``. XYZ + value requires both three coordinates and an
independent value channel. A three-dimensional display need not accept XY;
declare both layouts if it does. The bundled Cartesian and diagnostic example
factories do not opt into surface assembly.

Version-one ``SurfaceBinding`` defines exact rectilinear keys, whole-slice
identity/replacement, duplicate rejection or explicit replacement, acquisition
identity/reset and replay snapshots with slice catalogues. Missing cells stay
absent, and non-finite grid coordinates are rejected before renderer mutation.
Adapters must implement these policies and hydrate complete snapshots before
committing replacement. See :doc:`plotting_contracts` for the full extension.
The bundled XYZ and intensity displays implement this extension; canonical
assembly and renderer application remain separate responsibilities.

Cached command pages listen to ``PlotService.descriptions_changed`` and refresh
forms and axis selectors after replacement or axis edits. A saved unsupported
form stays selected and visibly marked; bindings survive the switch and execution
revalidates the complete request. Data-only updates do not rebuild selectors.

Replay and preferences
----------------------

``export_state()`` returns ``DisplayState`` with current axes, complete series,
visibility and source-coordinate marker identities/anchors. It must reflect
user edits as well as the last producer request. ``import_state(state)`` fully
hydrates a hidden candidate before returning; reject anything you cannot
represent. The host merges canonical data and bindings, checks capabilities,
then commits only after successful hydration and description validation.
Replacement requires an idle engine and an empty plot queue. Failed hydration
retains the original display and generation. Successful replacement advances
generation once and closes the old adapter before deferred widget deletion.

Do not project or relabel canonical data implicitly. Keep generalised ``x``,
``y`` and ``z`` bindings and explicit coordinate descriptors; polar, cylindrical
and spherical meanings and angular conventions are specified in the contract.
An intensity channel binds to ``value`` independently. Surface adapters must
implement the explicitly negotiated topology and missing/repeated-cell policies.

Adapters may declare ``supported_styles`` as a set of keys; the example declares
an empty set. During replacement the host retains unsupported style keys for
switching back and reports them. New requests with unsupported styles fail
explicitly. Required incompatible data, uncertainties, axes or markers refuse
replacement. A limited display can therefore be selected with an empty or
compatible plot; clearing plotted data can remove incompatible series/markers.

Use ``export_settings()`` and ``import_settings(settings)`` for renderer-specific,
versioned JSON preferences such as camera, palette or ranges. Accept an empty
mapping for defaults and validate supported versions and values. Include current
preferences in exported ``DisplayState.renderer_settings``. QSettings stores
the selected factory and per-factory preferences, never measurement arrays.
Restart restores controls without replaying acquired data.

Compatibility and verification
------------------------------

The existing ``stoner_measurement.ui.plot_widget.PlotWidget`` import and standalone
API remain available for embedded charts. ``engine.plot_widget`` is a legacy
facade with an explicit supported-method list; a display need not implement its
Cartesian methods. ``MainWindow.plot_widget`` and ``plot_display_host.display``
provide GUI inspection access, outside the portable producer API.

Before distributing a renderer, test real worker submissions and GUI application,
append/replace and validation failure, user-edited replay, incompatible switch
refusal, generation/completion identity, settings versions, repeated close and
partial-creation cleanup. Use the repository's managed Qt widget fixtures when
contributing tests here. Test your supported Qt bindings and rendering backends;
the diagnostic example does not validate OpenGL, camera or projection behaviour.
