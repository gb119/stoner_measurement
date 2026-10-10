# Testing Restructure Plan

## 2026-10-10: Polar display and angle-first plotting forms

- Startup follow-up: added two attachment regressions for saved XY commands
  with the polar display and legacy plot facade active. Both commands retain
  bindings and can select polar without creating incompatible axes. Focused
  command/polar/surface/menu regressions: **166 passed**. No tests moved.

- Follow-up: two parameterised configuration-page checks verify that polar
  controls use available height in both commands, retain compact spacing, and
  return to XY. No test modules moved or removed.
  Focused command/surface/polar regressions: **177 passed**.

- Added `tests/unit/ui/test_polar_canvas.py` and
  `tests/integration/sequence/test_polar_plot_commands.py` with scoped widget
  and complete configuration-page ownership. No tests moved or removed.
- Covered angle-first projection, clockwise/top-zero command defaults, source
  unit conversion, raw-state persistence, uncertainties, worker execution,
  capability-aware switching, invalid inputs, manual view replay and teardown.
- Updated prospective polar contract and registry expectations; Cartesian and
  cylindrical/spherical ordering remains unchanged. The 27 dedicated cases
  pass. Full suite with coverage: **4,002 passed, 2 skipped**. Full validation is
  recorded in `notes/2026-10-10-polar-display.md`.

## 2026-10-10: GUI-thread collection after managed widget teardown

- `managed_qt_widget` releases its final loop variable and collects Python
  cycles on the GUI thread after scoped widget deletion and deferred events.
- Added `tests/unit/ui/test_qt_widget_lifecycle.py` to verify cyclic wrappers
  are reclaimed and finalized on the GUI thread without changing automatic GC
  settings. No tests moved or removed.
- Regression and original plot-service module: **9 passed**. Three fresh
  integration runs with coverage: **87 passed, 1 skipped** each. Initial full
  suite: **3,974 passed, 2 skipped**. Final full suite including the new test
  and last-reference fix: **3,975 passed, 2 skipped** with coverage. Hosted-CI
  boundary is recorded in `notes/2026-10-10-ci-qt-cycle-collection.md`.

## 2026-10-06: Plot Trace automatic surface identity regression

### Follow-up: clear-and-switch compatibility recovery

- Added real-menu cases in `tests/integration/app/test_plot_display_menu.py`
  exercising both Cancel and Clear and switch, button defaults, diagnostic
  details, checkmarks, retained plots and discarded canonical samples.
- Added atomic reset success/failure cases to
  `tests/unit/ui/test_plot_display_replacement.py`; extended busy-engine coverage
  to reset requests. No tests moved or removed. All widgets use managed ownership.
- Focused menu/replacement/host/surface/command/axis-removal validation passed
  **76 tests** with offscreen PyQt5 and Windows fonts, using
  `--basetemp=.pytest-runtime/display-reset-final`. Ruff check/format and normal
  `git diff --check` pass; mypy passes for the display host. Alternative Qt bindings
  and live instrument acquisition are outside this local validation.

### Follow-up: automatic re-gridding of surface rows

- Added `tests/unit/core/test_plotting_regrid.py` for duplicate mean/first/last
  reduction, round-off repeats, interpolation of Z/value, bounds policies,
  nearest valid boundary/error pairing, NaN gaps, independent-error propagation,
  single-coordinate rows, invalid coordinates and strict-mode behaviour.
- Extended surface-command integration coverage for full 501-point triangle
  traces in all three surface forms, exact reuse of mismatched grids after
  renderer replay, clear/new-run resets, strict validation and settings persistence.
  The original manual branch-selection case is replaced by automatic preparation
  coverage and an explicit strict-mode rejection case.
- Final helper/command/core/native-adapter/canvas plus legacy XY and service
  verification: **266 passed** on offscreen PyQt5 with Windows fonts, using
  `--basetemp=.pytest-runtime/regrid-final`. Ruff check/format and normal
  `git diff --check` pass; mypy passes on helper/service. No physical magnet,
  interactive GPU or alternative Qt-binding validation is claimed.

- Added five regression cases to
  `tests/integration/sequence/test_plot_surface_commands.py`: empty, missing and
  whitespace saved IDs produce unique persistent identities shared across worker
  loop slices; clearing a loaded ID stays stable across executions; the reported
  501-point triangle rejects repeated current cells and its descending branch
  retains two complete rows. Extended invalid-request coverage to an explicit
  expression returning whitespace. No tests moved or removed.
- Validation uses the project Conda environment, offscreen Qt and Windows fonts.
  Final command/core/native-adapter checks passed 60 cases on Python 3.14.7 /
  PyQt5 5.15.11 / Qt 5.15.15. Ruff check and format checks passed for the three
  changed Python files; normal repository `git diff --check` passed.
  This does not validate physical magnet hardware or the hosted Qt matrix.

## 2026-10-02: Native Cartesian XYZ and XY intensity displays

### Follow-up: discoverable Cartesian axis removal

- Added a plot context-menu `Remove Axis` submenu with individual extra-axis
  actions and `Remove All Extra Axes`. Reuses existing removal semantics:
  default bottom/left axes stay, trace samples are retained/reassigned and
  anchored markers are removed. Existing Configure Axes removal remains.
- Added two managed-widget cases in
  `tests/unit/ui/widgets/test_plot_axis_removal.py` covering reassignment,
  marker cleanup, public/exported axis descriptions and removal enabling an
  empty Cartesian-to-intensity-to-XYZ switch. Updated the existing context-menu
  assertion; no tests moved or removed. XY data must still be cleared before
  changing to a renderer that cannot accept its binding.
- Validation: axis-removal, plot-widget, mouse-axis and display-replacement
  modules passed **127 tests** in the project Conda environment with offscreen
  PyQt5 and Windows fonts. Ruff check/format and `git diff --check` passed.

- Added 19 adapter/geometry cases in `tests/unit/ui/test_surface_canvas.py`,
  10 real command/replacement/configuration cases in
  `tests/integration/app/test_surface_displays.py` and one optional native GPU
  case in `tests/integration/app/test_surface_display_opengl.py`. Added one
  registry duplicate-entry regression and extended bundled-factory discovery
  expectations. No existing tests were moved or removed. Owned widgets and all
  configuration pages use the shared managed fixtures.
- Renderers negotiate surface version one and retain exact cells incrementally.
  A 1001-cell test proves no snapshot/repaint occurs per incoming point. Native
  geometry tests prove missing/NaN rectangles do not acquire triangles; an
  intensity pixel test distinguishes measured zero, missing cells and NaNs.
  Real worker trace/serpentine point loops, compatible replay, rejected switches,
  cached configuration refresh, colour limits and saved camera/zoom are covered.
- Full offscreen verbose runs: **3910 passed, two skipped** (72.43 and 72.86 s):
  `pytest -vv --tb=short -p no:cacheprovider
  --basetemp=.pytest-runtime/surface-displays-final`. Final log:
  `.pytest-runtime/surface-displays-final.log`. One skip is the existing suite
  skip; the native GPU test deliberately skips on Qt's offscreen platform.
- Native Windows GPU framebuffer test passed twice, including after scene
  cleanup changes: `QT_QPA_PLATFORM=windows pytest -q
  tests/integration/app/test_surface_display_opengl.py`. A hidden native context
  reported NVIDIA OpenGL 4.6.0; mesh, point and axis-line pixels were verified
  without GL errors. GLTextItem's widget/QPainter path and interactive mouse
  gestures are outside this hidden-framebuffer proof. Local binding is PyQt5
  5.15.11 / Qt 5.15.15, Python 3.14.7, PyQtGraph 0.14.0 and PyOpenGL 3.1.10;
  hosted PyQt6 validation remains outstanding.
- Quiet full-suite invocations intermittently abort with a Qt access violation
  while a plotting worker waits for completion. The affected integration prefix
  passes separately (74 passed/one skip before the final settings cases), and
  the crash also reproduces with all three new renderer test modules excluded
  (`.pytest-runtime/surface-lifecycle-baseline.log`). The precise native cause
  is unresolved; successful verbose runs do not establish a fix for quiet mode.
  Adapter shutdown was made idempotent, callbacks use owned Qt slots, and the
  widget property avoids a self-reference cycle. No global teardown or exception
  suppression was added.
- Focused adapter/native workflow/registry checks passed 38 cases before adding
  two saved-factory preference cases. Ruff check/format, mypy on four display
  modules and `git diff --check` pass. Fresh-interpreter discovery confirms no
  eager renderer/OpenGL import. Editable metadata includes three display entry
  points and PyOpenGL; project and all three Conda files plus the recipe agree.
- User documentation and both design plans now describe delivered features,
  linear-axis/uncertainty/marker limits and validation boundaries. Incremental
  Sphinx rebuild passes with five existing import warnings; a clean build retains
  the established 497-warning baseline. A wheel build succeeds; its three new
  renderer modules, display entry points and PyOpenGL requirement were verified.
  The only added runtime dependency is
  PyOpenGL, chosen by the user; temporary Matplotlib packages were removed.

## 2026-10-02: Plot command XYZ/intensity bindings and live display controls

- Added 19 surface-contract cases in `tests/unit/core/test_plotting_surfaces.py`
  and 25 worker/configuration/replay workflows in
  `tests/integration/sequence/test_plot_surface_commands.py`. No existing tests
  moved or removed. Cached plugin tabs use `managed_plugin_config_tabs`, and
  test displays/services use scoped managed Qt ownership.
- Verified explicit fixed-Y trace slices, multiple XYZ/intensity point sources,
  serpentine cell mapping, duplicate/reacquisition policy, run reset, metadata,
  immutable source capture, missing values, incremental storage, saved generated
  actions, headless execution, transactional replay/refusal and failure rollback.
  Configuration checks cover capability/axis changes, preserving unsupported
  saved forms, source-catalogue refresh and ignoring data-only notifications.
- Full suite: **3,880 passed, one skipped**, 3,881 collected, 95.11 seconds:
  `pytest -q --tb=short -p no:cacheprovider
  --basetemp=.pytest-runtime/plot-command-extensions-full`. Log:
  `.pytest-runtime/plot-command-extensions-full.log`. Final focused regression
  after documentation/import cleanup: **212 passed**.
