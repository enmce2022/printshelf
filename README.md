# PrintShelf

A simple Python desktop app for browsing a library of `.stl` and `.gcode` files.

## What it does

- Scans a selected folder recursively for STL and G-code files
- Stores metadata in SQLite
- Generates previews and caches them on disk
- Extracts embedded PNG thumbnails from G-code when available
- Falls back to generating a preview from toolpaths when a G-code thumbnail is missing or unsupported
- Lets you add tags, descriptions, and custom JSON metadata
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

Create a virtual environment, install dependencies, and start the app:

`python -m venv .venv`
`.venv\Scripts\activate` on Windows or `source .venv/bin/activate` on macOS/Linux
`pip install -e .`
`pip install -e .[dev]` for formatter/linter tooling
`python run.py`

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

If pywebview is unavailable on your platform, the app will still start the local server and open the UI in a browser.

## Notes for Linux

pywebview's documentation says Linux users need to choose a backend explicitly, for example `pip install pywebview[gtk]` or `pip install pywebview[qt]`.

## Suggested next upgrades

- Background scan jobs with progress reporting
- SQLite FTS5 for faster full-text search
- File watching with `watchdog`
- Multiple library roots
- Support for decoding embedded QOI thumbnails
- Packaging with PyInstaller
