# PrintShelf

A simple Python desktop app for browsing a library of `.stl` and `.gcode` files.

## What it does

- Scans a selected folder recursively for STL and G-code files
- Stores metadata in SQLite
- Generates previews and caches them on disk
- Extracts embedded PNG thumbnails from G-code when available
- Falls back to generating a preview from toolpaths when a G-code thumbnail is missing or unsupported
- Lets you add tags, descriptions, and custom JSON metadata
- Includes a dedicated Tags view for exploration and bulk tag operations
- Runs a local FastAPI server and opens the UI in a native desktop window via pywebview

## Preview strategy

### STL
- Load the mesh with `trimesh`
- Try to place the model in a stable resting orientation
- Render a clean isometric preview with `matplotlib`

### G-code
- First try to extract an embedded thumbnail block
- If the file contains a PNG thumbnail, use it directly
- If the file contains no supported thumbnail, parse the motion commands and render the extrusion toolpath as a preview

## Current limitation

PrusaSlicer can emit both PNG and QOI thumbnails in modern G-code. This starter app extracts PNG thumbnails. If it encounters an unsupported embedded format such as QOI, it falls back to generating a preview from the G-code moves instead.

## Run it

PrintShelf uses [uv](https://docs.astral.sh/uv/) for environment and dependency management. Install uv first, then:

```
uv sync --extra dev    # creates .venv and installs runtime + dev tooling
uv run python run.py   # launch the desktop app
```

`uv.lock` is committed, so `uv sync` produces an identical environment on every machine. The optional `--extra dev` pulls in formatter/linter/test tooling (`black`, `isort`, `ruff`, `pytest`).

If you prefer the classic flow it still works (`python -m venv .venv`, then `pip install -e .[dev]`), but uv is the documented path.

Worker model:
PrintShelf starts Uvicorn with a single worker (`1`) by default.
The app does not set `workers` explicitly in code.
If `WEB_CONCURRENCY` is set in the environment, Uvicorn can override the default worker count.

Set `WEB_CONCURRENCY` (optional):
Use this to override the default worker count for the current shell session. This is temporary unless you persist it in your shell/profile settings.

```powershell
# Windows PowerShell (current session)
$env:WEB_CONCURRENCY = "2"
python run.py
```

```cmd
:: Windows Command Prompt (current session)
set WEB_CONCURRENCY=2
python run.py
```

```bash
# macOS/Linux (current shell session)
export WEB_CONCURRENCY=2
python run.py
```

## Data location and reset

PrintShelf stores local app data in your home directory:

- Base data directory: `~/.printshelf`
- SQLite database: `~/.printshelf/printshelf.sqlite3`
- Preview cache: `~/.printshelf/previews/`

Reset options:

- Soft reset: delete only `printshelf.sqlite3` (keeps cached previews).
- Full reset: delete the entire `~/.printshelf` directory (removes DB, previews, and scan state).

Before resetting, close/stop PrintShelf.

### Soft reset (keep preview cache)

```powershell
# Windows PowerShell
Remove-Item "$HOME\.printshelf\printshelf.sqlite3" -Force
```

```cmd
:: Windows Command Prompt (CMD)
del "%USERPROFILE%\.printshelf\printshelf.sqlite3"
```

```bash
# macOS/Linux
rm -f ~/.printshelf/printshelf.sqlite3
```

Optional verification:

```powershell
Test-Path "$HOME\.printshelf\printshelf.sqlite3"
```

```cmd
if exist "%USERPROFILE%\.printshelf\printshelf.sqlite3" (echo EXISTS) else (echo MISSING)
```

```bash
test -f ~/.printshelf/printshelf.sqlite3 && echo EXISTS || echo MISSING
```

### Full reset (remove all PrintShelf local data)

```powershell
# Windows PowerShell
Remove-Item "$HOME\.printshelf" -Recurse -Force
```

```cmd
:: Windows Command Prompt (CMD)
rmdir /s /q "%USERPROFILE%\.printshelf"
```

```bash
# macOS/Linux
rm -rf ~/.printshelf
```

Optional verification:

```powershell
Test-Path "$HOME\.printshelf"
```

```cmd
if exist "%USERPROFILE%\.printshelf" (echo EXISTS) else (echo MISSING)
```

```bash
test -d ~/.printshelf && echo EXISTS || echo MISSING
```

If pywebview is unavailable on your platform, the app will still start the local server and open the UI in a browser.

## Tags view

Use the `Tags` view switch in the sidebar to open the dedicated tag explorer.

- Search tags by name and select one active tag at a time.
- Tag item results combine the active tag with current Search, Type, and Sort filters.
- Rename supports merge behavior: renaming to an existing tag name merges them.
- Delete detaches the tag from all items (items/files remain).
- Bulk add/remove actions apply only to checked items in the tag result list.

## Notes for Linux

pywebview's documentation says Linux users need to choose a backend explicitly, for example `pip install pywebview[gtk]` or `pip install pywebview[qt]`.

## Suggested next upgrades

- Background scan jobs with progress reporting
- SQLite FTS5 for faster full-text search
- File watching with `watchdog`
- Multiple library roots
- Support for decoding embedded QOI thumbnails
- Packaging with PyInstaller
