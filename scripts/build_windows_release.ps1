#Requires -Version 7.0
# Build the offline guide before building distributable Python packages.
param([string]$Hhc)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path $PSScriptRoot -Parent
$condaExe = $env:CONDA_EXE
if (-not $condaExe -or $condaExe -like '*\Miniconda3\*') {
    $condaExe = @(
        'C:\ProgramData\anaconda3\Scripts\conda.exe',
        'C:\ProgramData\Miniforge3\Scripts\conda.exe'
    ) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}
if (-not $condaExe) { throw 'A supported Conda installation is required.' }
# Resolve the environment's interpreter explicitly: inherited PATH entries can
# otherwise select a different Python even inside conda run.
$environments = & $condaExe env list --json | ConvertFrom-Json -AsHashtable
if ($LASTEXITCODE -ne 0) { throw 'Could not list Conda environments.' }
$prefix = @($environments.envs | Where-Object { (Split-Path $_ -Leaf) -eq 'stoner_measurement' } | Sort-Object -Unique)
if ($prefix.Count -ne 1) { throw 'Expected one stoner_measurement Conda environment.' }
$pythonExe = Join-Path $prefix[0] 'python.exe'
Push-Location $repoRoot
try {
    $compilerArgs = @()
    if ($Hhc) { $compilerArgs = @('--hhc', $Hhc) }
    & $condaExe run -n stoner_measurement $pythonExe scripts/build_chm.py @compilerArgs
    if ($LASTEXITCODE -ne 0) { throw 'User Guide build failed; no release built.' }
    & $condaExe run -n stoner_measurement $pythonExe -m build
    if ($LASTEXITCODE -ne 0) { throw 'Package build failed.' }
}
finally { Pop-Location }
