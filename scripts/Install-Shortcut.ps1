<#
.SYNOPSIS
    Create (or remove) a Windows shortcut that launches SpoolHouse.

.DESCRIPTION
    Builds a .lnk on the Desktop (and optionally the Start Menu) that starts the
    SpoolHouse desktop app. When the project's virtualenv exists the shortcut
    targets .venv\Scripts\python.exe directly, so it launches without needing
    `uv` on PATH. If there is no venv, it falls back to `uv run python run.py`.

    Note: a small console window opens alongside the app window. That is
    intentional - SpoolHouse's pywebview (WinForms) window does not reliably
    appear when launched without a console (pythonw.exe), so we use python.exe.
    Closing the console window quits the app.

.PARAMETER Name
    Shortcut file name (without extension). Default: "SpoolHouse".

.PARAMETER DataDir
    Optional path passed through as --data-dir, so the shortcut always uses the
    same data directory regardless of where it is launched from.

.PARAMETER StartMenu
    Also create the shortcut under the current user's Start Menu.

.PARAMETER Uninstall
    Remove the shortcut(s) instead of creating them.

.EXAMPLE
    pwsh -ExecutionPolicy Bypass -File scripts\Install-Shortcut.ps1

.EXAMPLE
    pwsh -File scripts\Install-Shortcut.ps1 -StartMenu -DataDir D:\spoolhouse-data

.EXAMPLE
    pwsh -File scripts\Install-Shortcut.ps1 -Uninstall
#>
[CmdletBinding()]
param(
    [string]$Name = "SpoolHouse",
    [string]$DataDir,
    [switch]$StartMenu,
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"

# Project root is the parent of this script's directory (scripts\..).
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$RunScript = Join-Path $ProjectRoot "run.py"

$Desktop = [Environment]::GetFolderPath("Desktop")
$StartMenuDir = [Environment]::GetFolderPath("Programs")

$targets = @(Join-Path $Desktop "$Name.lnk")
if ($StartMenu) {
    $targets += (Join-Path $StartMenuDir "$Name.lnk")
}

if ($Uninstall) {
    foreach ($lnk in $targets) {
        if (Test-Path $lnk) {
            Remove-Item $lnk -Force
            Write-Host "Removed $lnk"
        } else {
            Write-Host "Not found (skipped): $lnk"
        }
    }
    return
}

if (-not (Test-Path $RunScript)) {
    throw "Could not find run.py at $RunScript - is this the SpoolHouse project?"
}

# Prefer the project venv's python.exe: no need for uv on PATH. We use
# python.exe (not pythonw.exe) because the pywebview WinForms window does not
# reliably show when launched windowless - a console window comes along.
$venvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (Test-Path $venvPython) {
    $exe = $venvPython
    $argLine = "`"$RunScript`""
} else {
    $uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
    if (-not $uv) {
        throw "No .venv found and 'uv' is not on PATH. Run 'uv sync --extra dev' first."
    }
    Write-Warning "No .venv found - falling back to 'uv run python run.py'. Run 'uv sync --extra dev' to target the venv directly."
    $exe = $uv
    $argLine = "run python `"$RunScript`""
}

if ($DataDir) {
    $argLine += " --data-dir `"$DataDir`""
}

# Use a custom .ico if one is shipped; otherwise the launcher's own icon is used.
$icon = Join-Path $ProjectRoot "spoolhouse\static\spoolhouse.ico"

$shell = New-Object -ComObject WScript.Shell
foreach ($lnk in $targets) {
    $sc = $shell.CreateShortcut($lnk)
    $sc.TargetPath = $exe
    $sc.Arguments = $argLine
    $sc.WorkingDirectory = $ProjectRoot
    $sc.Description = "Browse a library of STL and G-code files"
    if (Test-Path $icon) {
        $sc.IconLocation = $icon
    }
    $sc.Save()
    Write-Host "Created $lnk"
}

Write-Host "`nDone. Launch SpoolHouse from the '$Name' shortcut."
