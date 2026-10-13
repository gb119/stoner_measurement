# Plot display foundation: Stage 5 handover

All five approved stages are complete. The main Cartesian measurement plot uses
the stable request service, separate factory registry and explicit GUI adapter.
Existing embedded `PlotWidget` imports, XY sequences, generated commands,
active-axis interaction and marker anchors remain compatible. Select installed
displays through **View → Plot display**. Cartesian traces remain the only
bundled production renderer.

## Authoring and follow-on design

`docs/plot_display_plugins.rst` documents external registration, capabilities,
lifecycle, validation/completion, replay, preferences and compatibility. It is
linked from the Sphinx index, contracts and third-party package guide.
`docs/examples/summary_display.py` is a downloadable independent Qt factory and
adapter, accepting compatible trace/point data, append/replace and axis records
with explicit replay/preferences. It rejects unsupported markers, uncertainties
and styles. It is a diagnostic author example, not a bundled production chart.
`PlotDisplay` now specifies typed state export/import and mapping preferences.

The command-extension plan at
`notes/2026-10-01-plot-command-extension-plan.md` preserves existing XY behaviour
and details `Z(X,Y=fixed)` trace slices from one loop, `(X,Y,Z)` points from nested
loops, explicit height/intensity bindings, identities, grid/reset/duplicate
policies and review gates. Its API reuse table covers current capabilities,
records, submission helpers, completion and replay. Grouping/topology need new
negotiated records before surface controls are enabled. This plan documents
subsequent implementation, not implemented surface command modes or renderers.

## Independence audit and final gate

Plot Trace, Plot Points, clear/marker commands and extremum annotations use the
portable service and public axis descriptions. They do not inspect renderer
`_axis_orientations`, `pg_widget` or private graphics state. Remaining `_traces`
lookups refer to the acquisition catalogue. Standalone no-client paths keep
legacy signal routing; the engine facade retains its explicit compatibility API.

The integration tests load the exact published example source and discover its
factory using matching simulated installed entry-point metadata. Existing trace
and point commands run on the actual engine worker inside MainWindow; appends
and switching to Cartesian and back preserve samples. Incompatible markers
refuse replacement while retaining the original. No changes to MainWindow,
SequenceEngine or ordinary producers were needed for this second factory.

## Validation and boundaries

- Focused example/host/registry/replacement/menu checks: **36 passed**.
- Full single-process suite: **3,836 passed, one skipped**, 3,837 collected,
  71.44 seconds: `pytest -q --tb=short -p no:cacheprovider
  --basetemp=.pytest-runtime/plot-stage5-full`. Output:
  `.pytest-runtime/plot-stage5-full.log`.
- Ruff check/format passed for the new example/test and protocol; Ruff also
  checked core plotting, UI plotting and the bridge. Focused mypy passed for
  11 source files. `git diff --check` passed.
- All 15 contract doctests passed. The command plan's XYZ slice example was
  separately executed and checked for three dimensions and repeated Y.
- Sphinx HTML and the downloadable example built with the existing 497-warning
  API baseline; no new author-guide warnings. Output:
  `.pytest-runtime/plot-stage5-docs-final.log`.
- No existing tests moved or removed. Test-owned windows use managed Qt fixtures.
  Used project Conda, Python 3.14.7, offscreen PyQt5 5.15.11 and Windows fonts.
  Hosted CI, other Qt bindings and GPU/OpenGL rendering are not validated here.

The editable installation has not been refreshed for the new entry-point group;
the bundled source fallback works and external discovery is tested with matching
metadata. Install an external package into the application environment and
restart before its display appears in the menu. No graphics library is chosen
for future surfaces. Begin the next implementation with the surface records,
capability/version negotiation and grid policies in the command-extension plan.
