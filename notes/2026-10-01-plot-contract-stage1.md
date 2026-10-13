# Plot display migration: Stage 1 contract and handover

Status: implemented contract; application routing remains unchanged.
Working plan: [display-plugin plan](2026-10-01-plot-display-plugin-plan.md).

## Implemented boundary

`core/plotting/contracts.py` defines version-one sample snapshots, source-channel
metadata, generalised coordinate descriptors/bindings, atomic update payloads,
axis and series descriptions, capability rejection rules and request/results.
`PlotClient` and `PlotTicket` are structural interfaces only. There is no service,
registry, widget replacement, entry-point registration or live selection yet.
The existing `AxisLabel` class and its imports remain untouched; channel metadata
can be converted at the Cartesian adapter boundary in Stage 2.

Executable examples in `docs/plotting_contracts.rst` cover point append, a trace
with errors/labels/style/axes, clear, markers, cylindrical x/y/z and an explicit
spherical convention. Presentation and independent intensity are separate from
coordinates. Existing `TraceData` column-role interpretation is unchanged.

Record constructors reject malformed sample tables and coordinate bindings before
submission. The service must check state-dependent conditions: duplicate request
IDs, unknown series/axes, append schema changes, axis-domain errors and invalid
style values. `PlotCapabilities` covers structural support only. No renderer is
claimed to support a new coordinate system merely because its record exists.

## Compatibility facade agreed for Stage 2

Keep `engine.plot_widget` as a compatibility access path while introducing the
typed service/client. Migrate ordinary producers to requests rather than teaching
every renderer the full Cartesian widget API. The legacy facade must preserve:

| Legacy surface | Required mapping or preservation |
| --- | --- |
| `append_point`, `set_trace`, `set_trace_with_errors` | Complete append/replace requests with captured arrays |
| `set_default_axis_labels`, `set_axis_label` | Label updates through public axis metadata |
| `ensure_x_axis`, `ensure_y_axis`, `add_x_axis`, `add_y_axis` | Configure named Cartesian axes |
| `assign_trace_axes` | Update the series binding to named axes |
| `set_trace_style`, `set_trace_style_from_dict`, `set_trace_visible` | Partial presentation updates |
| `remove_trace`, `rename_trace` | Removal; preserve current collision checks and legacy identity changes |
| `add_data_marker`, `remove_data_marker`, `clear_data_markers` | Source-coordinate marker operations |
| `clear_all` | Clear series, styles, errors, markers, labels and colour cycle; retain configured axes |
| `set_axis_scale`, `set_axis_log_scale` | Supported Cartesian mapping configuration |
| `set_axis_side`, `set_axis_visible`, `set_axis_mouse_active`, `set_axis_grid` | Cartesian axis presentation |
| `set_axis_range`, `reset_all_view_ranges`, `set_rolling_time_window` | Preserve source ranges and auto/manual bounds |
| `x_data`, `y_data`, `trace_names`, `axis_names`, `trace_style` | Read-only public state snapshots |
| `mark_data_update_queued`, `is_busy_for_data` | Temporary counter bridge, retired as ticket producers migrate |
| `wait_for_plot_ready` in generated scripts | Wait on service requests, including timeout/pause/stop semantics |

`pg_widget` is a documented Cartesian-only escape hatch, accessible through the
active display rather than the portable client. Qt lifecycle/sizing and private
members such as `_axis_orientations` do not belong to the compatibility service.
Embedded controller charts retain the current concrete widget and full API.

Preserve legacy signals as observations while migrating their rendering path.
Requests and old signal bindings must never both render the same operation.
Metadata/style requests previously emitted separately must be included in each
new complete data request. Existing getters returning copies must continue to
return snapshots, and new series descriptions separate identity from title.
Legacy rename continues changing the legacy identity; `ModifySeries.title` in
the new contract changes only the visible title.

