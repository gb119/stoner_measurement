# Plot command extensions for surfaces and generalised coordinates

Status: command implementation authorised by the user on 2026-10-02. Stages 1
and 2 are complete: optional surface contract, command bindings/persistence and
live configuration refresh. Stages 3/4 now provide native PyQtGraph Cartesian
XYZ and XY intensity factories; angular coordinate renderers remain future work.
The five-stage display foundation supplies the stable client, immutable data,
factory discovery and idle replay. The original design below records the intended
workflows; the decisions in the implementation section resolve its open choices.

## 2026-10-02 implementation decisions

### 2026-10-06: blank Plot Trace surface identities

- Saved empty/missing/whitespace surface-ID expressions now receive a unique
  persistent literal on restoration. Clearing the editor after loading generates
  one on execution, reused by every later slice. Explicit expressions retain
  validation: their results must be nonblank strings. Titles remain independent
  of grouping. The editor explains the automatic default.
- Triangle I-V traces revisit current coordinates and cannot represent a
  single-valued rectilinear row in full. No samples are silently discarded or
  averaged. For the reported 501-point, phase-zero, one-period triangle, X/Z
  expressions sliced with `[125:376]` select the descending monotonic branch.
  Sample-index X is another option when preserving the whole acquisition matters.
  The repeated-slice replacement policy does not resolve repeated X within a row.
- Regression coverage and local validation are recorded in
  `notes/testing_restructure_plan.md`.

### 2026-10-06: automatic trace re-gridding

- Follow-up user instruction supersedes the manual triangle-branch workaround
  and the original no-interpolation producer policy. The canonical accumulator
  still validates exact finite, unique grid cells. Plot Trace now prepares rows
  before immutable submission; XY plots and instrument-produced tables are intact.
- Default `regrid_policy="mean"` sorts X and combines repeated coordinates,
  including round-off equivalents within 64 machine eps times the source scale.
  `first`/`last` select acquisition-order samples; `strict` preserves the exact
  original requirements. Mean ignores missing signals, leaving all-missing
  groups missing. The UI explicitly explains that averaging merges branches.
- The first accepted row establishes a sorted X grid. The standard service's
  optional thread-safe `surface_x_grid(series_id, acquisition_id)` accessor reads
  it without assembling a full sample snapshot. Later rows interpolate onto it.
  Replayed grids remain authoritative; clear/removal/new acquisition removes or
  replaces the grid. Clients lacking the optional accessor can still prepare
  duplicate coordinates, but require matching grids between rows.
- Default `regrid_bounds="nearest"` holds the nearest valid boundary sample
  outside a row's measured range, as requested by the user. `missing` leaves NaN
  gaps instead. Internal NaN samples are not bridged. Z and independent value
  channels use the same coordinates; uncertainties propagate as independent
  errors through mean/interpolation. Branch spread does not create error bars.
- Settings round-trip with older JSON receiving the automatic defaults. Managed
  configuration pages expose both controls. Developer validation is recorded in
  `notes/testing_restructure_plan.md`.

### Original implementation

- Bundled `cartesian_3d` and `intensity` factories use native PyQtGraph. XYZ uses
  `GLViewWidget`, `GLMeshItem`, lines and points; the only additional dependency
  is PyOpenGL, explicitly selected by the user. Intensity uses sparse Qt picture
  cells in a PyQtGraph scene, including nonuniform coordinate spacing. Neither
  builds a dense Cartesian product or fills unacquired cells. 3D triangles
  require all four finite corners of a neighbouring rectangle.
- GUI adapters retain incremental `SurfaceGrid` cells. A single-shot 40 ms
  timer coalesces painting; logical application/acknowledgement is immediate.
  Snapshots and graphics are assembled only on repaint or explicit export.
  Camera and manually zoomed XY bounds survive data updates. Palettes and
  automatic/fixed colour limits use bundled maps without Matplotlib.
- Both factories implement replay/settings, descriptions and owned cleanup.
  Linear axes, titles, visibility, remove-series and clear are supported;
  uncertainty, marker and nonlinear-axis requests are explicitly unsupported.
  Angular coordinates and per-slice visibility remain outside these factories.
  Switching display refreshes existing command pages through the service's
  public descriptions/capabilities signal.