- Ruff check/format, focused mypy (seven source files), `git diff --check` and
  15 contract doctests passed. Sphinx built with its existing 497 warnings.
  Rendered/inspected both XYZ pages at 540px width and corrected narrow nested
  editors before delivery. Used project Conda, Python 3.14.7 and offscreen
  PyQt5 5.15.11 with Windows fonts. No cross-binding CI/GPU claims.
- Stages 1/2 handover and extension semantics:
  `notes/2026-10-01-plot-command-extension-plan.md`. Production intensity/3D
  factories remain stages 3/4 and must explicitly negotiate surface support.

## 2026-10-01: Plot display author guide and final handover Stage 5

- Added two cases in `tests/integration/app/test_plot_display_example.py`.
  They load the exact downloadable factory example, simulate installed discovery,
  run existing trace/point commands on the engine worker inside MainWindow,
  append data, replay through Cartesian and reject an incompatible marker
  snapshot. No existing tests moved or removed; windows use managed Qt ownership.
- Focused example/host/registry/replacement/menu checks: **36 passed**.
- Full suite: **3,836 passed, one skipped**, 3,837 collected, 71.44 seconds:
  `pytest -q --tb=short -p no:cacheprovider
  --basetemp=.pytest-runtime/plot-stage5-full`. Output:
  `.pytest-runtime/plot-stage5-full.log`.
- Ruff check/format, focused mypy (11 source files) and `git diff --check` passed.
  All 15 contract doctests and the command plan's XYZ trace-slice example passed.
  Sphinx built the guide/downloadable example with the existing 497-warning
  baseline. Used project Conda, Python 3.14.7, offscreen PyQt5 5.15.11 and fonts.
  No hosted cross-binding CI or GPU validation is claimed.
- All five foundation stages are complete; handover:
  `notes/2026-10-01-plot-display-stage5.md`. The command-extension plan records
  single-loop trace slices, nested-loop points and which plotting APIs to reuse;
  optional surface controls, grouping/topology and renderers remain future work.

This is the historical migration log for the test-suite restructure. Durable
test layout and philosophy guidance lives in `notes/testing_guidelines.md`.

This document records the test-suite restructure so future Codex sessions can
continue without rediscovering the same coverage map.

## 2026-10-01: Plot replacement, settings and UI Stage 4

- Added 12 cases in `tests/unit/ui/test_plot_display_replacement.py` and two
  menu workflows in `tests/integration/app/test_plot_display_menu.py`. No
  existing tests moved or rewritten; old and failed candidate teardown stays
  scoped to host-owned adapters/widget containers.
- Verified explicit Cartesian state round trips through a non-PyQtGraph test
  adapter: data/errors, source bindings/metadata and auxiliary channels, user
  styles/titles, hidden traces, named axes, scales/ranges, active axes, exact
  legend height and marker IDs/anchors. Covered idle engine/queue refusal,
  hydration/capability failure rollback, generation advancement, unsupported
  style retention, restart settings without arrays, corrupt settings fallback
  and View-menu selection/refusal feedback.
- Focused legacy plotting, engine and application regression: 294 passed.
  Final replacement/menu selection: 14 passed.
- Final full suite: **3,834 passed, one skipped**, 3,835 collected, 69.37 seconds;
  `pytest -q --tb=short -p no:cacheprovider
  --basetemp=.pytest-runtime/plot-stage4-full`. Output is retained locally in
  `.pytest-runtime/plot-stage4-full.log`.
- Changed-file Ruff check/format, focused mypy (11 source files) and
  `git diff --check` passed. The plotting page's 15 doctest examples passed;
  Sphinx built successfully with the existing 497-warning baseline.
- Used project Conda, Python 3.14.7, offscreen PyQt5 5.15.11 and Windows fonts.
  No other Qt binding, hardware or GPU renderer validation is claimed.
- Handover: `notes/2026-10-01-plot-replacement-stage4.md`. The replaceable
  Cartesian foundation is complete; further production displays remain separate.

## 2026-10-01: Plot display host and factories Stage 3

- Added ten registry cases and ten host cases under
  `tests/unit/ui/test_plot_display_registry.py` and
  `tests/unit/ui/test_plot_display_host.py`; no existing tests moved or rewritten.
  Host-owned services shut down before scoped adapter/widget teardown.
- Covered lazy factory discovery, bundled fallback without installed metadata,
  import/version/ID failures, startup selection fallback, interface validation,
  partial widget cleanup, worker ownership, close/cancellation and a minimal
  portable display receiving real engine trace/point commands inside MainWindow.
  Cartesian compatibility checks cover eager named axes and point-label edits
  retaining their observable rename signal while using the service queue.
- Initial focused gate: 47 passed. The portable axis refinement passed 144
  producer/service/host tests; the final host selection passed all ten cases.
  Initial full suite: 3,819 passed, one skipped (70.12 seconds).
- Final full suite including the label-edit repair: **3,820 passed, one skipped**,
  3,821 collected (82.40 seconds), using
  `pytest -q --tb=short -p no:cacheprovider
  --basetemp=.pytest-runtime/plot-stage3-final`. Local output is retained at
  `.pytest-runtime/plot-stage3-final.log`.
- Mypy passed for ten source files covering display interfaces, host, registry,
  factory, service and bridge. Changed-file Ruff check/format and
  `git diff --check` passed. All 15 plotting doctest examples passed; Sphinx
  built successfully with the existing 497-warning baseline.
- Source entry-point registration was verified; installed editable metadata
  currently has no entries in the new group. No install refresh was performed.
  The bundled source fallback and isolated third-party discovery are tested.
- Used the project Conda environment, Python 3.14.7, offscreen PyQt5 5.15.11
  and Windows fonts. These results do not claim hosted cross-binding CI.
- Handover: `notes/2026-10-01-plot-host-stage3.md`. Live replacement/replay and
  versioned display settings remain Stage 4 work.

## 2026-10-01: Plot service routing Stage 2

- Added 15 service cases in `tests/unit/core/test_plotting_service.py` and eight
  real engine/compatibility workflows in
  `tests/integration/sequence/test_plot_service_commands.py`. Existing tests
  were not moved or rewritten. The tests use managed widget ownership and
  release the borrowed plot service before Qt teardown.
- Coverage includes GUI-only rendering from workers, request ordering and
  exactly-once completion, immutable data, metadata/style acknowledgement,
  invalid/unsupported requests, renderer failures, bounded pending work,
  headless execution, pause/stop/timeout/shutdown, repeated endpoint attachment,
  legacy keyword/return-value semantics and saved/generated command execution.
- Complete-suite validation: **3,800 passed, one skipped**, 3,801 collected;
  `pytest -q --tb=short -p no:cacheprovider
  --basetemp=.pytest-runtime/plot-stage2-full` (69.89 seconds). Used the project
  Conda environment, Python 3.14.7, offscreen PyQt5 5.15.11 and Windows fonts.
  This does not establish the other Qt bindings' CI results.
- Focused mypy for `core/plotting` and `ui/plotting_bridge.py` passed (five files).
  Changed-file Ruff check/format and `git diff --check` passed; all 15 plotting
  documentation doctest examples passed. Sphinx retains unrelated existing
  API documentation warnings, as recorded in Stage 1.
- The implementation and next-stage boundaries are in
  `notes/2026-10-01-plot-service-stage2.md`. Host/factory discovery and display
  replacement are not implemented by this stage.

## 2026-10-01: Plot display contract Stage 1

- Added `tests/unit/core/test_plotting_contracts.py` with 41 cases for owned
  immutable array/metadata snapshots, malformed shapes, generalised coordinate
  bindings and units, spherical conventions, independent intensity, capability
  rejection, markers, axis ranges and terminal results. No existing tests moved
  or changed; application plotting remains on the original implementation.
- Pre-change baseline: 262 passed across the Cartesian plot widget, mouse axes,
  plot trace/point/clear/marker commands, extremum transform and main window.
- New contracts plus the same baseline: 303 passed. After refining snapshot
  output typing, the 41 contract cases passed again. Commands used the project
  Conda environment with offscreen PyQt5 5.15.11 and Windows fonts, Python 3.14.7.
- `python -m doctest -v docs/plotting_contracts.rst`: 15 examples passed.
  `mypy src/stoner_measurement/core/plotting --follow-imports=silent` passed;
  Ruff check and format apply to the new package and test module.
- Full collection: 3,778 tests with `pytest --collect-only -q -p no:cacheprovider`.
  The focused combined run used `-q --tb=short -p no:cacheprovider` and
  `--basetemp=.pytest-runtime/plot-stage1-final`; collection output is retained
  locally at `.pytest-runtime/plot-stage1-collection.txt`.
- Fresh-process contract import loaded neither PyQtGraph nor OpenGL. Records
  contain no widgets; existing package-level Qt imports are unchanged.
- Sphinx HTML build completed with exit code 0. The new page's title warning
  was corrected. Existing API documentation still warns about obsolete
  `core.sequence`/`core.runner` imports and other existing source/stub formatting;
  this is not a warning-free documentation baseline. Markdownlint was unavailable
  in the installed tools; Markdown spacing, links and line lengths were checked
  locally. Generated autosummary sources were removed after the build.
- The API examples are in `docs/plotting_contracts.rst`; compatibility, consumer
  inventory and state ownership are in `notes/2026-10-01-plot-contract-stage1.md`.
  Stage 2 dispatcher, tickets, pause/stop delivery and renderer lifecycle are not
  implemented or claimed as tested by these record tests.

## 2026-10-01: SR830 auto-function completion deadlines

- Extended `tests/unit/instruments/drivers/test_srs830.py` with simulated slow
  completion, active time-constant readback, bounded timeout, transport-timeout
  preservation, explicit-deadline and connection-failure cases. No tests moved.
- Focused driver run: 34 passed using `conda run -n stoner_measurement pytest
  tests/unit/instruments/drivers/test_srs830.py -q --tb=short -p no:cacheprovider
  --basetemp=.pytest-runtime/sr830-auto`. Ruff passed for the driver and tests.
