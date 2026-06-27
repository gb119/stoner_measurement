# Codex Instructions

Run project commands through the conda environment:

```powershell
conda run -n stoner_measurement <command>
```

## Examples

```powershell
conda run -n stoner_measurement pytest
conda run -n stoner_measurement ruff check
conda run -n stoner_measurement codacy issues gh gb119 stoner_measurement --limit 1000 --output json
```

Prefer `conda run -n stoner_measurement ...` over `conda activate`, because
Codex shell calls may run as separate non-interactive PowerShell sessions and
activation may not persist between commands.

## Tooling Available

The `stoner_measurement` conda environment includes the project installed in
editable mode plus the main development tools:

```powershell
conda run -n stoner_measurement python
conda run -n stoner_measurement pytest
conda run -n stoner_measurement ruff
conda run -n stoner_measurement pylint
conda run -n stoner_measurement bandit
conda run -n stoner_measurement mypy
conda run -n stoner_measurement pre-commit
conda run -n stoner_measurement sphinx-build
conda run -n stoner_measurement codacy
conda run -n stoner_measurement python -m build
conda run -n stoner_measurement twine
conda run -n stoner_measurement check-manifest
```

Packaging tools (`build`, `twine`, and `check-manifest`) are installed through
the `pip:` section of `environment.yml` so the environment remains usable on
newer Python versions where conda packages may lag.

Useful commands:

```powershell
conda run -n stoner_measurement pytest
conda run -n stoner_measurement pytest tests
conda run -n stoner_measurement ruff check
conda run -n stoner_measurement ruff format
conda run -n stoner_measurement pylint src tests docs
conda run -n stoner_measurement bandit -r src
conda run -n stoner_measurement mypy src
conda run -n stoner_measurement pre-commit run --all-files
conda run -n stoner_measurement python -m build
conda run -n stoner_measurement twine check dist/*
conda run -n stoner_measurement check-manifest
conda run -n stoner_measurement codacy issues gh gb119 stoner_measurement --limit 1000 --output json
```

## Qt Tests

The environment includes Qt bindings and Qt test tooling, including `PyQt6`,
`PySide6`, `qtpy`, and `pytest-qt`. Use the conda environment for any
GUI/widget tests so the correct Qt stack is available.

## Codacy

The Codacy cloud CLI is available as:

```powershell
conda run -n stoner_measurement codacy
```

Use it for repository issue pulls and Codacy checks rather than assuming a
global `codacy` command exists.

## Notes For Agents

- The shell is PowerShell on Windows.
- Use `rg` for repository searches when available.
- Do not assume globally installed Python tooling; prefer the conda environment.
- If a command fails outside the environment, retry it through
  `conda run -n stoner_measurement`.
- Before adding, moving, or rewriting tests, read
  `notes/testing_guidelines.md`. Keep migration progress in
  `notes/testing_restructure_plan.md`.
- Developer-facing notes belong in `notes/`; keep `docs/` for user-facing
  Sphinx documentation.
