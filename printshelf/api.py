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


class TagRenameUpdate(BaseModel):
    name: str = ""


class TagBulkUpdate(BaseModel):
    item_ids: list[int] = Field(default_factory=list)
    add_tags: list[str] = Field(default_factory=list)
    remove_tags: list[str] = Field(default_factory=list)


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

    @app.post("/api/scan/cancel")
    def cancel_scan_route() -> dict[str, Any]:
        return service.cancel_scan()

    @app.get("/api/items")
    def list_items(
        q: str = "", file_type: str = "", tag: str = "", sort: str = "date_added_desc"
    ) -> list[dict[str, Any]]:
        return service.list_items(query=q, file_type=file_type, tag=tag, sort=sort)

    @app.get("/api/tags")
    def list_tags(q: str = "") -> list[dict[str, Any]]:
        return service.list_tags(query=q)

    @app.post("/api/tags/bulk-update")
    def bulk_update_tags(payload: TagBulkUpdate) -> dict[str, Any]:
        return service.bulk_update_tags(
            item_ids=payload.item_ids,
            add_tags=payload.add_tags,
            remove_tags=payload.remove_tags,
        )

    @app.patch("/api/tags/{tag_id}")
    def rename_tag(tag_id: int, payload: TagRenameUpdate) -> dict[str, Any]:
        try:
            updated = service.rename_tag(tag_id=tag_id, name=payload.name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not updated:
            raise HTTPException(status_code=404, detail="Tag not found")
        return updated

    @app.delete("/api/tags/{tag_id}")
    def delete_tag(tag_id: int) -> dict[str, Any]:
        deleted = service.delete_tag(tag_id=tag_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Tag not found")
        return {"deleted": True}

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
