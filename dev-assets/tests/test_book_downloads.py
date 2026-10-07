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


async def enable_native(reader, scheduler, *, missing=(), damage=None):
    scheduler._plugins['fixture'].capabilities.append('full_book')
    calls = []
    async def full_book(source_id, url, chapters, *, name):
        calls.append(url)
        if damage == 'network':
            raise TimeoutError()
        result = [{**c, 'content': 'Native body ' + str(i)} for i, c in enumerate(chapters) if i not in missing]
        if damage == 'url':
            result[-1]['chapterUrl'] = 'https://books.example/other/0'
        if damage == 'title':
            result[-1]['title'] = 'Wrong book chapter'
        if damage == 'paid':
            result[-1]['isPaid'] = True
        if damage == 'duplicate':
            result[-1] = result[0]
        if damage == 'oversize':
            result[-1]['content'] = 'x' * (2 * 1024 * 1024 + 1)
        return result
    scheduler.full_book = full_book
    return calls


async def test_native_download_reuses_txt_only_fills_missing_and_is_private(app_env, tmp_path):
    _, _, reader, repo, scheduler, a, b = app_env
    uid = a['userId']
    repo.save(uid, await reader.detail(BOOK))
    calls = await enable_native(reader, scheduler, missing=(1,))
    service = BookDownloadService(reader, repo, tmp_path / 'cache')
    service.enqueue(uid, BOOK)
    await service.run(uid, BOOK)
    assert repo.download(uid, BOOK)['state'] == 'completed'
    assert len(calls) == 1
    assert scheduler.chapter_calls == ['https://books.example/book/1/1']
    assert 'Native body 0' in service.file(uid, BOOK).read_text()
    assert service.cached(b['userId'], BOOK, 'chapter-0.json') is None
    await service.run(uid, BOOK)
    assert len(calls) == 1  # completed/resumed cache causes no new native download


@pytest.mark.parametrize('damage', ['network', 'url', 'title', 'paid', 'duplicate', 'oversize'])
async def test_invalid_native_result_falls_back_without_partial_cache(app_env, tmp_path, damage):
    _, _, reader, repo, scheduler, a, _ = app_env
    uid = a['userId']
    repo.save(uid, await reader.detail(BOOK))
    await enable_native(reader, scheduler, damage=damage)
    service = BookDownloadService(reader, repo, tmp_path / 'cache')
    service.enqueue(uid, BOOK)
    await service.run(uid, BOOK)
    assert repo.download(uid, BOOK)['state'] == 'completed'
    assert len(scheduler.chapter_calls) == 3
    assert 'Native body' not in service.file(uid, BOOK).read_text()


async def test_pause_cancels_native_operation_then_resume(app_env, tmp_path):
    _, _, reader, repo, scheduler, a, _ = app_env
    uid = a['userId']
    repo.save(uid, await reader.detail(BOOK))
    await enable_native(reader, scheduler)
    started, cancelled = asyncio.Event(), asyncio.Event()
    original = scheduler.full_book
    async def blocked(*args, **kwargs):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
    scheduler.full_book = blocked
    service = BookDownloadService(reader, repo, tmp_path / 'cache')
    await service.start()
    try:
        service.enqueue(uid, BOOK)
        await asyncio.wait_for(started.wait(), 2)
        await service.cancel(uid, BOOK)
        assert cancelled.is_set()
        assert repo.download(uid, BOOK)['state'] == 'paused'
        scheduler.full_book = original
        service.enqueue(uid, BOOK)
        await wait_for_state(repo, uid, 'completed')
        assert scheduler.chapter_calls == []
    finally:
        await service.stop()


async def test_aggregate_native_matches_origin_url_and_title_not_position(app_env):
    from app.services.direct_aggregation import AggregateReadingService
    _, _, reader, repo, scheduler, a, b = app_env
    await enable_native(reader, scheduler)
    aggregation = AggregateReadingService(reader, repo)
    book = await aggregation.add(a['userId'], [BOOK])
    personal = aggregation.for_user(a['userId'])
    toc = await personal.toc(book['bookId'])
    toc['chapters'][0]['index'] = 7
    toc['chapters'][1]['title'] = 'Different edition'
    toc['chapters'][2]['originBookId'] = 'another-book'
    result = await personal.full_book(book['bookId'], toc)
    assert len(result) == 1
    assert result[toc['chapters'][0]['url']]['index'] == 7
    with pytest.raises(HTTPException):
        await aggregation.for_user(b['userId']).full_book(book['bookId'], toc)


async def test_native_legacy_book_requires_personal_shelf_ownership_before_network(app_env):
    from app.services.direct_aggregation import AggregateReadingService
    _, _, reader, repo, scheduler, a, b = app_env
    calls = await enable_native(reader, scheduler)
    repo.save(a['userId'], await reader.detail(BOOK))
    toc = await reader.toc(BOOK)
    with pytest.raises(HTTPException) as error:
        await AggregateReadingService(reader, repo).for_user(b['userId']).full_book(BOOK, toc)
    assert error.value.status_code == 404
    assert calls == []


async def test_native_text_is_all_saved_before_slow_missing_chapter_and_survives_pause(app_env, tmp_path):
    _, _, reader, repo, scheduler, a, _ = app_env
    uid = a['userId']
    repo.save(uid, await reader.detail(BOOK))
    calls = await enable_native(reader, scheduler, missing=(0,))
    started, release = asyncio.Event(), asyncio.Event()
    original = scheduler.chapter
    async def chapter(source, url):
        started.set()
        await release.wait()
        return await original(source, url)
    scheduler.chapter = chapter
    service = BookDownloadService(reader, repo, tmp_path / 'cache')
    await service.start()
    try:
        service.enqueue(uid, BOOK)
        await asyncio.wait_for(started.wait(), 2)
        assert repo.download(uid, BOOK)['completed'] == 2
        for index in (1, 2):
            assert service.cached(uid, BOOK, f'chapter-{index}.json')['content'] == f'Native body {index}'
        assert service.cached(uid, BOOK, 'chapter-0.json') is None
        await service.cancel(uid, BOOK)
        assert repo.download(uid, BOOK)['state'] == 'paused'
        assert repo.download(uid, BOOK)['completed'] == 2
        # Pause leaves all native text reusable. On resume only the missing
        # chapter needs HTML; its eventual TXT export stays in TOC order.
        release.set()
        service.enqueue(uid, BOOK)
        await wait_for_state(repo, uid, 'completed')
        assert scheduler.chapter_calls == ['https://books.example/book/1/0']
        text = service.file(uid, BOOK).read_text()
        assert text.index('Paragraph') < text.index('Native body 1') < text.index('Native body 2')
    finally:
        await service.stop()
