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
- Render a clean isometric preview with `pyvista` (VTK offscreen)

### G-code
- First try to extract an embedded thumbnail block
- If the file contains a PNG thumbnail, use it directly
- If the file contains no supported thumbnail, parse the motion commands and render the extrusion toolpath as a preview

## Current limitation

PrusaSlicer can emit both PNG and QOI thumbnails in modern G-code. This starter app extracts PNG thumbnails. If it encounters an unsupported embedded format such as QOI, it falls back to generating a preview from the G-code moves instead.

## Run it

PrintShelf uses [uv](https://docs.astral.sh/uv/) for environment and dependency management. Install uv first, then:

```
uv sync --extra dev          # creates .venv and installs runtime + dev tooling
uv run python run.py         # launch the desktop app
```

`uv.lock` is committed, so `uv sync` produces an identical environment on every machine. The optional `--extra dev` pulls in formatter/linter/test tooling (`black`, `isort`, `ruff`, `pytest`).

### Worker concurrency

PrintShelf starts Uvicorn with a single worker by default. Pass `--workers N` to spawn N worker processes:

```
uv run python run.py --workers 2
```

When `N > 1`, Uvicorn's multiprocess supervisor runs in a background thread alongside the pywebview window, and each worker subprocess opens its own connection to the shared SQLite file in the data directory. Scan state is coordinated cross-process via the DB. The native "scan" button on the toolbar calls into the parent process directly; HTTP requests from the UI are load-balanced across workers.

### Scan parallelism

Preview generation (STL mesh + G-code toolpath rendering) is the dominant cost during a library scan. Pass `--scan-workers N` to render previews on a process pool:

```
uv run python run.py --scan-workers 7
```

`--scan-workers` defaults to `1` (sequential, current behavior). Set it to roughly `cpu_count - 1` for the fastest scans; each worker holds a VTK render context plus a trimesh state in memory (~150 MB), so a 16-core box at `--scan-workers 15` will use a few GB during a scan. The flag is independent of `--workers` (HTTP). Can also be set via `PRINTSHELF_SCAN_WORKERS`.

Cancel and pause continue to work: cancellation drops pending work and lets in-flight files finish; pause stops dispatching new work until you resume.

## Data location and reset

PrintShelf is portable: it keeps all of its local data in a single folder
next to where you run it. Nothing is written to your home directory.

Default layout (relative to the current working directory at launch):

- Base data directory: `./printshelf-data/`
- SQLite database: `./printshelf-data/printshelf.sqlite3`
- Preview cache: `./printshelf-data/previews/`
- Log file: `./printshelf-data/printshelf.log`

To use a different location, pass `--data-dir` or set the `PRINTSHELF_DATA_DIR`
environment variable. The CLI flag takes precedence over the env var.

```powershell
# Windows PowerShell
uv run python run.py --data-dir D:\printshelf-library
$env:PRINTSHELF_DATA_DIR = "D:\printshelf-library"; uv run python run.py
```

```bash
# macOS/Linux
uv run python run.py --data-dir ~/printshelf-library
PRINTSHELF_DATA_DIR=~/printshelf-library uv run python run.py
```

### Reset

Close the app first, then:

- **Soft reset**: delete `printshelf.sqlite3` from your data directory
  (keeps the preview cache).
- **Full reset**: delete the whole data directory.

Because the data directory lives wherever you ran the app from, reset is
just a normal file delete — no system paths to chase. For example, if you
launched with the default layout from the repo root, soft reset is:

```powershell
# Windows PowerShell
Remove-Item .\printshelf-data\printshelf.sqlite3 -Force
```

```bash
# macOS/Linux
rm -f ./printshelf-data/printshelf.sqlite3
```

For a full reset, remove the whole `printshelf-data` folder.

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

## Next upgrades i consider

- Background scan jobs with progress reporting
- SQLite FTS5 for faster full-text search
- File watching with `watchdog`
- Multiple library roots
- Support for decoding embedded QOI thumbnails