- Optional `SeriesUpdate.surface: SurfaceBinding` uses extension version one,
  negotiated by `PlotCapabilities.surface_versions` (empty for existing factories).
  The base factory/message version remains one: ordinary requests are unchanged,
  and factories must explicitly opt into surface semantics. XYZ acceptance alone
  does not imply assembly support. Independent value uncertainty has its own
  `value_uncertainties` flag.
- One surface is one series: its ID is independent of its displayed title. Slice
  updates insert/replace a whole fixed-Y row under an explicit slice ID (default
  exact fixed-Y representation). Cell updates address exact finite X/Y pairs.
  Duplicate rejection is the default; an explicit replace policy permits
  reacquisition. Slice IDs retain their Y; complete trace slices retain the first
  X grid. Acquisition IDs change only with explicit reset, or after clearing.
- Service-owned `SurfaceGrid` retains incremental cells and slice catalogues.
  Only snapshots assemble sorted Y/X samples. Missing cells remain absent, signal
  NaNs remain missing values, and source schema/units/errors remain consistent.
  Snapshot descriptors carry slice ID/Y pairs through transactional idle replay.
  Existing visibility/removal address the entire surface; independent slice
  visibility/removal and interpolation are outside this extension.
- Both commands default to XY for old JSON. Additional forms have independent
  X/Z/value and fixed-Y/point-Y expressions; point Z entries have distinct surface
  identities. Expressions resolve once at execution before immutable capture.
  Metadata comes from catalogues where possible; trace fixed Y has label/unit
  controls. Existing XY fields, transpose and multi-Y behaviour retain their meaning.
- Configuration pages use widget-owned subscriptions to the stable service's
  `descriptions_changed`, rebinding when their engine changes. They compare axes
  and capabilities, avoiding refresh on data-only updates. Current supported
  forms are offered; saved unsupported forms/axes retain their bindings. New
  controls occupy a bounded scroll area; XY controls are hidden for other forms.
- A non-graphics test adapter validates real worker-loop submissions and replay.
  No production intensity/3D renderer or graphics dependency is introduced.

### Verification and handover

- Added 44 cases: `tests/unit/core/test_plotting_surfaces.py` (19) and
  `tests/integration/sequence/test_plot_surface_commands.py` (25). Existing
  tests remain in place. Coverage includes real worker loops and generated saved
  actions, multiple measured channels, exact/serpentine cells, metadata/schema,
  fixed-Y/shape validation, duplicate policy changes, run resets, partial/missing
  values, immutable inputs, replay/refusal, failure rollback, headless execution,
  capability-gated cached controls and catalogue refresh. A 1,001-cell case
  verifies that incremental acquisition does not assemble/copy the complete grid.
- Full suite: **3,880 passed, one skipped**, 3,881 collected, 95.11 seconds.
  Command: `pytest -q --tb=short -p no:cacheprovider
  --basetemp=.pytest-runtime/plot-command-extensions-full`; log:
  `.pytest-runtime/plot-command-extensions-full.log`.
- Final focused regression after documentation/import cleanup: **212 passed**.
  Changed-source/test Ruff check and formatting, mypy for seven source files,
  `git diff --check`, and all 15 plotting-contract doctests passed. Sphinx HTML
  built with the existing 497-warning baseline. Both XYZ configuration pages
  were rendered and inspected offscreen; bounded/scrolling controls retain
  readable editors at 540px width.
- Used project Conda, Python 3.14.7, offscreen PyQt5 5.15.11 and Windows fonts.
  No hosted cross-binding CI, physical instrument or GPU validation is claimed.
  Additional forms require a factory explicitly advertising surface extension
  version one and the matching layouts/presentations; the bundled Cartesian
  factory and diagnostic example remain XY-compatible displays.

## Intended acquisition workflows

Preserve the current Cartesian XY behaviour without reinterpretation:

- Plot Trace replaces a `Y(X)` series, including existing multi-channel selection,
  error bars, expressions, labels and axis assignments.