- Related driver, lock-in contract and multi-lock-in plugin regressions: 163
  passed in the project Conda environment with offscreen PyQt5. The run covered
  the SR830/SR7265 driver modules, lock-in exports, per-lock-in settings and
  `tests/test_k6221_multi_sr830_plugin.py`. `git diff --check` passed.
- Timing policy and remaining bench checks are in `notes/sr830_autosensitivity.md`.

## 2026-09-15: Plot legend sizing and scrollbar contrast

- Updated the existing plot-widget height check for a compact, resizable legend
  with room for its horizontal scrollbar. Added coverage that resizing survives
  adding and clearing traces; no tests were moved.
- Verified the plot-widget and theme-contrast modules: 114 passed. Rendered dark
  and light previews to check scrollbar visibility and the plot/legend divider.
- Scrollbar thumb/track contrast measures 6.14:1 in dark mode and 5.34:1 in light
  mode; hover/pressed contrast is 5.08:1 and 4.51:1 respectively.

## 2026-09-14: Per-lock-in settings and fresh overload checks

- Added 15 focused cases in
  `tests/unit/plugins/trace/test_k6221_lockin_settings.py` for legacy JSON
  migration, independent controls/configuration/readback, current-input ranges
  and units, range rounding, and cleared versus reasserted overload flags.
- Updated affected expectations in `tests/test_k6221_multi_sr830_plugin.py`;
  its remaining lifecycle/acquisition/UI coverage remains in that legacy file.
  Added the native inverted-B command test to the SR7265 driver unit tests.
- Validation through `conda run -n stoner_measurement`, with
  `QT_QPA_PLATFORM=offscreen` and `QT_QPA_FONTDIR=C:\Windows\Fonts`:
  `pytest tests/unit/plugins/trace/test_k6221_lockin_settings.py
  tests/test_k6221_multi_sr830_plugin.py
  tests/unit/instruments/drivers/test_sr7265.py
  tests/unit/instruments/drivers/test_srs830.py
  tests/unit/instruments/contracts/test_lockin_amplifier_exports.py -q --tb=short`
  passed all 144 tests. Full collection found 3,613 tests; Ruff passed for the
  changed plugin, SR7265 driver, and affected test modules. No bench validation
  was performed.

## Current Baseline

### 2026-09-16: Keithley DC point scan and set commands

- Follow-up: added `tests/unit/plugins/state/test_point_voltmeter.py` covering
  independent controls and persistence in scan/set, capability changes, legacy
  182 defaults, unsupported operations and runtime expressions. Updated the
  point-scan meter doubles to report real driver capabilities. Related point,
  set and trace tests: 125 passed, exit code 0; Ruff passed. No tests moved.

- Added focused modules `tests/unit/plugins/state/test_k6221_point_scan.py` and
  `tests/unit/plugins/command/test_keithley_set.py`. No legacy tests moved.
- Coverage includes independent optional meters, source-only schema, held DC
  behavior, resource ownership and failure cleanup, JSON/UI, expressions and
  generated sequence lifecycle. Pulsed-current plugins and standalone 6221
  trigger output are explicitly deferred.
- Related regression run: 168 passed with exit code 0, covering both new test
  modules, existing 2400 point/trace tests, 6221 trace/secondary tests and
  Reconfigure tests. Ruff passed for the new modules and package exports.
  New entry points were loaded from installed metadata. No real-instrument
  validation was performed.

### 2026-09-14: Reconfigure and shared lifecycle contract

- Added `tests/unit/plugins/command/test_reconfigure_command.py` with 22 cases
  covering selection unions, optional startup suppression, removal and disable
  rebuilding, JSON/rename preservation, standalone generated scripts, runtime
  conditional/loop behavior, fresh-run readiness, and reconnect cleanup.
- Resource tests cover repeated calls, partial connection failure, cleanup
  failure preventing replacement, failed configuration invalidating readiness,
  and the concrete 6221/lock-in plugin releasing previous driver instances.
- No legacy tests moved. Full offscreen suite: **3,631 passed, 1 skipped**
  (`conda run -n stoner_measurement pytest -q --tb=short`). Three additional
  focused cases were then added; all **22** Reconfigure cases passed together.
  Ruff passed for the changed lifecycle, engine, UI and command modules.
- Refreshed the editable installation with
  `pip install --no-user --no-deps --no-build-isolation -e .` through the
  project Conda environment and verified the Reconfigure entry point loads.
- Real hardware reconnection remains a bench-validation boundary. Resource
  tests use fake transports/drivers and do not establish instrument timing.

Baseline command, run from the repository root:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
conda run -n stoner_measurement pytest --cov=stoner_measurement --cov-report=json:coverage.json --cov-report=term-missing
```

Latest observed result:

- Coverage artifact timestamp: 2026-07-21T15:25:56.
- Combined branch-aware coverage: 76%.
- Statement coverage: 80%.
- Branch coverage: 58%.

Latest rerun note:

- The 2026-07-21 local rerun emitted `coverage.json` with the totals above, but
  pytest exited non-zero after a Windows fatal access violation in the
  Qt/IPython stack during teardown. Treat pass-count status as unverified until
  a stable rerun completes.

The lower branch coverage means new tests should prefer branch/edge cases over
more happy-path assertions for already-covered code.

## Target Layout

```text
tests/
  unit/
    scan/
    sweep/
    instruments/
      transport/
      drivers/
      contracts/
    plugins/
      command/
      trace/
      transform/
      state/
      monitor/
    ui/
      widgets/
      panels/
      dialogs/
    control/
      magnet/
      motor/
      temperature/
    core/
  integration/
    app/
    sequence/
    plugin_workflows/
  fixtures/
    fake_instruments.py
    fake_transports.py
    qt_helpers.py
    plugin_factories.py
```

## Hot Test Files

These files carry too much unrelated behavior and should be split by module or
contract as they are touched:

| File                             | Tests | Lines | Suggested split                                           | Status                                        |
| -------------------------------- | ----: | ----: | --------------------------------------------------------- | --------------------------------------------- |
| `tests/test_new_ui_widgets.py`   |   139 |  1876 | `unit/ui/widgets/`, `unit/ui/panels/`, `integration/app/` | In progress; SI spin box moved in pass 23     |
| `tests/test_curve_fit_plugin.py` |   109 |  1241 | keep focused, but split UI/config from fit execution      | Open                                          |
| `tests/test_sequence_engine.py`  |   100 |   906 | `unit/core/` and `integration/sequence/`                  | Open                                          |
| `tests/test_instruments.py`      |   452 |  4692 | `unit/instruments/drivers/` plus shared driver contracts  | Complete; removed in pass 22                  |
| `tests/test_command_plugin.py`   |   256 |  3244 | `unit/plugins/command/test_<command>.py`                  | Complete; removed in command-plugin migration |
| `tests/test_plugin_subtypes.py`  |   121 |  1092 | plugin contracts plus subtype-specific unit files         | Complete; removed in plugin-subtype migration |

## Cold Coverage Spots

Ranked by missed lines plus missed branches:

| Module                                             | Coverage | Debt | Recommended approach                                                             |
| -------------------------------------------------- | -------: | ---: | -------------------------------------------------------------------------------- |
| `ui/value_watch.py`                                |      29% |  663 | Unit-test model/state transitions and threshold formatting before widget flows   |
| `ui/widgets/round_dial.py`                         |      44% |  532 | Parametrize modes, label placement, collision handling, and color/theme branches |
| `ui/dock_panel.py`                                 |      66% |  425 | Split tree-model behavior from drag/drop and selection integration               |
| `ui/temperature_panel.py`                          |      73% |  414 | Extract/test state helpers; add thin Qt signal and chart-refresh tests           |
| `ui/plot_widget.py`                                |      80% |  322 | Cover axes-dialog branches, context-menu actions, and persistence wiring         |
| `app.py`                                           |      67% |  316 | Add focused app-shell tests for action wiring and plugin-tree edge cases         |
| `ui/magnet_panel.py`                               |      77% |  255 | Test state rendering, limits handling, and command enablement with fake engine   |
| `temperature_control/engine.py`                    |      67% |  242 | Contract tests for driver connection, error paths, and state transitions         |
| `ui/pressure_panel.py`                             |      69% |  225 | Add fake-engine panel tests for state rendering, limits, and button gating       |
| `plugins/trace/k6221_multi_sr830.py`               |      80% |  212 | Fill branch cases around config validation and UI callbacks                      |
| `instruments/eurotherm/temperature_controllers.py` |      70% |  197 | Add driver contract tests for parsing, limits, and error-reporting branches      |
| `magnet_control/engine.py`                         |      73% |  194 | Add fake-driver state transition and failure-path tests                          |
| `instruments/transport/gpib_transport.py`          |      46% |  173 | Mock PyVISA resources under a transport contract                                 |

## Migration Rules

- Move tests by behavior, not by old filename.
- Prefer one test module per production module unless a contract file covers a
  family of implementations.
- Keep slow app-level workflows under `tests/integration/`.
- Keep widget construction, signal, and property synchronization tests under
  `tests/unit/ui/`.
- Use contract helper functions for repeated interfaces:
  - transport open/read/write/error behavior
  - instrument identity, validation, query/write mapping
  - plugin JSON/config/generated-code/lifecycle behavior
  - monitor/state plugin connect/read/reported-values behavior
- When adding coverage to cold UI modules, first look for extractable pure
  helpers. Avoid testing large panels only through full application workflows.
- Keep `QT_QPA_PLATFORM=offscreen` for Qt test runs.
- Use `conda run -n stoner_measurement ...` for every project command.

## Suggested CI Buckets

```text
fast unit: non-Qt logic, contracts, serializers
qt unit: widgets/panels/dialogs with offscreen Qt
integration: app/plugin workflow tests
coverage: combined report
```

Possible commands:

```powershell
conda run -n stoner_measurement pytest tests/unit
conda run -n stoner_measurement pytest tests/unit/ui
conda run -n stoner_measurement pytest tests/integration
conda run -n stoner_measurement pytest --cov=stoner_measurement --cov-report=term-missing
```

## Completed In First Migration Pass

- Created the target directory skeleton.
- Moved the first low-risk widget tests to `tests/unit/ui/widgets/`.
- Verified nested pytest discovery for the migrated tests.

- Moved:
  - `tests/test_percent_slider.py` -> `tests/unit/ui/widgets/test_percent_slider.py`
  - `tests/test_si_combo_box.py` -> `tests/unit/ui/widgets/test_si_combo_box.py`
  - `tests/test_visa_resource_widget.py` -> `tests/unit/ui/widgets/test_visa_resource_widget.py`

## Completed In Second Migration Pass

- Moved `tests/test_round_dial.py` to `tests/unit/ui/widgets/test_round_dial.py`.
- Split `tests/test_ui.py` into:
  - `TestDockPanel` -> `tests/unit/ui/panels/test_dock_panel.py`
  - `TestPlotWidget` -> `tests/unit/ui/widgets/test_plot_widget.py`
  - `TestConfigPanel` -> `tests/unit/ui/panels/test_config_panel.py`
  - `TestMainWindow` -> `tests/integration/app/test_main_window.py`
- Removed the old monolithic `tests/test_ui.py`.
- Normalized one plot-widget assertion to expect the real ellipsis glyph in
  `"Configure Axes…"`'s UI label.
- Verified the migrated tranche:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
conda run -n stoner_measurement pytest tests/unit/ui/widgets/test_round_dial.py tests/unit/ui/widgets/test_plot_widget.py tests/unit/ui/panels/test_dock_panel.py tests/unit/ui/panels/test_config_panel.py tests/integration/app/test_main_window.py --tb=short
conda run -n stoner_measurement pytest --collect-only -q
conda run -n stoner_measurement ruff check tests/unit/ui tests/integration/app --select "F401,F811,F821,F841"
```

