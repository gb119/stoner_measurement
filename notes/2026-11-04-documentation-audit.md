# Documentation purpose, audience and code audit

## Scope and navigation

Reviewed every original top-level Sphinx page and the API entry point against
the current checkout. The landing page now offers three ordered paths:

- New users: installation → basic hardware-free measurement → complete data workflow.
- Experienced users: execution, scripting, data, plotting, configuration and rig references.
- Developers: external sequence/display extensions → integration contracts → repository contribution/API reference.

Each page states its audience and links to the adjacent task/reference instead
of requiring readers to pass through implementation details to find operations.
Existing dark-mode workflow screenshots and downloadable sequences are retained.

## Original page audit

| Page | Intended audience and purpose | Finding and disposition |
| --- | --- | --- |
| `index.rst` | All audiences: choose an appropriate route | Replaced one undifferentiated contents list with explicit audience paths and three navigation groups. |
| `installation.rst` | New users: obtain a working runtime | Corrected declared Python minimum, supplied-environment constraints, Qt extras/binding choices and OpenGL requirements. Separated source, supplied Conda environment and local recipe routes. |
| `usage.rst` | New users: first configured, executed measurement | Retained illustrated walkthrough and Run Selection; removed implementation tutorial and conflicting trace schema descriptions. Added next-step links. |
| `data_workflows.rst` | Guided progression to collecting, plotting, filtering, fitting and saving | Kept the complete illustrated worked sequence together. Clarified purpose and corrected the h5py dependency statement. |
| `simulated_instruments.rst` | Users/developers: understand available controller simulations | Distinguished the first hardware-free trace from controller simulations. Added existing motor, pressure and mass-flow simulators and their actual limitations. |
| `temperature_controllers.rst` | Operators/rig administrators: dual-controller connections, identities and stability | Moved console snippets to the script reference; corrected obsolete synchronous-polling description to worker-dispatched polling. Retained controller-local assignment and qualified identities. |
| `keithley_point_commands.rst` | Operators: configure held-DC point scans and set commands | Added user routes, linked Reconfigure instructions and replaced obsolete blanket deferral of pulsed plugins with the implemented Pulse Delta reference. Preserved bench-validation limitation. |
| `keithley_pulse_delta.rst` | Operators: configure native Pulse Delta acquisition | Added audience/cross-references and separated connection, timing and result/lifecycle sections. Kept timing and auxiliary-meter constraints. |
| `xray_diffractometer.rst` | Operators/rig administrators: connect, configure and acquire diffraction data | Added purpose/routes and corrected language describing implemented scans/set commands as future work. |
| `console_api.rst` | Experienced users: inspect live sequence objects and write measurement scripts | Replaced positional/assumed-instrument examples with named instances from the workflows. Corrected generator-specific settings and explicit controller service acquisition. Added moved temperature examples and readiness/display references. |
| `third_party_plugins.rst` | External plugin authors/assistants: implement integration contracts | Redrafted discovery, identities, base families, lifecycle/ownership, namespace, output catalogues, UI, persistence and generated execution. Removed operational Reconfigure walkthrough. Replaced obsolete trace/action examples with a downloadable executable command. |
| `plot_display_plugins.rst` | Display authors: register and implement a factory | Moved bundled-display operation to `plot_displays.rst`, retained the factory example and authoring/verification contract, corrected stale rendering-status wording. |
| `plotting_contracts.rst` | Developers: producer/service/renderer protocol | Retained request/data/completion/ownership/replay contracts; moved surface UI controls and display-menu instructions to the user reference. Kept a producer example with explicit engine context. |
| `plugin_tab_ordering.rst` | Developers: consistent configuration-page composition | Added purpose and current shared-widget, cache, inherited-identity and top-packed layout rules. |
| `round_dial_widget.rst` | Developers: embed the reusable readback widget | Distinguished readback from movement controls, added QApplication/event-loop setup and corrected snippet indentation. |
| `contributing.rst` | Repository contributors: environment, checks and documentation conventions | Replaced generic development notes with the repository's Conda, managed-Qt-fixture, testing and packaging workflow. Distinguished external plugin authoring from application changes. |
| `api/index.rst`, `api/core.rst` | Developers/script authors: signatures and implementation reference | Added routes to task-oriented guides; replaced nonexistent `core.sequence`/`core.runner` imports with current engine/serializer/TraceData modules. |