- Plot Points appends `(X, Y)` samples for its configured dependent channels.
- Existing sequence JSON and generated scripts retain those meanings, even when
  the application selects a different display. A display must explicitly support
  the requested layout; unsupported forms produce an actionable diagnostic.

Add two complementary surface acquisition workflows:

1. **Trace slices in one loop.** Each iteration acquires arrays of X and measured
   Z. The loop variable supplies a fixed Y coordinate for that complete trace.
   Plot Trace submits `Z(X, Y=fixed)` with equal-length X, repeated-Y and Z
   channels. Successive iterations add slices to one surface. Reacquiring a
   slice replaces that slice only when the configured duplicate policy permits.
2. **Points in nested loops.** The outer loop supplies Y, the inner loop X, and a
   measurement supplies Z. Plot Points submits `(X, Y, Z)` rows to the same
   surface. Coordinates, rather than acquisition order, identify grid cells, so
   reverse or serpentine inner loops do not scramble the resulting surface.

Illustrative sequence trees (these are proposed UI workflows, not executable
Python API examples):

```text
Loop temperature T:
    Acquire voltage trace V(field)
    Plot Trace: X=field, fixed Y=T, Z=voltage, surface="field-temperature"

Loop temperature T:
    Loop field H:
        Measure voltage V
        Plot Points: X=H, Y=T, Z=V, surface="field-temperature"
```

Evaluate the fixed-Y expression once on every trace execution, using the live
engine namespace after acquisition. Capture the value with the submitted data;
never defer reading the changing loop variable until GUI application. Point
coordinate/value expressions are likewise evaluated once per execution.
Neither command owns or controls the surrounding loops or instrument sessions.

## Coordinate slots and presentation

Keep `x`, `y` and `z` as generalised coordinate slots. Cartesian defaults remain
unchanged. Explicit descriptors define polar, cylindrical or spherical meanings,
angular units, wrapping, orientation and the spherical angle convention. Fixed-Y
means the second declared coordinate, for example a fixed azimuth in cylindrical
coordinates; it does not always mean a Cartesian vertical axis.

Distinguish geometric coordinates from an independent measured intensity:

| Requested form | Source channels | Binding and intent |
| --- | --- | --- |
| Existing XY | X, Y | `x=X, y=Y`, Cartesian 2D, line/points |
| XY intensity map | X, Y, measured Z | `x=X, y=Y, value=Z`, Cartesian 2D, intensity |
| XYZ surface/points | X, Y, geometric or measured height Z | `x=X, y=Y, z=Z`, Cartesian 3D, surface/points |
| Coloured 3D display | X, Y, Z, independent signal | three coordinates plus explicit `value`, 3D presentation |

Both surface acquisition workflows can supply the first two additional forms.
The user selects the intent explicitly; selecting another renderer does not
rewrite a command's `z` binding into `value` or convert XY to polar coordinates.
Do not infer any binding from `TraceData.COLUMN_ROLE_Z`, since it also denotes
ordinary auxiliary dependent channels. Projection belongs to the renderer and
must not overwrite acquisition tables or source units.

## Proposed command controls and persistence

Add a persisted form selection, defaulting to **XY** when the field is absent.
Offer **XY intensity** and **XYZ** only where their complete requirements can be
represented. Keep existing XY controls and serialized attributes intact.

For Plot Trace's additional forms, expose:

- X trace channel and measured Z trace channel, or separate advanced expressions.
- A **Fixed Y** expression evaluated per execution, plus label/unit metadata when
  it cannot be derived from a selected catalogue channel.
- Surface identity expression and displayed title; an optional explicit slice
  identity expression for irregular acquisitions.
- Presentation, coordinate descriptor and applicable uncertainty/style controls.

For Plot Points, expose X and Y scalar sources/expressions and one or more
measured Z entries. Each Z entry has a stable surface identity and displayed
label, preserving the existing ability to plot several measured channels.
Add an optional independent value source only for explicitly coloured 3D intent.

Use separate new Z and fixed-Y fields rather than changing the meaning of
existing `y_expr`, `y_entries` or selector keys. Build one complete immutable
request after resolving all channels. Scalar fixed Y is broadcast to the trace
row count; X/Z arrays must have equal lengths. Reject mismatches and non-scalar
fixed-Y values before submission. Preserve ordinary XY NaN/error-bar semantics;
surface grid validation applies additional rules described below.

