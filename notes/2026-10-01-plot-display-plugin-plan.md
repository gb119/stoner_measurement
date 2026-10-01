# Replaceable measurement plot displays

Status: approved architecture; Stages 1–5 implemented and validated.
The replaceable Cartesian display foundation, author guide and independent
factory example are complete. New production displays are subsequent work.

## Objective and scope

Make the main measurement plot replaceable through a documented communications
contract, delivering the existing Cartesian display as the first display plugin.
Keep current sequences, plotting commands, data storage and interactive behaviour
working. Later displays should support polar coordinates, XY intensity maps and
3D coordinates without requiring producers to know their rendering library.

The initial implementation retains one application-wide measurement display.
Embedded temperature, magnet and pressure charts and scan previews remain outside
this migration. Multiple simultaneous displays, polar rendering, interpolation,
3D graphics and a general acquisition-data redesign are subsequent work.

## Findings from the current code

| Component | Current coupling | Required boundary |
| --- | --- | --- |
| `ui/main_window.py:62` | Constructs `PlotWidget` directly; sizes and closes it | Stable display host |
| `app.py:189` | Assigns the concrete widget to the engine | Assign a stable plot service |
| `core/sequence_engine.py:761` | Exposes an untyped widget reference | Typed producer-facing client |
| `core/sequence_engine.py:794` | Polls the widget for plot readiness | Service-owned request completion |
| `plugins/command/base.py:205` | Increments the widget's pending counter from producers | Thread-safe submission |
| `plugins/command/plot_trace.py:73` | Connects several signals to individual widget methods | Complete update requests |
| `plugins/command/plot_points.py:61` | Separate point, axis, label and style signals | Complete point requests |
| Both plotting command modules | Read private `_axis_orientations` for selectors | Public axis descriptions |
| Plot clear/marker commands | Wire directly to widget slots | Service operations |
| `plugins/transform/extremum_locator.py:169` | Wires optional markers directly | Marker capability through service |
| `ui/plot_widget.py:689` | Stores data, axes, styles, markers, controls and graphics | Cartesian renderer behind adapter |
| `core/plugin_manager.py` | Discovers and instantiates sequence plugins | Separate display-factory registry |
| `core/trace_data.py` | Tabular data with one independent column and auxiliary channels | Explicit display channel bindings |

The existing widget already supports multiple X and Y axes, error bars, axis
mappings, marker anchors, pointer readouts, styles, visibility and a resizable
legend. These are compatibility requirements, not expendable prototype features.

Signal connections are established when commands attach to an engine. Merely
replacing `engine.plot_widget` does not rewire already attached commands. The
current pending counter acknowledges data application, while axis assignment and
style arrive separately. A replacement must address both lifetime and ordering.

`PlotWidget` is also imported by controller panels. Preserve that import and its
standalone API. Application settings currently save main-window geometry; there
is no complete main-plot state serializer to reuse.

## Proposed architecture

```text
Sequence commands / transforms / console
                    |
           PlotClient / PlotService
       requests, results, canonical state
                    |
          GUI-thread request dispatcher
                    |
               PlotDisplayHost
                    |
         PlotDisplayPlugin factory + adapter
                    |
       existing Cartesian PlotWidget initially
```

### Contracts and responsibilities

- `core/plotting/contracts.py`: renderer-independent request/result records,
  channel metadata, coordinate bindings, axis descriptions and capabilities.
  This module must not import PyQtGraph or an OpenGL renderer. Move pure label
  types here if useful, retaining imports through `ui.axis_mappings`.
- `core/plotting/service.py`: stable producer endpoint, request IDs, ordered
  dispatch, completion tracking and renderer-independent display state. The
  engine borrows the client; the application owns the service and its shutdown.
- `ui/plotting/host.py`: permanent centre-panel widget, display selection,
  renderer lifecycle and GUI-side error presentation.
- `ui/plotting/registry.py`: discovers display factories through a separate
  `stoner_measurement.plot_displays` entry-point group. Factories expose an ID,
  name, contract version and capabilities, then create a widget on demand.
