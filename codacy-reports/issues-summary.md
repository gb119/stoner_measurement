# Codacy Issues Summary

Repository: `gh/gb119/stoner_measurement`
Branch: `main`
Downloaded: 2026-08-09

## Refresh Status

- Codacy authentication succeeded on 2026-08-09.
- The current issue list was downloaded with `--branch main --limit 1000`.
- `codacy-reports/issues.json` is the authoritative raw snapshot.
- `codacy-reports/issues.csv` is regenerated from the same 57 issues.
- The local checkout and `origin/main` were both at
  `a72b0bb4e2e20f38e9ddad5ab396b98d34afb09c` when the snapshot was refreshed.

## Snapshot Totals

- Total: **57** (previous snapshot: 70)
- `Error`: **1** (previously 0)
- `High`: **2** (previously 1)
- `Warning`: **34** (previously 40)
- `Info`: **20** (previously 29)

The total has fallen by 13. In particular, the old
`MassFlowController` High finding and most of the earlier formatting and
hardcoded-time-format findings have cleared. The three current Error/High
findings were classified locally; none looks like a runtime defect.

After downloading this snapshot, narrow local suppressions were added for the
three classified Error/High false positives, the two intentional user-code
`exec` boundaries, the fixed-argument subprocess import, and the public Qt
signal name. The four stable backup filename findings already carry narrow
Semgrep suppressions in the analyzed commit, so they were not duplicated or
broadened. A Codacy reanalysis is required before expecting those findings to
disappear from the service.

Focused local verification after the suppressions:

- Ruff: passed on all touched Python files.
- Pylint `E1102,E0110`: passed for the dynamic callable and abstract-test sites.
- Bandit: no findings in the affected security-boundary files.
- Pytest: 157 passed across motor/HDR50, Keithley 2182A, arbitrary-function
  scans, and curve-fit plugin tests.
- Import/mechanical cleanup: targeted Pylint passed at 10.00/10, Ruff passed,
  and a further 623 focused tests passed.
- Pytest emitted only a pre-existing cache-directory warning under the managed
  workspace.

## Category Split

- `Complexity`: 27
- `CodeStyle`: 18
- `BestPractice`: 5
- `Security`: 4
- `ErrorProne`: 2
- `UnusedCode`: 1

## Error and High Findings

1. `src/stoner_measurement/instruments/thorlabs/hdr50.py:573`
   (`PyLintPython3_E1102`, Error): `homed is not callable`.
   The call is explicitly guarded by `callable(homed)`, so this is a dynamic
   API false positive. Prefer a narrow Pylint suppression or a small typed
   helper; do not alter the hardware behaviour to satisfy the analyser.
2. `src/stoner_measurement/instruments/keithley/k2182.py:281`
   (`Bandit_B105`, High): `REPEAT` is an allowed Keithley SCPI filter token,
   not a password. Add a narrow `nosec B105` rationale.
3. `tests/test_motor_controller.py:30` (`PyLintPython3_E0110`, High): the test
   deliberately instantiates a dynamically created incomplete abstract class
   and asserts that Python raises `TypeError`. It already uses `cast(Any, ...)`.
   Treat this as a test-contract false positive and suppress it narrowly.

## Largest Buckets

- `Prospector_mccabe`: 27 complexity findings.
- `PyLintPython3_W0404`: 10 reimport findings.
- `Semgrep_codacy.python.i18n.no-hardcoded-strftime`: 4 findings for stable
  backup filename formats.
- `PyLintPython3_W0108`: 4 unnecessary-lambda findings in tests.
- `Bandit_B102`: 2 intentional `exec` findings in user-expression paths.
- `Prospector_pycodestyle`: 2 findings: one real `E305` and one intentional
  mixed-case Qt signal name.

## Priorities

### P0: classify and silence the three hot findings (done locally)

Narrow, documented suppressions now cover the SCPI token, intentional
abstract-class test, and callable-guarded dynamic Thorlabs API. Focused local
checks remain required, followed by Codacy reanalysis.

### P1: review the intentional dynamic-code security boundary (classified)

The two `exec` sites in `curve_fit.py` and
`arbitrary_function_generator.py` implement explicit user-authored fitting and
scan-code features; they are not sandboxes. The `sequence_engine.py` subprocess
passes the current interpreter and fixed Ruff arguments as an argument list,
without a shell. These sites now carry narrow Bandit suppressions with their
rationale; preserve the capability and its documented trust boundary.

### P2: remove redundant inner imports, without pursuing lazy imports (done locally)

The 10 `W0404` findings are mostly imports repeated inside functions or tests
even though the same names are already imported at module scope. All 10 were
classified as genuinely redundant and removed. The package-export contract
test now compares package exports with their defining types directly, making
the test stronger without reimporting names. Function-local imports remain
appropriate where they break a demonstrated cycle, isolate an optional
dependency, or are needed for test monkeypatch/import-state behaviour.

Project import policy for now:

- Prefer ordinary eager module-level imports.
- Keep `TYPE_CHECKING` imports for annotation-only dependencies.
- Keep explicit runtime discovery/imports for plugins, drivers, resources, and
  genuinely optional packages.
- Do not introduce proxy objects, module `__getattr__`, or move imports into
  functions merely to reduce startup time.
- Profile startup/import cost before making any import lazy.

This matches the application's usage pattern: a normal GUI run uses most of
the Qt, plotting, data, and instrument stack, so deferral is likely to move the
cost rather than remove it while making failure timing and imports harder to
reason about.

Python 3.15's accepted PEP 810 provides explicit `lazy import` syntax and the
backwards-compatible `__lazy_modules__` bridge. When Python 3.15 is supported,
revisit only imports shown by profiling to be both expensive and unused on
common paths. There is no reason to build a project-specific lazy-import
framework before then.

### P3: mechanical cleanup (done locally)

The real `E305`, public Qt `N815`, unused test variable, unnecessary cleanup
`pass`, `range(len(...))`, and four unnecessary test lambdas have been handled.
The four UTC backup filename formats retain their existing narrow Semgrep
markers as stable machine identifiers.

### P4: complexity reductions paired with tests

Do not chase all 27 McCabe findings as a single cleanup. Prioritize production
code where extraction creates a clear boundary and the behaviour has focused
tests. The best candidates are:

1. `plugins/command/plot_points.py` (complexity 35 and 17)
2. `plugins/trace/k6221_2182a.py` (36, 24, and 18)
3. `ui/plot_widget.py` (23 and 22, plus one style finding)
4. `plugins/trace/k6221_multi_sr830.py` (24 and 24)
5. `plugins/trace/base.py` (29)

Test-helper complexity is lower priority unless it is actively making tests
hard to extend or hiding duplicated setup defects.

## Recommended Next Tranche

Push these local changes and allow Codacy to reanalyse before comparing issue
counts. After that, begin structural complexity work with
`plugins/command/plot_points.py`, extracting one test-backed responsibility at
a time rather than attempting a repository-wide complexity rewrite.