Round-trip the new fields in sequence JSON with backward-compatible defaults.
Generated actions call the configured plugin through existing engine mechanisms;
they must evaluate expressions at execution, not generation. UI controls use
shared widgets and existing catalogue labels. Keep pages concise and top-packed.

## Capability discovery and UI behaviour

Use `engine.plot_client.capabilities()` and public axis/series descriptions.
Inspect coordinate-system/dimension `layouts`, `presentations`, `operations`,
`uncertainties` and `value_channel`, then check the complete proposed request.
An XYZ renderer can advertise both Cartesian 2D and 3D when it supports both;
three-coordinate support alone does not imply support for existing XY requests.
An XY intensity renderer needs a two-coordinate layout and an independent value
channel, not a three-coordinate layout.

Surface assembly also needs an explicit negotiated capability, because accepting
three-coordinate points does not imply grouping slices into a surface. Define
that extension before enabling surface modes in commands. The version-one
capabilities and records do not yet advertise grouping or topology support.

Show the current supported forms in configuration pages, refreshing after a
successful idle display change. Retain and visibly mark an already-saved form
that the active display cannot support; do not clear bindings or silently switch
it back to XY. Revalidate on execution, including scripted or headless execution.
Keep headless acquisition's existing no-display completion semantics.
Renderer identity is available through the GUI host's `factory_id`; commands
must branch on capabilities rather than specific factory names. Do not add
renderer-object inspection to worker commands.

## Which existing plotting APIs to use

| Requirement | Existing API | Implementation note |
| --- | --- | --- |
| Discover accepted forms | `engine.plot_client.capabilities()`; `PlotCapabilities.layouts`, `presentations`, `operations`, `uncertainties`, `value_channel` | Query through the stable client, never the widget. Handle a missing client/capabilities for headless execution. Surface grouping needs an additional capability. |
| Check a concrete binding | `capabilities.unsupported_reasons(PlotRequest(update))` | Checks structural support. The adapter still validates domain/style/state before mutation. Check again at execution. |
| Refresh axes/selectors | `client.axes()`, `client.series()`; concrete service `descriptions_changed` Qt signal | Use immutable public descriptions. Follow existing public-selector patterns; do not read `_axis_orientations` or graphics objects. Notify forms after idle replacement as well as axis edits. |
| Capture source samples | `PlotData(channels, metadata, uncertainties)`; `ChannelMetadata(label, unit)` | Copies arrays into immutable snapshots. Trace fixed Y must be expanded to row count first. Metadata/error dictionaries use source channel keys. |
| Declare meanings | `CoordinateBinding(x, y, z=None, value=None)`; `CoordinateDescriptor` | Coordinate keys name source channels. Cartesian is the compatible default; angular systems need explicit descriptors. Height binds to `z`; map intensity binds to `value`. |
| Submit a trace/slice | `SeriesUpdate(..., mode=UpdateMode.REPLACE)` | Current semantics replace one identified series. Distinct slice IDs avoid replacement of prior slices, but shared-surface grouping requires a new descriptor/payload. |
| Submit individual points | `SeriesUpdate(..., mode=UpdateMode.APPEND)` | Appends rows of one identified series. APPEND must retain channel schema, metadata, coordinate bindings and uncertainty keys. Grid-cell deduplication/replacement is a new surface policy. |
| Route from command plugins | `CommandPlugin._submit_plot_operation(payload)`; shared `submit_from_plugin(plugin, payload)` | Existing helpers select GUI `apply_now` or worker `submit`, wait through the engine and propagate required failures. Do not additionally connect rendering signals. A new unsupported non-XY form must not fall through to old XY slots. |
| Route from other producers | `client.submit(PlotRequest(payload))`; `CompletionTicket`; `SequenceEngine.wait_for_plot_ticket(ticket)` | Workers use the engine wait for pause/stop handling. Accepted requests receive one terminal `PlotResult`; inspect `ResultStatus` and its diagnostic. A wait timeout alone does not cancel a request. |
| Clear/style/visibility | `ClearPlot`, `ModifySeries`, `RemoveSeries`, axis and marker payloads | Check operation support. Existing identities address individual series; define whole-surface/slice reset and removal in the extension rather than overloading titles. |
| Replay acquired state | `DisplayState`, `SeriesState`, `MarkerState`; adapter `export_state`/`import_state` | Service merges canonical data with current user presentation. Extend this explicit model for surface grouping/cell policies, including partial acquisition. No graphics-object reflection. |
| Preserve bounded incremental data | `PlotService.data_snapshot(series_id)` and service append chunks | Snapshot assembles canonical samples on demand. Keep production per-point updates incremental; do not call full snapshot on every cell. Surface policy needs canonical incremental assembly alongside the existing series model. |
| Register/render | `PlotDisplayFactory`, `PlotDisplay`, `PlotDisplayRegistry`; `stoner_measurement.plot_displays` entry points | Factories expose metadata without constructing widgets; adapters apply only on the GUI thread. Existing `MainWindow` and engine wiring need no renderer-specific branches. |
| Replace/save preferences | `PlotDisplayHost.switch_display`, adapter state/settings methods | Host checks idle/capabilities, hydrates before commit and retains the original on failure. Extend source replay, keep palette/camera settings as versioned JSON without arrays. |