- `ui/plotting/cartesian.py`: adapter around the current `PlotWidget`.
  It implements the display contract without initially moving or rewriting the
  existing 3,000-line widget.

Display plugins have their own protocol; they do not inherit `BasePlugin`.
Sequence execution, instrument lifecycle and generated code do not apply to
renderer widgets. Discovery must avoid constructing every candidate widget.
Plugin import/creation errors should be isolated and logged. The bundled
Cartesian factory remains available if installed entry-point metadata is missing.

## Communications contract

### Producer requests

Use typed requests with a stable display target, series ID and request ID:

- Replace a series snapshot, or append a batch of rows/points.
- Set/remove a series, rename its displayed title, and change visibility/style.
- Configure/query supported axes and coordinate bindings.
- Add/remove/clear markers, and clear plotted data.

A data update includes its channel arrays, labels/units, coordinate binding,
optional uncertainties, axis selection and requested style in one logical
request. Validate before mutation; apply settings and data in the correct order;
acknowledge the entire request. Renderer failure may leave partial graphics, so
do not promise rollback of drawing operations; retain the last valid model state
and report failure for explicit recovery/replay.

Use current plot titles as legacy series IDs at the compatibility boundary.
The new contract separates series identity from display title. Future source
references should use catalogue keys and column keys, never row numbers or
human-readable labels alone. Preserve current title-collision behaviour during
extraction, with any change treated as a separately reviewed migration.

### Data and future coordinate systems

Channel data is a named mapping of equally sized arrays with names and units.
Retain `x`, `y` and `z` as generalised coordinate slots in the public contract;
they need not represent Cartesian coordinates. Bind source channels to these
slots and declare a coordinate-system descriptor that defines their meaning:

| Coordinate system | `x` means | `y` means | `z` means |
| --- | --- | --- | --- |
| Cartesian | X | Y | Z |
| Polar (2D) | Radius r | Angle theta | Unused |
| Cylindrical | Radius r | Azimuth theta | Axial coordinate z |
| Spherical | Radius r | Angle theta | Angle phi |

For example, a polar series can bind `x` to magnitude and `y` to phase without
changing the API's coordinate-slot names. Labels shown to the user follow the
coordinate system and channel metadata. Cartesian remains the default for
legacy requests and saved configuration.

The coordinate-system descriptor records angular units, wrapping, orientation
and angle conventions. Spherical conventions must explicitly identify which
angle is inclination and which is azimuth; theta/phi naming alone is insufficient.
Keep canonical data, ranges, markers and uncertainties in the declared source
coordinates. A renderer performs any required projection into Cartesian graphics
coordinates and maps pointer positions back into the declared system. Do not
overwrite acquisition data with projected coordinates. Specify uncertainty
transformation when implementing a renderer that supports it.

Coordinate system and presentation type are separate choices: a three-coordinate
dataset might be rendered as points, lines or a surface. Intensity is a separate
value-channel binding, not intrinsically the third coordinate. An XY intensity
display binds `x` and `y` to position channels and `value` to the signal; a 3D
display can also bind an independent value channel for colour. Existing auxiliary
channels remain available as either coordinates or values through explicit
bindings.

`TraceData.COLUMN_ROLE_Z` denotes an auxiliary dependent channel, not necessarily
a spatial coordinate. Choose bindings explicitly. Existing tables can supply
several channels; later map/surface displays will also need topology, shape,
missing-cell and repeated-coordinate policies. Define extension points now, but
do not invent interpolation or reshape rules during the Cartesian extraction.

Submission captures owned snapshots of arrays and metadata. Queued Qt object
signals do not copy NumPy arrays; neither a frozen dataclass nor `np.asarray`
alone prevents concurrent mutation. Copy at the producer boundary and expose
read-only data to renderers. Avoid copying the entire acquisition catalogue or
building a second measurement store; retain only currently plotted snapshots.

### Results, capabilities and threading

- All QWidget/graphics operations run in GUI-thread slots through explicitly
  queued dispatch. Worker methods touch only thread-safe service state.
