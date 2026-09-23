# Secondary temperature controller implementation plan

Date: 2026-09-21
Status: implementation and software validation complete; physical bench
acceptance outstanding. Secondary remains optional and disabled by default.
Baseline: main at 052bde7519b16f8a2738c0f5e86bb0d3cc7f4181.

## Objective

Support a primary and optional secondary temperature controller through the
existing shared engine, panel, and sequence plugins. Present combined loop and
sensor catalogues while retaining controller ownership, hardware restrictions,
independent connection settings, and compatibility with existing single-controller
rigs and saved sequences.

## Inspection findings

Paths below are relative to src/stoner_measurement unless otherwise stated.

- temperature_control/engine.py: TemperatureControllerEngine is a singleton with
  one `_driver`, one preferred/live connection triple, one timer and RLock. All
  control and input-settings methods route directly to that driver.
  connect_instrument replaces the existing connection and clears every history;
  disconnect_instrument and shutdown clear the whole service. `_disconnect_driver`
  logs and suppresses cleanup exceptions; failed connection handling does not
  explicitly clean up the candidate driver.
- engine.py:_build_state, _collect_readings and _collect_loop_data obtain one
  capability descriptor. History keys are bare channel strings and loop keys are
  integers. Two instruments with channel A and loop 1 would collide.
  read_controller_state has one error boundary and one cache-age timestamp.
- temperature_control/types.py: TemperatureEngineState uses string channel keys
  and integer loop keys. Needle-valve and gas-auto values are single scalars.
  StabilityConfig is global; bands contain bare tolerance/rate channel names.
- engine.py:_evaluate_stability uses the global band for every loop.
  _reading_for_channel falls back to the first reading even when a specifically
  requested channel is absent. Missing readings can fall back to the reported
  setpoint and zero rate. These behaviours must not validate an unavailable
  secondary loop or select an unrelated sensor after aggregation.
- instruments/temperature_controller.py: ControllerCapabilities lists inputs and
  loops, optional features, heater ranges and temperature limits, but has no
  per-loop list of permitted inputs. Concrete Lakeshore/Oxford drivers validate
  local identifiers; Eurotherm validates its sole PV input. Driver commands must
  continue receiving native local identifiers.
- ui/temperature_panel.py: one connection form, one status, and one capabilities
  object drive the control groups, zone editor, input settings, curve names,
  stability selectors and cryogen controls. `_LoopControlGroup` currently offers
  all inputs from that descriptor. Charts and saved trace preferences use loop/
  channel-derived keys; the needle-valve trace has the single key NV.
  Connection forms use ui/widgets/controller_connection.py helpers, which expect
  a panel-like object with one engine and connection form.
- plugins/state/_temperature_controller_plugin.py: scan/sweep share the singleton,
  integer control_loop, bare sensor_channels, primary-driver connection checks,
  and limits obtained from connected_driver. _state_control_loop can fall back
  to another loop. Configuration uses a free integer spin box and sensor text.
- plugins/state_scan/temperature_controller.py and
  plugins/state_sweep/temperature_controller.py inherit that shared behaviour.
- plugins/command/set_temperature.py: integer loop, primary connection check,
  setpoint/stability/readback keyed by that integer. Keep its configurable timeout
  and Timed Out output semantics.
- plugins/monitor/temperature_controller.py: integer loop lists, bare sensor lists,
  one-driver capability fallback, cached/forced polling, and generated expression
  strings/labels all need explicit ownership. Its disconnect must continue leaving
  the shared service running.
- plugins/command/make_safe.py:_make_temperature_safe reads connected_driver and
  iterates range(1, num_loops + 1). It must cover both controllers using actual
  advertised loop_numbers, including non-contiguous numbers.
- app.py creates one panel and subscribes to one engine status/activity publisher;
  its stop-temperature action calls shutdown. Keep one application feature and
  service, with shutdown covering both instruments. Public exports in __init__.py
  and temperature_control/__init__.py need review if new reference types are public.