## Focused homes added after the moves

| Page | Gap filled | Principal owning source |
| --- | --- | --- |
| `sequence_execution.rst` | Ordering/readiness, one-off selected execution, Reconfigure, document saving and reconstruction from result metadata | `core/sequence_engine.py`, `plugins/command/reconfigure.py`, `app.py`, `core/sequence_metadata.py` |
| `trace_data.rst` | One canonical public table/role/catalogue reference, independent of the first-run tutorial | `core/trace_data.py`, `core/sequence_engine.py`, state scan/sweep collection bases |
| `plot_displays.rst` | User-facing bundled display controls and surface preparation | Plot command forms/preparation, `ui/plotting/`, display host/registry |
| `configuration.rst` | Preferences, YAML/resource locations, templates, custom toolbar sequences and portability | `resources.py`, `config.py`, Preferences/toolbar UI and `conf/` resources |
| `rig_controls.rst` | Shared magnet, motor, pressure/flow panels previously lacking a user-guide home | Corresponding controller engines, connection/configuration/control/chart panels and sequence plugins |

Important code corrections include ordinary-column X coordinates rather than a
special DataFrame index; `TracePlugin._measure()` returning named TraceData
tables rather than a generator; callable command generation; runtime-derived
Reconfigure delay flags; cleanup ownership; catalogues containing current step
instances rather than manager templates; and generator-specific console fields.

## Remaining documentation opportunities

These are gaps to plan explicitly rather than burying unrelated material in the
new focused pages:

- A dedicated **instrument-driver authoring guide**: the current API reference
  explains composition and discovery and exposes classes, but does not provide a complete transport/protocol/capability,
  registration and hardware-commissioning tutorial. Keep it separate from
  sequence-plugin orchestration. The repository's instrument-driver skill and
  current driver implementations provide development guidance meanwhile.
- A **troubleshooting reference** organised by symptom (discovery failure,
  transport timeout, absent output, numerical failure, display rejection).
  Current pages cover local constraints and debugging entry points; they do not
  form a systematic diagnostic guide.
- Device-specific **commissioning checklists and connection screenshots** for
  physical rigs. Simulators and code inspection cannot establish actual wiring,
  vendor-runtime installation, calibration or bench timing. The present generic
  rig reference is deliberately an operational overview.

## Validation

- Full Sphinx HTML rebuild completed (exit 0). No warnings/errors originate in
  the authored top-level guide pages. The live preview serves the revised index.
- Checked 22 authored guide/navigation pages: 1,669 local links, assets and
  fragments resolved. Dark-mode screenshots and downloadable sequences remain.
  This checks generated HTML structure/targets, not a fresh visual browser review.
- Executed the downloadable command through a real SequenceEngine and Cartesian
  display host; checked independent instances, JSON reconstruction, editable
  configuration and current-step output catalogue publication.
- Executed the TraceData construction and round-dial snippets; all 15 plotting
  request doctest examples passed.
- Existing focused display/plugin/widget/serializer/container tests: **216 passed**.
- Ruff check and formatting check passed for the new downloadable Python example;
  `git diff --check` passed.

The full generated API build still emits **499 warnings and four nonfatal
docutils errors**, principally missing autosummary stubs and malformed unchanged
source docstrings. One serializer indentation error is newly exposed by replacing
the invalid core API imports with the actual serializer module. The signal
docstrings also generate broken internal diagnostic links on the core API page;
the successful guide-link check excludes that generated member inventory.
These need a separate API-generation/docstring cleanup rather than suppression
or a claim that the whole API build is warning-free.

Hardware commissioning is outside this documentation-only change; no runtime
behavior is changed. The remaining opportunities above are identified gaps,
not claims that new complete authoring/commissioning manuals were delivered.
