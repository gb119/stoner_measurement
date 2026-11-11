# Codacy Issues Summary

Repository: `gh/gb119/stoner_measurement`, branch `main`

Analysed commit: `4f5fb24182e7a0566ab664d16036c22b308cea87`

Analysis completed: 2026-11-11T21:19:45.348Z

## Current result

**12 active issues**, all reviewed and addressed locally; hosted reanalysis is pending.

## Review of the 12 findings

| Findings | Disposition |
| --- | --- |
| Oxford re-export: Pyflakes F401 and Pylint W0611 (2) | Explicit public exports preserve the Mercury compatibility import |
| Lake Shore nested CSV formatter: E306 (1) | Added the required blank lines |
| Editor selection and regression: C0123 (2) | Exact type is required to switch from the specialised subclass back to the generic editor; documented line-scoped suppressions |
| Packaged guide launch: B606 (1) | Intentional Windows association launch of the fixed-name cached bundled guide; documented call-scoped suppression |
| Build script and test imports: B404 (2) | Intentional subprocess use; the test mocks execution; documented import-scoped suppressions |
| Sphinx and HHC calls: B603 (2) | Trusted developer build tools, separate arguments, no command shell; documented call-scoped suppressions |
| HHC environment-selected tool: Opengrep (1) | Explicit compiler selection is intentional build capability, not untrusted application input; exact-rule suppression |
| CHM stylesheet: declaration-no-important (1) | Replaced !important with a more specific html body selector |

No remote ignore states or global analyser exclusions were changed. The subprocess
findings identify intentional developer tooling, not an application command-input
path. Compiler selection, shell-free invocation and artifact checks are preserved.

## Validation and evidence

- 168 affected guide, controller and editor tests passed on Python 3.14.7/PyQt5.
- Ruff and targeted Pylint W0611, C0123 and W0012 passed.
- Targeted Bandit B404, B603 and B606 passed.
- Strict Sphinx HTML Help build passed after correcting literal markup in the
  Mercury identity docstring; the generated stylesheet retains the same gutter.
- `issues.json` and `repository.json` hold the current remote snapshot.
- `issues.csv` records active findings and dispositions.
- `resolved-issues.csv` preserves earlier resolutions and, after remote confirmation,
  records these findings with the immutable source-fix commit and analysis time.
