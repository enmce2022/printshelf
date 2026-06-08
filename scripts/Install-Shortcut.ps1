<#
.SYNOPSIS
    Create (or remove) a Windows shortcut that launches PrintShelf.

.DESCRIPTION
    Builds a .lnk on the Desktop (and optionally the Start Menu) that starts the
    PrintShelf desktop app. When the project's virtualenv exists the shortcut
    targets .venv\Scripts\pythonw.exe directly, so the app opens with no console
    window and without needing `uv` on PATH. If there is no venv, it falls back
    to `uv run pythonw run.py`.

.PARAMETER Name
    Shortcut file name (without extension). Default: "PrintShelf".

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
    pwsh -File scripts\Install-Shortcut.ps1 -StartMenu -DataDir D:\printshelf-data

.EXAMPLE
    pwsh -File scripts\Install-Shortcut.ps1 -Uninstall
#>
[CmdletBinding()]
param(
    [string]$Name = "PrintShelf",
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
    throw "Could not find run.py at $RunScript - is this the PrintShelf project?"
}

# Prefer the project venv's pythonw.exe: launches windowless, no uv on PATH.
$venvPythonw = Join-Path $ProjectRoot ".venv\Scripts\pythonw.exe"
if (Test-Path $venvPythonw) {
    $exe = $venvPythonw
    $argLine = "`"$RunScript`""
} else {
    $uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
    if (-not $uv) {
        throw "No .venv found and 'uv' is not on PATH. Run 'uv sync --extra dev' first."
    }
    Write-Warning "No .venv found - falling back to 'uv run'. A console window may flash on launch. Run 'uv sync --extra dev' for a windowless shortcut."
    $exe = $uv
    $argLine = "run pythonw `"$RunScript`""
}

if ($DataDir) {
    $argLine += " --data-dir `"$DataDir`""
}

# Use a custom .ico if one is shipped; otherwise the launcher's own icon is used.
$icon = Join-Path $ProjectRoot "printshelf\static\printshelf.ico"

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

Write-Host "`nDone. Launch PrintShelf from the '$Name' shortcut."
