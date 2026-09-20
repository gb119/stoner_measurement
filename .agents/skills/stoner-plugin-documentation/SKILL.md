---
name: stoner-plugin-documentation
description: Write, correct or audit user-facing stoner_measurement plugin class docstrings and their About documentation. Use for documentation work and documentation checks on changed plugins; do not automatically audit the whole repository for a small feature edit.
---

# Stoner plugin documentation

Make concrete plugin class documentation accurate and useful to both sequence
users and users of the Script tab or QtConsole.

## Scope and source of truth

Read [repository documentation rules](../../../.github/copilot-instructions.md)
and [AGENTS.md](../../../AGENTS.md). Paths here are relative to this skill directory.
Use current code to verify behaviour; historical audits are evidence, not a
substitute for inspecting the implementation.

For a focused change, inspect only the affected classes and their relevant bases.
For a complete built-in audit, enumerate `stoner_measurement.plugins` entry points
from `pyproject.toml`, rather than relying on class-name suffixes or the curated
catalogue. State any additional scope, such as third-party plugins or internal
containers. Do not count compatibility aliases twice.

## Write from the implementation

Trace each class through its constructor, base/mixin attributes, configuration
page factories, persistence, execution/generated-code path and output reporting.
Check inherited documentation against the actual current API.

Cover:

- Measurement purpose and when a user would choose this plugin.
- Actual tab names and controls, units, meaningful defaults and expression
  timing. Distinguish shared controller settings from per-instance settings.
- Runtime behaviour, child-step semantics where relevant, outputs and important
  limitations. State retained-output and cleanup behaviour for hardware plugins.
- Typed instance attributes, including useful inherited identity, engine context,
  generators and result state. Distinguish editable settings from read-only or
  dynamically available results. Avoid dumping internal widgets and signals
  merely to make an attribute list exhaustive.
- Constructor parameters and applicable exceptions using repository sections.
- Useful console interactions with an explicitly identified existing instance,
  or a complete construction example. Include imports and namespace prerequisites.
  Identify when results become available. Keep examples within 79 source columns.

Use British English and Google-style sections. Do not add headings solely to
pass a mechanical check. Keep valid examples and useful existing explanations;
rewrite only what the requested scope or a demonstrated defect requires.

## Check safely

Run the static inventory helper from the repository root through its Conda
environment, selecting individual entry-point names when appropriate:

```powershell
& $env:CONDA_EXE run -n stoner_measurement python `
    .agents/skills/stoner-plugin-documentation/scripts/audit_docstrings.py `
    --plugin reconfigure --plugin run_again
```

Omit `--plugin` for all registered built-ins. Use `--json` for structured output.
The helper reads source only: it never imports plugins, constructs widgets or
executes examples. It flags structural omissions and identifies direct custom
About overrides. Its results require review; it cannot establish semantic
accuracy, inherited attribute existence or runtime rendering.

After reviewing constructor/property side effects, use isolated Qt fixtures and
fake services for any runtime checks. Do not blindly execute arbitrary docstring
examples or connect to instruments. Compile code fragments first; exercise only
the examples whose effects have been understood and isolated. Assignments need
checking too: Python can silently create a misspelt attribute.

Inspect the shared `_docstring_to_html` renderer and `_about_html` resolution.
The renderer currently omits developer sections including Examples. Some classes
override About HTML, so a class-docstring edit may not change their displayed
page. Report that distinction; preserve useful custom material and change the
rendering path only when required by the user's scope.

For documentation-only changes, use `--compare-ref HEAD` to check that executable
ASTs of selected plugin modules are unchanged. This comparison includes existing
working-tree changes: a difference is a review finding, not permission to revert
someone else's code. Run relevant existing documentation/About tests, lint the
changed files and inspect the diff. New tests are only useful where they protect
behaviour beyond the wording of the documentation itself.

Deliver a concise findings/corrections summary with validation boundaries. For
repository-wide audits, save a class inventory and evidence under `notes/`.
