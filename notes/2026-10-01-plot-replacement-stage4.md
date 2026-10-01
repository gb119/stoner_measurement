# Plot display replacement Stage 4 handover

Stage 4 of the [approved plan](2026-10-01-plot-display-plugin-plan.md) is complete.
The first implementation step now has a replaceable Cartesian display, stable
producer endpoint and tested state/lifecycle contract. Cartesian remains the only
bundled production rendering option; the non-PyQtGraph memory display is a test
adapter proving replacement without a renderer-specific producer API.

## UI and ownership

**View → Plot display** lists discovered factories and checks the active factory.
The selection is application-wide across sequence documents. A refused switch
shows its diagnostic and restores the previous checkmark. Successful switches
with unsupported style preferences show status-bar feedback. Third-party packages
add choices through `stoner_measurement.plot_displays`; no alternative production
display is added by this stage.

`PlotDisplayHost.switch_display(factory_id)` owns replacement. It reserves an idle
plot service, checks the application's engine-idle callback, exports current
state, constructs a hidden candidate and hydrates it. The host checks capability
support and hydrated descriptions before committing. Required incompatible
bindings, axes or markers refuse replacement; coordinate systems are never
reinterpreted. Factory/import/hydration failures retain the current display,
shared source data and generation. Candidate cleanup is scoped to its own widget
container and adapter resources.

Successful commit keeps the same service and engine attachments, advances the
generation once, disconnects old renderer signals and explicitly closes its
graphics before deferred deletion. Completed tickets keep their original result
and generation. Pending requests prevent switching; new submissions during
hydration are rejected before acceptance. A renderer cleanup or settings-save
failure after successful commit is reported as a diagnostic without closing the
new active display. Closing the host saves preferences when possible and always
shuts down requests before closing owned graphics.

The application supplies `SequenceEngine.is_plot_idle`. Queue task accounting
covers both scripts and REPL commands, including queued work and paused execution;
it does not rely only on the pre-existing running-script flag. Standalone hosts
can supply their own `idle_check`; their service's pending-work gate remains active.

## Explicit state and settings

`core/plotting/state.py` supplies immutable `DisplayState`, `SeriesState` and
`MarkerState`. The records contain portable data, source-coordinate bindings,
axis descriptions, current visibility, stable marker IDs and resolved anchors.
Renderer preferences accept only finite JSON-compatible values, rejecting arrays
and graphics objects. Preferences are captured independently of caller mutation.

`PlotWidget.export_plot_state()` and `import_plot_state()` are explicit public
APIs implemented inside the owning widget. The host/adapter does not reflect over
private widget members. Export reads current controls rather than replaying the
original producer's presentation: data/errors, titles, styles, widths/sizes,
visibility, axis assignment, labels, scales/parameters, source ranges, per-bound
automatic range state, side/order, grid and active axes, marker anchors/labels/IDs,
legend sizing, next marker identity and automatic colour cycle are preserved.
The service merges canonical source channels, bindings, coordinate descriptors
and channel metadata, including auxiliary channels not drawn by Cartesian.

Marker addition/removal, label updates, manual axis gestures and legend resizing
notify public state changes. Replay restores data first and final labels/ranges
after trace creation so accumulated labels and auto-ranging cannot overwrite
user controls. Automatic markers retain their resolved anchor and automatic-label
behaviour. A renderer may declare `supported_styles`; unsupported keys are retained
in host state for switching back and reported visibly. Required data layouts and
coordinate systems cannot be downgraded this way.

The application uses QSettings `plotDisplay/preferences` for the selected factory
and per-factory versioned renderer preferences. The envelope and Cartesian settings
are version 1. Preferences contain no measurement or plotted arrays. Restart
restores the selected factory and settings without restoring acquired series.
Missing saved factories, unsupported envelope versions, and malformed Cartesian
settings use Cartesian defaults with diagnostics. `save_preferences()`, successful
replacement and close persist controls. Individual renderer settings are cached
separately so switching back restores Cartesian legend and layout preferences.

Adapters supporting replacement implement `export_state()` / `import_state()`
and `export_settings()` / `import_settings()`. Stage 3 adapters without replay
methods can still be used at startup but replacement involving them is refused
with a diagnostic. Embedded charts and scan previews retain their standalone
`PlotWidget` API.

## Validation and next work

Added 12 replacement/state cases in
`tests/unit/ui/test_plot_display_replacement.py` and two menu cases in
`tests/integration/app/test_plot_display_menu.py`. Existing tests were not moved
or rewritten. Coverage proves non-PyQtGraph round trips, current UI presentation,
data/errors, hidden traces, exact legend height, named-axis mappings/ranges,
active axes, marker identities/anchors, source metadata and auxiliary channels,
generation stability/advancement, hydration/capability failures, queued engine
and plot refusal, reentrant submission refusal, unsupported style preservation,
restart preferences, corrupt settings, array exclusion and UI feedback.

Focused legacy/engine/application regression passed 294 tests; final menu/state
checks passed 14. Final full suite: **3,834 passed, one skipped**, 3,835 collected,
69.37 seconds, using `pytest -q --tb=short -p no:cacheprovider
--basetemp=.pytest-runtime/plot-stage4-full`. Output is retained locally in
`.pytest-runtime/plot-stage4-full.log`. Commands used the project Conda environment,
Python 3.14.7, offscreen PyQt5 5.15.11 and Windows fonts.

Changed-file Ruff checks and formatting, focused mypy (11 source files),
`git diff --check`, and all 15 plotting documentation doctest examples passed.
Sphinx built successfully with the existing 497-warning API documentation baseline.
This does not establish other Qt bindings' CI results, instrument bench validation
or GPU/OpenGL compatibility. No production alternative renderer was validated.

Stage 5 can review the final public author guide and examples; subsequent work
adds polar, intensity and 3D factories individually, with binding UI and their own
capability/rendering tests. Preserve generalised x/y/z slots, explicit coordinate
system metadata and the stable client. No acquisition-data schema migration is
needed for this replacement foundation.