- `submit(request)` returns a ticket. Results distinguish applied, unsupported,
  failed and cancelled requests. Acknowledge accepted requests exactly once,
  including validation failures and shutdown; never strand a pending waiter.
- Worker waits use that ticket and honour timeout, pause and stop. Completion
  means state was applied, not that the screen has repainted or buffers swapped.
- GUI callers submit asynchronously and receive result signals; they must never
  block waiting for their own GUI event loop. Test real worker and GUI paths.
- Retain `wait_for_plot_ready()` for generated scripts, implemented using service
  outstanding requests. Initially preserve ordered, bounded producer flow;
  defer coalescing/dropping updates and specify those policies separately.
- Queries return public, thread-safe snapshots of axis/series descriptions.
  A change signal refreshes command selectors; remove access to private maps.
- Capabilities describe accepted coordinate bindings and optional operations
  such as multi-axis assignment, uncertainties and markers. Unsupported requests
  produce explicit results. Required sequence requests raise meaningful errors;
  optional extremum annotations may warn and continue. Hide or disable controls
  that the active display cannot support.
- A missing display retains existing headless behaviour: no plotting is required
  for acquisition to continue. Document completed no-display submissions rather
  than waiting for acknowledgements from a nonexistent renderer.

## State, replacement and compatibility

Service state holds plotted snapshots and shared presentation descriptors.
Renderer-specific state holds Cartesian axis sides/mappings, view ranges, active
mouse axes and legend sizing, or later camera/colour-map settings. Add an explicit
export/import API; do not obtain state by reflecting over private widget members.
User changes inside the Cartesian controls must update exported/service state,
including styles, axes and visibility, so replay cannot restore stale settings.

Initially allow switching only while the measurement engine is idle and all
outstanding requests have finished. Live switching is a later feature.
Create a candidate, validate its capabilities and hydrate it before committing
the replacement. Keep the existing display on failure. After success, disconnect
old renderer signals, explicitly close its graphics, then schedule deletion.
Commands stay attached to the stable service throughout. Generation identifiers
prevent any stale result from being attributed to the replacement.

Reject a switch that cannot represent current required coordinate bindings;
report the incompatible series. A plugin-specific unsupported styling option
can remain stored for switching back, with visible capability feedback. Never
silently reinterpret XY data as polar or 3D data.

Provide a compatibility facade for the current `engine.plot_widget` surface
during migration, with an explicit supported-method list. Preserve old sequence
JSON and generated actions; route old slots through the service once per request.
Do not both render directly and submit a service request. Keep public legacy
signals observable where tests/external clients rely on them. Renderer-specific
`pg_widget` access remains an explicit Cartesian-only escape hatch, outside the
portable contract. Add a separate public host/display accessor for GUI inspection.

First-stage display choice belongs to the application, matching the current
shared main plot across sequence documents. Persist factory ID and versioned
renderer settings through QSettings; use Cartesian when a saved factory is
unavailable. Do not persist measurement arrays there. Per-sequence display
recipes and reproducible visualisations in saved data require a subsequent
schema decision.

## Implementation stages and gates

1. **Agree the contract and baseline.** Finalise the records, capability rules,
   compatibility facade and state ownership above. Catalogue current public
   consumers and establish focused Cartesian/command integration baselines.
   Gate: API examples cover point append, trace-with-errors, clear and markers,
   plus a future three-channel binding without relying on widget internals.
   Keep generalised `x`/`y`/`z` slots and explicit coordinate-system metadata,
   including cylindrical and spherical mappings, in these examples.
2. **Introduce service routing with the current renderer fixed.** Add tickets,
   GUI dispatch and a Cartesian bridge. Migrate engine readiness, point/trace
   commands, clear/marker commands, extremum annotations and axis selectors in
   bounded batches. Consolidate split data/axis/style emissions into complete
   requests while retaining compatibility observations. Gate: real worker tests
   show GUI-only rendering, correct ordering, propagated failure and stop-safe
   waits; existing sequence JSON and generated scripts still work.
