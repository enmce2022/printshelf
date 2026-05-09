# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Common commands

```powershell
# First-time setup (uv is the documented path; uv.lock is committed)
uv sync --extra dev

# Run the desktop app
uv run python run.py

# Format / lint (dev extras)
uv run black printshelf
uv run isort printshelf
uv run ruff check printshelf

# Tests
uv run pytest                              # whole suite (~4s)
uv run pytest tests/test_scan_state.py     # single file
uv run pytest -k rename                    # filter by test name
```

The classic `python -m venv .venv` + `pip install -e .[dev]` flow still works but uv is preferred. There is no build step beyond `uv sync` — the package is pure Python plus static assets under `printshelf/static/`.

The app's runtime data is portable: by default it lives in `./printshelf-data/` (SQLite at `printshelf.sqlite3`, generated previews under `previews/`, log at `printshelf.log`) — relative to the cwd at launch. Override with `--data-dir PATH` or the `PRINTSHELF_DATA_DIR` env var; resolution happens in `printshelf.desktop.resolve_data_dir`, where CLI > env var > cwd default. Nothing is written under `~/`. README.md has the reset commands; close the app first. `WEB_CONCURRENCY` env var overrides the default uvicorn worker count (default 1).

## Architecture

PrintShelf is a single-process desktop app: a FastAPI server runs on a background thread inside the same process as the pywebview window that displays its UI. There is no separate client/server deployment.

**Process model (`printshelf/desktop.py`)** — `run_desktop_app()` builds the `PrintShelfService`, creates the FastAPI app, picks a free localhost port, starts uvicorn in a daemon thread, then opens a `webview` window pointing at that port. If pywebview fails to load (e.g. missing Linux backend), the same URL is opened in the system browser instead — so the FastAPI app must remain self-sufficient and not depend on the bridge being present.

**JS ↔ Python bridge** — `NativeBridge` is exposed to the webview as `window.pywebview.api`. The frontend feature-detects `window.pywebview?.api` and only uses native methods (`pick_folder`, `reveal_in_explorer`, `open_file`) when present; everything else goes through the HTTP API. When adding native-only capabilities, always provide a fallback path or hide/disable the affected UI in browser mode.

**Layered backend**

- `api.py` — thin FastAPI layer. Routes are I/O glue: validate Pydantic models, call into `PrintShelfService`, translate `ValueError` → 400 and missing entities → 404. No business logic here.
- `service.py` — `PrintShelfService` is the single orchestration point. It owns the DB handle, the `ScanRunStore`, the preview directory, and the scan worker thread. `_serialize_item` is the canonical item-shape boundary between DB rows and JSON responses (note that `meta_json` is user-editable JSON and `indexed_meta_json` is scanner-extracted; both are deserialized into `meta` / `indexed_meta` for the client).
- `database.py` — a hand-rolled SQLite layer. Schema baseline is in `_BASELINE_SCHEMA` (idempotent `CREATE TABLE IF NOT EXISTS`); future additive changes go in `_MIGRATIONS` as `(version, sql)` tuples and get applied by `_run_migrations()` against the `schema_migrations` tracking table. Tags are stored as a normalized `tags` + `item_tags` join with `COLLATE NOCASE`, so renaming-onto-existing merges automatically. Multi-statement operations (`update_item`, `rename_tag`, `bulk_update_item_tags`, `set_tags`) run inside `Database.transaction()` so a crash mid-operation rolls back. `list_items` and `get_item` aggregate tags via a single `GROUP_CONCAT` subquery (NUL-delimited) — there is no per-row tag fetch.
- `scan_state.py` — `ScanRunStore` encapsulates all reads/writes against the `scan_state` table. The schema lives in `Database`; `ScanRunStore` only owns the operations (`start_run`, `claim_owner`, `request_restart`, `request_cancel`, `claim_restart`, `mark_canceling`, `update_progress`, `complete_run`, `fail_run`, `is_cancel_requested`, `get_state`). `service.py` orchestrates the worker loop using these named methods.
- `scanner.py` — walks the library root, skipping `.git`, `__pycache__`, `.venv`, `node_modules`. Supported extensions are `.stl` and `.gcode` (see `SUPPORTED_EXTENSIONS`). Cancellation is cooperative: callers pass a `should_cancel` callback that the walker checks between files and raises `ScanCanceledError`.
- `preview.py` — generates and caches preview PNGs, keyed by SHA-1 of `(resolved_path, mtime)`. Strategy registry in `_STRATEGIES` (`StlStrategy`, `GcodeEmbeddedThumbStrategy`, `GcodeToolpathStrategy`). `generate_preview` walks strategies for the file's extension, taking the first one that returns a non-None result; embedded-thumb beats toolpath for G-code. Add new file types or thumbnail formats by appending a `PreviewStrategy` subclass — no edits to `generate_preview`. Render constants (`RENDER_FIGSIZE`, `RENDER_DPI`, `STL_VIEW_ELEV`, `GCODE_MAX_SEGMENTS`, etc.) live at module top. Matplotlib is set to the Agg backend at import time — do not switch backends.
- `logging_setup.py` — single `configure_logging(data_dir)` call sets up a rotating file handler at `<data_dir>/printshelf.log` plus stderr, both at INFO. The `printshelf` logger root has `propagate=False` so it doesn't leak into uvicorn's default config. `PrintShelfService.__init__` calls this; tests should pass a tmp dir.

