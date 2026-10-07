"""One authenticated browser entrypoint for anonymous third-party source reading."""
import json
import time
from collections import Counter

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse, FileResponse
from app.services.book_downloads import book_downloads
from starlette.background import BackgroundTask
from pydantic import BaseModel, ConfigDict, Field

from app.services.user_auth import auth_service
from app.services.direct_reading import direct_reading
from app.services.direct_aggregation import aggregate_reading, grouped_books
from app.storage.direct_reading import direct_repository
from app.api import attachment_sources
from app.services.txtnovel_import import txtnovel_import, SOURCE_ID, SOURCE_NAME

router = APIRouter(prefix="/api/direct")
router.include_router(attachment_sources.router)
_active_searches = Counter()


class ProgressRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chapterIndex: int = Field(ge=0, le=1000000)
    position: float = Field(ge=0, le=1, allow_inf_nan=False)
    revision: int = Field(ge=0)


@router.get("/sources")
def sources(request: Request):
    user = auth_service.require_user(request)
    items = direct_reading.sources()
    if txtnovel_import.status(user.user_id)["bound"]:
        items.append({"id": SOURCE_ID, "name": SOURCE_NAME, "attachmentSource": True})
    return {"items": items}


@router.get("/search")
async def search(request: Request, keyword: str = Query(min_length=1, max_length=100), sources: str = Query(max_length=3000), page: int = Query(default=1, ge=1, le=100)):
    user = auth_service.require_user(request)
    if not keyword.strip():
        raise HTTPException(400, "请输入书名或作者")
    source_ids = list(dict.fromkeys(filter(None, sources.split(","))))
    if not source_ids or len(source_ids) > 64:
        raise HTTPException(400, "请选择 1 至 64 个书源")
    for source_id in source_ids:
        if source_id == SOURCE_ID:
            txtnovel_import.session(user.user_id)
        else:
            direct_reading.plugin(source_id)
    if _active_searches[user.user_id] >= 2:
        raise HTTPException(429, "请先停止已有搜索")
    _active_searches[user.user_id] += 1
    released = False
    def release():
        nonlocal released
        if not released:
            released = True
            _active_searches[user.user_id] -= 1
            if not _active_searches[user.user_id]:
                del _active_searches[user.user_id]
    async def stream():
        items = []
        try:
            async for result in direct_reading.search(keyword.strip(), [s for s in source_ids if s != SOURCE_ID], page):
                items.extend(result["items"])
                result["groups"] = grouped_books(items, keyword.strip())
                yield "data: " + json.dumps(result, ensure_ascii=False) + "\n\n"
            if SOURCE_ID in source_ids:
                started = time.monotonic()
                try:
                    async with attachment_sources.one_operation(user.user_id):
                        attachments = await txtnovel_import.search(user.user_id, keyword.strip(), page)
                    result = {"sourceId": SOURCE_ID, "items": attachments,
                              "groups": [*grouped_books(items, keyword.strip()), *attachments]}
                except Exception as exc:
                    result = {"sourceId": SOURCE_ID, "items": [], "error": {"message": str(getattr(exc, "detail", "书香门第搜索暂时不可用"))}}
                result["latencyMs"] = round((time.monotonic()-started)*1000)
                yield "data: " + json.dumps(result, ensure_ascii=False) + "\n\n"
            yield 'event: done\ndata: {}\n\n'
        finally:
            release()
    return StreamingResponse(stream(), media_type="text/event-stream", background=BackgroundTask(release), headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@router.get("/books/{book_id}/detail")
async def detail(book_id: str, request: Request):
    user = auth_service.require_user(request)
    return book_downloads.cached(user.user_id, book_id, "detail.json") or await aggregate_reading.for_user(user.user_id).detail(book_id)


@router.get("/books/{book_id}/toc")
async def toc(book_id: str, request: Request):
    user = auth_service.require_user(request)
    result = book_downloads.cached(user.user_id, book_id, "toc.json") or await aggregate_reading.for_user(user.user_id).toc(book_id)
    return {"bookId": book_id, "chapters": [{"index": c["index"], "title": c["title"]} for c in result["chapters"]]}


@router.get("/books/{book_id}/overview")
async def overview(book_id: str, request: Request, page: int = Query(default=1, ge=1),
                   pageSize: int = Query(default=50, ge=1, le=100), keyword: str = Query(default="", max_length=100),
                   status: str = Query(default="all", pattern="^(all|downloaded|cached|on_demand|failed)$")):
    user = auth_service.require_user(request)
    book = direct_repository.get(user.user_id, book_id)
    if not book:
        raise HTTPException(404, "书籍不在你的书库中")
    snapshot = book_downloads.cached(user.user_id, book_id, "toc.json")
    toc = snapshot or await aggregate_reading.for_user(user.user_id).toc(book_id, allow_empty=True)
    # Legacy upgrade may enrich shelf metadata while loading the directory.
    book = direct_repository.get(user.user_id, book_id) or book
    summaries = direct_repository.chapter_summaries(user.user_id, book_id)
    directory = book_downloads.directory(user.user_id, book_id)
    # Filenames suffice for download status. Never deserialize the entire book.
    files = {p.name for p in directory.glob("chapter-*.json")} if snapshot else set()
    job = direct_repository.download(user.user_id, book_id)
    counts = {"downloaded": 0, "cached": 0, "on_demand": 0, "failed": 0}
    rows = []
    for chapter in toc["chapters"]:
        index = chapter["index"]
        cached = summaries.get(index)
        cached = cached if cached and cached["title"] == chapter["title"] else None
        audit = cached.get("aggregation") if cached else None
        state = "downloaded" if f"chapter-{index}.json" in files else "cached" if cached else "on_demand"
        if state == "on_demand" and job and job["state"] == "failed" and index == job["completed"]:
            state = "failed"
        counts[state] += 1
        if keyword.casefold() not in chapter["title"].casefold() or (status != "all" and state != status):
            continue
        rows.append({"index": index, "title": chapter["title"], "status": state,
                     "selectedSourceName": audit.get("selectedSourceName") if audit else None,
                     "aggregation": audit, "error": job["error"] if state == "failed" else None})
    catalog = toc
    if snapshot and not snapshot.get("sources"):
        # Enrich old downloaded books without replacing their frozen chapter axis.
        try:
            catalog = await aggregate_reading.for_user(user.user_id).toc(book_id, allow_empty=True)
        except HTTPException as exc:
            if exc.status_code != 502:
                raise
    stored_toc, _ = direct_repository.aggregate_toc(user.user_id, book_id)
    sources = catalog.get("sources") or (stored_toc or {}).get("sources")
    if not sources:
        sources = [{"sourceId": s["sourceId"], "sourceName": s["sourceName"], "status": "unknown",
                    "chapterCount": None, "lastChapter": "", "latencyMs": None}
                   for s in book.get("sources") or [book]]
    start = (page-1)*pageSize
    return {"book": book, "sources": sources, "checkedAt": catalog.get("checkedAt"),
            "progress": direct_repository.progress(user.user_id, book_id), "download": job,
            "chapterCount": len(toc["chapters"]), "counts": counts, "total": len(rows),
            "chapters": rows[start:start+pageSize], "page": page, "pageSize": pageSize}


@router.get("/books/{book_id}/chapters/{index}")
async def chapter(book_id: str, index: int, request: Request):
    user = auth_service.require_user(request)
    result = book_downloads.cached(user.user_id, book_id, f"chapter-{index}.json")
    if result:
        return {k: v for k, v in result.items() if k != "url"}
    snapshot = book_downloads.cached(user.user_id, book_id, "toc.json")
    if snapshot:
        if not 0 <= index < len(snapshot["chapters"]):
            raise HTTPException(404, "章节不存在")
        return await aggregate_reading.for_user(user.user_id).chapter_at(book_id, snapshot["chapters"][index])
    return await aggregate_reading.for_user(user.user_id).chapter(book_id, index)


@router.get("/shelf")
def shelf(request: Request):
    user = auth_service.require_user(request)
    return {"items": direct_repository.shelf(user.user_id)}


class AggregateAddRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sourceBookIds: list[str] = Field(min_length=1, max_length=64)
    expectedBookId: str | None = Field(default=None, pattern=r"^agg-[a-f0-9]{32}$")


@router.post("/shelf")
async def add_aggregate(payload: AggregateAddRequest, request: Request):
    user = auth_service.require_user(request)
    return await aggregate_reading.add(user.user_id, payload.sourceBookIds, expected_identity=payload.expectedBookId)


@router.put("/shelf/{book_id}")
async def save(book_id: str, request: Request):
    user = auth_service.require_user(request)
    return direct_repository.save(user.user_id, await aggregate_reading.for_user(user.user_id).detail(book_id))


@router.delete("/shelf/{book_id}")
async def remove(book_id: str, request: Request):
    user = auth_service.require_user(request)
    book_downloads.remove(user.user_id, book_id)
    return {"ok": True}


@router.get("/books/{book_id}/progress")
def progress(book_id: str, request: Request):
    user = auth_service.require_user(request)
    aggregate_reading.for_user(user.user_id).book_target(book_id)
    return direct_repository.progress(user.user_id, book_id)


@router.put("/books/{book_id}/progress")
async def update_progress(book_id: str, payload: ProgressRequest, request: Request):
    user = auth_service.require_user(request)
    toc = book_downloads.cached(user.user_id, book_id, "toc.json") or await aggregate_reading.for_user(user.user_id).toc(book_id)
    if payload.chapterIndex >= len(toc["chapters"]):
        raise HTTPException(400, "章节超出目录范围")
    return direct_repository.update_progress(user.user_id, book_id, payload.chapterIndex, payload.position, payload.revision)


@router.get("/downloads")
def downloads(request: Request):
    user = auth_service.require_user(request)
    return {"items": direct_repository.downloads(user.user_id)}


@router.post("/books/{book_id}/download")
async def start_download(book_id: str, request: Request):
    user = auth_service.require_user(request)
    return book_downloads.enqueue(user.user_id, book_id)


@router.delete("/books/{book_id}/download")
async def pause_download(book_id: str, request: Request):
    user = auth_service.require_user(request)
    return await book_downloads.cancel(user.user_id, book_id)


@router.get("/books/{book_id}/download/file")
def download_file(book_id: str, request: Request):
    user = auth_service.require_user(request)
    path = book_downloads.file(user.user_id, book_id)
    book = direct_repository.get(user.user_id, book_id)
    return FileResponse(path, media_type="text/plain; charset=utf-8", filename=book["name"][:100] + ".txt")
