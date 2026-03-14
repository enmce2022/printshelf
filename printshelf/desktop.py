from __future__ import annotations

import socket
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
        self.service = service
        self.window = None

    def attach_window(self, window: Any) -> None:
        self.window = window

    def pick_folder(self) -> dict[str, str]:
        if self.window is None:
            return {"root_path": self.service.get_root_path()}
        result = self.window.create_file_dialog(
            3,  # FOLDER_DIALOG
            directory=self.service.get_root_path() or str(Path.home()),
        )
        if result:
            root = self.service.set_root_path(result[0])
            return {"root_path": root}
        return {"root_path": self.service.get_root_path()}

    def scan_now(self) -> dict[str, Any]:
        return self.service.scan()


def run_desktop_app() -> None:
    app_dir = Path(__file__).resolve().parent
    static_dir = app_dir / "static"
    data_dir = Path.home() / ".printshelf"

    service = PrintShelfService(data_dir=data_dir)
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
        bridge.attach_window(window)
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
