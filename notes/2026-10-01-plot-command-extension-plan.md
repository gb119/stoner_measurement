# Plot command extensions for surfaces and generalised coordinates

Status: documented follow-on design; implementation is not yet authorised by
this plan. The five-stage display-plugin foundation supplies the stable client,
capability discovery, immutable data records, factory discovery and idle replay.
This plan extends command data binding and defines the additional surface model
before introducing production heatmap or 3D renderers.

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
requested loop/surface workflows; it does not imply that surface assembly or
three-coordinate command controls already exist.