These APIs live under `src/stoner_measurement/core/plotting/` and
`src/stoner_measurement/ui/plotting/`. The existing producer helper `xy_update`
in `core/plotting/producers.py` intentionally remains XY-only. Add a separate
generalised binding helper there for new forms; do not change its default
meaning. `PlotClient`/`PlotTicket` protocols are in `contracts.py`; Qt completion
and description signals belong to the concrete service, outside those protocols.

For example, the current records can already express a single XYZ trace slice:

```python
import numpy as np
from stoner_measurement.core.plotting.contracts import (
    ChannelMetadata, CoordinateBinding, PlotData, Presentation,
    SeriesUpdate, UpdateMode,
)

x_samples = np.array([0.0, 1.0, 2.0])
z_samples = np.array([4.0, 5.0, 6.0])
fixed_y = 10.0  # Resolve once from the live loop expression on this execution.
slice_update = SeriesUpdate(
    series_id="slice-1",  # Explicit identity; this string is not parsed for grouping.
    data=PlotData(
        {"field": x_samples, "temperature": np.full(x_samples.shape, fixed_y),
         "voltage": z_samples},
        metadata={"field": ChannelMetadata("Field", "T"),
                  "temperature": ChannelMetadata("Temperature", "K"),
                  "voltage": ChannelMetadata("Voltage", "V")},
    ),
    binding=CoordinateBinding(x="field", y="temperature", z="voltage"),
    presentation=Presentation.LINE,
    mode=UpdateMode.REPLACE,
)
```

For an XY intensity slice, retain the channels and instead bind
`CoordinateBinding(x="field", y="temperature", value="voltage")` with
`Presentation.INTENSITY`. For one XYZ point, supply one-element arrays and
`Presentation.POINTS`/`UpdateMode.APPEND`. An assembled XYZ surface uses
`Presentation.SURFACE`; changing the presentation alone does not define topology.
The bundled Cartesian factory rejects these new requests; use a conforming
test adapter until the relevant production renderer exists. This example carries
one slice, not a shared surface or grid. Stage 1 below must add and negotiate
that missing information before command surface modes are enabled.

## Surface identity, slices and portable state

Separate three identities: the acquisition source, the displayed surface and
the trace slice. Titles are user-facing labels and must not determine grouping.
Two measured Z channels from the same acquisition are distinct surfaces unless
the user explicitly selects another arrangement.

Define a portable, immutable grouping/topology extension in a contract-first
stage. It must carry surface identity, slice/cell identity, assembly policy and
the source bindings. Decide there whether this is a new payload or a descriptor
on `SeriesUpdate`, and whether negotiation requires contract version two.
Do not sneak unrecognised fields into style dictionaries or rely on series-name
prefix parsing. Version-one factories must reject the new form predictably.