Return-value compatibility needs explicit thread handling: legacy synchronous
GUI calls such as `add_data_marker` can apply through the same validated GUI
dispatcher immediately and return the marker ID, without waiting on a queued
GUI callback. Legacy worker calls needing return values must use a ticket and
cancellable worker wait. New GUI callers always submit asynchronously. Boolean
marker removal results require inspecting current service state at application.

Legacy `add_data_marker` defaults to bottom/left anchors; retain those defaults.
The new `AddMarker` permits omitted anchors, resolved once at application to
the first active axis in each coordinate slot. Context-menu placement already
uses active axes. An existing marker's anchor never changes on axis selection;
automatic labels/readouts preserve the current widget behaviour.

## Producer and consumer inventory

- `app.py` and `ui/main_window.py`: ownership, engine attachment, size and close.
- `core/sequence_engine.py`: widget reference and worker readiness/pause/stop.
- `plugins/command/base.py`: pending-update registration and response timeout.
- `plugins/command/plot_trace.py`: array/error requests, labels, styles, named
  axes, advanced expressions, JSON and private axis-selection introspection.
- `plugins/command/plot_points.py`: point requests, per-series settings and axes.
- `plugins/command/plot_clear.py` and `plot_markers.py`: clear/annotation wiring.
- `plugins/transform/extremum_locator.py`: optional marker output; unsupported
  annotation warns without discarding the numerical transform result.
- `ui/axis_mappings.py`: physical labels and Cartesian mappings.
- `ui/temperature_panel.py`, `magnet_panel.py` and `pressure_panel.py`: retain
  their standalone plots. Scan-generator PyQtGraph previews are also excluded.

Commands attach signals when their engine changes; changing a widget reference
alone does not rewire them. Stage 2 must route these connections through one
stable endpoint before host replacement begins.

## State ownership and Stage 2 requirements

The application owns the service and host. Engines and plugins borrow the client;
they cannot close a shared display. The service owns current plotted snapshots,
series identities, source bindings/metadata and shared presentation state.
Renderers own graphics and renderer-specific state, including Cartesian axis
placement/mappings, manual ranges, active axes and legend splitter size.
Renderer UI changes must be reflected in exported shared state before replay.
Keep measurements in their existing acquisition store; retain only plotted data
in the service. Do not persist measurement arrays in QSettings.

New requests apply data, axes and style together before acknowledgement. Invalid
requests must not mutate model state. Graphics failures do not promise rollback;
retain the previous valid model snapshot for explicit replay. Append requires
the same channel schema, metadata, binding and coordinate descriptor as the
existing series. Reject incompatible appends instead of silently transforming.

Tickets identify requests, not just global busy state. A wait timeout leaves the
request pending; stop/shutdown explicitly cancel accepted pending requests.
Accepted requests terminate once, including unsupported requests and failures.
Assign generation at dispatch and reject stale renderer completions. Queries
return locked snapshots; only GUI slots access QWidget objects. A detached
display completes with `NO_DISPLAY`, preserving current headless operation.
Retain current pause/stop behaviour in generated readiness waits and test it
with actual worker-to-GUI delivery, not only synchronous mocks.

## Validation evidence

The pre-change Cartesian/command baseline passed 262 tests in the project Conda
environment, offscreen PyQt5 5.15.11, Python 3.14.7. The selection covered plot
widget, mouse axes, trace/point/clear/marker commands, extremum transform and
main-window integration. This establishes current behaviour on the available
binding; it does not establish PyQt6 CI results.

Final checks: 303 combined tests passed, including 41 new contract cases;
the final typed snapshot refinement also passed all 41 contract cases. All 15
documentation examples passed, focused mypy and Ruff checks passed, and full
collection found 3,778 tests. Sphinx built the new page successfully, with
existing unrelated API documentation warnings remaining. Detailed commands and
limits are recorded in the [testing restructure log](testing_restructure_plan.md).
No existing tests are moved or rewritten. Stage 2 is not started by this change.
