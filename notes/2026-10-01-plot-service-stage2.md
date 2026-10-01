# Plot service Stage 2 handover

Stage 2 of the [approved plan](2026-10-01-plot-display-plugin-plan.md) is complete.
The main application retains its existing Cartesian widget and now owns a stable
plot service. Display factories, the host, discovery, replacement and replay are
reserved for Stages 3 and 4. Embedded controller charts and scan previews retain
their existing concrete widgets.

## Routing and ownership

- `core/plotting/service.py` owns ordered requests, completion tickets, bounded
  pending work, plotted channel snapshots and thread-safe public descriptions.
  Every accepted request receives one terminal result. Reused IDs and queue
  overflow are rejected before acceptance. IDs remain reserved for the service
  lifetime; completed tickets leave the pending collection.
- `ui/plotting_bridge.py` borrows the fixed Cartesian widget. Only GUI dispatch
  accesses the renderer. Validation rejects unsupported coordinates and invalid
  styles, axis orientations and mapping domains before applying an operation.
  Renderer exceptions produce failed results and retain the previous canonical
  data snapshot; graphics rollback is not promised.
- `CompletionTicket.wait()` supports worker waits and zero-time polling. Pending
  GUI waits are rejected. GUI compatibility uses ordered `apply_now()`; it drains
  earlier requests and rejects synchronous re-entry during an active operation.
  A wait timeout leaves its request pending. Stop/shutdown cancel queued work;
  an operation already applying may finish. Shutdown does not close the borrowed
  widget. The application shuts down its service before closing the display.
- `SequenceEngine.plot_client` is the stable endpoint. Assigning or clearing it
  rebinds already attached producers without duplicate rendering connections.
  Engine ticket waits honour pause, stop and timeout. Engines borrow the service
  and cancel pending work on shutdown without taking ownership of the display.
- `engine.plot_widget` in the application is an explicit legacy facade. Its
  allowlist is the Stage 1 compatibility table. Data calls enter the portable
  route; other supported Cartesian operations use the same ordered GUI queue.
  Keyword calls, marker IDs, Boolean marker-removal results, copied getters and
  legacy rename semantics are preserved. It exposes no private graphics members.
  GUI inspection can still use `MainWindow.plot_widget` while the host is deferred.

## Migrated producers and state

Point and trace commands submit complete data, uncertainty, metadata, axis and
style requests. Their existing signals remain observable but are disconnected
from the renderer when a client is present. Clear and marker commands use the
same service. Optional extremum annotations log failures without discarding the
numerical transform result. JSON fields and generated action syntax are unchanged.
Standalone engines without a client retain legacy signal routing.

Axis selectors read public descriptions rather than private orientation maps.
The Cartesian widget provides public axis/series descriptions and uncertainty
snapshots. Series titles can change without changing portable identity. Axis
activation, named axes, manual ranges, marker anchors and existing styles remain
governed by the Cartesian widget. A signal updates cached descriptions when
controls change. Full export/import of styles, markers, ranges and legend settings
is Stage 4 work; these snapshots are not a replacement/replay implementation.

Plot data uses immutable captured arrays. Appends preserve channel schema,
metadata, binding, coordinate descriptor and uncertainty columns. The service
retains append chunks and only assembles a full dataset for an explicit snapshot
query. Ordinary point append uses the widget's existing list buffers, avoiding
a new full-series copy per point. Error-bar append still concatenates renderer
arrays. This is not a latency or memory guarantee for future 3D displays.

## Validation and next gate

Added 23 cases in `tests/unit/core/test_plotting_service.py` and
`tests/integration/sequence/test_plot_service_commands.py`. Coverage includes real
Python-worker and engine-worker delivery, GUI ownership, immutable submission,
ordered clear/update, exactly-once results, complete metadata/style acknowledgement,
renderer failure, capability rejection, queue bounds, pause/stop/timeout/shutdown,
headless execution, repeated attachment, keyword compatibility and saved point
commands executing generated actions with markers and clear.

The complete suite passed **3,800 tests with one skip**, collecting 3,801, using
Python 3.14.7, PyQt5 5.15.11, offscreen Qt and Windows fonts. The command was
`pytest -q --tb=short -p no:cacheprovider
--basetemp=.pytest-runtime/plot-stage2-full` through the project Conda environment.
New service/bridge typing checks and changed-file Ruff checks passed. All 15
Sphinx-page doctest examples passed. Sphinx validation retains the existing API
documentation warning baseline. This does not claim PyQt6/PySide6 CI validation
or instrument bench testing.

Stage 3 may now introduce a stable host and factory/discovery contract. Keep the
service borrowed by producers and the current concrete display fixed until that
gate is proven. Stage 4 must implement explicit export/import before replacement;
do not reconstruct renderer state by reflecting over private widget members.
