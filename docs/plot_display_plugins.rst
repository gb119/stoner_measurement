Writing a plot display plugin
=============================

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
application to discover it. Select it through **View → Plot display**. Cartesian
traces remain the only bundled production renderer. A missing or broken saved
selection falls back to Cartesian. Installation adds the menu choice without
editing ``MainWindow``, ``SequenceEngine`` or plotting commands.

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

The current Plot Points and Plot Trace commands still construct two-coordinate
Cartesian requests. They already use public axis descriptions and capabilities
for axis setup. Future three-coordinate or non-Cartesian command controls must
explicitly select source channels for ``x``, ``y``, ``z`` and optional ``value``,
plus the coordinate descriptor. A three-dimensional display need not accept
two-dimensional data; declare both layouts when it does. Do not infer Z from an
auxiliary acquisition column or reinterpret XY as radius/angle automatically.

For an additional three-coordinate command form, Plot Trace should describe
``Z(X, Y=fixed)``: an X array, a fixed Y value repeated for each row, and a Z
array. Plot Points should append ``(X, Y, Z)`` samples. Keep existing Cartesian
XY forms unchanged: ``Y(X)`` traces and ``(X, Y)`` points. Select the additional
form explicitly for a capable display and retain it in command configuration;
do not change a saved sequence's meaning when switching renderers. These command
extensions and their binding controls are subsequent work, not part of the
current Cartesian extraction.

An intended surface acquisition uses one loop to acquire complete traces at
successive Y values: evaluate the loop-variable expression at each execution
and repeat that value alongside the X and Z arrays. Each trace needs a distinct
slice identity within a shared surface identity so that acquiring the next row
does not replace the preceding row. Plot Points can instead run inside two
nested loops and append X, Y and measured Z samples to the same surface.
The future surface binding UI and data model must define those identities and
the grid/topology policy, including repeated coordinates, missing cells and
whether reacquiring a slice replaces it. The current contract can carry the
coordinate samples, but does not yet define surface assembly or interpolation.

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
An intensity channel binds to ``value`` independently. Future map and surface
plugins must define topology and missing/repeated-sample policies explicitly.

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
