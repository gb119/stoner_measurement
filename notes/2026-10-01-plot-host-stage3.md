# Plot display host Stage 3 handover

Stage 3 of the [approved plan](2026-10-01-plot-display-plugin-plan.md) is complete.
The main measurement panel now contains a stable display host instead of directly
constructing its Cartesian widget. No live replacement, state replay or saved
display preference is implemented; those remain Stage 4 work.

## Factory contract and discovery

`ui/plotting/interfaces.py` defines version-one display and factory protocols.
Factories expose an ID, display name, contract version, immutable capabilities
and `create(parent)`. Adapters expose their GUI-owned widget, matching capabilities,
a no-argument `changed` signal, portable descriptions, validation/application and
idempotent close. Display factories do not inherit the sequence `BasePlugin`.

`ui/plotting/registry.py` discovers no-argument factory classes through the separate
`stoner_measurement.plot_displays` entry-point group. Discovery loads metadata and
does not construct candidate widgets. Import, creation-of-factory, ID and version
errors are isolated, logged and retained as diagnostics. IDs must match entry-point
names; duplicates are rejected. The bundled Cartesian factory is always registered
from source, including when installed metadata is unavailable, and cannot be
overridden. The matching bundled installed entry point is recognised as the same
factory rather than a collision.

`pyproject.toml` registers `cartesian` as
`stoner_measurement.ui.plotting.cartesian:CartesianDisplayFactory`. Source
registration was verified separately from installed metadata: the current editable
installation has no entries in this new group. It was not reinstalled; the source
fallback is active and third-party discovery is covered with entry-point fixtures.
Factory creation lazily imports the existing Cartesian widget and bridge.

## Host and ownership

`ui/plotting/host.py` is the stable measurement-panel QWidget. It selects a factory
at startup, constructs only that display on the GUI thread, checks ownership,
capabilities, methods/signals and portable descriptions, and owns a child plot
service. Unknown or broken selections fall back to Cartesian with logged and
queryable diagnostics. Failed candidates release their adapter resources and
parented widgets before deferred deletion; factories remain responsible for
non-widget resources acquired before a failed `create()` return.

The host delegates portable operations without requiring Cartesian widget APIs.
Unsupported optional legacy calls terminate with an `UNSUPPORTED` result. Closing
the host shuts down requests and disconnects signals before closing its owned
adapter once. Stage 2 standalone bridges continue borrowing their widgets;
the bundled factory opts into owned close. No global widget cleanup is used.

`MainWindow.plot_display_host` exposes the host and stable service.
`host.display` exposes the GUI adapter. `host.display_widget` and the retained
`MainWindow.plot_widget` accessor expose the concrete GUI widget, including the
explicit Cartesian `pg_widget` escape hatch. MainWindow sizes and closes the host.
The application borrows its service and attaches the existing legacy facade to
the engine. Embedded controller charts and scan previews retain `PlotWidget`.

Configured producer axes now use portable `ConfigureAxes` when supported.
Displays without explicit axis configuration handle axes in their complete data
updates. This preserves eager named-axis creation for Cartesian without requiring
other displays to expose `ensure_x_axis` or `ensure_y_axis`. A compatibility review
also found that point-label editing only emitted the disconnected legacy rename
signal after Stage 2; those edits now invoke the ordered Cartesian compatibility
queue while retaining the observable signal. Legacy identity rename remains an
optional Cartesian operation rather than a new portable identity-change contract.

## Gate evidence and remaining stages

Added 20 cases across `tests/unit/ui/test_plot_display_registry.py` and
`tests/unit/ui/test_plot_display_host.py`; existing tests were not moved or rewritten.
The minimal test adapter is a plain QWidget with portable methods and no
PyQtGraph-specific methods. It receives data from a Python worker and from real
engine trace/point commands hosted inside MainWindow, without changes to the engine
or data request format. Unsupported markers and legacy calls finish cleanly.
Discovery tests cover missing metadata, failed imports, invalid metadata, duplicate
IDs and mismatched entry-point names. Host tests cover missing selections, failed
creation, invalid capabilities/descriptions/signals, partial-widget cleanup,
GUI-only construction, owned close, queued cancellation, configured axes and
Cartesian point-label rename.

Initial focused validation passed 47 tests. After the portable axis refinement,
144 producer/service/host tests passed; the final compatibility test passed with
all ten host cases. The initial complete run passed 3,819 tests with one skip.
Final complete validation, including the compatibility repair, passed **3,820
tests with one skip**, collecting 3,821, in 82.40 seconds. It used
`pytest -q --tb=short -p no:cacheprovider
--basetemp=.pytest-runtime/plot-stage3-final`; output is retained locally in
`.pytest-runtime/plot-stage3-final.log`. See the
[testing log](testing_restructure_plan.md).

Commands use the project Conda environment, offscreen Qt, Windows fonts, Python
3.14.7 and PyQt5 5.15.11. Focused mypy passed for ten service/display source files;
changed-file Ruff checks and formatting passed. The plotting page's 15 doctest
examples passed. Sphinx built successfully with the existing 497-warning baseline.
No other Qt binding, hardware, OpenGL or production alternative renderer is claimed
as validated by this stage.

Stage 4 must define explicit state export/import, idle-only replacement, validation
and hydration before commit, rollback, scoped old-display teardown and versioned
settings. Preserve data, metadata, errors, styles, visibility, markers/anchors,
axis mappings/ranges, active axes and legend sizing. Keep producers attached to the
stable service throughout switching; do not reflect over private graphics state.
