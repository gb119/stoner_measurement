# Codacy Issues Summary

Repository: `gh/gb119/stoner_measurement`
Branch: `main`
Analyzed checkout: `23dfbf4fb8eedd31bf338e469b8d59cedb45763f`
Downloaded: 2026-08-28

## Refresh Status

- The issue list was downloaded with `--branch main --limit 1000`.
- `codacy-reports/issues.json` is the authoritative raw snapshot.
- `codacy-reports/issues.csv` was regenerated from that snapshot.
- The snapshot contains **43 issues**: 4 Error, 5 High, 28 Warning, and 6 Info.
- The previous snapshot contained 31 issues: 0 Error, 0 High, 30 Warning, and 1 Info.

## Current Pattern Split

- 22 `Prospector_mccabe` complexity findings.
- 4 `PyLintPython3_E1102` guarded-callable false positives.
- 4 `PyLintPython3_W0404` redundant imports.
- 2 each of `Bandit_B102`, `PyLintPython3_E0203`, `PyLintPython3_W0108`,
  `PyLintPython3_W0122`, and `Semgrep_codacy.python.i18n.no-hardcoded-strftime`.
- 1 each of `Agentlinter_structure_modular-files`, `Bandit_B311`, and
  `Prospector_pyflakes`.

## Fixes Applied After This Snapshot

These changes require Codacy reanalysis before their remote findings clear:

- added narrow Pylint suppressions after explicit `callable()` guards for the
  four `E1102` reports;
- documented and suppressed the two test-only generated-code `exec` calls for
  both Bandit and Pylint;
- documented the deterministic simulator PRNG as non-cryptographic (`B311`);
- documented and line-suppressed the two locale-independent timestamp formats;
- documented PyQtGraph's dynamically initialised `autoSIPrefixScale` member;
- removed three redundant local imports and the duplicate direct-run `pytest`
  import;
- replaced the unnecessary engine lambda with its callable class and connected
  the save button directly to its slot;
- extracted shared plugin identity-editor binding and split the trace Scan page
  into header, generator-selector, output-option, and content builders;
- separated axis-dialog row collection from normalisation and split accepted
  plot-axis changes into property, range, removal, addition, and visibility
  operations;
- separated configured plugin-tree construction from fallback category
  grouping in the dock panel;
- separated round-dial custom-label, evenly-spaced, and endpoint-preserving
  candidate selection.
- split the Keithley 6221/2182A and Keithley 2400 configuration paths into
  sweep preparation, compliance, meter setup, and trigger-routing helpers;
- split Multi-SR830 validation into source, threshold, per-lock-in, and
  cross-lock-in checks, and extracted the lock-in editor's stateful callbacks;
- shared capability-driven combo population across the optional
  nanovoltmeter configuration pages.

If every analyzer accepts the scoped suppressions, this tranche should remove
all 4 Error findings, all 5 High findings, and all 6 Info findings, plus 11 of
the Warning findings. Together with the later production-plugin refactors, the
expected remainder is 9 warnings: 8 test-only complexity findings and the
Agentlinter advisory.

## Prioritised Remaining Work

### Completed P1: Production UI and shared infrastructure

- `BasePlugin._general_config_widget` (22);
- `_ScanPage.__init__` (29);
- `AxesConfigDialog.axis_changes` (22);
- `PlotWidget._open_axes_dialog` (23);
- `DockPanel._refresh_plugins` (16);
- `RoundDialWidget._preferred_label_values` (17).

These six methods were split into cohesive construction, parsing, selection,
and update helpers. Local McCabe checks no longer report any of them at the
Codacy threshold, and focused offscreen Qt tests cover the preserved behaviour.
Codacy reanalysis is still required to clear the remote findings.

### Completed P2: Hardware trace plugins

- Keithley 6221/2182A: complexities 16, 18, 24, and 36.
- Keithley 6221/Multi-SR830: complexities 24 and 40.
- Keithley 2400: complexities 17 and 21.

Preserve configuration ordering, restoration, trigger, and protocol boundaries.
Unit tests reduce regression risk but do not replace live instrument validation.

The configuration and UI methods were split along those boundaries. Local
McCabe checks no longer report any of the eight methods at the Codacy threshold.
Focused fake-instrument and offscreen Qt coverage passes; live instrument
validation remains outstanding.

### P3: Test helpers and scenarios

Eight complexity findings are test-only (17–30). Consolidate repeated fake
driver/controller construction first; split long scenarios only where doing so
improves behavioural clarity. These do not affect runtime behaviour.

### P4: Repository guidance advisory

The Agentlinter `AGENTS.md` modular-file warning is informational for this
repository: the file is intentionally the single source of maintainer guidance.
Do not split it solely to satisfy the heuristic.