Result:

- Migrated tranche: 156 passed.
- Full collection: 2386 tests collected.
- Focused Ruff import/name checks passed.

## Completed In Third Migration Pass

- Moved the scan generator tests into `tests/unit/scan/`:
  - `tests/test_scan_generators.py` -> `tests/unit/scan/test_scan_generators.py`
  - `tests/test_stepped_scan_generator.py` -> `tests/unit/scan/test_stepped_scan_generator.py`
  - `tests/test_list_scan_generator.py` -> `tests/unit/scan/test_list_scan_generator.py`
  - `tests/test_ramp_scan_generator.py` -> `tests/unit/scan/test_ramp_scan_generator.py`
  - `tests/test_arbitrary_function_scan_generator.py` -> `tests/unit/scan/test_arbitrary_function_scan_generator.py`
- Verified the migrated tranche:

```powershell
conda run -n stoner_measurement pytest tests/unit/scan --tb=short
conda run -n stoner_measurement pytest --collect-only -q
conda run -n stoner_measurement ruff check tests/unit/scan --select "F401,F811,F821,F841"
```

Result:

- Scan tranche: 274 passed.
- Full collection: 2386 tests collected.
- Focused Ruff import/name checks passed.

## Completed In Fourth Migration Pass

- Started transport contract tests in `tests/unit/instruments/contracts/` with
  reusable checks for open/close, context-manager lifecycle, and query
  write-then-read behavior.
- Moved the concrete `NullTransport` tests from `tests/test_instruments.py` to
  `tests/unit/instruments/transport/test_null_transport.py`.
- Left the existing URI parsing and GPIB/PyVISA tests in `tests/test_instruments.py`
  for the next transport-focused pass so they can move with their mock resource
  scaffolding.
- Verified the migrated tranche:

```powershell
conda run -n stoner_measurement python -m pytest tests\unit\instruments\contracts tests\unit\instruments\transport\test_null_transport.py --tb=short
conda run -n stoner_measurement python -m pytest --collect-only -q
conda run -n stoner_measurement python -m ruff check tests\unit\instruments\contracts tests\unit\instruments\transport\test_null_transport.py --select F401,F811,F821,F841
```

Result:

- Transport tranche: 13 passed.
- Full collection: 2389 tests collected.
- Focused Ruff import/name checks passed.

## Completed In Fifth Migration Pass

- Continued transport migration by moving URI/resource parsing tests from
  `tests/test_instruments.py` to
  `tests/unit/instruments/transport/test_transport_uri.py`.
- Moved GPIB protocol termination and `PassThroughGpibTransport` tests from
  `tests/test_instruments.py` to
  `tests/unit/instruments/transport/test_gpib_transport.py`.
- Kept serial flow-control tests in `tests/test_instruments.py` for a later
  serial-specific transport pass.
- Verified the migrated tranche:

```powershell
conda run -n stoner_measurement python -m pytest tests\unit\instruments\contracts tests\unit\instruments\transport --tb=short
conda run -n stoner_measurement python -m pytest --collect-only -q
conda run -n stoner_measurement python -m ruff check tests\unit\instruments\transport tests\unit\instruments\contracts --select F401,F811,F821,F841
```

Result:

- Transport tranche: 48 passed.
- Full collection: 2389 tests collected.
- Focused Ruff import/name checks passed.

## Completed In Sixth Migration Pass

- Finished the transport reshuffle from `tests/test_instruments.py` by moving:
  - UDP socket tests to `tests/unit/instruments/transport/test_udp_transport.py`
  - Ethernet framing tests to `tests/unit/instruments/transport/test_ethernet_transport.py`
  - Serial flow-control tests to `tests/unit/instruments/transport/test_serial_transport.py`
- Left instrument locking and driver behavior in `tests/test_instruments.py` for
  the later driver-focused split.
- Verified the migrated tranche:

```powershell
conda run -n stoner_measurement python -m pytest tests\unit\instruments\contracts tests\unit\instruments\transport --tb=short
conda run -n stoner_measurement python -m pytest --collect-only -q
conda run -n stoner_measurement python -m ruff check tests\unit\instruments\transport tests\unit\instruments\contracts --select F401,F811,F821,F841
```

Result:

- Transport tranche: 66 passed.
- Full collection: 2391 tests collected.
- Focused Ruff import/name checks passed.

## Completed In Seventh Migration Pass

- Added first cold-spot tests for `ui/settings_dialog.py` under
  `tests/unit/ui/dialogs/test_settings_dialog.py`.
- Covered construction from saved settings, unknown-theme fallback,
  accept/reject persistence behavior, toolbar row loading/collection/removal,
  validation warnings, and save/cancel handling without touching real user
  settings or toolbar config files.
- Verified the tranche:

```powershell
conda run -n stoner_measurement python -m pytest tests\unit\ui\dialogs --tb=short
conda run -n stoner_measurement python -m pytest --collect-only -q
conda run -n stoner_measurement python -m ruff check tests\unit\ui\dialogs --select F401,F811,F821,F841
```

Result:

- Settings-dialog tranche: 10 passed.
- Full collection: 2401 tests collected.
- Focused Ruff import/name checks passed.

## Completed In Eighth Migration Pass

- Began splitting `tests/test_command_plugin.py` into
  `tests/unit/plugins/command/test_<command>.py`.
- Moved the low-dependency command coverage into focused unit files:
  - `tests/unit/plugins/command/test_base_command.py`
  - `tests/unit/plugins/command/test_wait_command.py`
  - `tests/unit/plugins/command/test_status_command.py`
  - `tests/unit/plugins/command/test_alert_command.py`
  - `tests/unit/plugins/command/test_plot_clear_command.py`
- Trimmed `tests/test_command_plugin.py` so it now retains only the larger
  `SaveCommand`, `PlotTraceCommand`, `DetailsCommand`, and `PlotPointsCommand`
  groups for follow-up passes.
- Updated the migrated base command config-tabs assertion to match the current
  base plugin contract: command config tab first, optional About tab last.
- Verified the tranche:

```powershell
conda run -n stoner_measurement python -m pytest tests\unit\plugins\command\test_base_command.py tests\unit\plugins\command\test_wait_command.py tests\unit\plugins\command\test_status_command.py tests\unit\plugins\command\test_alert_command.py tests\unit\plugins\command\test_plot_clear_command.py tests\test_command_plugin.py --tb=short
conda run -n stoner_measurement python -m ruff check tests\unit\plugins\command tests\test_command_plugin.py
conda run -n stoner_measurement python -m pytest --collect-only -q
```

Result:

- Command-plugin tranche: 256 passed.
- Full collection: 2401 tests collected.
- Ruff checks passed for the migrated command files and remaining command
  plugin file.

## Completed In Ninth Migration Pass

- Continued splitting `tests/test_command_plugin.py` by moving
  `DetailsCommand` coverage into
  `tests/unit/plugins/command/test_details_command.py`.
- Replaced repeated inline imports in the migrated tests with module-level
  imports for the command, Qt widgets, settings helpers, and `BasePlugin`.
- Trimmed `tests/test_command_plugin.py` so it now retains only the larger
  `SaveCommand`, `PlotTraceCommand`, and `PlotPointsCommand` groups.
- Verified the tranche:

```powershell
conda run -n stoner_measurement python -m pytest tests\unit\plugins\command\test_details_command.py tests\test_command_plugin.py --tb=short
conda run -n stoner_measurement python -m ruff check tests\unit\plugins\command tests\test_command_plugin.py
conda run -n stoner_measurement python -m pytest --collect-only -q
```

Result:

- Details-command tranche plus remaining command monolith: 174 passed.
- Full collection: 2401 tests collected.
- Ruff checks passed for the command test area.

## Completed In Tenth Migration Pass

- Continued splitting `tests/test_command_plugin.py` by moving
  `PlotPointsCommand` coverage into
  `tests/unit/plugins/command/test_plot_points_command.py`.
- Kept the small plot-timeout test double local to the new file so
  `PlotPointsCommand` tests are independent of the remaining PlotTrace block.
- Trimmed `tests/test_command_plugin.py` so it now retains only
  `SaveCommand` and `PlotTraceCommand` coverage.
- Verified the tranche:

