# Codex Instructions

## Agent Identity

Codex acts as a careful Python project maintainer for this repository. Prefer
small, reviewable changes that preserve existing behaviour and fit the current
testing and packaging conventions.

Run project commands through the conda environment:

```powershell
conda run -n stoner_measurement <command>
```

Prefer `conda run -n stoner_measurement ...` over `conda activate`, because
Codex shell calls may run as separate non-interactive PowerShell sessions and
activation may not persist between commands.

If `CONDA_EXE` is set, prefer it because the Conda installation varies between
testing machines:

```powershell
& $env:CONDA_EXE run -n stoner_measurement <command>
```

Otherwise, use the Conda executable from either
`C:\ProgramData\anaconda3\Scripts` or
`C:\ProgramData\Miniforge3\Scripts`, depending on the machine. Never use the
Conda installation under `C:\ProgramData\Miniconda3\Scripts`; it does not host
the project's environment reliably.

## Tools

The `stoner_measurement` conda environment includes the project in editable
mode plus the main development tools:

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

Packaging tools (`build`, `twine`, and `check-manifest`) are installed through
the `pip:` section of `environment.yml` so the environment remains usable on
newer Python versions where conda packages may lag.

## Qt Tests

The environment includes `PyQt6`, `PySide6`, `qtpy`, and `pytest-qt`. Use the
conda environment for graphical user interface (GUI) or widget tests so the correct Qt stack is
available.

For offscreen widget rendering or screenshot-based visual checks, point Qt at
the Windows font directory as well as selecting the offscreen platform:

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
$env:QT_QPA_FONTDIR = "C:\Windows\Fonts"
```

Without `QT_QPA_FONTDIR`, Qt's offscreen platform may discover no system fonts
and render labels, button text, and editor content as square placeholder glyphs.

For tests calling a plugin's `config_tabs()`, use the
`managed_plugin_config_tabs` fixture so every returned page, including hidden
scan previews, stays alive until deterministic Qt teardown. Managing only the
Settings page leaves PyQtGraph previews exposed to deferred-event crashes.

## Shared Qt Widgets

- Before constructing or subclassing a raw Qt widget, check
  `stoner_measurement.ui` and `stoner_measurement.ui.widgets` for the
  repository's shared equivalent. Use the shared widget so that application
  styling, sizing, accessibility, persistence, and cross-binding behaviour
  remain consistent.
- Use `FontAwareTabWidget` instead of `QTabWidget` and `FontAwareTabBar`
  instead of `QTabBar`. Specialized tab widgets should inherit from
  `FontAwareTabWidget`; standalone tab bars should be `FontAwareTabBar`. These
  classes reserve enough space for the selected bold label and prevent tab
  text from being clipped when selection changes.
- Use `SISpinBox` for physical quantities and rates that support International System of Units (SI) units or
  prefixes rather than a raw `QDoubleSpinBox`.
- Keep configuration-tab titles concise and role-based, such as `General`,
  `Scan`, `Data`, `Settings`, and `About`. Do not prefix them with the
  plugin or class name; the selected sequence step already provides that
  identity.

## Qt Configuration Pages

- Top-pack configuration-page controls: add widgets and layouts at their
  natural size, then add one stretch at the bottom of the page layout.
- Do not place stretch space between configuration controls or allow a table,
  text editor, or other expanding widget to consume otherwise empty vertical
  space unintentionally. Give intentionally bounded controls an explicit
  height based on their visible content.

## Codacy

Use Codacy through the conda environment:

```powershell
conda run -n stoner_measurement codacy
```

Use it for repository issue pulls and Codacy checks rather than assuming a
global `codacy` command exists.

The Codacy configuration uses recursive `tests/**` exclusions for Prospector
(including its McCabe findings) and the separate `metric` complexity engine.
Keep production complexity checks active; test-only complexity should not drive
scenario or fake-driver rewrites. The refreshed inventory and dispositions live
in `codacy-reports/`; local fixes need remote reanalysis before findings clear.

## Boundaries For Agents

- Temperature control has a primary and optional secondary session. Legacy loop
  integers, sensor strings and connected_driver refer to primary; use LoopRef,
  ChannelRef and the service catalogues for combined selections. Restrict each
  loop's input choices to its owning driver's get_loop_input_channels result.
  Plugins borrow this shared service and must not close its sessions on cleanup.
  Stability uses one shared ordered table: first matching upper bound wins.
  Criteria may reference either controller; hardware input assignment remains local.
  See [secondary controller implementation](notes/2026-09-21-secondary-temperature-controller-plan.md).

- Keithley direct-current (DC) set commands opt into instrument lifecycle despite being leaf
  commands: retain source output between executions and disable it during
  sequence cleanup. On the Keithley 6221, `LIST` means its programmed-current
  list mode. The point scan must hold DC throughout child steps; do not
  substitute a `LIST` sweep merely to emit a trigger pulse.
  Pulsed-current plugins are deferred; see
  [Keithley point-command design](notes/2026-09-16-keithley-point-commands.md).

- Plugin lifecycle contract: repeated `connect()` calls must release the
  instance's existing resources before opening replacements. `BasePlugin`
  tracks connection attempts and calls `disconnect()` before reconnecting,
  including after a partially failed attempt. Resource-owning plugins must
  implement idempotent cleanup of complete and partial connections, clear
  their references, and propagate cleanup failures. Do not close resources
  owned by other instances or shared controller services.
- Reconfigure selections derive `delay_configuration`; do not add a direct
  editor or persist that flag independently. Suppression defaults on per
  Reconfigure command. Readiness is checked at runtime, including conditional
  and loop execution; do not replace it with static reachability checks.

- The shell is PowerShell on Windows.
- Use `rg` for repository searches when available.
- Do not assume globally installed Python tooling; prefer the conda environment.
- If a command fails outside the environment, retry it through
  `conda run -n stoner_measurement`.
- If `CONDA_EXE` is set, use it. Otherwise, if `conda` is not available on
  the executable search path (`PATH`), retry with `C:\ProgramData\anaconda3\Scripts\conda.exe` or
  `C:\ProgramData\Miniforge3\Scripts\conda.exe`, depending on which exists.
- Never use `C:\ProgramData\Miniconda3\Scripts\conda.exe` for this repository.
- Before adding, moving, or rewriting tests, read
  `notes/testing_guidelines.md`. Keep migration progress in
  `notes/testing_restructure_plan.md`.
- Developer-facing notes belong in `notes/`; keep `docs/` for user-facing
  Sphinx documentation.
