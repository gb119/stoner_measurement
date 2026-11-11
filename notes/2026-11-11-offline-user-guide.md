# Offline Windows User Guide

Help > User Guide (F1) opens the bundled CHM in Windows. A content-addressed
local cache keeps the document available to the external viewer after launch.
Missing documentation and launch failures produce a message in the application.

## Build a Windows release

Install Microsoft HTML Help Workshop on the build machine. End-user machines
do not need the compiler, Sphinx or internet access. From the repository root
in PowerShell 7 or newer:

```powershell
.\scripts\build_windows_release.ps1
# Nonstandard installation:
.\scripts\build_windows_release.ps1 -Hhc 'D:\Help Workshop\hhc.exe'
# Build only the documentation:
conda run -n stoner_measurement python scripts/build_chm.py
```

Compiler lookup accepts `--hhc`, the `HHC` environment variable, PATH, then the
standard Program Files locations. A clean Sphinx htmlhelp build is compiled and
staged at `src/stoner_measurement/help/stoner_measurement.chm`. HHC can return 1
on success; the script also requires a fresh file with the CHM header. Failed
rebuilds remove the previous staged guide to avoid shipping outdated help.

The release script builds the guide before invoking `python -m build` and stops
on failure. Setuptools package data and MANIFEST.in include the staged CHM in
the wheel and sdist. Before building the existing Conda recipe from a checkout,
run the documentation build so its pip install includes the same package data.
Plain development installs and ordinary builds may omit help; use the release
script for packages promising offline documentation. Generated CHMs are ignored
by Git. Online site builds remain independent.

## Release checks

`.github/workflows/release.yml` runs when a GitHub release is published, or
manually through Actions. Its Windows job installs the pinned Chocolatey
`html-help-workshop` 1.32.1 package, creates the project Conda environment,
builds the CHM, and only then builds the wheel and source distribution.
Both archives must contain exactly the freshly compiled guide; missing or
different help fails the job before any release assets are uploaded.

Successful builds retain the packages and standalone CHM as Actions artifacts.
For release events, a separate job attaches these files to that release using
the built-in GitHub token. Manual runs do not publish release assets. The
existing documentation website workflow remains independent. Compiler setup
requires network access to Chocolatey's package and its upstream installer;
this requirement applies only to the release runner.

Inspect wheel and sdist contents for `help/stoner_measurement.chm`. Install the
wheel and check Help > User Guide and F1 with networking disconnected. Verify
contents, index, search, images, styling and links between topics in Windows
Help Viewer. External Python and Qt documentation links still require internet.