- temperature_control/config.py merges bundled and machine YAML and backs up saves.
  conf/temperature_controller.yaml currently has connection, polling_rate_hz and
  stability. Preserve that loader/save workflow.

## Proposed architecture and contracts

### 1. One service, two owned controller sessions

Keep TemperatureControllerEngine.instance() and its publisher as the application
entry point. Introduce a small private session record for each stable slot:
primary and secondary. Each session owns its driver, preferred/live connection
settings, capabilities, status, last successful poll time and connection generation.
The secondary slot defaults disabled. Labels may be editable, but never become IDs.

Provide slot-aware connection, disconnection, readiness and capability methods.
Existing no-slot connection properties/methods remain primary aliases; shutdown
always attempts both sessions. Plugins request the specific controller(s) they
need, rather than testing whether any driver is connected. Do not silently route
a missing secondary target to primary. Allow secondary to remain useful when
primary is disconnected.

Replacing or disconnecting a session clears only its readings, target setpoints,
stability timers, histories and cached settings. Clean up partial connection
attempts, propagate cleanup failures and abort replacement on failed cleanup.
Attempt cleanup of both sessions during shutdown even if one fails; report the
failures after all attempts. Reject an identical normalized physical connection
assigned to both slots, while allowing distinct simulated instrument instances.

Retain the existing polling interval and synchronous execution model initially.
Poll connected sessions independently and publish a combined result, catching
failures per session. A slow transport can still delay the next poll of its peer;
measure this with the rig before considering worker threads as a separate change.

### 2. Stable references and combined catalogues

Use immutable LoopRef(controller_id, local_loop) and
ChannelRef(controller_id, local_channel) internally. Never allocate secondary loop
numbers by offsetting the primary loop count: replacement or disconnection must
not change the identity of a saved sequence target.

Expose ordered combined loop/channel descriptors containing reference, display
label, owner, availability and applicable capabilities. Example labels are
Primary / Loop 1, Secondary / Loop 1, Primary / A and Secondary / A. Store references
in combo-box item data; do not parse display labels.

Keep canonical state keyed by qualified references. Preserve existing primary-only
state mappings as compatibility views/accessors, and introduce explicitly named
aggregate mappings/accessors for migrated consumers. Avoid duplicate entries in
canonical iteration and independent mutable copies of the same state. Verify
existing TemperatureEngineState construction used by tests/public consumers when
finalising this adapter. Legacy engine calls with loop 1 or channel A continue to
mean primary; aggregate callers use references explicitly.

Store controller-scoped auxiliary state (needle valve, gas-auto mode, calibration
curve names) by slot. Legacy scalar accessors remain primary-only. Capability
queries are per selected loop/channel/controller; a union of optional-feature
flags is insufficient for deciding whether a write is supported.

### 3. Loop/channel compatibility

Add an additive driver contract for valid inputs per local loop (for example,
get_loop_input_channels(loop)), with a default matching existing advertised inputs
and driver overrides where restrictions exist. Verify restrictions against the
relevant instrument manuals when implementing overrides; this inspection did not
establish new hardware claims.

The service qualifies those inputs with their owner. A loop input selector shows
only that set. Validate owner, local loop and local channel at the engine boundary,
including script calls and loaded settings. Validate all references in Apply All
before sending its first hardware command, so an invalid channel does not cause a
partial setpoint/mode update. ZoneEntry.input_channel is a native instrument index;
keep that meaning and validate it against the selected controller's zone semantics.
Monitoring may combine readings from either controller.

### 4. Stability, freshness and failures

Give each controller its own stability configuration initially, retaining the
current band semantics within that controller. Migrate existing stability settings
to primary; initialise secondary with defaults rather than copying primary sensor
names. All rate histories and per-loop stability state use qualified identities.

Preserve blank-channel legacy selection within the owning controller for this
migration. An explicitly selected missing sensor must be unavailable, not silently
replaced. A future per-loop stability table can be considered separately if rigs
need different criteria for different loops of the same instrument.

