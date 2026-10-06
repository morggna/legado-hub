import asyncio

import pytest
from fastapi import HTTPException

from app.services.book_downloads import BookDownloadService
from test_direct_reading import app_env, BOOK


async def wait_for_state(repo, uid, state):
    async def poll():
        while repo.download(uid, BOOK)["state"] != state:
            await asyncio.sleep(.01)
    await asyncio.wait_for(poll(), timeout=3)


async def test_add_is_metadata_only_download_is_explicit_and_offline_is_private(app_env, tmp_path):
    _, _, reader, repo, scheduler, a, b = app_env
    await reader.detail(BOOK)
    repo.save(a["userId"], await reader.detail(BOOK))
    assert scheduler.chapter_calls == []
    service = BookDownloadService(reader, repo, tmp_path / "cache")
    with pytest.raises(HTTPException):
        service.enqueue(b["userId"], BOOK)
    await service.start()
    try:
        service.enqueue(a["userId"], BOOK)
        await wait_for_state(repo, a["userId"], "completed")
        assert len(scheduler.chapter_calls) == 3
        assert "Paragraph" in service.file(a["userId"], BOOK).read_text()
        assert service.cached(b["userId"], BOOK, "chapter-0.json") is None
        assert service.cached(a["userId"], BOOK, "chapter-1.json")["content"]
        with pytest.raises(HTTPException):
            service.file(b["userId"], BOOK)
        # Recreating the download service does not fetch completed chapters again.
        reopened = BookDownloadService(reader, repo, tmp_path / "cache")
        assert reopened.cached(a["userId"], BOOK, "chapter-0.json")["content"]
        service.enqueue(a["userId"], BOOK)
        assert len(scheduler.chapter_calls) == 3
    finally:
        await service.stop()


async def test_pause_resume_reuses_completed_chapters_and_remove_deletes_files(app_env, tmp_path):
    _, _, reader, repo, scheduler, a, _ = app_env
    uid = a["userId"]
    repo.save(uid, await reader.detail(BOOK))
    service = BookDownloadService(reader, repo, tmp_path / "cache")
    original = scheduler.chapter
    second_started = asyncio.Event()
    block = asyncio.Event()
    async def chapter(source, url):
        if url.endswith("/1"):
            second_started.set()
            await block.wait()
        return await original(source, url)
    scheduler.chapter = chapter
    await service.start()
    try:
        service.enqueue(uid, BOOK)
        await second_started.wait()
        assert repo.download(uid, BOOK)["completed"] == 1
        with pytest.raises(HTTPException):
            service.remove(uid, BOOK)
        await service.cancel(uid, BOOK)
        assert repo.download(uid, BOOK)["state"] == "paused"
        block.set()
        service.enqueue(uid, BOOK)
        await wait_for_state(repo, uid, "completed")
        assert scheduler.chapter_calls.count("https://books.example/book/1/0") == 1
        service.remove(uid, BOOK)
        assert repo.get(uid, BOOK) is None
        assert not service.directory(uid, BOOK).exists()
    finally:
        await service.stop()


async def test_worker_restart_recovers_interrupted_jobs(app_env, tmp_path):
    _, _, reader, repo, scheduler, a, _ = app_env
    uid = a["userId"]
    repo.save(uid, await reader.detail(BOOK))
    repo.queue_download(uid, BOOK)
    repo.set_download(uid, BOOK, "running")
    service = BookDownloadService(reader, repo, tmp_path / "cache")
    await service.start()
    try:
        await wait_for_state(repo, uid, "completed")
        assert len(scheduler.chapter_calls) == 3
    finally:
        await service.stop()
