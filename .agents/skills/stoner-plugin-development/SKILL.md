---
name: stoner-plugin-development
description: Add or extend stoner_measurement sequence plugins, including commands, scans, sweeps, traces, monitors and transforms. Use for plugin behaviour and integration changes, not standalone instrument-driver work or documentation-only edits.
---

# Stoner plugin development

Deliver the requested plugin behaviour together with the configuration,
persistence, sequence integration and tests that behaviour needs.

## Establish the contract

Read the repository [AGENTS.md](../../../AGENTS.md) and the relevant sections
of [the plugin guide](../../../docs/third_party_plugins.rst). Resolve these
paths relative to this skill directory. Follow current source when an older
guide or example disagrees with it, and correct affected guidance within scope.

Before editing, identify:

- The closest existing plugin and the appropriate base class: command for a
  single action, state scan for discrete points with children, state sweep for
  measurements during motion, trace for complete acquisitions, monitor for
  passive readings, transform for computation, or sequence for orchestration.
- Which resources this instance owns and which belong to shared controllers.
- Which settings are literals, runtime expressions or derived state; when each
  expression is evaluated; and which outputs downstream steps consume.
- Whether the change affects existing saved sequences or generated scripts.

Use the feature's existing note in `notes/` as its working specification when
one exists. Keep an approved bounded change within its agreed scope.

## Implement the relevant integration

- Keep hardware commands in instrument drivers. Plugins orchestrate drivers or
  shared controller services; configuration widgets edit plugin settings.
- Resource-owning plugins need idempotent cleanup after complete and partial
  connection attempts. Preserve the base wrapper's reconnect behaviour and
  propagate cleanup failures. Never close another instance's resources.
- Do not infer lifecycle solely from the command family: Keithley set commands
  retain output between actions and participate in sequence cleanup. Preserve
  the held-DC point-scan contract in the repository instructions.
- Reconfigure selections derive `delay_configuration`. Preserve runtime
  readiness checks inside branches and loops; do not add a direct flag editor.
- Evaluate expressions through the shared plugin evaluators and live engine
  namespace at the appropriate phase. Preserve expression text in persistence.
- Declare scalar and trace outputs consistently with their actual data and
  units. Refresh catalogues when configuration changes available outputs.
  Preserve `TraceData` column roles and shared-x structure.
- Round-trip editable settings through `to_json()` and `_restore_from_json()`.
  Provide compatible defaults for older files. Do not persist live drivers,
  widgets, engine references or derived lifecycle flags.
- Use shared widgets and the established cached configuration-tab construction
  path. Check existing factories before creating a new page or selection control.
- For a new built-in plugin, inspect entry points, package exports, catalogue
  placement and default configuration. Update only the mechanisms it needs.
  Verify source registration separately from installed discovery; refresh the
  editable install only if the environment needs the new entry point.

## Verify and deliver

Read [testing guidance](../../../notes/testing_guidelines.md) before changing
tests. Choose focused cases that exercise changed contracts: lifecycle failure
and retry, expression timing, generated action code, output shape/units,
configuration reload, or widget interaction. Use fake drivers for automated
hardware tests. Ordinary UI edits do not justify a driver refactor.

Run project commands through the prescribed Conda environment. For Qt checks,
use the documented offscreen/font setup and managed widget fixtures. Check the
actual Qt binding; a passing run on one binding does not validate the CI matrix.
Broaden testing when the affected shared boundary or observed failures warrant
it, rather than rerunning unrelated suites after every small edit.

Update user-facing class documentation with purpose, controls, attributes and
console examples using [the documentation rules](../../../.github/copilot-instructions.md).
The sibling `stoner-plugin-documentation` skill supplies a focused audit workflow
when documentation itself needs substantial work.

Report changed behaviour, relevant checks and any remaining bench-validation
boundary. Keep developer evidence in `notes/`; do not claim remote CI or hardware
success from local fake-driver tests.
