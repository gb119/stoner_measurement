#Requires -Version 5.1
<#
.SYNOPSIS
Create or update the current user's Stoner Measurement Start menu shortcut.
.DESCRIPTION
Requires CONDA_EXE to name an existing conda executable and the application to
be installed in the stoner_measurement environment. No administrator rights
are needed. Rerun after moving the repository or the conda installation.
.PARAMETER StartMenuDirectory
Shortcut destination; defaults to the current user's Start menu Programs folder.
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$StartMenuDirectory = [Environment]::GetFolderPath('Programs')
)

$ErrorActionPreference = 'Stop'
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw 'This script requires Windows.'
}
if (-not $env:CONDA_EXE -or -not (Test-Path -LiteralPath $env:CONDA_EXE -PathType Leaf)) {
    throw 'Set CONDA_EXE to the full path of your conda executable before running this script.'
}
$condaExe = (Resolve-Path -LiteralPath $env:CONDA_EXE).ProviderPath
$repoRoot = Split-Path $PSScriptRoot -Parent

# Use an absolute interpreter path so an inherited PATH cannot select another Python.
$environmentJson = & $condaExe env list --json
if ($LASTEXITCODE -ne 0) { throw 'Could not list conda environments.' }
$environments = $environmentJson | ConvertFrom-Json
$prefixes = @($environments.envs | Where-Object {
    (Split-Path $_ -Leaf) -eq 'stoner_measurement'
} | Sort-Object -Unique)
if ($prefixes.Count -ne 1) {
    throw 'Expected exactly one conda environment named stoner_measurement.'
}
$pythonExe = Join-Path $prefixes[0] 'python.exe'
if (-not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) {
    throw "The environment's Python executable does not exist: $pythonExe"
}
if ([string]::IsNullOrWhiteSpace($StartMenuDirectory)) {
    throw 'Could not determine the Start menu Programs directory.'
}
$shortcutPath = Join-Path $StartMenuDirectory 'Stoner Measurement.lnk'
if ($PSCmdlet.ShouldProcess($shortcutPath, 'Create or update Start menu shortcut')) {
    New-Item -ItemType Directory -Path $StartMenuDirectory -Force | Out-Null
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $condaExe
    $shortcut.Arguments = 'run --no-capture-output -n stoner_measurement "{0}" -m stoner_measurement.main' -f $pythonExe
    $shortcut.WorkingDirectory = $repoRoot
    $shortcut.Description = 'Run Stoner Measurement in its conda environment'
    $shortcut.IconLocation = (Join-Path $repoRoot 'src\stoner_measurement\conf\resources\StonerLogo2.ico') + ',0'
    # Keep the conda console available for diagnostics, but start it minimized.
    $shortcut.WindowStyle = 7
    $shortcut.Save()
    Write-Output "Created Start menu shortcut: $shortcutPath"
}
