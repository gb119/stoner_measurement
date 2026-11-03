# Codacy Issues Summary

Repository: `gh/gb119/stoner_measurement`

Branch: `main`

Analysed commit: `5ba9cce32c21ca7e24e2ad63a14b8777e030ecfb`

Analysis completed: 2026-11-03T23:13:46.427Z

Downloaded and triaged: 2026-11-03, approximately 23:24 UTC

## Snapshot completeness

The main-branch pull contains **five active issues**: three Warning, one Error
and one High. Repository metadata independently reports five issues and the
same pre-fix analysed commit. The issue limit was 1,000,
so this snapshot is complete rather than a truncated first page.

`issues.json` preserves the downloaded issue inventory. `repository.json`
preserves the analysis identity, totals, pattern overview and metrics.
`issues.csv` records every result ID, its source evidence and recommended action.
Reported locations refer to the analysed commit.

The previous saved inventory had 20 issues. One result ID persists (Plot Trace
complexity), 19 previous IDs are no longer in the active inventory, and four
current IDs are absent from that older inventory. A changed ID does not by
itself establish when the underlying behaviour was introduced. No Agentlinter
findings remain in this active snapshot; no claim is made about why they left.

Coverage is still marked **Waiting** for this commit. The displayed 86% is
associated with older commit `b631ca8c7b3620ebeb7ab0b42394fd766737e898`, not
verified coverage of the Pulse Delta commit.

## Implemented fixes

All five findings have been addressed locally. The raw JSON and repository
metadata above remain the unmodified pre-fix remote snapshot, not a claim of
remote clearance.

- Extracted the simple-XY path from `PlotTraceCommand.execute`. McCabe is now
  5 for the dispatcher, 12 for the new helper, and at most 14 across the module.
- Added documented, line-scoped Pylint suppressions for the two intentional
  exact-int checks, guarded engine-provider call and guarded exception raise.
  Runtime validation, callable guards and exception handling are unchanged.
- **326 affected tests passed** in 12.32 seconds. Ruff lint, targeted Pylint
  (`C0123,E1102,E0710`) and whitespace checks pass. Ruff format checks pass for
  Plot Trace and the edited discovery-test module. The state base and driver
  have existing formatting differences; no broad formatting changes were made.
- No tests or assertions were added, moved or removed. No remote ignore states
  or analysis exclusions were changed. Remote reanalysis is pending push.

The following section preserves the original diagnosis for audit context;
the per-issue CSV now records the implemented local dispositions.

## Original triage

| Disposition | Count | Action |
| --- | ---: | --- |
| Actionable production complexity | 1 | P2 maintenance refactor |
| Intentional exact integer validation | 2 | Retain the validation contract |
| Analyzer false positives | 2 | No correctness fix required |

### Plot Trace complexity: actionable maintenance

- Result `131545788801`, Warning, `Prospector_mccabe`.
- `src/stoner_measurement/plugins/command/plot_trace.py:478`.
- `PlotTraceCommand.execute` has independently measured McCabe complexity
  **16**, exceeding the existing production threshold of 15.
- This is a maintainability finding, not evidence of a functional plotting bug.
  A cohesive extraction of the simple-XY trace path can separate it from
  advanced-XY and non-XY dispatch. Preserve missing-data skips, positional
  error-column selection, multi-Y output, axis labels and acknowledgement order.
  Check every resulting helper rather than just moving the complexity.
- Existing Plot Trace regressions passed. No refactor was applied in this triage.

### Pulse Delta integer checks: intentional validation

- Results `131558956747` and `131558956746`, Warning, `PyLintPython3_C0123`.
- `src/stoner_measurement/instruments/keithley/k6221.py:752` and `:844`.
- The code requires built-in integers for the low-measurement count and buffer
  size. `True` is an `int` subclass and compares equal to 1. Replacing these
  checks with `isinstance(value, int)` alone would accept `True`, then format
  `True` into native SCPI commands instead of an integer token.
- Existing tests demonstrate rejection of booleans and invalid sizes before
  instrument writes. Exact checks also exclude subclasses with custom formatting.
- Retain the contract. A style rewrite is optional only if it preserves these
  guarantees; the suggested substitution alone is incorrect. Local Pylint
  reproduces both advisories. These are accepted-use style findings, not bugs.

### State engine factory: false positive

- Result `131548945898`, Error, `PyLintPython3_E1102`.
- `src/stoner_measurement/plugins/state_scan/base.py:679`.
- The expression calls `engine_factory()` only when `callable(engine_factory)`
  is true. Missing or non-callable attributes produce `None`. The runtime guard
  prevents the invalid call alleged by the analyzer.
- Pylint 4.0.8 reproduces E1102. The state and controller regression modules
  passed. An explicit branch or Callable cast could clarify the intent to the
  analyzer, but no runtime correctness fix is required.

### Discovery test exception: false positive

- Result `131548934880`, High, `PyLintPython3_E0710`.
- `tests/unit/ui/test_plot_display_registry.py:35`.
- The test double raises its local `factory` value only inside
  `isinstance(factory, Exception)`. Every such instance inherits BaseException.
  The broken-import regression exercises this guarded raise and passed.
- Pylint 4.0.8 does not reproduce E0710 locally. No scenario rewrite or blanket
  test suppression is justified by this finding.

## Verification and scope

- **166 existing tests passed** in 5.36 seconds on Python 3.14.7 / PyQt5 5.15.11.
- Independently measured complexity with `mccabe.PathGraphingAstVisitor`.
- Ran Pylint 4.0.8 / Astroid 4.0.4 with only `C0123,E1102,E0710` enabled over
  the three flagged type/call/raise files. Two C0123 and one E1102 reproduced;
  E0710 did not reproduce. The nonzero Pylint result is expected evidence,
  not a claim of a clean lint run.
- No production code, tests, lint exclusions or remote issue states changed.
  The original triage did not change code or remote ignore states; see Implemented fixes for the subsequent source changes.
- The Conda environment still lacks a `codacy` launcher. The cached official
  cloud CLI entry point was run through `CONDA_EXE run -n stoner_measurement node`.
  Both JSON responses were parsed and their counts checked before replacement.

Run these commands through the project Conda environment (substitute the cached
official CLI after `node` if the launcher is unavailable):

```text
codacy issues gh gb119 stoner_measurement --branch main --limit 1000 --output json
codacy repository gh gb119 stoner_measurement --output json
```

The affected regression selection was:

```powershell
conda run -n stoner_measurement pytest `
    tests/unit/instruments/drivers/test_keithley_6221_pulse_delta.py `
    tests/unit/ui/test_plot_display_registry.py `
    tests/unit/plugins/state/test_state_control_plugin.py `
    tests/test_controller_state_plugins.py `
    tests/unit/plugins/command/test_plot_trace_command.py `
    -q --tb=short -p no:cacheprovider `
    --basetemp=.pytest-runtime/codacy-triage-20261103
```

Qt used the offscreen platform and `C:/Windows/Fonts`. Other bindings, hosted CI
and hardware were not exercised for this read-only code triage.