Default stability selectors to channels on the owning controller. Cross-controller
stability criteria are outside this initial change; reporting both remains allowed.
Keep hardware feedback-input compatibility distinct from stability observation:
stability can use another sensor on the same controller without changing its PID
input assignment.

Track freshness and errors per controller. Failed/disconnected/stale/invalid-sensor
loops cannot satisfy a stability wait. Reset their continuous stability window;
retain last values only as explicitly stale display data. Do not use setpoint as
an absent sensor measurement. Preserve healthy peer histories and continued
polling. Report aggregate ERROR when a required enabled session has failed, with
per-session details; a deliberately disconnected session is shown as disconnected.
The toolbar remains aggregate, while the panel explains which session is affected.
Preserve existing timeout/continue behaviour and Timed Out reporting; connection
or target-resolution failures must be explicit errors, not successful no-op writes.

### 5. Configuration and sequence migration

Use a versioned YAML schema with controllers.primary and controllers.secondary,
each containing enabled, label, connection and stability. Keep polling_rate_hz at
service scope. Load old connection/stability into primary and disable secondary.
Normalise legacy machine YAML before merging schema defaults, so new bundled
primary defaults cannot shadow old user values. New schema wins deterministically
if both formats are present. Preserve existing backup/atomic replacement behaviour.

For command/scan/sweep JSON add controller_id (default primary), retaining the
local control_loop integer. For mixed monitor selections and explicit sensor lists,
write structured references such as {controller_id: secondary, channel: A} and
{controller_id: secondary, loop: 1}; restore legacy integers/strings as primary.
Make parsing shared and strict for explicit new references. Keep missing targets
visible when editing offline and fail clearly at execution instead of resetting
selection to the first available target.

Keep old primary output labels and script calls working. Add unambiguous qualified
secondary labels/accessor arguments, using proper repr-based expression generation.
Refresh data catalogues when topology/selection changes. Test sequence JSON,
saved-data sequence reconstruction and expression round trips so selected outputs
continue identifying the same sensors after reload. New two-controller sequences
need not be loadable by older releases; document that boundary.

### 6. Panel and plugin experience

Show Primary and optional Secondary connection groups, each with its own driver,
transport/address, connect/disconnect action and health. Extract a small connection
form using existing shared widgets/helpers; do not duplicate the entire panel.
Keep one Save Settings to YAML action and persist both forms' edited preferences,
including an unconnected secondary configuration.

Amalgamate control groups and input-channel rows, clearly labelled by owner. Zone,
curve and cryogen controls use the selected owner and its capabilities. Present
one cryogen group per supporting controller. Stability editing selects the
controller whose table is being edited. Use shared FontAwareTabWidget/SISpinBox
and top-packed layouts.

Charts combine both controllers with stable qualified trace identities, including
setpoint, heater, rate and needle valve. Preserve per-trace timestamps, history
window trimming and selected-rate-channel alignment. Migrate old chart preference
keys to primary and ensure a reconnect neither renames nor mixes traces.

Replace plugin free-form loop numbers with catalogue-backed selectors that retain
unavailable saved references. Monitor selectors allow both controllers, and blank
sensor selection still means all available sensors across the service. Explicit
lists retain their exact identities. Remove fallback-to-another-loop behaviour
from target execution and readiness decisions. Scan/sweep limits come from the
selected loop's owner. Plugins continue borrowing, never closing, engine resources.

## Implementation batches and completion gates

0. Record baseline and agree the reference/compatibility, stability and schema
   contracts above. Read notes/testing_guidelines.md and the migration log before
   test changes. Run existing temperature, command, scan/sweep and chart tests in
   the project Conda environment; record failures separately from new regressions.
1. Add reference types, descriptors, valid-input contract and YAML/JSON normalisers
   with legacy fixtures. Gate: deterministic IDs, collision-free same-model rigs,
   legacy primary settings and malformed-reference rejection.
2. Add owned sessions, slot lifecycle and aggregate catalogues; route all engine
   reads/writes, zones, input settings, curves and auxiliaries through resolution.
   Gate: two fake drivers receive only their own native commands; invalid Apply
   All writes nothing; reconnect/failure/shutdown clean up the correct resources.
