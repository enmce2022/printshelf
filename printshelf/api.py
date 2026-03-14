from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .service import PrintShelfService


class ConfigUpdate(BaseModel):
    root_path: str = ""


class ItemUpdate(BaseModel):
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


def create_app(service: PrintShelfService, static_dir: Path) -> FastAPI:
    static_dir = Path(static_dir)
    static_dir.mkdir(parents=True, exist_ok=True)
    service.preview_dir.mkdir(parents=True, exist_ok=True)

    app = FastAPI(title="PrintShelf", docs_url="/api/docs", redoc_url=None)
    app.mount("/assets", StaticFiles(directory=str(static_dir)), name="assets")
    app.mount(
        "/previews", StaticFiles(directory=str(service.preview_dir)), name="previews"
    )

    @app.get("/")
    def root() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    @app.get("/api/config")
    def get_config() -> dict[str, Any]:
        return service.get_config()

    @app.post("/api/config")
    def set_config(payload: ConfigUpdate) -> dict[str, Any]:
        root = service.set_root_path(payload.root_path)
        return {"root_path": root}

    @app.post("/api/scan")
    def scan_library_route() -> dict[str, Any]:
        try:
            return service.request_scan()
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/scan/status")
    def scan_status_route() -> dict[str, Any]:
        return service.get_scan_status()

    @app.get("/api/items")
    def list_items(
        q: str = "", file_type: str = "", tag: str = ""
    ) -> list[dict[str, Any]]:
        return service.list_items(query=q, file_type=file_type, tag=tag)

    @app.get("/api/items/{item_id}")
    def get_item(item_id: int) -> dict[str, Any]:
        item = service.get_item(item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")
        return item

    @app.put("/api/items/{item_id}")
    def update_item(item_id: int, payload: ItemUpdate) -> dict[str, Any]:
        item = service.update_item(
            item_id=item_id,
            description=payload.description,
            tags=payload.tags,
            meta=payload.meta,
        )
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")
        return item

    return app
