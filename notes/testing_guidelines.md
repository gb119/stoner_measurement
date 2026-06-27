# Testing Guidelines For Assistants

This note is the developer-facing source of truth for how tests should be
structured and maintained in this repository. AI coding assistants should read
this file before adding, moving, or rewriting tests.

## Test Layout

Use behaviour-focused test locations rather than large top-level monoliths:

```text
tests/
  unit/
    core/
    control/
    instruments/
      contracts/
      drivers/
      transport/
    plugins/
      command/
      monitor/
      state/
      trace/
      transform/
    scan/
    sweep/
    ui/
      dialogs/
      panels/
      widgets/
  integration/
    app/
    plugin_workflows/
    sequence/
```

Prefer one test module per production module or plugin class. Use a
`test_<thing>.py` name that makes the production target obvious, for example
`tests/unit/plugins/command/test_save_command.py`.

Keep broad workflows under `tests/integration/`. Unit tests may instantiate Qt
widgets, but they should stay focused on one widget, plugin, helper, or
contract at a time.

## Test Philosophy

- Test behaviour and contracts, not implementation trivia.
- Avoid re-asserting every default in multiple places. Keep one clear test for
  defaults and use later tests to cover branches, edge cases, and interactions.
- Prefer narrow fake objects, fake drivers, fake transports, or existing test
  doubles over real hardware, real user settings, or broad application startup.
- Add coverage where it changes confidence. More assertions are not better if
  they only mirror the implementation.
- When splitting legacy tests, preserve coverage first, then simplify only when
  the replacement remains clearly equivalent.
- Keep tests deterministic: avoid arbitrary sleeps unless the behaviour under
  test is timing-related and the assertion tolerates scheduler variation.
- For Qt tests, use the conda environment and keep Qt offscreen.

## Monolith Migration Rules

Large legacy files should be split by behaviour or production module as they
are touched. When migrating:

1. Move one cohesive tranche at a time.
2. Run the moved file plus the source monolith before deleting old coverage.
3. Run a full collection check to catch lost or duplicated tests.
4. Update `notes/testing_restructure_plan.md` with what moved, what remains,
   and the commands that verified it.
5. Leave unrelated files and untracked workspace artefacts alone.

The command plugin monolith has already been split into
`tests/unit/plugins/command/`. Use that layout as the reference pattern for
future plugin splits.

## Direct File Runs

Developer workflows include running an individual test file directly from an
IDE. New test modules should therefore include this block at the end:

```python
if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
```

If the file does not otherwise need `pytest`, either import it at module level
or inside the block. Ruff must still pass. The command plugin split keeps this
block in every `tests/unit/plugins/command/test_*_command.py` file so IDE
direct-run behaviour is preserved after removing the old monolith.

## Commands

Run project commands through the conda environment:

```powershell
conda run -n stoner_measurement python -m pytest tests\unit\plugins\command --tb=short
conda run -n stoner_measurement python -m pytest --collect-only -q
conda run -n stoner_measurement python -m ruff check tests
```

For Qt/widget tests, keep the correct Qt stack by using the same environment.
When necessary, set:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
```

## Documentation Location

Developer-facing testing notes belong in `notes/`, not `docs/`. The `docs/`
tree is for user-facing Sphinx documentation. Keep test migration status in
`notes/testing_restructure_plan.md`.
