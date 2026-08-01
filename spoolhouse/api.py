from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .service import SpoolHouseService


class ConfigUpdate(BaseModel):
    root_path: str = ""
    # Optional: when present, replaces the list of folder-name patterns whose
    # leaf is treated as transparent during group derivation. Absent means
    # leave the existing setting alone. Patterns are plain (exact, case-
    # insensitive), ``glob:<pat>``, or ``re:<pat>``.
    dirs_to_ignore_when_group: list[str] | None = None


class ItemUpdate(BaseModel):
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)
    # Optional override; presence is detected via model_fields_set so callers
    # can distinguish "leave as-is" from "explicit None / empty string".
    group_override: str | None = None


class TagRenameUpdate(BaseModel):
    name: str = ""


class TagBulkUpdate(BaseModel):
    item_ids: list[int] = Field(default_factory=list)
    add_tags: list[str] = Field(default_factory=list)
    remove_tags: list[str] = Field(default_factory=list)


class GroupRenameUpdate(BaseModel):
    group_path: str = ""
    display_name: str | None = None


class GroupBulkAssignUpdate(BaseModel):
    item_ids: list[int] = Field(default_factory=list)
    group_override: str | None = None


def create_app(service: SpoolHouseService, static_dir: Path) -> FastAPI:
    static_dir = Path(static_dir)
    static_dir.mkdir(parents=True, exist_ok=True)
    service.preview_dir.mkdir(parents=True, exist_ok=True)

    app = FastAPI(title="SpoolHouse", docs_url="/api/docs", redoc_url=None)
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
        service.set_root_path(payload.root_path)
        if (
            "dirs_to_ignore_when_group" in payload.model_fields_set
            and payload.dirs_to_ignore_when_group is not None
        ):
            service.set_dirs_to_ignore_when_group(payload.dirs_to_ignore_when_group)
        return service.get_config()

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

    @app.post("/api/scan/pause")
    def pause_scan_route() -> dict[str, Any]:
        return service.pause_scan()

    @app.post("/api/scan/resume")
    def resume_scan_route() -> dict[str, Any]:
        return service.resume_scan()

    @app.get("/api/items")
    def list_items(
        q: str = "",
        file_type: str = "",
        tag: str = "",
        sort: str = "date_added_desc",
        group: str | None = None,
    ) -> list[dict[str, Any]]:
        return service.list_items(
            query=q, file_type=file_type, tag=tag, sort=sort, group=group
        )

    @app.get("/api/groups")
    def list_groups() -> list[dict[str, Any]]:
        return service.list_groups()

    @app.patch("/api/groups")
    def rename_group(payload: GroupRenameUpdate) -> dict[str, Any]:
        if payload.display_name is None or not payload.display_name.strip():
            return service.reset_group_display(payload.group_path)
        try:
            return service.rename_group(
                group_path=payload.group_path, display_name=payload.display_name
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/items/bulk-group")
    def bulk_assign_group(payload: GroupBulkAssignUpdate) -> dict[str, Any]:
        return service.bulk_assign_group(
            item_ids=payload.item_ids, group_override=payload.group_override
        )

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
        kwargs: dict[str, Any] = {
            "item_id": item_id,
            "description": payload.description,
            "tags": payload.tags,
            "meta": payload.meta,
        }
        if "group_override" in payload.model_fields_set:
            kwargs["group_override"] = payload.group_override
        item = service.update_item(**kwargs)
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")
        return item

    return app
