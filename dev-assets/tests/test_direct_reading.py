import asyncio
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from app.api import auth, direct
from app.services.direct_reading import DirectReadingService
from app.services.direct_aggregation import AggregateReadingService
from app.services.user_auth import UserAuthService
from app.source_plugins.id_codec import encode_book_id
from app.storage.db import initialize_database
from app.storage.direct_reading import DirectReadingRepository
from app.services.book_downloads import BookDownloadService

BOOK = encode_book_id("fixture", "https://books.example/book/1")


class FakeScheduler:
    def __init__(self):
        meta = SimpleNamespace(id="fixture", name="Fixture", enabled=True, domains=["books.example"], base_urls=[], auth={"mode": "none"}, content={"access": "free"}, is_official_source=lambda: False)
        self._plugins = {"fixture": SimpleNamespace(metadata=meta, capabilities=["search", "detail", "toc", "chapter"])}
        self.chapter_calls = []
        self.cancelled = False

    async def detail(self, source_id, url):
        return {"data": {"name": "Test book", "author": "Author", "tocUrl": url}, "debug": {}}

    async def toc(self, source_id, url):
        return {"chapters": [{"title": f"Chapter {i}", "rawChapterUrl": f"https://books.example/book/1/{i}"} for i in range(3)]}

    async def chapter(self, source_id, url):
        self.chapter_calls.append(url)
        return {"title": "Title", "content": "Paragraph\nAnother paragraph"}

    async def search_one(self, source_id, keyword, page):
        return {"items": [{"bookUrl": "https://books.example/book/1", "name": "Test book"}, {"bookUrl": "http://127.0.0.1/private", "name": "Invalid"}]}


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    db = tmp_path / "app.db"
    initialize_database(db)
    service = UserAuthService(db)
    service.bootstrap_admin("admin", "admin-pass-123")
    a = service.create_user("readerA", "reader-pass-123")
    b = service.create_user("readerB", "reader-pass-123")
    fake = FakeScheduler()
    reader = DirectReadingService(fake)
    repo = DirectReadingRepository(db)
    monkeypatch.setattr(direct, "auth_service", service)
    monkeypatch.setattr(auth, "auth_service", service)
    monkeypatch.setattr(direct, "direct_reading", reader)
    monkeypatch.setattr(direct, "direct_repository", repo)
    aggregation = AggregateReadingService(reader, repo)
    monkeypatch.setattr(direct, "aggregate_reading", aggregation)
    monkeypatch.setattr("app.services.book_downloads.aggregate_reading", aggregation)
    monkeypatch.setattr(direct, "book_downloads", BookDownloadService(None, repo, tmp_path / "books"))
    app = FastAPI()
    app.state.entrypoint = "combined"
    app.include_router(auth.router)
    app.include_router(direct.router)
    return app, service, reader, repo, fake, a, b


async def client(app, username=None):
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")
    if username:
        async with c:
            r = await c.post("/api/auth/login", json={"username": username, "password": "reader-pass-123"})
            assert r.status_code == 200, r.text
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver", cookies=c.cookies)
    return c


@pytest.mark.parametrize("path", ["/sources", "/search?keyword=test&sources=fixture", f"/books/{BOOK}/detail", f"/books/{BOOK}/toc", f"/books/{BOOK}/chapters/0", "/shelf", f"/books/{BOOK}/progress"])
async def test_anonymous_denied(app_env, path):
    c = await client(app_env[0])
    async with c:
        assert (await c.get("/api/direct" + path)).status_code == 401


async def test_combined_password_login_and_admin_boundary(app_env):
    app, service, *_ = app_env
    c = await client(app, "readerA")
    async with c:
        r = await c.get("/api/auth/me")
        assert r.json()["user"]["role"] == "user"
        from starlette.requests import Request
        request = Request({"type": "http", "headers": [(b"cookie", f"legadohub_session={c.cookies.get('legadohub_session')}".encode())]})
        with pytest.raises(HTTPException) as error:
            service.require_admin(request)
        assert error.value.status_code == 403
    app.state.entrypoint = "admin"
    c = await client(app)
    async with c:
        assert (await c.post("/api/auth/login", json={"username": "readerA", "password": "reader-pass-123"})).status_code == 401


async def test_personal_shelf_progress_persistence_and_stale_writes(app_env):
    app, _, _, repo, fake, a, b = app_env
    ca, cb = await client(app, "readerA"), await client(app, "readerB")
    async with ca, cb:
        assert (await ca.put(f"/api/direct/shelf/{BOOK}")).status_code == 200
        assert len((await ca.get("/api/direct/shelf")).json()["items"]) == 1
        assert (await cb.get("/api/direct/shelf")).json()["items"] == []
        payload = {"chapterIndex": 1, "position": .5, "revision": 0}
        r = await ca.put(f"/api/direct/books/{BOOK}/progress", json=payload)
        assert r.json()["revision"] == 1
        assert (await cb.get(f"/api/direct/books/{BOOK}/progress")).json()["revision"] == 0
        assert (await ca.put(f"/api/direct/books/{BOOK}/progress", json=payload)).status_code == 409
        payload["user_id"] = b["userId"]
        assert (await ca.put(f"/api/direct/books/{BOOK}/progress", json=payload)).status_code == 422
        assert not fake.chapter_calls  # Metadata/progress did not fetch any body.
        reopened = DirectReadingRepository(repo.db_path)
        assert reopened.progress(a["userId"], BOOK)["position"] == .5
        await cb.delete(f"/api/direct/shelf/{BOOK}")
        assert len(repo.shelf(a["userId"])) == 1