```powershell
conda run -n stoner_measurement python -m pytest tests\unit\plugins\command\test_plot_points_command.py tests\test_command_plugin.py --tb=short
conda run -n stoner_measurement python -m ruff check tests\unit\plugins\command tests\test_command_plugin.py
conda run -n stoner_measurement python -m pytest --collect-only -q
```

Result:

- Plot-points tranche plus remaining command monolith: 153 passed.
- Full collection: 2401 tests collected.
- Ruff checks passed for the command test area.

## Completed In Eleventh Migration Pass

- Continued splitting `tests/test_command_plugin.py` by moving
  `SaveCommand` coverage into
  `tests/unit/plugins/command/test_save_command.py`.
- Preserved the existing Save command test bodies during the move and added a
  focused module header/imports.
- Trimmed `tests/test_command_plugin.py` so it now contains only
  `PlotTraceCommand` coverage, making the final monolith removal a straight
  PlotTrace move/rename.
- Verified the tranche:

```powershell
conda run -n stoner_measurement python -m pytest tests\unit\plugins\command\test_save_command.py tests\test_command_plugin.py --tb=short
conda run -n stoner_measurement python -m ruff check tests\unit\plugins\command tests\test_command_plugin.py
conda run -n stoner_measurement python -m pytest --collect-only -q
```

Result:

- Save-command tranche plus remaining PlotTrace monolith: 118 passed.
- Full collection: 2401 tests collected.
- Ruff checks passed for the command test area.

## Completed In Twelfth Migration Pass

- Finished splitting the command plugin monolith by moving the remaining
  `PlotTraceCommand` coverage from `tests/test_command_plugin.py` to
  `tests/unit/plugins/command/test_plot_trace_command.py`.
- Removed the top-level `tests/test_command_plugin.py` monolith.
- Preserved IDE/direct-file execution for the split command test files by
  adding a small `if __name__ == "__main__": pytest.main([__file__, "--pdb"])`
  block to each new command test module.
- Verified the final command-plugin tranche:

```powershell
conda run -n stoner_measurement python -m pytest tests\unit\plugins\command\test_plot_trace_command.py --tb=short
conda run -n stoner_measurement python -m ruff check tests\unit\plugins\command
conda run -n stoner_measurement python -m pytest tests\unit\plugins\command --tb=short
conda run -n stoner_measurement python tests\unit\plugins\command\test_wait_command.py
conda run -n stoner_measurement python -m pytest --collect-only -q
```

Result:

- PlotTrace command tranche: 64 passed.
- Command test area: 256 passed.
- Direct-file smoke test: `test_wait_command.py` passed when run as a script.
- Full collection: 2401 tests collected.
- Ruff checks passed for the command test area.
- `tests/test_command_plugin.py` no longer exists.

## Completed In Thirteenth Migration Pass

- Split `tests/test_plugin_subtypes.py` into focused plugin-family files:
  - `tests/unit/plugins/trace/test_trace_plugin.py`
  - `tests/unit/plugins/state/test_state_control_plugin.py`
  - `tests/unit/plugins/state/test_state_control_data_collection.py`
  - `tests/unit/plugins/monitor/test_monitor_plugin.py`
  - `tests/unit/plugins/transform/test_transform_plugin.py`
  - `tests/unit/plugins/test_reported_outputs.py`
- Preserved the small local test doubles inside the split files so the new
  modules remain independently runnable from an IDE.
- Removed the top-level `tests/test_plugin_subtypes.py` monolith after the
  overlap run confirmed the moved coverage still passed.
- Verified the tranche:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
conda run -n stoner_measurement python -m pytest tests\test_plugin_subtypes.py --tb=short
conda run -n stoner_measurement python -m pytest tests\unit\plugins\trace\test_trace_plugin.py tests\unit\plugins\state\test_state_control_plugin.py tests\unit\plugins\state\test_state_control_data_collection.py tests\unit\plugins\monitor\test_monitor_plugin.py tests\unit\plugins\transform\test_transform_plugin.py tests\unit\plugins\test_reported_outputs.py tests\test_plugin_subtypes.py --tb=short
conda run -n stoner_measurement python -m pytest --collect-only -q
conda run -n stoner_measurement python -m ruff check tests\unit\plugins
```

Result:

- Overlap run before deletion: 246 passed.
- Split plugin test area after deletion: 123 passed.
- Direct-file smoke test: `test_state_control_plugin.py` passed when run as a script.
- Full collection: 2490 tests collected.
- Ruff checks passed for the split plugin test area.

## Completed In Fourteenth Migration Pass

- Split the first SCPI driver tranche out of `tests/test_instruments.py` into:
  - `tests/unit/instruments/drivers/test_keithley_2400.py`
  - `tests/unit/instruments/drivers/test_keithley_2000.py`
  - `tests/unit/instruments/drivers/test_keithley_2182a.py`
- Moved the following legacy groups:
  - `TestKeithley2400`
  - `TestKeithley24xxVariants`
  - `TestKeithley2000`
  - `TestKeithley2000Variants`
  - `TestKeithley2182A`
  - `TestKeithley2182Variants`
- Kept the small `_null(...)` helper local to each split file so the modules
  remain directly runnable from an IDE without depending on package-style test
  imports.
- Trimmed the moved imports and classes out of `tests/test_instruments.py`.
- Verified the tranche:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
conda run -n stoner_measurement python -m pytest tests\unit\instruments\drivers\test_keithley_2400.py tests\unit\instruments\drivers\test_keithley_2000.py tests\unit\instruments\drivers\test_keithley_2182a.py tests\test_instruments.py --tb=short
conda run -n stoner_measurement python -m ruff check tests\unit\instruments\drivers tests\test_instruments.py
conda run -n stoner_measurement python -m pytest tests\unit\instruments\drivers\test_keithley_2400.py tests\unit\instruments\drivers\test_keithley_2000.py tests\unit\instruments\drivers\test_keithley_2182a.py --tb=short
conda run -n stoner_measurement python tests\unit\instruments\drivers\test_keithley_2000.py
conda run -n stoner_measurement python -m pytest --collect-only -q
```

Result:

- Overlap run before trimming: 473 passed.
- Split driver area after trimming: 63 passed.
- Direct-file smoke test: `test_keithley_2000.py` passed when run as a script.
- Full collection: 2490 tests collected.
- Ruff checks passed for the split driver area and remaining monolith.

## Completed In Fifteenth Migration Pass

- Split the next focused instrument tranche out of `tests/test_instruments.py`
  into:
  - `tests/unit/instruments/drivers/test_srs830.py`
  - `tests/unit/instruments/drivers/test_lakeshore_m81_lockin.py`
  - `tests/unit/instruments/drivers/test_keithley_6221.py`
- Moved the following legacy groups:
  - `TestSRS830`
  - `TestLakeshoreM81LockIn`
  - `TestKeithley6221`
- Kept the small `_null(...)` helper local to each split file so the modules
  remain directly runnable from an IDE without depending on package-style test
  imports.
- Treated `TestSRS830` as its own focused lock-in slice because the SR830 is
  not SCPI-based in the same sense as the other two moved classes, while
  `LakeshoreM81LockIn` and `Keithley6221` remain straightforward SCPI driver
  migrations.
- Trimmed the moved imports and classes out of `tests/test_instruments.py`.
- Verified the tranche:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
conda run -n stoner_measurement python -m pytest tests\unit\instruments\drivers\test_srs830.py tests\unit\instruments\drivers\test_lakeshore_m81_lockin.py tests\unit\instruments\drivers\test_keithley_6221.py tests\test_instruments.py --tb=short
conda run -n stoner_measurement python -m ruff check tests\unit\instruments\drivers tests\test_instruments.py
conda run -n stoner_measurement python -m pytest tests\unit\instruments\drivers\test_srs830.py tests\unit\instruments\drivers\test_lakeshore_m81_lockin.py tests\unit\instruments\drivers\test_keithley_6221.py --tb=short
conda run -n stoner_measurement python tests\unit\instruments\drivers\test_srs830.py
conda run -n stoner_measurement python -m pytest --collect-only -q
```

Result:

- Overlap run before trimming: 406 passed.
- Split driver area after trimming: 59 passed.
- Direct-file smoke test: `test_srs830.py` passed when run as a script.
- Full collection: 2490 tests collected.
- Ruff checks passed for the split driver area and remaining monolith.

## Completed In Sixteenth Migration Pass

- Split the next adjacent driver tranche out of `tests/test_instruments.py`
  into:
  - `tests/unit/instruments/drivers/test_keithley_electrometers.py`
  - `tests/unit/instruments/drivers/test_lakeshore_m81_current_source.py`
  - `tests/unit/instruments/drivers/test_lakeshore_625.py`
- Moved the following legacy groups:
  - `TestKeithleyElectrometers`
  - `TestLakeshoreM81CurrentSource`
  - `TestLakeshore625`
- Kept the small local `_null(...)` helper in each split file so the new
  modules remain directly runnable from an IDE without depending on test
  package imports.
- Trimmed the moved imports and classes out of `tests/test_instruments.py`.
- Verified the tranche:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
conda run -n stoner_measurement python -m pytest tests\unit\instruments\drivers\test_keithley_electrometers.py tests\unit\instruments\drivers\test_lakeshore_m81_current_source.py tests\unit\instruments\drivers\test_lakeshore_625.py tests\test_instruments.py --tb=short
conda run -n stoner_measurement python -m ruff check tests\unit\instruments\drivers tests\test_instruments.py
conda run -n stoner_measurement python -m pytest tests\unit\instruments\drivers\test_keithley_electrometers.py tests\unit\instruments\drivers\test_lakeshore_m81_current_source.py tests\unit\instruments\drivers\test_lakeshore_625.py --tb=short
conda run -n stoner_measurement python tests\unit\instruments\drivers\test_keithley_electrometers.py
conda run -n stoner_measurement python -m pytest --collect-only -q
```

Result:

- Overlap run before trimming: 288 passed.
- Split driver area after trimming: 48 passed.
- Direct-file smoke test: `test_keithley_electrometers.py` passed when run as
  a script.