A logical trace update replaces/inserts one whole slice atomically in canonical
state. Stable slice identity must permit reacquisition without clearing other
slices. Point updates append/replace cells in the same canonical surface model.
For repeated Y slices or repeated `(X, Y)` cells, support an explicit replacement
policy; initially reject ambiguous duplicates by default. A new run must have
an explicit reset/new-surface policy, rather than inheriting stale cells solely
because the displayed title is unchanged. Reuse the existing clear command for
application-wide reset; specify any targeted reset as part of the new payload.

Canonical source data and assembly descriptors belong to the service. Renderers
own camera, projection, palette, colour limits and view settings. Export/import
must preserve grouping, slices/cells, bindings and acquired values during idle
replacement, including partially acquired surfaces. Preferences must still
exclude measurement arrays. Define removal and visibility semantics for a whole
surface and for slices before adding their UI.

## Initial grid policy

Start with an explicitly selected rectilinear grid policy, with no automatic
interpolation or extrapolation:

- For trace slices, establish the X grid from the first slice and require later
  slices to use compatible X coordinates and bindings. Irregular/variable-X
  traces require an explicitly supported later topology rather than reshaping.
- For nested-loop points, map coordinate pairs to cells independently of visit
  order. The model records incomplete cells as missing; renderers show gaps or
  masks while acquisition proceeds. Do not manufacture zero-valued measurements.
- Do not silently merge near-equal floating-point coordinates. Define exact
  coordinate keys or an explicit user-configured tolerance/grid catalogue.
- Reject non-finite grid coordinates; measured signal NaNs remain missing data.
  Define duplicate coordinate handling and coordinate sorting independently of
  acquisition order. Avoid joining across missing cells accidentally.
- Keep source units/metadata consistent across slices/cells. Define uncertainty
  interpretation separately for height/intensity and projected coordinates;
  declare unsupported cases rather than drawing misleading error bars.

Large acquisitions require append/chunk storage and incremental graphics
updates. Avoid rebuilding every slice or copying the entire surface at each
point. Surface topology must remain separate from acquisition table persistence;
this plan does not migrate instrument-produced `TraceData` schemas.

## Implementation stages and review gates

1. **Agree surface records and policies.** Finalise grouping, reset, duplicate and
   grid semantics, immutable ownership, capability/version negotiation and state
   export/import. Publish complete requests for a trace slice and a nested-loop
   point. Gate: no renderer name or implicit channel interpretation is needed.
2. **Extend command binding and persistence.** Add the optional forms, runtime
   fixed-Y evaluation, explicit channels and controls to Plot Trace/Plot Points.
   Use a lightweight conforming test display before choosing graphics libraries.
   Gate: old JSON/generated actions keep XY behaviour; real worker loops retain
   every slice/cell with the correct iteration coordinate and one completion.
3. **Implement one XY intensity factory.** Deliver incremental grid display,
   visible gaps, palette/limits, source-coordinate pointer readout and explicit
   replay/preferences. Gate: trace-loop and nested-loop acquisitions produce the
   same rectilinear surface, including serpentine traversal and partial grids.
4. **Implement XYZ/generalised renderers separately.** Choose dependencies after
   reviewing deployment/backend support. Add camera/projection and angular
   coordinate behaviour with explicit capabilities and separate tests. Gate:
   compatible idle switching preserves source samples, grouping and settings;
   unsupported layouts/topologies retain the original display with diagnostics.

Keep checks in the existing test layout and record each authorised stage in
`notes/testing_restructure_plan.md`. Cover dynamic loop expressions, multiple
Z channels, identity collisions, repeat/reset policies, missing/non-finite cells,
metadata/schema mismatch, capability changes, pause/stop, failed application,
headless execution and queue completion. Include large incremental acquisitions
and binding/backend checks appropriate to each concrete renderer. Do not claim
GPU or alternative Qt-binding validation from the current offscreen PyQt5 tests.

See [display-plugin foundation plan](2026-10-01-plot-display-plugin-plan.md) and
[author guide](../docs/plot_display_plugins.rst). This follow-on plan records the
requested loop/surface workflows; the implementation decisions above describe
the delivered Cartesian features and the remaining angular-coordinate scope.