**Scan worker model** — there is exactly one scan thread per process, guarded by `_scan_thread_lock`. The interesting design is in `service._scan_worker_loop` plus `ScanRunStore`:

- A run is identified by a `run_id` (uuid). The worker takes ownership by writing its `_scan_owner_token` into the row via `ScanRunStore.claim_owner`; only the owner may update progress.
- `request_scan()` is idempotent. If a scan is already active (`counting`/`running`/`canceling`), it sets `restart_requested` + a new root path on the existing row via `request_restart` instead of starting a parallel run. The current run sees `is_cancel_requested`, raises `ScanCanceledError`, and the worker loop calls `claim_restart` to atomically pick up the queued restart and continue without releasing the thread.
- `cancel_scan()` (`POST /api/scan/cancel`) sets `cancel_requested=1` *without* `restart_requested=1`. When the worker exits a `canceling` state with no restart pending, the loop transitions the run to `failed` with message "Scan canceled".
- This means the scan thread's lifetime can span multiple `run_id`s, and any new scan logic must respect cancellation checks at the file-loop level (see how `scanner.scan_library` and `count_supported_files` thread `should_cancel` through).

**Frontend** — vanilla JS organized as native ES modules under `printshelf/static/js/` (no bundler). The entry point is `js/app.js`, loaded as `<script type="module">` from `index.html`. Layout: `state.js` (mutable app state), `api.js` (fetch helper), `utils.js` (`escapeHtml`, `formatBytes`, `buildItemQueryParams`, etc.), `ui/` (reusable components — `toast.js`, `modal.js` for confirm/prompt/message dialogs, `tag-input.js` for chip-style autocomplete), and `views/` (`browse.js`, `tags.js`, `scan.js`). Static assets are mounted at `/assets` and SQLite-cached previews at `/previews`. The UI has two top-level views (Browse / Tags) selected from the sidebar; tag-filtered item queries combine the active tag with current Search/Type/Sort filters server-side via `/api/items?tag=...`.

## Conventions

- Python target is 3.10+; ruff/black/isort all configured at line-length 88 (ruff selects E/F/I, ignores E501).
- Routes return plain `dict[str, Any]` or lists thereof — Pydantic is used for request validation only, not response serialization.
- Keep `_serialize_item` as the only place that shapes item JSON; routes and services should round-trip through it rather than constructing item dicts ad-hoc.

## Tests

Tests live under `tests/`. The suite is intentionally focused — smoke coverage on the scariest seams, not exhaustive. Notable fixtures (in `tests/conftest.py`):

- `tmp_db` — fresh `Database` backed by a per-test tmp file (not `:memory:` because Database opens a new connection per call).
- `scan_store` — a `ScanRunStore` wrapping `tmp_db`.
- `make_item` — factory that calls `upsert_item` with sensible defaults; pass kwargs to override fields.

Coverage by file:
- `test_scan_state.py` — drives the full state machine: start/claim/progress/complete, restart-while-running atomic pickup, cancel-without-restart, concurrent claim collision, complete blocked when cancel pending, fail clears flags.
- `test_tag_rename.py` — rename to new name, rename-onto-existing merges items under the canonical tag, case-only rename preserves id, empty/unknown rejected; delete cascades through `item_tags` and detaches from items.
- `test_query_building.py` — every WHERE branch in `list_items` (filename/path/description/tag-name search), file-type filter, NOCASE tag filter, combined intersection, sort orderings, unknown sort key falls back safely (SQL injection guard), N+1-fixed tag aggregation order.
- `test_preview_strategies.py` — feeds synthetic G-code (a real PNG base64-embedded in `; thumbnail begin/end` comments) and confirms embedded-thumb strategy wins; without thumb, falls back to toolpath; unsupported extensions get placeholder; toolpath failure converts to `placeholder-error`.