- Full collection: 2490 tests collected.
- Ruff checks passed for the split driver area and remaining monolith.

## Completed In Seventeenth Migration Pass

- Split the next adjacent controller tranche out of `tests/test_instruments.py`
  into:
  - `tests/unit/instruments/drivers/test_oxford_ips120.py`
  - `tests/unit/instruments/drivers/test_lakeshore_temperature_controllers.py`
  - `tests/unit/instruments/drivers/test_oxford_temperature_controllers.py`
- Moved the following legacy groups:
  - `TestOxfordIPS120`
  - `TestLakeshoreTemperatureControllers`
  - `TestOxfordTemperatureControllers`
- Kept the small local `_null(...)` helper in each split file so the new
  modules remain directly runnable from an IDE without depending on test
  package imports.
- Trimmed the moved imports and classes out of `tests/test_instruments.py`.
- Verified the tranche:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
conda run -n stoner_measurement python -m pytest tests\unit\instruments\drivers\test_oxford_ips120.py tests\unit\instruments\drivers\test_lakeshore_temperature_controllers.py tests\unit\instruments\drivers\test_oxford_temperature_controllers.py tests\test_instruments.py --tb=short
conda run -n stoner_measurement python -m ruff check tests\unit\instruments\drivers tests\test_instruments.py
conda run -n stoner_measurement python -m pytest tests\unit\instruments\drivers\test_oxford_ips120.py tests\unit\instruments\drivers\test_lakeshore_temperature_controllers.py tests\unit\instruments\drivers\test_oxford_temperature_controllers.py --tb=short
conda run -n stoner_measurement python tests\unit\instruments\drivers\test_oxford_ips120.py
conda run -n stoner_measurement python -m pytest --collect-only -q
```

Result:

- Overlap run before trimming: 240 passed.
- Split driver area after trimming: 53 passed.
- Direct-file smoke test: `test_oxford_ips120.py` passed when run as a script.
- Full collection: 2490 tests collected.
- Ruff checks passed for the split driver area and remaining monolith.

## Completed In Eighteenth Migration Pass

- Split the next adjacent instrument-core error-handling tranche out of
  `tests/test_instruments.py` into:
  - `tests/unit/instruments/contracts/test_instrument_error.py`
  - `tests/unit/instruments/contracts/test_protocol_error_handling.py`
  - `tests/unit/instruments/contracts/test_base_instrument_error_handling.py`
- Moved the following legacy groups:
  - `TestInstrumentError`
  - `TestScpiErrorHandling`
  - `TestOxfordErrorHandling`
  - `TestLakeshoreErrorHandling`
  - `TestCheckForErrors`
  - `TestAutoCheckErrors`
- Kept the small local `_null(...)` and `_NullTransportWithEsb` helpers inside
  the new base-instrument error file so the contract modules remain directly
  runnable from an IDE without test-package imports.
- Trimmed the moved classes out of `tests/test_instruments.py`.
- Normalized the existing import block in
  `tests/unit/instruments/contracts/test_transport_contracts.py` so the
  contract-area Ruff check stays green.
- Verified the tranche:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
conda run -n stoner_measurement python -m pytest tests\unit\instruments\contracts\test_instrument_error.py tests\unit\instruments\contracts\test_protocol_error_handling.py tests\unit\instruments\contracts\test_base_instrument_error_handling.py tests\test_instruments.py --tb=short
conda run -n stoner_measurement python -m ruff check tests\unit\instruments\contracts tests\test_instruments.py
conda run -n stoner_measurement python -m pytest tests\unit\instruments\contracts\test_instrument_error.py tests\unit\instruments\contracts\test_protocol_error_handling.py tests\unit\instruments\contracts\test_base_instrument_error_handling.py --tb=short
conda run -n stoner_measurement python tests\unit\instruments\contracts\test_instrument_error.py
conda run -n stoner_measurement python -m pytest --collect-only -q
```

Result:

- Overlap run before trimming: 187 passed.
- Split contract area after trimming: 35 passed.
- Direct-file smoke test: `test_instrument_error.py` passed when run as a
  script.
- Full collection: 2490 tests collected.
- Ruff checks passed for the contract area and remaining monolith.

## Completed In Nineteenth Migration Pass

- Split the next adjacent instrument-core tranche out of
  `tests/test_instruments.py` into:
  - `tests/unit/instruments/contracts/test_base_instrument_identity.py`
  - `tests/unit/instruments/contracts/test_instrument_locking.py`
- Moved the following legacy groups:
  - `TestIdentityAndQueueClearing`
  - `TestInstrumentLocking`
- Kept the small local `_null(...)` and `_NullTransportWithEsb` helpers inside
  the new identity-focused contract file so the modules remain directly
  runnable from an IDE without test-package imports.
- Trimmed the moved classes and now-unused imports out of
  `tests/test_instruments.py`.
- Verified the tranche:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
conda run -n stoner_measurement python -m pytest tests\unit\instruments\contracts\test_base_instrument_identity.py tests\unit\instruments\contracts\test_instrument_locking.py tests\test_instruments.py --tb=short
conda run -n stoner_measurement python -m ruff check tests\unit\instruments\contracts tests\test_instruments.py
conda run -n stoner_measurement python -m pytest tests\unit\instruments\contracts\test_base_instrument_identity.py tests\unit\instruments\contracts\test_instrument_locking.py --tb=short
conda run -n stoner_measurement python tests\unit\instruments\contracts\test_base_instrument_identity.py
conda run -n stoner_measurement python -m pytest --collect-only -q
```

Result:

- Overlap run before trimming: 152 passed.
- Split contract area after trimming: 15 passed.
- Direct-file smoke test: `test_base_instrument_identity.py` passed when run
  as a script.
- Full collection: 2490 tests collected.
- Ruff checks passed for the contract area and remaining monolith.

## Completed In Twentieth Migration Pass

- Split the adjacent temperature-controller contract tranche out of
  `tests/test_instruments.py` into:
  - `tests/unit/instruments/contracts/test_temperature_controller_contracts.py`
- Moved the following legacy groups into that dedicated contract module:
  - `TestTemperatureControllerCore`
  - `TestTemperatureControllerEnums`
  - `TestTemperatureControllerDataClasses`
  - `TestTemperatureControllerComposite`
  - `TestTemperatureControllerOptional`
  - `TestTemperatureControllerExports`
  - `TestZoneEntry`
  - `TestZoneEntryOptionalAPI`
- Folded the `ramp_to_setpoint` composite-method assertions into the same
  temperature-controller contract module so the `_make_tc(...)` helper could
  leave the top-level monolith entirely.
- Trimmed the moved helper, classes, and now-unused temperature-controller
  imports out of `tests/test_instruments.py`.
- Verified the tranche:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
conda run -n stoner_measurement python -m pytest tests\unit\instruments\contracts\test_temperature_controller_contracts.py tests\test_instruments.py --tb=short
conda run -n stoner_measurement python -m ruff check tests\unit\instruments\contracts tests\test_instruments.py
conda run -n stoner_measurement python -m pytest tests\unit\instruments\contracts\test_temperature_controller_contracts.py --tb=short
conda run -n stoner_measurement python tests\unit\instruments\contracts\test_temperature_controller_contracts.py
conda run -n stoner_measurement python -m pytest --collect-only -q
```

Result:

- Overlap run before/after trimming: 137 passed.
- Split temperature-controller contract module: 70 passed.
- Direct-file smoke test:
  `test_temperature_controller_contracts.py` passed when run as a script.
- Full collection: 2490 tests collected.
- Ruff checks passed for the contract area and remaining monolith.

## Recommended After Twentieth Migration Pass

1. Continue `tests/test_instruments.py` with the final adjacent tail:
   - `TestLockInAmplifierExports`
   - `TestOxfordMercuryIPS`
2. That would leave the top-level file focused almost entirely on the abstract
   instrument/protocol foundations, with the remaining concrete Oxford driver
   tests moved into `tests/unit/instruments/drivers/` and the lock-in export
   check either folded into an existing lock-in contract file or a tiny new
   contract module.

## Completed In Twenty-First Migration Pass

- Split the final adjacent tail out of `tests/test_instruments.py` into:
  - `tests/unit/instruments/contracts/test_lockin_amplifier_exports.py`
  - `tests/unit/instruments/drivers/test_oxford_mercury_ips.py`
- Moved the following legacy groups:
  - `TestLockInAmplifierExports`
  - `TestOxfordMercuryIPS`
- Kept the small local `_null(...)` helper in the new Oxford Mercury iPS driver
  module so it remains directly runnable from an IDE without package-style test
  helper imports.
- Trimmed the moved classes and now-unused Oxford Mercury iPS / magnet-status
  imports out of `tests/test_instruments.py`.
- Verification notes:

```powershell
conda run -n stoner_measurement python -m pytest tests\unit\instruments\contracts\test_lockin_amplifier_exports.py tests\unit\instruments\drivers\test_oxford_mercury_ips.py tests\test_instruments.py --tb=short
python -m pytest tests/unit/instruments/contracts/test_lockin_amplifier_exports.py tests/unit/instruments/drivers/test_oxford_mercury_ips.py tests/test_instruments.py --tb=short
python -m ruff check tests/unit/instruments/contracts/test_lockin_amplifier_exports.py tests/unit/instruments/drivers/test_oxford_mercury_ips.py tests/test_instruments.py
```

Result:

- The requested conda-environment pytest command could not run in this Linux
  container because `conda` is not on `PATH`.
- The fallback plain-Python pytest command could not collect tests because the
  ambient Python environment has `qtpy` but no Qt binding installed.
- Ruff checks passed for the new focused modules and the remaining monolith.

## Recommended After Twenty-First Migration Pass

1. Continue reducing `tests/test_instruments.py` by moving the remaining
   abstract hierarchy, base instrument, and protocol contract groups into
   focused modules under `tests/unit/instruments/contracts/`:
   - `TestAbstractEnforcement`
   - `TestBaseInstrument`
   - `TestScpiProtocol`
   - `TestOxfordProtocol`
   - `TestLakeshoreProtocol`
