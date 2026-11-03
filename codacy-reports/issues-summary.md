# Codacy Issues Summary

Repository: `gh/gb119/stoner_measurement`

Branch: `main`

Analysed source-fix commit: `087b592f352f839235cda1dfba6bb97e2a049123`

Analysis completed: 2026-11-03T23:32:41.382Z

Reports downloaded: 2026-11-03T23:33:49.478643+00:00

## Current remote result

**Zero active Codacy issues.** The complete main-branch issue pull and the
independent repository issue count both report zero after analysis of the
source-fix commit above. This is verified remote clearance, not an estimate
based only on local lint results.

- `issues.json`: latest raw active-issue inventory (empty).
- `issues.csv`: matching active-issue table (header only).
- `repository.json`: repository metadata and immutable analysis identity.
- `resolved-issues.csv`: all five original findings, evidence, local changes
  and the commit/analysis that confirmed clearance. The E0710 row also records
  its intermediate follow-up result ID.

This report update is committed separately from the analysed source changes
so the recorded SHA identifies the exact code Codacy checked.

## Resolutions

| Finding | Resolution |
| --- | --- |
| Plot Trace McCabe complexity 16 | Extracted the existing simple-XY path |
| Two exact-int advisories in the 6221 driver | Documented line-scoped Pylint suppressions |
| Guarded engine-provider call | Documented line-scoped `not-callable` suppression |
| Guarded exception raise in discovery test | Documented line-scoped `E0710` suppression |

McCabe measurements are **5** for `PlotTraceCommand.execute`, **12** for
`_execute_simple_xy`, and at most **14** across the module, below threshold 15.
The extraction preserves trace lookup, missing-data skips, positional error
columns, multi-Y output, axis labels and acknowledgement ordering.

Exact integer checks still reject booleans and subclasses with custom SCPI
formatting. Callable and exception guards are unchanged. Suppressions target
only the reported lines; no remote ignore states or analysis exclusions changed.

The first pushed fix cleared four findings. The remaining E0710 identified an
incorrect symbolic suppression name, which was corrected to the exact code.
The subsequent analysis recorded above confirms clearance of all five.

## Validation

- **326 affected tests passed** in 12.32 seconds, covering driver validation,
  discovery, state/control, Plot Trace and generated sequence failure,
  surface and polar plotting workflows.
- After the final suppression correction, all **11 discovery tests passed**.
- Ruff lint and targeted Pylint `C0123,E1102,E0710` passed. The final E0710
  check also enabled `W0012` to reject invalid suppression names.
- Independent `mccabe.PathGraphingAstVisitor` inspection covered every method
  and helper in Plot Trace; whitespace checks passed.
- Ruff format checks passed for Plot Trace and the edited discovery-test
  module. Existing unrelated formatting in the state base and driver was not
  expanded into this change.
- No tests or assertions were added, moved or removed. Test-double changes
  consist only of a suppression and its explanation.

Tests used the project Conda environment, Python 3.14.7 / PyQt5 5.15.11,
offscreen Qt and Windows fonts. This does not establish other Qt bindings,
hardware operation or the complete hosted CI matrix.

The source analysis result above concerns Codacy issues. Coverage status and
its associated commit remain separately inspectable in `repository.json`.

See [the maintenance note](../notes/2026-11-03-codacy-cleanup.md) for context.