3. Add combined polling/state, compatibility views, per-session freshness and
   stability isolation. Gate: a failed secondary cannot satisfy a wait or erase
   primary history; recovery starts a new stability window. Cover overlapping
   channel names, non-contiguous loops and different capabilities.
4. Adapt panel connections, combined controls, settings and charts. Gate: offscreen
   interaction and visual checks demonstrate correct selectors, independent
   connection status, mixed feature visibility, saved settings and trace identity.
5. Adapt Set Temperature, scan, sweep, monitor, Make Safe and application status/
   shutdown integration. Gate: run a sequence controlling secondary while reporting
   both; reload it and verify the same targets and output expressions. Make Safe
   attempts every advertised loop on both connected controllers even after one
   operation fails, and reports failures. Preserve existing output-off semantics.
6. Update plugin About documentation, user configuration examples and migration
   notes, then run broader regressions. Record results and any bounded deferrals
   in this plan. Bench-validate a two-controller rig before claiming hardware
   readiness; include a mixed-model rig if available.

Each batch should remain reviewable and update this plan with evidence. Do not
bundle unrelated driver protocol changes or a polling-thread redesign.

## Verification scope

Existing coverage anchors: tests/test_temperature_control.py,
tests/test_temperature_monitor_plugin.py,
tests/unit/ui/panels/test_temperature_panel_chart.py,
tests/unit/plugins/state/test_temperature_controller_scan.py, command tests under
tests/unit/plugins/command, and driver contracts/tests under tests/unit/instruments.
Locate shared state-sweep and saved-data restoration coverage before batch 5.

Add focused behaviour tests in the unit/integration layout from the testing guide.
If a touched legacy monolith requires migration, move one cohesive tranche, run
both modules plus collection, and update notes/testing_restructure_plan.md.
Use narrow fake drivers, isolated settings and deterministic timestamps, not real
user configuration or arbitrary sleeps. Test primary-only and secondary-only
operation, both identical and mixed controllers, disabled-secondary startup,
connection failure, cleanup failure, repeated reconnect, stale cache, missing
sensors, invalid sensor status and missing saved selections.

Run tools through conda run -n stoner_measurement (prefer CONDA_EXE); use
QT_QPA_PLATFORM=offscreen and QT_QPA_FONTDIR=C:\Windows\Fonts for UI validation.
Run focused pytest and Ruff checks per batch, appropriate integration regressions
at completion, and git diff --check. Bench checks must verify actual channel
assignment, independent setpoints/ramps, disconnect/reconnect and Make Safe on
both instruments. Simulated tests cannot establish physical controller behaviour.

## Inspection validation

The current local checkout and code paths were inspected. No production code or
tests were changed or executed for this planning task. Existing unrelated untracked
files were left untouched. The proposed hardware capability extensions still need
manual verification during implementation. Local tool sandbox setup failed;
repository inspection and writing this note used approved elevated shell access.

## Implementation record

- Baseline: 169 focused tests passed on PyQt5 after supplying a dedicated pytest
  temporary directory. The first attempt had 166 passes and three setup errors
  caused by permissions on the default temporary directory.
- Batches 1-3: added stable LoopRef/ChannelRef references, configuration
  normalisation before merging, optional secondary sessions, qualified routing,
  driver input-compatibility contract and isolated stability/freshness handling.
  The existing per-instrument engine code is reused as _ControllerSession;
  TemperatureServiceMixin supplies aggregation/routing. Local snapshots remain
  authoritative; all_readings and loop_values provide qualified aggregate views
  without maintaining duplicate mutable state. Primary state fields retain their
  original meaning and constructor compatibility.
- Batch 4: extracted the shared connection form; added the optional secondary
  group, combined owned loops/zones, owner-specific input/curve/cryogen controls,
  local stability editing and secondary-prefixed chart traces. Primary trace
  keys are unchanged, so no rewrite of existing chart preferences is needed.