2. Once those groups move, `tests/test_instruments.py` can be removed or left
   only as a temporary compatibility shim while collection counts are compared.

## Completed In Twenty-Second Migration Pass

- Split the remaining instrument monolith contract groups out of
  `tests/test_instruments.py` into:
  - `tests/unit/instruments/contracts/test_abstract_instrument_contracts.py`
  - `tests/unit/instruments/contracts/test_base_instrument_core.py`
  - `tests/unit/instruments/contracts/test_protocol_formatting.py`
- Moved the following legacy groups:
  - `TestAbstractEnforcement`
  - `TestBaseInstrument`
  - `TestScpiProtocol`
  - `TestOxfordProtocol`
  - `TestLakeshoreProtocol`
- Kept the small local `_null(...)` helper in the new base-instrument core
  module so it remains directly runnable from an IDE without package-style test
  helper imports.
- Removed `tests/test_instruments.py` now that its remaining coverage has been
  split into focused contract and driver modules.
- Verification notes:

```powershell
conda run -n stoner_measurement python -m pytest tests\unit\instruments\contracts\test_abstract_instrument_contracts.py tests\unit\instruments\contracts\test_base_instrument_core.py tests\unit\instruments\contracts\test_protocol_formatting.py --tb=short
python -m pytest tests/unit/instruments/contracts/test_abstract_instrument_contracts.py tests/unit/instruments/contracts/test_base_instrument_core.py tests/unit/instruments/contracts/test_protocol_formatting.py --tb=short
python -m ruff check tests/unit/instruments/contracts
```

Result:

- The requested conda-environment pytest command could not run in this Linux
  container because `conda` is not on `PATH`.
- The fallback plain-Python pytest command could not collect tests because the
  ambient Python environment has `qtpy` but no Qt binding installed.
- Ruff checks passed for the full instrument contract test area.

## Recommended After Twenty-Second Migration Pass

1. Pick the next top-level plugin or UI test monolith listed in the test suite
   and split one cohesive behaviour group into the corresponding `tests/unit/`
   or `tests/integration/` area.
2. For instrument tests specifically, keep future driver-specific additions in
   `tests/unit/instruments/drivers/`, transport additions in
   `tests/unit/instruments/transport/`, and abstract/protocol contract additions
   in `tests/unit/instruments/contracts/` rather than recreating
   `tests/test_instruments.py`.

## Completed In Twenty-Third Migration Pass

- Split the SI spin-box widget tranche out of `tests/test_new_ui_widgets.py` into:
  - `tests/unit/ui/widgets/test_si_spin_box.py`
- Moved the `TestSISpinBox` legacy group, including the widget export checks and
  theme stylesheet regression check that depended on the same widget import
  context.
- Trimmed the moved class and now-unused imports from `tests/test_new_ui_widgets.py`.
- Verification notes:

```powershell
conda run -n stoner_measurement python -m pytest tests\unit\ui\widgets\test_si_spin_box.py tests\test_new_ui_widgets.py --tb=short
python -m pytest tests/unit/ui/widgets/test_si_spin_box.py tests/test_new_ui_widgets.py --tb=short
python -m ruff check tests/test_new_ui_widgets.py tests/unit/ui/widgets/test_si_spin_box.py
```

Result:

- The requested conda-environment pytest command could not run in this Linux
  container because `conda` is not on `PATH`.
- The fallback plain-Python pytest command could not collect tests because the
  ambient Python environment has `qtpy` but no Qt binding installed.
- Ruff checks passed for the new SI spin-box module and the remaining UI widget
  monolith.

## Next Recommended Migration Batch

1. Continue reducing `tests/test_new_ui_widgets.py` with another focused widget
   tranche, for example `TestEditorWidget` and `TestPythonHighlighter` into a
   dedicated editor-widget module under `tests/unit/ui/widgets/`.
2. Keep application-wide `MeasurementApp` workflow tests for a later pass under
   `tests/integration/app/` rather than mixing them into widget unit modules.

## Completed In Twenty-Fourth Maintenance Pass

- Added the shared `managed_qt_widget` fixture for tests that construct
  top-level or lifecycle-sensitive widgets. It retains strong references until
  fixture teardown, then closes widgets and drains deferred-delete events.
- Applied the fixture to the main-window integration tests and the focused
  PlotWidget/plot-command suites.
- Added an explicit `MainWindow.closeEvent()` ownership boundary so its child
  `PlotWidget` closes its PyQtGraph scene before the containing window is
  destroyed.
- Added regression coverage for the parent-to-plot close handoff.

## Completed In Twenty-Fifth Migration Pass

- Replaced the 509-line legacy `tests/test_trace_data.py` compatibility
  monolith with focused canonical-contract coverage in
  `tests/unit/core/test_trace_data.py`.
- Removed tests for the retired tuple constructor, iteration/indexing shims,
  `add_column()`, and the duplicate trace-plugin acquisition APIs.
- Added behavior coverage for DataFrame copying, role and metadata validation,
  default completion, single-y construction, error views, acquisition failure
  status, shared-x multi-output acquisition, and multicolumn saving.
- Verification commands and results are recorded with the implementation that
  performed this migration.

## Completed In Twenty-Sixth Migration Pass

- Made `TraceData` the shared container for instrument traces and data
  accumulated by state scan/sweep plugins.
- Moved the `TraceData` implementation, column-role constants, and their
  focused tests into `stoner_measurement.core` and `tests/unit/core`.
- Removed the state-DataFrame catalogue and the DataFrame-to-trace transform;
  collecting state plugins now publish their data directly in `_traces`.
- Collapsed SaveCommand's trace/data branches into one TraceData path while
  retaining incremental TDI and NeXus saving.
- Removed the retired `save_mode`, `data_source`, and `dataframe_trace`
  configuration and entry-point fields from repository fixtures and metadata.

## Differential Trace-Mode Maintenance Coverage

- Added focused shared-helper and plugin coverage in
  `tests/unit/plugins/trace/test_differential_mode.py` for Keithley 2400 and
  6221/2182A alternating delta-current sweeps.
- Covered sweep modulation, three-reading voltage/dV reduction, endpoint
  voltage estimation, resistance/conductance selection, optional secondary
  nanovoltmeter data, conditional JSON persistence, configuration controls,
  and current-source validation.
- Verified this coverage together with the existing 2400, 6221/2182A,
  measurement-setting, and secondary-nanovoltmeter suites.

## Data Manager UI Coverage

- Added focused `tests/unit/ui/test_data_manager.py` coverage for catalogue-to-row
  rendering, rows-by-columns summaries, detailed column tooltips, selection
  preservation, and background TDI snapshot saving.
- Kept the existing application-shell toolbar grouping assertion in
  `tests/test_new_ui_widgets.py` aligned with the new Data Manager action; that
  broader application tranche remains a future migration candidate.
- Verified the focused Data Manager, Save command, and application-shell set
  (138 passed, 1 skipped), then the full suite (2,852 passed, 1 skipped).

## Font-Aware UI Sizing Coverage

- Replaced hard pixel caps on text-bearing buttons, spin boxes, controller
  status rows, and scan preset buttons with minimum dimensions so Qt can grow
  them from their current font metrics.
- Added application-wide tab sizing that reserves each label's selected
  demi-bold width and keeps non-elided labels available through scroll buttons.
- Added focused large-font checks in
  `tests/unit/ui/test_font_aware_sizing.py`.
- Verified 338 focused tab and panel tests, including stable selected and
  unselected widths for a large demi-bold label. The combined suite also
  completed cleanly: 2,855 tests passed and 1 was skipped.

## CI Test-Load Diagnostics

- Every test-matrix job writes JUnit XML so per-test durations can be compared
  across Python and Qt combinations.
- The PyQt6/Python 3.14 job records pytest test IDs as coverage contexts. Its
  raw coverage database can therefore identify which tests executed each
  source line without imposing the context-recording overhead on all four jobs.
- Matrix coverage artifacts retain the raw database, Codacy XML, and JUnit XML
  for 30 days. The merged XML and Codacy upload remain unchanged.
- After downloading `coverage-data-pyqt6-3.14`, generate inspectable context
  JSON with:

```powershell
coverage json `
  --data-file=coverage-pyqt6-3.14 `
  --show-contexts `
  -o coverage-contexts.json
