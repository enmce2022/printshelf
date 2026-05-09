from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any

import uvicorn

from .api import create_app
from .service import PrintShelfService


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class NativeBridge:
    def __init__(self, service: PrintShelfService) -> None:
        self._service = service
        self._window = None

    def _attach_window(self, window: Any) -> None:
        self._window = window

    def pick_folder(self) -> dict[str, str]:
        if self._window is None:
            return {"root_path": self._service.get_root_path()}
        import webview

        result = self._window.create_file_dialog(
            webview.FileDialog.FOLDER,
            directory=self._service.get_root_path() or str(Path.home()),
        )
        if result:
            root = self._service.set_root_path(result[0])
            return {"root_path": root}
        return {"root_path": self._service.get_root_path()}

    def scan_now(self) -> dict[str, Any]:
        return self._service.request_scan()

    def reveal_in_explorer(self, path: str) -> dict[str, Any]:
        target = Path(str(path or "")).expanduser()
        if not target.exists():
            return {"error": f"Path does not exist: {target}"}
        try:
            if sys.platform == "win32":
                subprocess.run(["explorer", "/select,", str(target)], check=False)
            elif sys.platform == "darwin":
                subprocess.run(["open", "-R", str(target)], check=False)
            else:
                parent = target.parent if target.is_file() else target
                subprocess.run(["xdg-open", str(parent)], check=False)
            return {"ok": True}
        except Exception as exc:
            return {"error": str(exc)}

    def open_file(self, path: str) -> dict[str, Any]:
        target = Path(str(path or "")).expanduser()
        if not target.exists():
            return {"error": f"Path does not exist: {target}"}
        try:
            if sys.platform == "win32":
                os.startfile(str(target))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.run(["open", str(target)], check=False)
            else:
                subprocess.run(["xdg-open", str(target)], check=False)
            return {"ok": True}
        except Exception as exc:
            return {"error": str(exc)}


DEFAULT_DATA_DIR_NAME = "printshelf-data"


def resolve_data_dir(cli_value: str | None = None) -> Path:
    """Resolve the data directory, in priority order:

    1. Explicit CLI value (`--data-dir`).
    2. `PRINTSHELF_DATA_DIR` environment variable.
    3. `./printshelf-data` relative to the current working directory.

    Tilde expansion is applied so `~/foo` works in any source.
    """
    raw = cli_value or os.environ.get("PRINTSHELF_DATA_DIR")
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.cwd() / DEFAULT_DATA_DIR_NAME).resolve()


def run_desktop_app(data_dir: Path | None = None) -> None:
    app_dir = Path(__file__).resolve().parent
    static_dir = app_dir / "static"
    resolved_data_dir = data_dir if data_dir is not None else resolve_data_dir()

    service = PrintShelfService(data_dir=resolved_data_dir)
    app = create_app(service=service, static_dir=static_dir)
    port = _find_free_port()
    url = f"http://127.0.0.1:{port}"

    server_config = uvicorn.Config(
        app=app, host="127.0.0.1", port=port, log_level="warning"
    )
    server = uvicorn.Server(server_config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    for _ in range(100):
        if getattr(server, "started", False):
            break
        time.sleep(0.05)

    try:
        import webview

        bridge = NativeBridge(service)
        window = webview.create_window(
            title="PrintShelf",
            url=url,
            js_api=bridge,
            width=1380,
            height=920,
            min_size=(980, 700),
        )
        bridge._attach_window(window)
        webview.start()
    except Exception:
        webbrowser.open(url)
        print(f"PrintShelf is running at {url}")
        print("A browser window should open automatically. Press Ctrl+C to stop.")
        try:
            while thread.is_alive():
                time.sleep(1.0)
        except KeyboardInterrupt:
            pass