- Batch 5: command/scan/sweep target selection and JSON carry controller_id;
  monitor and sensor selections accept qualified references and catalogue pickers.
  Make Safe attempts both controllers and reports collected failures. Plugins
  retain borrowed-service ownership. Single-controller settings still work.
- Validation to date: 205 focused tests pass, including 28 new/migrated controller,
  panel and sequence workflow cases. A Qt-specific integration test identified
  that QVariant lookup does not reliably compare Python reference dataclasses;
  selectors now compare their item data explicitly and retain offline targets.
- Batch 6: user guide and plugin About documentation now explain optionality,
  ownership, migration, console references, failure handling and timing limits.
- Hardware commands are unchanged. The additive valid-input driver method defaults
  to existing advertised native channels; restricted drivers can override it.
  No new model-specific hardware restrictions are claimed without manual evidence.
- Bench validation is not available in this workspace. Two-controller physical
  assignment, timing, reconnect and Make Safe checks remain deployment acceptance
  steps; simulated success must not be described as hardware validation.

- User refinement after visual review: the Control page now uses Primary and
  Secondary subtabs so four loops do not require one wide row. Secondary is hidden
  while disabled. Charts and plugin catalogues still combine both controllers.

## Final software validation

- 834 passed, 1 skipped in 12.89 seconds on offscreen PyQt5. The run covered the
  temperature engine/panel and monitor monoliths, controller state and sweep
  plugins, temperature scan tests, all command plugins, all three new secondary
  controller test modules, temperature driver contracts and Lakeshore/Oxford/
  Eurotherm drivers, plus tests/integration/app. All 33 new/migrated cases passed.
- Full repository collection: 3700 tests collected. This is a collection check,
  not a claim that the entire repository suite was executed.
- Ruff passed for all changed Python modules. Pylint error checks passed for the
  changed production modules. git diff --check passed.
- Sphinx HTML build succeeded with 495 warnings elsewhere in the documentation
  tree, including missing autosummary stubs. No warning identified the new
  temperature_controllers.rst guide. The build is not warning-free.
- Offscreen renders checked the connection, stability, chart and both control
  pages at 1150 by 950 pixels. Primary and Secondary each fit two simulated loops
  without horizontal scrolling. PID and ramp controls remain readable.
- Tab validation exposed legacy panel tests releasing chart wrappers before Qt
  drained geometry events. Added managed_temperature_panel to retain panels and
  enable genuine close at teardown; the panel now explicitly closes its PlotWidget
  during application shutdown. The normal close action still hides the panel.
- Physical two-controller testing remains required as described above. Polling
  remains synchronous by design; this change does not add acquisition threads.

## Shared stability and chart follow-up

The user requested a draggable chart/legend divider, compact .2 secondary labels,
cross-controller stability sensors, and one dT/dt trace. They explicitly selected
one shared stability table with first-matching-row priority for overlapping bands.

- Shared criteria use completed readings from both controllers. Per-loop target
  checks remain independent; stale or disconnected dependencies invalidate waits.
- Rows retain explicit priority, adjustable with Move Up/Down. First matching
  upper bound wins; last-row fallback preserves above-range behaviour. One chart
  rate uses the earliest active row across loops, ties primary then native loop.
- The chart plots the actual engine rate, rather than independently estimating it
  a second time. Its history resets on sensor changes or missing/invalid data.
- Version 3 YAML stores one shared table; previous primary criteria take priority
  when migrating version 2. Secondary-only criteria must be reviewed on migration.
- Secondary labels use .2 while internal chart keys preserve existing preferences.

Follow-up validation: 843 passed, 1 skipped across the same affected regression
scope; 97 panel/engine tests passed again after final layout adjustments. Full
collection found 3709 tests. Ruff, Pylint error checks and git diff --check passed.
Offscreen chart and stability renders confirmed compact .2 labels, one rate entry,
and a top-packed shared table. Splitter dragging was exercised with held-button
mouse events. Hardware bench validation remains outstanding.
