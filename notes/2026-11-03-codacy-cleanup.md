# Codacy cleanup: 3 November 2026

## Changes

The five-issue inventory for `5ba9cce32c21ca7e24e2ad63a14b8777e030ecfb`
contained one production-complexity finding and four intentional-use or analyzer
false positives. The downloaded snapshot and dispositions are in
[codacy-reports](../codacy-reports/issues-summary.md).

Extracted the existing simple-XY trace path into `_execute_simple_xy()` without
changing its statements, warning handling, error-column mapping, signal order
or axis-label updates. Non-XY and advanced-XY dispatch remain in `execute()`.
Independent McCabe measurements are 16 before, then 5 for `execute()`, 12 for
the helper and at most 14 across the complete module (threshold 15).

Added documented Pylint suppressions at the four reported lines only:

- `unidiomatic-typecheck` for exact integer validation in the 6221 driver.
  Booleans and custom-formatting integer subclasses must remain rejected.
- `not-callable` for the engine-provider call guarded by `callable()`.
- `E0710` for the discovery fake's `isinstance(..., Exception)` raise.

No runtime guards, analysis exclusions or remote ignore flags were changed.
No tests or assertions were added, moved or removed; the test-double edit is
only a suppression and its explanation.

## Verification

- 326 affected tests passed in 12.32 seconds on Python 3.14.7 / PyQt5 5.15.11.
  Scope includes Pulse Delta validation, display discovery, state/control,
  Plot Trace and generated sequence failure/surface/polar plotting workflows.
- Ruff lint and targeted Pylint `C0123,E1102,E0710` passed on all four files.
- Ruff formatting passed for Plot Trace and the discovery-test module. Existing
  formatting differences in the state base and driver were left out of scope.
- Independent `mccabe.PathGraphingAstVisitor` checks covered every Plot Trace
  method and helper; `git diff --check` passed.

Commands ran through the project Conda environment with offscreen Qt and
Windows fonts. Hosted Codacy results are recorded below.

Codacy analysed `febf111957ab10590ce2cc9e9d1511f7ee6f2ea0` and cleared four
findings. Its remaining E0710 showed that the first test suppression used the
wrong symbolic rule name (`raising-bad-type`). Corrected it to the exact E0710
code, preserving the guarded raise and discovery scenarios.

## Hosted confirmation

Codacy analysed `087b592f352f839235cda1dfba6bb97e2a049123` at
2026-11-03T23:32:41.382Z and reports **zero active issues**. The full issue
pull and repository metadata independently agree. Reports were refreshed after
this verification; `resolved-issues.csv` preserves all five original diagnoses
and their resolutions. No remote ignore states were changed.

After correcting the final E0710 suppression, all 11 discovery tests passed;
targeted Pylint also checked for invalid suppression names (`W0012`).