3. **Introduce host, factory contract and discovery.** Wrap the existing widget
   as the bundled Cartesian plugin and replace MainWindow's direct construction
   with the stable host. Leave embedded charts intact. Gate: a deliberately
   minimal test display accepts data without PyQtGraph-specific API, while
   missing/broken factories fall back predictably.
4. **Complete replacement and state lifecycle.** Implement explicit Cartesian
   export/import and state-change reporting, idle replacement, replay, failed
   switch rollback, scoped teardown and versioned settings. Gate: switching away
   and back preserves supported data, labels, errors, styles, visibility, marker
   anchors, axis mappings/ranges and legend sizing; no duplicate signals or
   stale completions appear. Unsupported requests terminate cleanly.
5. **Document and hand over.** Publish display-plugin author guidance and public
   API examples in Sphinx, retain the compatibility import/facade, and record
   verified test results in `notes/testing_restructure_plan.md`. Gate: no ordinary
   plot producer reads renderer internals; a second factory can be added without
   changes to MainWindow, SequenceEngine or existing Cartesian producer paths.

Stage 4 completes the requested first step: one functional, replaceable Cartesian
display and a proven contract. Subsequent development adds polar, intensity-map
and 3D plugins one at a time with their own data-binding UI, capability tests and
rendering dependencies. No new rendering-library choice is required now.

## Validation plan and risks

Preserve the existing modules under `tests/unit/ui/widgets/`, plot-command tests,
extremum transform tests and `tests/integration/app/test_main_window.py`. Add
contract/service tests under `tests/unit/core/` and host/adapter tests under
`tests/unit/ui/`, following `notes/testing_guidelines.md`. Update the migration
log when tests move or substantive coverage is added.

Use `managed_qt_widget` for test-owned hosts/renderers and the project Conda
environment with offscreen Qt and Windows fonts. Test supported Qt bindings in
CI; future OpenGL displays need separate rendering-capability checks. Preserve
axis click activation, bottom/left defaults, active-axis marker placement and
existing marker anchors, manual ranges, error bars, colour cycling, point/trace
styles, nonlinear mappings and splitter behaviour.

Specific regression cases include duplicate attach/detach, producer mutation
after submission, multiple queued commands, clear/update ordering, no-display
execution, GUI-side failure, request timeout, pause/stop/shutdown, switch refusal
during execution, capability rejection, failed plugin imports and old settings.
Measure memory/copy costs and responsiveness on representative large traces;
avoid adding per-point copies of whole datasets.

The initial investigation used source inspection only. Stage 1 supplies
validated records, capability rules, executable API examples, documented facade
semantics and a focused Cartesian/command baseline. See the
[Stage 1 contract and handover](2026-10-01-plot-contract-stage1.md) and the
[testing log](testing_restructure_plan.md) for implementation and validation
evidence. Stage 2 now implements service routing, completion tickets and a fixed
Cartesian bridge. Its worker, failure, cancellation and compatibility evidence
is recorded in the [Stage 2 service handover](2026-10-01-plot-service-stage2.md).
Stage 3 supplies a stable host, separate factory protocols/registry and bundled
Cartesian factory. A deliberately minimal test display accepts real worker
commands without Cartesian widget methods; startup failures fall back to the
bundled display. See the [Stage 3 host handover](2026-10-01-plot-host-stage3.md).
Stage 4 supplies explicit Cartesian export/import, idle transactional replacement,
rollback, scoped old-display teardown, generation advancement and versioned
preferences. The UI is **View → Plot display**. See the
[Stage 4 replacement handover](2026-10-01-plot-replacement-stage4.md).
Stage 5 publishes the [display author guide](../docs/plot_display_plugins.rst)
and a tested independent Qt example factory. See the
[Stage 5 handover](2026-10-01-plot-display-stage5.md).
All five stages are complete. Cartesian is the only bundled production renderer.
The [command extension plan](2026-10-01-plot-command-extension-plan.md) details
optional `Z(X, Y=fixed)` trace slices in a loop, `(X, Y, Z)` points in nested
loops, surface grouping/topology and capability-aware controls while retaining
current XY behaviour. New intensity, polar and 3D displays remain subsequent work.
