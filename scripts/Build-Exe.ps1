<#
.SYNOPSIS
    Build SpoolHouse into a standalone Windows .exe bundle with PyInstaller.

.DESCRIPTION
    Produces dist\SpoolHouse\SpoolHouse.exe — a self-contained onedir bundle
    that runs without Python, uv, or any installed dependencies. Double-click
    the .exe (or distribute the whole dist\SpoolHouse folder) to run.

    Onedir (a folder containing the .exe) is used rather than a single loose
    .exe on purpose: SpoolHouse spawns child processes for parallel scans, and
    a onefile build would re-extract its ~400 MB VTK payload to a temp dir on
    every child spawn. The folder layout shares one unpacked copy.

.PARAMETER Clean
    Remove build\ and dist\ before building for a fully fresh bundle.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\Build-Exe.ps1
#>
[CmdletBinding()]
param(
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

Write-Host "Ensuring dev dependencies (incl. PyInstaller) are installed..." -ForegroundColor Cyan
uv sync --extra dev
if ($LASTEXITCODE -ne 0) { throw "uv sync failed" }

$pyiArgs = @("run", "pyinstaller", "spoolhouse.spec", "--noconfirm")
if ($Clean) { $pyiArgs += "--clean" }

Write-Host "Building SpoolHouse.exe (this pulls in VTK; expect a couple of minutes)..." -ForegroundColor Cyan
uv @pyiArgs
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed" }

$exe = Join-Path $repoRoot "dist\SpoolHouse\SpoolHouse.exe"
if (-not (Test-Path $exe)) {
    throw "Build reported success but $exe is missing"
}

$size = (Get-ChildItem (Join-Path $repoRoot "dist\SpoolHouse") -Recurse | Measure-Object Length -Sum).Sum / 1MB

# Clean up PyInstaller's intermediate work tree — it's pure scratch (~56 MB);
# the dist\SpoolHouse bundle is the only artifact worth keeping. Only done once
# the exe is confirmed present, so a failed build leaves build\ for debugging.
$buildDir = Join-Path $repoRoot "build"
if (Test-Path $buildDir) {
    Remove-Item $buildDir -Recurse -Force
    Write-Host "Cleaned up intermediate build\ directory." -ForegroundColor DarkGray
}

Write-Host ("Done. Bundle: {0} ({1:N0} MB total)" -f $exe, $size) -ForegroundColor Green
Write-Host "Run it by double-clicking the .exe, or distribute the dist\SpoolHouse folder." -ForegroundColor Green
