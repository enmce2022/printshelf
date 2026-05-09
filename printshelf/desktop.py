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


def create_default_app():
    """App factory used by uvicorn worker subprocesses.

    Each spawned worker re-imports this module and calls this factory to build
    its own `PrintShelfService` and FastAPI app. The data directory is read
    from the `PRINTSHELF_DATA_DIR` env var, which `run_desktop_app` exports
    before launching the multiprocess supervisor.
    """
    data_dir = resolve_data_dir()
    static_dir = Path(__file__).resolve().parent / "static"
    service = PrintShelfService(data_dir=data_dir)
    return create_app(service=service, static_dir=static_dir)


def run_desktop_app(data_dir: Path | None = None, workers: int = 1) -> None:
    app_dir = Path(__file__).resolve().parent
    static_dir = app_dir / "static"
    resolved_data_dir = data_dir if data_dir is not None else resolve_data_dir()

    # Parent's service backs the NativeBridge (pick_folder, scan_now, ...).
    # When workers > 1, it shares the same SQLite file with the children but
    # serves no HTTP traffic itself.
    service = PrintShelfService(data_dir=resolved_data_dir)
    port = _find_free_port()
    url = f"http://127.0.0.1:{port}"

    supervisor = None
    if workers > 1:
        # Multiprocess path: uvicorn supervisor spawns N workers; each worker
        # constructs its own service via create_default_app. Cross-process scan
        # state is coordinated via the DB (run_id ownership tokens).
        os.environ["PRINTSHELF_DATA_DIR"] = str(resolved_data_dir)

        from uvicorn.supervisors import Multiprocess

        config = uvicorn.Config(
            "printshelf.desktop:create_default_app",
            factory=True,
            host="127.0.0.1",
            port=port,
            log_level="warning",
            workers=workers,
        )
        sock = config.bind_socket()
        server = uvicorn.Server(config)
        # Multiprocess.__init__ registers signal handlers; must run on main thread.
        supervisor = Multiprocess(config, target=server.run, sockets=[sock])
        thread = threading.Thread(target=supervisor.run, daemon=True)
        thread.start()
        # Socket is already listening; give children a moment to start accepting.
        time.sleep(0.3)
    else:
        app = create_app(service=service, static_dir=static_dir)
        config = uvicorn.Config(
            app=app, host="127.0.0.1", port=port, log_level="warning"
        )
        server = uvicorn.Server(config)
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        for _ in range(100):
            if getattr(server, "started", False):
                break
            time.sleep(0.05)

    try:
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
    finally:
        if supervisor is not None:
            # Stop the supervisor's monitoring loop, then force-kill children
            # directly. uvicorn's terminate_all uses CTRL_BREAK_EVENT on
            # Windows, which doesn't reach children spawned without their own
            # process group — so we call TerminateProcess via Process.kill()
            # to guarantee they exit.
            supervisor.should_exit.set()
            thread.join(timeout=1.0)
            for proc in supervisor.processes:
                try:
                    proc.kill()
                except Exception:
                    pass
            thread.join(timeout=5.0)