```

Use the context data and JUnit timings together when proposing test
consolidation. A high test count or overlapping line coverage alone is not
enough evidence to remove distinct branch, error-path, or lifecycle contracts.

## Coverage-Guided Hardware Plugin Maintenance

- Used the retained PyQt6/Python 3.14 context database and all four JUnit
  reports to distinguish runtime hotspots from merely numerous tests.
- Patched the Keithley 6221 driver's real settling delay only in its
  transport-isolated unit module; its 38 tests retain their command assertions
  without spending roughly five seconds sleeping.
- Replaced the two narrow Multi-SR830 validation scenarios with parameterized
  common-setting, per-lock-in, and uniqueness contracts covering the extracted
  validation helpers.
- Added a compact parameterized Keithley 2400 routing table covering immediate,
  bus, external, trigger-link, timer, and trigger-output command sequences.
- Kept application and Qt lifecycle tests isolated; coverage overlap was not
  used as evidence to share live application instances or remove lifecycle
  contracts.
- Verified the changed files with Ruff formatting/linting and local McCabe
  checks at the Codacy threshold. The complete offscreen PyQt6 suite passed:
  3,323 tests passed and 1 dependency-path test was skipped.

## Priority Cold-Spot Coverage

- Added behaviour-focused coverage for the highest-value missed-line areas in:
  - `tests/unit/ui/widgets/test_round_dial.py`
  - `tests/unit/plugins/trace/test_daqmx_runtime.py`
  - `tests/unit/plugins/monitor/test_pressure_controller.py`
  - `tests/unit/plugins/transform/test_branch_split.py`
  - `tests/unit/instruments/transport/test_ftdi_d2xx_transport.py`
- Moved the small top-level `tests/test_pressure_monitor_plugin.py` module into
  the canonical monitor-plugin unit-test directory while extending it.
- Round-dial additions cover public range validation, clock/compass modes,
  label selection, theme colours, geometry, and complete offscreen rendering.
- DAQmx runtime additions cover task-definition validation, physical/global/
  saved task construction, resource cleanup, finite timing, trigger routing,
  output shaping, reads, and lifecycle calls through hardware-free fakes.
- Pressure-monitor and branch-split additions cover channel selection,
  missing-data/error behaviour, conditional catalogues, persistence, and Qt
  configuration interactions.
- FTDI D2XX coverage uses a narrow fake native library to exercise index and
  serial opening, timeout configuration, I/O, short writes, partial reads,
  timeout, purge, cleanup, and status errors without a driver or device.

## 2026-09-20 Codacy test policy

- Exclude tests from Prospector and Codacy's separate complexity metric using
  recursive `tests/**` globs. Production complexity remains checked.
- No test files, scenarios or fake-driver classes were moved or split in this
  cleanup. Retained test edits remove redundant lambdas and narrowly document
  deliberate generated-code execution and analyzer false positives.
- Final focused verification of the retained changes: 485 tests passed on
  offscreen PyQt5; Ruff, targeted Pylint and Bandit checks passed.
- See `notes/2026-09-20-codacy-cleanup.md` for the snapshot and validation scope.

## 2026-09-21: Optional secondary temperature controller

- Moved five affected behaviours from tests/test_temperature_control.py into
  tests/unit/control/test_secondary_temperature_controller.py and
  tests/unit/ui/panels/test_secondary_temperature_panel.py. Preserved setpoint
  invalidation, side-by-side loop layout and sensor-list coverage using real
  service sessions with simulated drivers. Updated disconnected-write expectations
  to explicit errors and the input-settings layout to owner-specific tables.
- Added tests/integration/plugin_workflows/test_secondary_temperature_sequence.py
  for secondary commands, scan/sweep routing, saved sequence/output expressions,
  optional-primary operation and Make Safe after a peer failure.
- Updated the sweep-generator test to select the loop its fake actually publishes;
  there is no longer an implicit fallback to a different loop. Updated command UI
  assertions for the advertised-loop selector replacing the free integer spin box.
- Initial migrated/source regression run: 205 passed. Full collection and broader
  checks are recorded in the secondary-controller implementation plan.

- Final affected regressions: 834 passed, 1 skipped; full collection: 3700 tests.
  The remaining legacy panel tests and chart chronology test now use the shared
  managed_temperature_panel fixture for deterministic PyQtGraph teardown. No
  further legacy test cases were removed during this lifecycle correction.

- Shared-stability follow-up: extended the existing secondary controller modules
  with cross-controller completed-poll checks, dependency freshness, row-priority
  migration, real splitter dragging and single-rate/source-switch regressions.
  Replaced the obsolete owner-local stability selector case with shared selection
  and offline-choice retention. No unrelated test migration was performed.

## 2026-09-21: Plot mouse-axis selection

- Added tests/unit/ui/widgets/test_plot_mouse_axes.py for real Qt clicks, pan,
  wheel/right-drag zoom, independent ranges, shared trace pairs, inactive
  autorange, and active-axis marker anchoring/labels. No legacy tests moved.
- Focused plot widget and marker-command regressions: 121 passed, using
  `conda run -n stoner_measurement pytest tests/unit/ui/widgets/test_plot_widget.py
  tests/unit/ui/widgets/test_plot_mouse_axes.py
  tests/unit/plugins/command/test_plot_markers_command.py -q -p no:cacheprovider`.
- Ruff check and format passed for both changed Python files.
- Visual check: rendered the dark-theme plot with bottom/right active and a
  marker. PyQt5 checks passed; PyQt6 validation was unavailable because that
  binding could not be imported in this environment.

## 2026-09-22: Secondary-controller regression follow-up

- Retained the ramp-stability scenario and updated its fake driver to advertise
  its input and loop through the controller capability contract.
- Replaced the DAQmx command's font-dependent window-height assertion with a
  check of the bottom stretch that keeps its controls top-packed.
- Added SI spin-box range coverage for default unbounded limits, one-sided
  limits, changed bounds and value clamping. The Qt-compatible range accessors
  report negative/positive infinity for missing bounds.
- No tests were moved or removed. The focused widget, stability, polling,
  DAQmx command, panel connection and secondary-controller modules passed
  together: 75 tests on offscreen PyQt5 in the project Conda environment.
- Complete-suite coverage in two processes: `pytest --ignore=tests/integration`
  passed 3,690 tests with one skip; `pytest tests/integration` passed 27 tests.
  Both used `-q --tb=short -p no:cacheprovider` and separate fresh workspace
  `--basetemp` directories to avoid the default temporary-directory permission
  failure. Ruff and `git diff --check` passed for the changes.
- A single-process default-order run aborted in Qt event processing during
  `test_dummy_plugin.py`, also on a retry without capture. The initial 318 tests
  through that module passed when selected together separately. The Qt abort
  remains unisolated; the split runs are not a claim of a clean single-process
  full-suite run.

## 2026-09-22: CI configuration-page lifetime failure

- GitHub run `35713068841`, commit `124beb3f`, aborted in the Python 3.14 /
  PyQt6 job; the other three matrix jobs passed. The exception was
  `QGraphicsTextItem has been deleted` in PyQtGraph `LabelItem.resizeEvent`
  during pytest-qt event processing at the Keithley 2400 configuration test.
- That test registered only Settings with `qtbot`; its scan-preview page and
  the configuration pages in the preceding Multi-SR830 module lacked scoped
  ownership. This matches the previously diagnosed deferred-event lifetime
  failure, although the precise originating page cannot be proved from the
  CI stack alone.
- Added `managed_plugin_config_tabs`, which registers every returned page with
  `managed_qt_widget`. Applied it to the Keithley 2400 configuration test and
  all 14 Multi-SR830 configuration tests. No assertions or tests were removed;
  the existing modules remain in place for this bounded lifecycle repair.
- Baseline: the two affected modules passed locally (119 tests), so the CI
  crash was not reproduced in the available PyQt5 environment.
- Validation: affected modules plus `tests/unit/plugins/trace/test_trace_plugin.py`
  passed 156 tests. A single-process full run passed 3,717 tests with one skip:
  `pytest -q --tb=short -p no:cacheprovider
  --basetemp=.pytest-runtime/ci-lifecycle-full` (72.52 seconds).
  Commands used the project Conda environment, offscreen Qt and Windows fonts.
- Ruff check/format and `git diff --check` passed. Local Python is 3.14.7 with
  PyQt5 5.15.11; PyQt6 cannot be imported. The patch still needs hosted PyQt6
  validation before the CI failure can be considered resolved.
- The exact Keithley configuration node also passed in ten separate fresh
  pytest processes. An earlier repeated-node invocation collected 20 entries
  but executed only one, so it is not counted as repeated validation.

## 2026-10-10: Codacy plotting maintenance

- No tests were added, moved or removed. The registry discovery fake now uses
  a local exception reference for Pylint narrowing; its failure contract and
  existing assertions are unchanged.
- The focused plotting selection passed 381 tests under Python 3.14.7 / PyQt5
  5.15.11, offscreen with Windows fonts and pytest caching disabled. It covers
  surface/service transactions, display discovery/replacement, plot and axis
  widgets, command signals and sequence integration.
- Commands and scope are recorded in
  [the maintenance note](2026-10-10-codacy-cleanup.md). No new Qt page ownership
  or test migration work was required; other bindings were not validated.

## 2026-10-10: plotting performance batches

- Extended existing core service/regrid and native canvas test modules; no
  tests were moved or removed. Added deterministic checks for bulk redraws,
  notification deduplication, immutable buffer isolation, snapshot/graphics
  reuse, topology invalidation, prepared validation, colour-bar ordering,
  ordered group failures/capacity rejection, dispatch yielding and engine use
  of condition-based readiness. Timing probes remain outside CI assertions.
- Existing scoped `managed_qt_widget` ownership is retained. The native GPU
  test now updates an existing mesh before painting its hidden framebuffer.
- Each of the five batches passed its focused selection and ran the standalone
  probe. Final verbose combined plotting/sequence selection: 560 passed;
  native Windows OpenGL: 1 passed. Python 3.14.7 / PyQt5 5.15.11 were validated.
- A quiet combined run reproduced the previously documented Windows Qt access
  violation during a surface worker wait. Scoped fixture ownership was checked;
  the failure remains unresolved. No global teardown or suppression was added.
- Detailed scope, measurements and limits are recorded in
  [the performance review](2026-10-10-plotting-performance-review.md).

## 2026-10-10: Cartesian bottom-axis layout

- Added four parameterized viewport-containment cases to the existing
  `tests/unit/ui/widgets/test_plot_widget.py`; no tests were moved or removed.
  They cover larger labels, additional bottom/top/right axes, legend resizing
  and repeated window resizing, with scoped managed widget ownership.
- Focused plotting/axis/display/service regression selection: 171 passed.
  The new cases also passed at 150% Qt scaling (4 passed). Ruff, formatting,
  error-level Pylint for the changed production module and diff checks passed.
- Reproduction details and validation limits are recorded in
  [the axis-layout note](2026-10-10-cartesian-axis-layout.md).

## 2026-10-10: Engine and command performance

- Added focused concurrency coverage in `tests/unit/core/test_controller_polling.py`
  and extended existing controller/command modules for worker timer ownership,
  slow-poll GUI responsiveness, completion invalidation, focused flow snapshots,
  state notifications, pending X-ray motion and propagated failures. Added a
  Make Safe failure case retaining the zero-field heater gate.
- The legacy magnet publisher poll case now waits for asynchronous publication
  before shutdown. No tests were moved or removed, and scoped Qt ownership is
  retained. Production hardware protocols and passive monitor defaults remain.
- Final expanded controller/command/state/scan/monitor/panel/sequence selection:
  1509 passed, 1 skipped. Ruff, error-level Pylint and diff checks passed.
  Follow-up deadline/cancellation/controller/sequence selection: 209 passed.
  Batch counts, simulated timing results and bench-validation limits are in
  [the implementation note](2026-10-10-engine-command-performance-implementation.md).