async def test_only_requested_chapter_is_fetched(app_env):
    reader, fake = app_env[2], app_env[4]
    result = await reader.chapter(BOOK, 1)
    assert result["content"]
    assert fake.chapter_calls == ["https://books.example/book/1/1"]
    with pytest.raises(HTTPException):
        await reader.chapter(BOOK, 99)


@pytest.mark.parametrize("url", ["http://127.0.0.1/", "https://evil.example/", "https://books.example.evil.org/", "https://user:pass@books.example/", "https://books.example:222/", "file:///etc/passwd"])
def test_source_url_boundary(app_env, url):
    with pytest.raises(HTTPException):
        app_env[2].book_target(encode_book_id("fixture", url))


async def test_search_filters_invalid_addresses(app_env):
    results = [r async for r in app_env[2].search("test", ["fixture"])]
    assert len(results[0]["items"]) == 1


async def test_search_cancellation_closes_source_tasks(app_env):
    fake = app_env[4]
    started = asyncio.Event()
    async def slow(*args):
        started.set()
        try:
            await asyncio.sleep(30)
        finally:
            fake.cancelled = True
    fake.search_one = slow
    async def consume():
        async for _ in app_env[2].search("test", ["fixture"]):
            pass
    task = asyncio.create_task(consume())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert fake.cancelled


def test_paid_and_official_sources_not_exposed(app_env):
    reader, fake = app_env[2], app_env[4]
    fake._plugins["fixture"].metadata.content["access"] = "paid"
    assert reader.sources() == []
    with pytest.raises(HTTPException):
        reader.plugin("fixture")


@pytest.mark.parametrize("method,path,payload", [
    ("PUT", f"/shelf/{BOOK}", None),
    ("DELETE", f"/shelf/{BOOK}", None),
    ("PUT", f"/books/{BOOK}/progress", {"chapterIndex": 0, "position": 0, "revision": 0}),
])
async def test_anonymous_writes_denied(app_env, method, path, payload):
    c = await client(app_env[0])
    async with c:
        assert (await c.request(method, "/api/direct" + path, json=payload)).status_code == 401


async def test_stream_completes_and_releases_user_slot(app_env):
    c = await client(app_env[0], "readerA")
    async with c:
        for _ in range(3):
            result = await c.get("/api/direct/search?keyword=test&sources=fixture")
            assert result.status_code == 200
            assert 'event: done' in result.text
        assert not direct._active_searches


async def test_cached_toc_does_not_deadlock_at_global_concurrency(app_env):
    # Eight distinct TOCs concurrently must not each hold a slot while waiting
    # for a detail operation that needs another slot from the same semaphore.
    reader = app_env[2]
    ids = [encode_book_id("fixture", f"https://books.example/book/{i}") for i in range(8)]
    results = await asyncio.wait_for(asyncio.gather(*(reader.toc(i) for i in ids)), timeout=2)
    assert all(len(r["chapters"]) == 3 for r in results)


async def test_read_during_download_uses_frozen_toc_for_uncached_chapter(app_env):
    app, _, reader, repo, scheduler, a, _ = app_env
    uid = a["userId"]
    repo.save(uid, await reader.detail(BOOK))
    directory = direct.book_downloads.directory(uid, BOOK)
    directory.mkdir(parents=True)
    direct.book_downloads.write_json(directory / "toc.json", {"chapters": [{"index": 0, "title": "Frozen", "url": "https://books.example/frozen/0"}]})
    async def frozen_chapter(source, url):
        scheduler.chapter_calls.append(url)
        return {"title": "Frozen", "content": "Original frozen chapter body. " * 10}
    scheduler.chapter = frozen_chapter
    c = await client(app, "readerA")
    async with c:
        assert (await c.get(f"/api/direct/books/{BOOK}/chapters/0")).status_code == 200
    assert scheduler.chapter_calls == ["https://books.example/frozen/0"]


async def test_aggregate_shelf_api_and_personal_ownership(app_env):
    app, _, _, _, _, _, _ = app_env
    a, b = await client(app, 'readerA'), await client(app, 'readerB')
    async with a, b:
        response = await a.post('/api/direct/shelf', json={'sourceBookIds':[BOOK]})
        assert response.status_code == 200, response.text
        book = response.json()
        assert book['sourceCount'] == 1 and book['bookId'].startswith('agg-')
        assert (await a.get(f"/api/direct/books/{book['bookId']}/toc")).status_code == 200
        for route in ['detail','toc','progress','chapters/0']:
            assert (await b.get(f"/api/direct/books/{book['bookId']}/{route}")).status_code == 404
        assert (await b.post(f"/api/direct/books/{book['bookId']}/download")).status_code == 404
