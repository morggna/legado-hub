"""Stage 1 bootstrap, update-check, and shared-file truth tests."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.services.aggregate_processor import AggregateProcessor
from app.services.library_books import LibraryBooksService
from app.services.shared_book_storage import SharedBookStorage
from app.source_plugins.id_codec import encode_chapter_id
from app.storage.db import initialize_database


@pytest.fixture(autouse=True)
def isolate_source_discovery_network(monkeypatch):
    # Storage/bootstrap fixtures use synthetic books and catalogs. Do not search
    # live installed sources for these names. Discovery-specific cases below
    # supply their own scheduler/processor doubles and still exercise discovery.
    monkeypatch.setattr("app.source_plugins.scheduler.PluginScheduler._enabled_plugins", lambda self: [])


# ── helpers ──────────────────────────────────────────────────────────────────


def _setup_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "test.db"
    initialize_database(db_path)

    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "app_config.json"
    workflow = {
        "autoAggregate": True,
        "processAggregateOnRead": True,
        "aggregateCheckIntervalMinutes": 10,
        "purifyMode": "conservative",
        "aiEnabled": False,
        "useSharedBookStorage": True,
        "sharedBookStorageReadMode": "shared",
        "sharedBookStorageDualWrite": True,
        "minReadableChaptersForDiscovery": 2,
    }
    config_data: dict[str, Any] = {"aggregate": {"contentWorkflow": workflow}}
    config_path.write_text(json.dumps(config_data, ensure_ascii=False), encoding="utf-8")

    import app.core.app_config as _app_config_module

    _app_config_module.APP_CONFIG_PATH = config_path
    _app_config_module.AppConfig.reset()
    return db_path


def _insert_book(
    db_path: Path,
    book_id: str,
    *,
    name: str = "测试书",
    author: str = "作者",
    primary_source_id: str = "official_src",
    start_index: int = 1,
    initial_snapshot_last_index: int = 0,
    auto_archive: bool = True,
    book_status: str = "ongoing",
    aggregate_payload: dict[str, Any] | None = None,
) -> None:
    payload = aggregate_payload or {
        "name": name,
        "author": author,
        "primarySourceId": primary_source_id,
        "primarySourceName": "官方源",
        "primaryBookId": f"{primary_source_id}:{book_id}",
        "sources": [
            {
                "bookId": f"{primary_source_id}:{book_id}",
                "sourceId": primary_source_id,
                "sourceName": "官方源",
                "score": 100,
            }
        ],
    }
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO aggregate_book_tasks (
                aggregate_book_id, name, author, primary_book_id, primary_source_id,
                aggregate_payload_json, status, ai_enabled, start_chapter_index,
                initial_snapshot_last_index, auto_archive_on_complete, book_status,
                total_chapters_at_subscribe, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'active', 0, ?, ?, ?, ?, 0,
                      datetime('now'), datetime('now'))
            """,
            (
                book_id,
                name,
                author,
                f"{primary_source_id}:{book_id}",
                primary_source_id,
                json.dumps(payload, ensure_ascii=False),
                start_index,
                initial_snapshot_last_index,
                1 if auto_archive else 0,
                book_status,
            ),
        )
        conn.commit()


def _chapter_rows(db_path: Path, book_id: str) -> list[dict[str, Any]]:
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT chapter_id, chapter_index, title, status, placeholder, preview_only,
                   preview_retry_count, next_retry_time
            FROM aggregate_chapter_tasks
            WHERE aggregate_book_id = ?
            ORDER BY chapter_index ASC
            """,
            (book_id,),
        ).fetchall()
    return [
        {
            "chapterId": row[0],
            "chapterIndex": row[1],
            "title": row[2],
            "status": row[3],
            "placeholder": bool(row[4]),
            "previewOnly": bool(row[5]),
            "previewRetryCount": row[6],
            "nextRetryTime": row[7],
        }
        for row in rows
    ]


def _book_row(db_path: Path, book_id: str) -> dict[str, Any] | None:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT status, search_visibility_status, visible_processed_chapters,
                   total_chapters, processed_chapters, book_status, archived_at
            FROM aggregate_book_tasks
            WHERE aggregate_book_id = ?
            """,
            (book_id,),
        ).fetchone()
    if not row:
        return None
    return {
        "status": row[0],
        "searchVisibilityStatus": row[1],
        "visibleProcessedChapters": row[2],
        "totalChapters": row[3],
        "processedChapters": row[4],
        "bookStatus": row[5],
        "archivedAt": row[6],
    }


class FakeCatalog:
    """Deterministic BookCatalog replacement for Stage 1 tests."""

    def __init__(
        self,
        chapters: list[dict[str, Any]],
        contents: dict[str, str],
        *,
        book_status: str = "ongoing",
        source_word_count: int = 100,
    ):
        self._chapters = chapters
        self._contents = contents
        self._book_status = book_status
        self._source_word_count = source_word_count

    async def book_detail(self, book_id: str) -> dict[str, Any]:
        return {
            "data": {
                "name": "测试书",
                "author": "作者",
                "status": self._book_status,
                "bookStatus": self._book_status,
                "coverUrl": "",
                "intro": "",
                "wordCount": "10000",
            }
        }

    async def toc(self, book_id: str) -> dict[str, Any]:
        return {"chapters": [dict(ch) for ch in self._chapters]}

    async def chapter(self, chapter_id: str) -> dict[str, Any]:
        content = self._contents.get(chapter_id, "")
        result = {
            "content": content,
            "title": "",
            "sourceWordCount": self._source_word_count,
        }
        if len(content) < 200:
            result["extra"] = {"previewOnly": True}
        return result


class EvolvingCatalog(FakeCatalog):
    """Catalog whose TOC grows between calls."""

    def __init__(self, chapter_sequences: list[list[dict[str, Any]]], contents: dict[str, str]):
        self._sequences = chapter_sequences
        self._contents = contents
        self._call_index = 0
        self._source_word_count = 100
        self._book_status = "ongoing"

    async def toc(self, book_id: str) -> dict[str, Any]:
        chapters = self._sequences[min(self._call_index, len(self._sequences) - 1)]
        self._call_index += 1
        return {"chapters": [dict(ch) for ch in chapters]}


class FailingTocCatalog(FakeCatalog):
    """Catalog that fails TOC fetch after a configurable number of successes."""

    def __init__(self, chapters: list[dict[str, Any]], contents: dict[str, str], *, fail_after: int = 0):
        super().__init__(chapters, contents)
        self._fail_after = fail_after
        self._toc_calls = 0

    async def toc(self, book_id: str) -> dict[str, Any]:
        self._toc_calls += 1
        if self._toc_calls > self._fail_after:
            raise TimeoutError("TOC fetch failed")
        return await super().toc(book_id)


class EmptyTocCatalog(FakeCatalog):
    """Catalog that returns an empty chapter list."""

    async def toc(self, book_id: str) -> dict[str, Any]:
        return {"chapters": []}


class MultiSourceCatalog(FakeCatalog):
    """Catalog that serves a separate TOC/content for one candidate source."""

    def __init__(
        self,
        official_chapters: list[dict[str, Any]],
        official_contents: dict[str, str],
        candidate_book_id: str,
        candidate_toc: list[dict[str, Any]],
        candidate_contents: dict[str, str],
    ):
        super().__init__(official_chapters, official_contents)
        self._candidate_book_id = candidate_book_id
        self._candidate_toc = candidate_toc
        self._candidate_contents = candidate_contents

    async def toc(self, book_id: str) -> dict[str, Any]:
        if book_id == self._candidate_book_id:
            return {"chapters": [dict(ch) for ch in self._candidate_toc]}
        return await super().toc(book_id)

    async def chapter(self, chapter_id: str) -> dict[str, Any]:
        if chapter_id in self._candidate_contents:
            result = {
                "content": self._candidate_contents[chapter_id],
                "title": "",
                "sourceWordCount": 100,
            }
            if len(result["content"]) < 200:
                result["extra"] = {"previewOnly": True}
            return result
        return await super().chapter(chapter_id)


PREVIEW_SNIPPET = "少年站在山巅望着远方，风吹动他的衣角，云层在脚下翻滚不止，远处的山脉连绵起伏，像一条沉睡的巨龙。"

# ── tests ────────────────────────────────────────────────────────────────────


def _make_chapters(count: int, prefix: str = "official_src") -> tuple[list[dict[str, Any]], dict[str, str]]:
    chapters = []
    contents: dict[str, str] = {}
    for i in range(1, count + 1):
        ch_url = f"https://{prefix}.example/ch{i}.html"
        ch_id = encode_chapter_id(prefix, ch_url)
        chapters.append({"chapterId": ch_id, "title": f"第{i}章", "index": i})
        contents[ch_id] = f"第{i}章正文" + "这是一个很长的正文段落，" * 50
    return chapters, contents


def test_auto_proxy_retry_passes_configured_url_to_plugin_fetcher():
    from app.source_plugins.scheduler import PluginScheduler

    scheduler = PluginScheduler.__new__(PluginScheduler)
    scheduler.config = {
        "proxy": {
            "enabled": True,
            "url": "http://proxy.example:7890",
            "allowAutoRetry": True,
        }
    }
    plugin = SimpleNamespace(metadata=SimpleNamespace(proxy={"mode": "auto", "required": False}))

    fetcher = scheduler._make_fetcher(plugin)

    assert fetcher.proxy_url == "http://proxy.example:7890"
    assert fetcher.proxy_mode == "auto"


@pytest.mark.asyncio
async def test_official_plugin_calls_share_one_serial_queue():
    from app.source_plugins.scheduler import PluginScheduler

    scheduler = PluginScheduler.__new__(PluginScheduler)
    scheduler._official_source_queue = asyncio.Semaphore(1)
    plugin = SimpleNamespace(
        metadata=SimpleNamespace(is_official_source=lambda: True),
    )
    active = 0
    max_active = 0

    async def operation(value: int) -> int:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.03)
        active -= 1
        return value

    results = await asyncio.gather(*[
        scheduler._call_plugin(plugin, lambda value=value: operation(value), timeout=0.2)
        for value in range(3)
    ])

    assert results == [0, 1, 2]
    assert max_active == 1


@pytest.mark.asyncio
async def test_browser_plugin_calls_share_one_serial_queue():
    from app.source_plugins.scheduler import PluginScheduler

    scheduler = PluginScheduler.__new__(PluginScheduler)
    scheduler._official_source_queue = asyncio.Semaphore(1)
    scheduler._browser_source_queue = asyncio.Semaphore(1)
    plugin = SimpleNamespace(
        metadata=SimpleNamespace(
            is_official_source=lambda: False,
            browser={"mode": "required"},
        ),
    )
    active = 0
    max_active = 0

    async def operation(value: int) -> int:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.03)
        active -= 1
        return value

    results = await asyncio.gather(*[
        scheduler._call_plugin(plugin, lambda value=value: operation(value), timeout=0.2)
        for value in range(3)
    ])

    assert results == [0, 1, 2]
    assert max_active == 1


@pytest.mark.asyncio
async def test_bootstrap_writes_shared_files_until_visible(tmp_path, monkeypatch):
    db_path = _setup_db(tmp_path)
    book_id = "book:bootstrap_visible"
    chapters, contents = _make_chapters(3)
    _insert_book(db_path, book_id)

    processor = AggregateProcessor(db_path)
    monkeypatch.setattr(processor, "_is_official_source", lambda sid: sid == "official_src")
    monkeypatch.setattr(
        "app.services.book_catalog.BookCatalog",
        lambda: FakeCatalog(chapters, contents),
    )

    result = await processor.bootstrap_book_until_visible(book_id)

    assert result["visible"] is True
    book_row = _book_row(db_path, book_id)
    assert book_row["searchVisibilityStatus"] == "visible"
    assert book_row["processedChapters"] == 3

    storage = SharedBookStorage(root=db_path.parent / "library")
    metadata = json.loads(storage.metadata_path(book_name="测试书", author="作者").read_text(encoding="utf-8"))
    assert metadata["bookState"]["processedChapterCount"] == 3
    assert metadata["bookState"]["readableChapterCount"] == 3
    assert metadata["bookState"]["searchVisibilityStatus"] == "visible"

    chapter_index = json.loads(storage.chapter_index_path(book_name="测试书", author="作者").read_text(encoding="utf-8"))
    assert chapter_index["schemaVersion"] == 2
    assert len(chapter_index["chapters"]) == 3
    for entry in chapter_index["chapters"]:
        assert entry["file"] is not None
        assert "isVip" in entry
        assert "officialWordCount" in entry
        assert "sourceId" in entry
        assert "alignedWith" in entry
        ch_path = storage.metadata_path(book_name="测试书", author="作者").parent / entry["file"]
        assert ch_path.exists()
        trace = storage.parse_trace_block(ch_path.read_text(encoding="utf-8"))
        assert trace["schemaVersion"] == 2
        assert trace["previewOnly"] is False
        assert trace["officialWordCount"] == 100
        assert trace["chapterStatus"] in {"readable", "supplemented"}


@pytest.mark.asyncio
async def test_book_task_tolerates_missing_optional_detail(tmp_path, monkeypatch):
    db_path = _setup_db(tmp_path)
    book_id = "book:missing_detail"
    chapters, contents = _make_chapters(1)
    _insert_book(db_path, book_id)

    class MissingDetailCatalog(FakeCatalog):
        async def book_detail(self, book_id: str) -> None:
            return None

    processor = AggregateProcessor(db_path)
    monkeypatch.setattr(processor, "_is_official_source", lambda sid: sid == "official_src")
    monkeypatch.setattr(
        "app.services.book_catalog.BookCatalog",
        lambda: MissingDetailCatalog(chapters, contents),
    )

    result = await processor.run_book_task(book_id)

    assert result["success"] is True
    assert result["processedChapters"] == 1


@pytest.mark.asyncio
async def test_preview_chapter_marked_in_shared_files(tmp_path, monkeypatch):
    db_path = _setup_db(tmp_path)
    book_id = "book:preview_mark"
    chapters, contents = _make_chapters(2)
    contents[chapters[1]["chapterId"]] = "少年站在山巅望着远方。"  # short preview
    _insert_book(db_path, book_id)

    processor = AggregateProcessor(db_path)
    monkeypatch.setattr(processor, "_is_official_source", lambda sid: sid == "official_src")

    async def _fake_ensure(_book_id, payload):
        return payload

    monkeypatch.setattr(
        processor,
        "_ensure_candidate_sources_for_book",
        _fake_ensure,
    )
    monkeypatch.setattr(
        "app.services.book_catalog.BookCatalog",
        lambda: FakeCatalog(chapters, contents),
    )

    await processor.bootstrap_book_until_visible(book_id)

    storage = SharedBookStorage(root=db_path.parent / "library")
    chapter_index = json.loads(storage.chapter_index_path(book_name="测试书", author="作者").read_text(encoding="utf-8"))
    preview_entry = chapter_index["chapters"][1]
    assert preview_entry["status"] == "fetched"

    ch_path = storage.metadata_path(book_name="测试书", author="作者").parent / preview_entry["file"]
    trace = storage.parse_trace_block(ch_path.read_text(encoding="utf-8"))
    assert trace["previewOnly"] is True
    assert trace["chapterStatus"] == "fetched"

    metadata = json.loads(storage.metadata_path(book_name="测试书", author="作者").read_text(encoding="utf-8"))
    assert metadata["bookState"]["previewChapterCount"] == 1
    assert metadata["bookState"]["processedChapterCount"] == 2


@pytest.mark.asyncio
async def test_update_check_discovers_and_processes_new_chapters(tmp_path, monkeypatch):
    db_path = _setup_db(tmp_path)
    book_id = "book:update_check"

    first_chapters, first_contents = _make_chapters(2)
    all_chapters, all_contents = _make_chapters(3)

    _insert_book(db_path, book_id)

    processor = AggregateProcessor(db_path)
    monkeypatch.setattr(processor, "_is_official_source", lambda sid: sid == "official_src")
    evolving_catalog = EvolvingCatalog([first_chapters, all_chapters], all_contents)
    monkeypatch.setattr(
        "app.services.book_catalog.BookCatalog",
        lambda: evolving_catalog,
    )

    first_result = await processor.run_book_task(book_id)
    assert first_result["success"] is True
    assert first_result["processedChapters"] == 2

    second_result = await processor.run_book_task(book_id)
    assert second_result["success"] is True
    assert second_result["processedChapters"] == 1

    storage = SharedBookStorage(root=db_path.parent / "library")
    chapter_index = json.loads(storage.chapter_index_path(book_name="测试书", author="作者").read_text(encoding="utf-8"))
    assert len(chapter_index["chapters"]) == 3
    assert sum(1 for e in chapter_index["chapters"] if e["file"] is not None) == 3

    metadata = json.loads(storage.metadata_path(book_name="测试书", author="作者").read_text(encoding="utf-8"))
    assert metadata["bookState"]["processedChapterCount"] == 3


@pytest.mark.asyncio
async def test_backlog_run_schedules_quick_followup(tmp_path, monkeypatch):
    db_path = _setup_db(tmp_path)
    book_id = "book:backlog_quick_followup"
    chapters, contents = _make_chapters(30)
    _insert_book(db_path, book_id)

    processor = AggregateProcessor(db_path)
    monkeypatch.setattr(processor, "_is_official_source", lambda sid: sid == "official_src")
    monkeypatch.setattr(
        "app.services.book_catalog.BookCatalog",
        lambda: FakeCatalog(chapters, contents),
    )

    result = await processor.run_book_task(book_id, chapter_limit=5)

    assert result["success"] is True
    assert result["processedChapters"] == 5
    assert result["pendingChapters"] == 25
    next_check = datetime.fromisoformat(result["nextCheckTime"])
    expected = datetime.now(timezone.utc) + timedelta(minutes=1)
    assert abs((next_check - expected).total_seconds()) < 5

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT next_check_time, processed_chapters FROM aggregate_book_tasks WHERE aggregate_book_id = ?",
            (book_id,),
        ).fetchone()
    assert datetime.fromisoformat(row[0]) == next_check
    assert row[1] == 5


@pytest.mark.asyncio
async def test_completed_book_auto_archives_shared_task(tmp_path, monkeypatch):
    db_path = _setup_db(tmp_path)
    book_id = "book:completed_archive"
    chapters, contents = _make_chapters(2)
    _insert_book(db_path, book_id, book_status="ongoing", auto_archive=True)

    processor = AggregateProcessor(db_path)
    monkeypatch.setattr(processor, "_is_official_source", lambda sid: sid == "official_src")
    monkeypatch.setattr(
        "app.services.book_catalog.BookCatalog",
        lambda: FakeCatalog(chapters, contents, book_status="completed"),
    )

    await processor.bootstrap_book_until_visible(book_id)

    book_row = _book_row(db_path, book_id)
    assert book_row["status"] == "archived"
    assert book_row["archivedAt"] is not None


@pytest.mark.asyncio
async def test_backfill_placeholder_to_pending(tmp_path, monkeypatch):
    db_path = _setup_db(tmp_path)
    book_id = "book:backfill"
    # Subscriber starts at chapter 3, but the initial snapshot already knows 5 chapters.
    chapters, contents = _make_chapters(5)
    _insert_book(
        db_path,
        book_id,
        start_index=3,
        initial_snapshot_last_index=5,
        book_status="ongoing",
    )

    processor = AggregateProcessor(db_path)
    monkeypatch.setattr(processor, "_is_official_source", lambda sid: sid == "official_src")
    monkeypatch.setattr(
        "app.services.book_catalog.BookCatalog",
        lambda: FakeCatalog(chapters, contents),
    )

    await processor.bootstrap_book_until_visible(book_id)

    rows = _chapter_rows(db_path, book_id)
    placeholder_rows = [r for r in rows if r["placeholder"]]
    assert len(placeholder_rows) == 0

    for r in rows:
        assert r["status"] in {"processed", "fallback"}

    storage = SharedBookStorage(root=db_path.parent / "library")
    chapter_index = json.loads(storage.chapter_index_path(book_name="测试书", author="作者").read_text(encoding="utf-8"))
    assert len(chapter_index["chapters"]) == 5


@pytest.mark.asyncio
async def test_metadata_matches_chapter_index_and_trace(tmp_path, monkeypatch):
    db_path = _setup_db(tmp_path)
    book_id = "book:metadata_consistency"
    chapters, contents = _make_chapters(3)
    contents[chapters[2]["chapterId"]] = "少年站在山巅望着远方。"  # one preview
    _insert_book(db_path, book_id)

    processor = AggregateProcessor(db_path)
    monkeypatch.setattr(processor, "_is_official_source", lambda sid: sid == "official_src")

    async def _fake_ensure(_book_id, payload):
        return payload

    monkeypatch.setattr(
        processor,
        "_ensure_candidate_sources_for_book",
        _fake_ensure,
    )
    monkeypatch.setattr(
        "app.services.book_catalog.BookCatalog",
        lambda: FakeCatalog(chapters, contents),
    )

    await processor.bootstrap_book_until_visible(book_id)

    storage = SharedBookStorage(root=db_path.parent / "library")
    metadata = json.loads(storage.metadata_path(book_name="测试书", author="作者").read_text(encoding="utf-8"))
    chapter_index = json.loads(storage.chapter_index_path(book_name="测试书", author="作者").read_text(encoding="utf-8"))

    index_entries = chapter_index["chapters"]
    file_entries = [e for e in index_entries if e["file"] is not None]
    preview_count_from_trace = 0

    assert metadata["bookState"]["chapterCount"] == len(index_entries)

    for entry in index_entries:
        if entry["file"] is None:
            continue
        ch_path = storage.metadata_path(book_name="测试书", author="作者").parent / entry["file"]
        trace = storage.parse_trace_block(ch_path.read_text(encoding="utf-8"))
        assert trace["chapterIndex"] == entry["index"]
        assert trace["chapterTitle"] == entry["title"]
        assert trace["chapterStatus"] == entry["status"]
        assert trace["officialWordCount"] > 0
        if trace["previewOnly"]:
            preview_count_from_trace += 1

    assert metadata["bookState"]["processedChapterCount"] == len(file_entries)
    assert metadata["bookState"]["previewChapterCount"] == preview_count_from_trace
    assert metadata["bookState"]["readableChapterCount"] == len(file_entries) - preview_count_from_trace


@pytest.mark.asyncio
async def test_chapter_write_preserves_source_map_health(tmp_path, monkeypatch):
    db_path = _setup_db(tmp_path)
    book_id = "book:preserve_sourcemap"
    chapters, contents = _make_chapters(2)
    _insert_book(db_path, book_id)

    processor = AggregateProcessor(db_path)
    storage = SharedBookStorage(root=db_path.parent / "library")
    monkeypatch.setattr(processor, "_shared_book_storage", lambda: storage)
    monkeypatch.setattr(processor, "_is_official_source", lambda sid: sid == "official_src")
    monkeypatch.setattr(
        "app.services.book_catalog.BookCatalog",
        lambda: FakeCatalog(chapters[:1], contents),
    )

    await processor.run_book_task(book_id, chapter_limit=1)

    metadata_path = storage.metadata_path(book_name="测试书", author="作者")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["sourceMap"] = {
        "summary": [
            {
                "sourceId": "third_party_src",
                "sourceName": "第三方源",
                "score": 80,
                "lastChapter": "第2章",
                "chapterCount": 2,
                "bookStatus": "ongoing",
                "author": "作者",
                "name": "测试书",
            }
        ],
        "health": {
            "lastVerifiedAt": "2026-06-30T00:00:00+00:00",
            "status": "healthy",
            "missingCriticalSource": False,
        },
    }
    metadata["sourceMapSummary"] = metadata["sourceMap"]["summary"]
    storage.atomic_write_json(metadata_path, metadata)

    monkeypatch.setattr(
        "app.services.book_catalog.BookCatalog",
        lambda: FakeCatalog(chapters, contents),
    )

    result = await processor.run_book_task(book_id, chapter_limit=1)

    assert result["success"] is True
    refreshed = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert refreshed["sourceMap"]["health"]["status"] == "healthy"
    assert refreshed["sourceMap"]["health"]["lastVerifiedAt"] == "2026-06-30T00:00:00+00:00"
    assert refreshed["sourceMapSummary"] == metadata["sourceMapSummary"]


@pytest.mark.asyncio
async def test_preview_fallback_retries_when_official_releases_full_text(tmp_path, monkeypatch):
    db_path = _setup_db(tmp_path)
    book_id = "book:preview_retry_full"
    chapters, contents = _make_chapters(1)
    contents[chapters[0]["chapterId"]] = "少年站在山巅望着远方。"  # preview
    _insert_book(db_path, book_id)

    processor = AggregateProcessor(db_path)
    monkeypatch.setattr(processor, "_is_official_source", lambda sid: sid == "official_src")

    async def _fake_ensure(_book_id, payload):
        return payload

    monkeypatch.setattr(processor, "_ensure_candidate_sources_for_book", _fake_ensure)
    monkeypatch.setattr(
        "app.services.book_catalog.BookCatalog",
        lambda: FakeCatalog(chapters, contents),
    )

    await processor.bootstrap_book_until_visible(book_id)

    rows = _chapter_rows(db_path, book_id)
    assert rows[0]["status"] == "fallback"
    assert rows[0]["previewOnly"] is True
    assert rows[0]["previewRetryCount"] == 1
    assert rows[0]["nextRetryTime"] is not None
    assert datetime.fromisoformat(rows[0]["nextRetryTime"]) <= datetime.now(timezone.utc)
    with sqlite3.connect(db_path) as conn:
        next_check_time = conn.execute(
            "SELECT next_check_time FROM aggregate_book_tasks WHERE aggregate_book_id = ?",
            (book_id,),
        ).fetchone()[0]
    assert datetime.fromisoformat(next_check_time) <= datetime.now(timezone.utc)

    # Official source now releases the full text.
    contents[chapters[0]["chapterId"]] = f"第1章正文" + "这是一个很长的正文段落，" * 50

    result = await processor.run_book_task(book_id)
    assert result["success"] is True
    assert result["processedChapters"] == 1

    rows = _chapter_rows(db_path, book_id)
    assert rows[0]["status"] == "processed"
    assert rows[0]["previewOnly"] is False
    assert rows[0]["previewRetryCount"] == 0
    assert rows[0]["nextRetryTime"] is None


@pytest.mark.asyncio
async def test_preview_retry_respects_max_retries(tmp_path, monkeypatch):
    db_path = _setup_db(tmp_path)
    book_id = "book:preview_retry_max"
    chapters, contents = _make_chapters(1)
    contents[chapters[0]["chapterId"]] = "少年站在山巅望着远方。"  # stays preview
    _insert_book(db_path, book_id)

    processor = AggregateProcessor(db_path)
    monkeypatch.setattr(processor, "_is_official_source", lambda sid: sid == "official_src")
    monkeypatch.setattr(
        "app.services.aggregate_processor.PREVIEW_RETRY_DELAYS_MINUTES",
        [0, 0, 0],
    )

    async def _fake_ensure(_book_id, payload):
        return payload

    monkeypatch.setattr(processor, "_ensure_candidate_sources_for_book", _fake_ensure)
    monkeypatch.setattr(
        "app.services.book_catalog.BookCatalog",
        lambda: FakeCatalog(chapters, contents, book_status="completed"),
    )

    await processor.bootstrap_book_until_visible(book_id)
    assert _book_row(db_path, book_id)["status"] == "active"
    chapter_id = _chapter_rows(db_path, book_id)[0]["chapterId"]

    for _ in range(3):
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "UPDATE aggregate_chapter_tasks SET next_retry_time = ? WHERE chapter_id = ?",
                ((datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(), chapter_id),
            )
            conn.commit()
        await processor.run_book_task(book_id)

    rows = _chapter_rows(db_path, book_id)
    assert rows[0]["status"] == "fallback"
    assert rows[0]["previewOnly"] is True
    assert rows[0]["previewRetryCount"] == 4
    assert rows[0]["nextRetryTime"] is None
    assert _book_row(db_path, book_id)["status"] == "archived"

    # One more run should not re-select the exhausted preview fallback.
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE aggregate_chapter_tasks SET next_retry_time = ? WHERE chapter_id = ?",
            ((datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(), chapter_id),
        )
        conn.commit()

    result = await processor.run_book_task(book_id)
    assert result["processedChapters"] == 0
    rows = _chapter_rows(db_path, book_id)
    assert rows[0]["previewRetryCount"] == 4


def test_non_preview_fallback_not_retried_as_preview(tmp_path, monkeypatch):
    db_path = _setup_db(tmp_path)
    book_id = "book:non_preview_fallback"
    chapters, _contents = _make_chapters(1)
    _insert_book(db_path, book_id)

    processor = AggregateProcessor(db_path)
    chapter_id = chapters[0]["chapterId"]
    now = datetime.now(timezone.utc)
    past = (now - timedelta(minutes=1)).isoformat()

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO aggregate_chapter_tasks (
                chapter_id, aggregate_book_id, source_chapter_id, chapter_index, title,
                status, placeholder, processed_content, preview_only, next_retry_time
            ) VALUES (?, ?, ?, ?, ?, 'fallback', 0, 'existing content', 0, ?)
            """,
            (chapter_id, book_id, chapter_id, 1, "第1章", past),
        )
        conn.commit()

    # Also insert a due preview-only fallback to confirm the query path is live.
    preview_id = f"{chapter_id}:preview"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO aggregate_chapter_tasks (
                chapter_id, aggregate_book_id, source_chapter_id, chapter_index, title,
                status, placeholder, processed_content, preview_only, next_retry_time
            ) VALUES (?, ?, ?, ?, ?, 'fallback', 0, 'preview content', 1, ?)
            """,
            (preview_id, book_id, preview_id, 2, "第2章", past),
        )
        conn.commit()

    monkeypatch.setattr(processor, "_due_stage3_deferred_chapter_ids", lambda _book_id: [])
    due = processor._chapters_for_processing(book_id, limit=10)
    due_ids = {ch["chapterId"] for ch in due}
    assert chapter_id not in due_ids
    assert preview_id in due_ids


@pytest.mark.asyncio
async def test_toc_fetch_failure_preserves_shared_files(tmp_path, monkeypatch):
    db_path = _setup_db(tmp_path)
    book_id = "book:toc_failure"
    chapters, contents = _make_chapters(3)
    _insert_book(db_path, book_id)

    processor = AggregateProcessor(db_path)
    monkeypatch.setattr(processor, "_is_official_source", lambda sid: sid == "official_src")

    # Bootstrap to visible first.
    monkeypatch.setattr(
        "app.services.book_catalog.BookCatalog",
        lambda: FakeCatalog(chapters, contents),
    )
    await processor.bootstrap_book_until_visible(book_id)

    book_row = _book_row(db_path, book_id)
    assert book_row["searchVisibilityStatus"] == "visible"

    # Now TOC fetch fails.
    failing_catalog = FailingTocCatalog(chapters, contents, fail_after=0)
    monkeypatch.setattr(
        "app.services.book_catalog.BookCatalog",
        lambda: failing_catalog,
    )
    result = await processor.run_book_task(book_id)

    assert result["success"] is False
    assert result.get("tocFetchFailed") is True

    storage = SharedBookStorage(root=db_path.parent / "library")
    chapter_index = json.loads(storage.chapter_index_path(book_name="测试书", author="作者").read_text(encoding="utf-8"))
    assert len(chapter_index["chapters"]) == 3

    metadata = json.loads(storage.metadata_path(book_name="测试书", author="作者").read_text(encoding="utf-8"))
    assert metadata["bookState"]["processedChapterCount"] == 3

    book_row = _book_row(db_path, book_id)
    assert book_row["status"] == "active"
    assert book_row["searchVisibilityStatus"] == "visible"
    assert book_row["totalChapters"] == 3


@pytest.mark.asyncio
async def test_empty_toc_treated_as_fetch_failure(tmp_path, monkeypatch):
    db_path = _setup_db(tmp_path)
    book_id = "book:empty_toc"
    chapters, contents = _make_chapters(2)
    _insert_book(db_path, book_id)

    processor = AggregateProcessor(db_path)
    monkeypatch.setattr(processor, "_is_official_source", lambda sid: sid == "official_src")

    monkeypatch.setattr(
        "app.services.book_catalog.BookCatalog",
        lambda: FakeCatalog(chapters, contents),
    )
    await processor.bootstrap_book_until_visible(book_id)

    monkeypatch.setattr(
        "app.services.book_catalog.BookCatalog",
        lambda: EmptyTocCatalog(chapters, contents),
    )
    result = await processor.run_book_task(book_id)

    assert result["success"] is False
    assert result.get("tocFetchFailed") is True

    storage = SharedBookStorage(root=db_path.parent / "library")
    chapter_index = json.loads(storage.chapter_index_path(book_name="测试书", author="作者").read_text(encoding="utf-8"))
    assert len(chapter_index["chapters"]) == 2


@pytest.mark.asyncio
async def test_empty_toc_preserves_plugin_error(tmp_path, monkeypatch):
    db_path = _setup_db(tmp_path)
    book_id = "book:empty_toc_error"
    chapters, contents = _make_chapters(2)
    _insert_book(db_path, book_id)

    class EmptyTocWithErrorCatalog(FakeCatalog):
        async def toc(self, book_id: str) -> dict[str, Any]:
            return {
                "chapters": [],
                "debug": {"error": {"code": "PLUGIN_RUNTIME_ERROR", "message": "HTTP 403"}},
            }

    processor = AggregateProcessor(db_path)
    monkeypatch.setattr(
        "app.services.book_catalog.BookCatalog",
        lambda: EmptyTocWithErrorCatalog(chapters, contents),
    )
    result = await processor.run_book_task(book_id)

    assert result["error"] == "PLUGIN_RUNTIME_ERROR: HTTP 403"
    with sqlite3.connect(db_path) as conn:
        last_error = conn.execute(
            "SELECT last_error FROM aggregate_book_tasks WHERE aggregate_book_id = ?",
            (book_id,),
        ).fetchone()[0]
    assert last_error == "PLUGIN_RUNTIME_ERROR: HTTP 403"


@pytest.mark.asyncio
async def test_rebuild_toc_preflight_failure_preserves_existing_rows(tmp_path, monkeypatch):
    from fastapi import HTTPException
    from types import SimpleNamespace

    import app.config as config_module
    from app.api import console as console_api

    db_path = _setup_db(tmp_path)
    book_id = "book:rebuild_preflight"
    chapters, _ = _make_chapters(1)
    _insert_book(db_path, book_id)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO aggregate_chapter_tasks
            (chapter_id, aggregate_book_id, source_chapter_id, chapter_index, title, status, processed_content)
            VALUES (?, ?, ?, 1, '第1章', 'processed', '已有正文')
            """,
            (chapters[0]["chapterId"], book_id, chapters[0]["chapterId"]),
        )
        conn.execute(
            """
            UPDATE aggregate_book_tasks
            SET total_chapters = 1, processed_chapters = 1, visible_processed_chapters = 1,
                search_visibility_status = 'visible'
            WHERE aggregate_book_id = ?
            """,
            (book_id,),
        )
        conn.commit()

    class InvalidCatalog:
        async def toc(self, primary_book_id: str) -> dict[str, Any]:
            return {"chapters": [], "debug": {"error": "HTTP 403"}}

    monkeypatch.setattr(config_module, "DB_PATH", db_path)
    monkeypatch.setattr(console_api, "BookCatalog", InvalidCatalog)
    monkeypatch.setattr(
        console_api.auth_service,
        "require_admin",
        lambda request: SimpleNamespace(user_id="admin", role="admin"),
    )

    with pytest.raises(HTTPException) as caught:
        await console_api.rebuild_library_book(None, book_id, {"refetchSources": True})

    assert caught.value.status_code == 409
    assert "已保留现有数据" in str(caught.value.detail)
    with sqlite3.connect(db_path) as conn:
        task = conn.execute(
            "SELECT total_chapters, processed_chapters, search_visibility_status FROM aggregate_book_tasks WHERE aggregate_book_id = ?",
            (book_id,),
        ).fetchone()
        chapter_count = conn.execute(
            "SELECT COUNT(*) FROM aggregate_chapter_tasks WHERE aggregate_book_id = ?",
            (book_id,),
        ).fetchone()[0]
    assert task == (1, 1, "visible")
    assert chapter_count == 1


@pytest.mark.asyncio
async def test_rebuild_refreshes_source_map_before_bootstrap(tmp_path, monkeypatch):
    from types import SimpleNamespace

    import app.config as config_module
    from app.api import console as console_api
    from app.services.library_books import LibraryBooksService
    from app.services.shared_book_storage import SharedBookStorage

    db_path = _setup_db(tmp_path)
    book_id = "book:rebuild_source_map"
    chapters, _ = _make_chapters(1)
    aggregate_payload = {
        "name": "测试书",
        "author": "作者",
        "primarySourceId": "official_src",
        "primarySourceName": "官方源",
        "primaryBookId": f"official_src:{book_id}",
        "sources": [
            {"bookId": f"official_src:{book_id}", "sourceId": "official_src", "sourceName": "官方源"},
            {"bookId": "candidate_src:old", "sourceId": "candidate_src", "sourceName": "旧候补源"},
        ],
    }
    _insert_book(db_path, book_id, aggregate_payload=aggregate_payload)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO aggregate_chapter_tasks
            (chapter_id, aggregate_book_id, source_chapter_id, chapter_index, title, status)
            VALUES (?, ?, ?, 1, '第1章', 'pending')
            """,
            (chapters[0]["chapterId"], book_id, chapters[0]["chapterId"]),
        )
        conn.execute(
            """
            INSERT INTO aggregate_book_sources
            (aggregate_book_id, source_id, source_book_id, source_name, role)
            VALUES (?, 'candidate_src', 'candidate_src:old', '旧候补源', 'candidate')
            """,
            (book_id,),
        )
        conn.execute(
            """
            INSERT INTO aggregate_source_snapshots
            (aggregate_book_id, chapter_index, source_id, clean_content, content_hash)
            VALUES (?, 1, 'candidate_src', '旧正文', 'old-hash')
            """,
            (book_id,),
        )
        conn.execute(
            """
            INSERT INTO user_book_subscriptions
            (user_id, aggregate_book_id, status, start_chapter_index, auto_archive_on_complete)
            VALUES ('reader-1', ?, 'active', 1, 1)
            """,
            (book_id,),
        )
        conn.execute(
            "UPDATE aggregate_book_tasks SET primary_source_id = '' WHERE aggregate_book_id = ?",
            (book_id,),
        )
        conn.commit()
    events = []
    storage = SharedBookStorage(tmp_path / "library")
    library_service = LibraryBooksService(db_path=db_path, shared_book_storage=storage)
    metadata_path = storage.metadata_path(book_name="测试书", author="作者")
    storage.atomic_write_json(
        metadata_path,
        {"name": "测试书", "sourceMap": {"health": {"status": "healthy"}}, "sourceMapSummary": []},
    )
    source_refs_path = storage.source_refs_path(book_name="测试书", author="作者")
    storage.atomic_write_json(source_refs_path, {"sourceMapRefs": [{"sourceId": "candidate_src"}]})

    class ValidCatalog:
        async def toc(self, primary_book_id: str) -> dict[str, Any]:
            return {"chapters": chapters}

    class FakeProcessor:
        _toc_fetch_error_message = staticmethod(lambda result: "")

        def enqueue_book(self, aggregate_book_id, payload):
            events.append(("enqueue", aggregate_book_id, payload))

        async def bootstrap_book_until_visible(self, aggregate_book_id):
            events.append(("bootstrap", aggregate_book_id))
            return {"visible": True}

    async def refresh_source_map(aggregate_book_id, payload=None):
        with sqlite3.connect(db_path, timeout=0) as conn:
            chapter_count = conn.execute(
                "SELECT COUNT(*) FROM aggregate_chapter_tasks WHERE aggregate_book_id = ?",
                (aggregate_book_id,),
            ).fetchone()[0]
            rebuild_log_count = conn.execute(
                "SELECT COUNT(*) FROM aggregate_operation_logs WHERE aggregate_book_id = ? AND operation_type = 'rebuild'",
                (aggregate_book_id,),
            ).fetchone()[0]
            snapshot_count = conn.execute(
                "SELECT COUNT(*) FROM aggregate_source_snapshots WHERE aggregate_book_id = ?",
                (aggregate_book_id,),
            ).fetchone()[0]
            candidate_count = conn.execute(
                "SELECT COUNT(*) FROM aggregate_book_sources WHERE aggregate_book_id = ? AND role = 'candidate'",
                (aggregate_book_id,),
            ).fetchone()[0]
            assert chapter_count == 0
            assert rebuild_log_count == 1
            assert snapshot_count == 0
            assert candidate_count == 0
            refreshed_payload = json.loads(conn.execute(
                "SELECT aggregate_payload_json FROM aggregate_book_tasks WHERE aggregate_book_id = ?",
                (aggregate_book_id,),
            ).fetchone()[0])
            assert [item["sourceId"] for item in refreshed_payload["sources"]] == ["official_src"]
            assert conn.execute(
                "SELECT COUNT(*) FROM user_book_subscriptions WHERE aggregate_book_id = ?",
                (aggregate_book_id,),
            ).fetchone()[0] == 1
            assert conn.execute(
                "SELECT next_check_time IS NOT NULL FROM aggregate_book_tasks WHERE aggregate_book_id = ?",
                (aggregate_book_id,),
            ).fetchone()[0] == 1
            assert not source_refs_path.exists()
            assert "sourceMap" not in json.loads(metadata_path.read_text(encoding="utf-8"))
            refreshed_payload["sourceMapRefreshed"] = True
            conn.execute(
                "UPDATE aggregate_book_tasks SET aggregate_payload_json = ? WHERE aggregate_book_id = ?",
                (json.dumps(refreshed_payload, ensure_ascii=False), aggregate_book_id),
            )
            conn.commit()
        events.append(("refresh", aggregate_book_id, payload))
        return {"ok": True, "bookId": aggregate_book_id}

    monkeypatch.setattr(config_module, "DB_PATH", db_path)
    monkeypatch.setattr(console_api, "BookCatalog", ValidCatalog)
    monkeypatch.setattr(console_api, "AggregateProcessor", FakeProcessor)
    monkeypatch.setattr(console_api, "_manual_source_map_refresh", refresh_source_map)
    monkeypatch.setattr(
        console_api,
        "library_books_service",
        library_service,
    )
    monkeypatch.setattr(
        console_api.auth_service,
        "require_admin",
        lambda request: SimpleNamespace(user_id="admin", role="admin"),
    )

    result = await console_api.rebuild_library_book(None, book_id, {"refetchSources": True})

    assert result["sourceMapRefresh"]["ok"] is True
    assert [event[0] for event in events] == ["refresh", "enqueue", "bootstrap"]
    assert events[1][2]["sourceMapRefreshed"] is True


@pytest.mark.asyncio
async def test_toc_shrink_does_not_delete_processed_chapters(tmp_path, monkeypatch):
    db_path = _setup_db(tmp_path)
    book_id = "book:toc_shrink"
    all_chapters, all_contents = _make_chapters(3)
    _insert_book(db_path, book_id)

    processor = AggregateProcessor(db_path)
    monkeypatch.setattr(processor, "_is_official_source", lambda sid: sid == "official_src")

    monkeypatch.setattr(
        "app.services.book_catalog.BookCatalog",
        lambda: FakeCatalog(all_chapters, all_contents),
    )
    await processor.bootstrap_book_until_visible(book_id)

    class ShrunkTocCatalog(FakeCatalog):
        async def toc(self, book_id: str) -> dict[str, Any]:
            return {"chapters": [dict(ch) for ch in all_chapters[:2]]}

    monkeypatch.setattr(
        "app.services.book_catalog.BookCatalog",
        lambda: ShrunkTocCatalog(all_chapters, all_contents),
    )
    result = await processor.run_book_task(book_id)

    assert result["success"] is True

    storage = SharedBookStorage(root=db_path.parent / "library")
    chapter_index = json.loads(storage.chapter_index_path(book_name="测试书", author="作者").read_text(encoding="utf-8"))
    assert len(chapter_index["chapters"]) == 3
    assert sum(1 for e in chapter_index["chapters"] if e["file"] is not None) == 3

    rows = _chapter_rows(db_path, book_id)
    assert len(rows) == 3
    assert all(r["status"] in {"processed", "fallback"} for r in rows)

    book_row = _book_row(db_path, book_id)
    assert book_row["status"] == "active"
    assert book_row["searchVisibilityStatus"] == "visible"


@pytest.mark.asyncio
async def test_backfill_then_update_check_adds_new_chapters(tmp_path, monkeypatch):
    db_path = _setup_db(tmp_path)
    book_id = "book:backfill_update"

    # Subscriber starts at chapter 3, initial snapshot knows chapters 1-5.
    first_toc, first_contents = _make_chapters(5)
    full_toc, full_contents = _make_chapters(7)
    _insert_book(
        db_path,
        book_id,
        start_index=3,
        initial_snapshot_last_index=5,
        book_status="ongoing",
    )

    processor = AggregateProcessor(db_path)
    monkeypatch.setattr(processor, "_is_official_source", lambda sid: sid == "official_src")
    evolving = EvolvingCatalog([first_toc, full_toc], full_contents)
    monkeypatch.setattr(
        "app.services.book_catalog.BookCatalog",
        lambda: evolving,
    )

    await processor.bootstrap_book_until_visible(book_id)

    rows = _chapter_rows(db_path, book_id)
    assert len(rows) == 5
    assert all(r["status"] in {"processed", "fallback"} for r in rows)

    # Update-check sees chapters 1-7 and processes 6-7.
    result = await processor.run_book_task(book_id)
    assert result["success"] is True
    assert result["processedChapters"] == 2

    rows = _chapter_rows(db_path, book_id)
    assert len(rows) == 7
    assert all(r["status"] in {"processed", "fallback"} for r in rows)
    assert all(not r["placeholder"] for r in rows)

    storage = SharedBookStorage(root=db_path.parent / "library")
    chapter_index = json.loads(storage.chapter_index_path(book_name="测试书", author="作者").read_text(encoding="utf-8"))
    assert len(chapter_index["chapters"]) == 7
    metadata = json.loads(storage.metadata_path(book_name="测试书", author="作者").read_text(encoding="utf-8"))
    assert metadata["bookState"]["processedChapterCount"] == 7


@pytest.mark.asyncio
async def test_source_map_refresh_does_not_break_stage1_or_leak_private_urls(tmp_path, monkeypatch):
    db_path = _setup_db(tmp_path)
    book_id = "book:sourcemap_refresh"
    official_chapters, official_contents = _make_chapters(2)
    official_contents[official_chapters[1]["chapterId"]] = "少年站在山巅望着远方。"  # preview
    _insert_book(db_path, book_id)

    processor = AggregateProcessor(db_path)
    monkeypatch.setattr(processor, "_is_official_source", lambda sid: sid == "official_src")

    async def _fake_ensure(_book_id, payload):
        return payload

    monkeypatch.setattr(processor, "_ensure_candidate_sources_for_book", _fake_ensure)
    monkeypatch.setattr(
        "app.services.book_catalog.BookCatalog",
        lambda: FakeCatalog(official_chapters, official_contents),
    )

    await processor.bootstrap_book_until_visible(book_id)

    rows = _chapter_rows(db_path, book_id)
    preview_row = next(r for r in rows if r["chapterIndex"] == 2)
    assert preview_row["status"] == "fallback"
    assert preview_row["previewOnly"] is True

    # Simulate a later sourceMap refresh that adds a third-party candidate.
    candidate_book_id = "third_party_src:https://third.example/book"
    candidate_source = {
        "sourceId": "third_party_src",
        "sourceName": "第三方源",
        "bookId": candidate_book_id,
        "bookUrl": "https://third.example/book",
        "tocUrl": "",
        "score": 80,
    }
    LibraryBooksService(db_path=db_path).save_payload_sources(book_id, [
        {
            "sourceId": "official_src",
            "sourceName": "官方源",
            "bookId": f"official_src:{book_id}",
            "bookUrl": "https://official.example/book",
            "tocUrl": "",
            "score": 100,
        },
        candidate_source,
    ])

    storage = SharedBookStorage(root=db_path.parent / "library")
    source_refs = {
        "schemaVersion": 1,
        "bookId": book_id,
        "primarySource": {
            "sourceId": "official_src",
            "sourceName": "官方源",
            "bookId": f"official_src:{book_id}",
            "bookUrl": "https://official.example/book",
            "tocUrl": "",
        },
        "sourceMapRefs": [
            {
                "sourceId": "third_party_src",
                "sourceName": "第三方源",
                "sourceBookId": candidate_book_id,
                "bookUrl": "https://third.example/book",
                "tocUrl": "",
                "lastVerifiedAt": datetime.now(timezone.utc).isoformat(),
                "status": "healthy",
                "priority": 80,
            }
        ],
    }
    storage.atomic_write_json(
        storage.source_refs_path(book_name="测试书", author="作者"),
        source_refs,
    )

    # TOC grows to 3 chapters; candidate now has full text for chapter 2.
    updated_official_chapters, updated_official_contents = _make_chapters(3)
    candidate_toc = [{"chapterId": encode_chapter_id("third_party_src", "https://third.example/ch2.html"), "title": "第2章", "index": 2}]
    candidate_contents = {
        candidate_toc[0]["chapterId"]: f"第2章候选全文" + "这是一个很长的正文段落，" * 50,
    }

    monkeypatch.setattr(
        "app.services.book_catalog.BookCatalog",
        lambda: MultiSourceCatalog(
            updated_official_chapters,
            updated_official_contents,
            candidate_book_id,
            candidate_toc,
            candidate_contents,
        ),
    )

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE aggregate_chapter_tasks SET next_retry_time = ? WHERE chapter_id = ?",
            ((datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(), preview_row["chapterId"]),
        )
        conn.commit()

    result = await processor.run_book_task(book_id)
    assert result["success"] is True

    rows = _chapter_rows(db_path, book_id)
    ch2_row = next(r for r in rows if r["chapterIndex"] == 2)
    assert ch2_row["status"] == "processed"
    assert ch2_row["previewOnly"] is False

    ch3_row = next(r for r in rows if r["chapterIndex"] == 3)
    assert ch3_row["status"] == "processed"

    metadata_text = storage.metadata_path(book_name="测试书", author="作者").read_text(encoding="utf-8")
    assert "https://third.example/book" not in metadata_text
    assert "https://third.example/ch2.html" not in metadata_text


@pytest.mark.asyncio
async def test_preview_retry_schedules_final_delay(tmp_path, monkeypatch):
    db_path = _setup_db(tmp_path)
    book_id = "book:preview_final_delay"
    chapters, contents = _make_chapters(1)
    contents[chapters[0]["chapterId"]] = "少年站在山巅望着远方。"
    _insert_book(db_path, book_id)

    processor = AggregateProcessor(db_path)
    monkeypatch.setattr(processor, "_is_official_source", lambda sid: sid == "official_src")

    async def _fake_ensure(_book_id, payload):
        return payload

    monkeypatch.setattr(processor, "_ensure_candidate_sources_for_book", _fake_ensure)
    monkeypatch.setattr(
        "app.services.book_catalog.BookCatalog",
        lambda: FakeCatalog(chapters, contents),
    )

    await processor.bootstrap_book_until_visible(book_id)

    chapter_id = _chapter_rows(db_path, book_id)[0]["chapterId"]
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE aggregate_chapter_tasks SET preview_retry_count = 4, next_retry_time = ? WHERE chapter_id = ?",
            ((datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(), chapter_id),
        )
        conn.commit()

    result = await processor.run_book_task(book_id)
    assert result["success"] is True

    row = _chapter_rows(db_path, book_id)[0]
    assert row["previewRetryCount"] == 5
    assert row["nextRetryTime"] is not None
    scheduled = datetime.fromisoformat(row["nextRetryTime"])
    expected = datetime.now(timezone.utc) + timedelta(minutes=480)
    assert abs((scheduled - expected).total_seconds()) < 5


@pytest.mark.asyncio
async def test_preview_retry_stops_after_all_delays_consumed(tmp_path, monkeypatch):
    db_path = _setup_db(tmp_path)
    book_id = "book:preview_exhausted"
    chapters, contents = _make_chapters(1)
    contents[chapters[0]["chapterId"]] = "少年站在山巅望着远方。"
    _insert_book(db_path, book_id)

    processor = AggregateProcessor(db_path)
    monkeypatch.setattr(processor, "_is_official_source", lambda sid: sid == "official_src")
    monkeypatch.setattr(
        "app.services.aggregate_processor.PREVIEW_RETRY_DELAYS_MINUTES",
        [0, 0, 0, 0, 0],
    )

    async def _fake_ensure(_book_id, payload):
        return payload

    monkeypatch.setattr(processor, "_ensure_candidate_sources_for_book", _fake_ensure)
    monkeypatch.setattr(
        "app.services.book_catalog.BookCatalog",
        lambda: FakeCatalog(chapters, contents),
    )

    await processor.bootstrap_book_until_visible(book_id)
    chapter_id = _chapter_rows(db_path, book_id)[0]["chapterId"]

    # Walk through all five delays; each one schedules the next with a 0-minute delay.
    for _ in range(5):
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "UPDATE aggregate_chapter_tasks SET next_retry_time = ? WHERE chapter_id = ?",
                ((datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(), chapter_id),
            )
            conn.commit()
        await processor.run_book_task(book_id)

    row = _chapter_rows(db_path, book_id)[0]
    assert row["previewRetryCount"] == 6
    assert row["nextRetryTime"] is None


@pytest.mark.asyncio
async def test_candidate_preview_falls_back_to_official_preview(tmp_path, monkeypatch):
    db_path = _setup_db(tmp_path)
    book_id = "book:candidate_preview_fallback"
    official_chapters, official_contents = _make_chapters(1)
    official_contents[official_chapters[0]["chapterId"]] = PREVIEW_SNIPPET
    _insert_book(db_path, book_id)

    processor = AggregateProcessor(db_path)
    monkeypatch.setattr(processor, "_is_official_source", lambda sid: sid == "official_src")

    candidate_book_id = "third_party_src:https://third.example/book"
    LibraryBooksService(db_path=db_path).save_payload_sources(book_id, [
        {"sourceId": "official_src", "sourceName": "官方源", "bookId": f"official_src:{book_id}", "bookUrl": "https://official.example/book", "tocUrl": "", "score": 100},
        {"sourceId": "third_party_src", "sourceName": "第三方源", "bookId": candidate_book_id, "bookUrl": "https://third.example/book", "tocUrl": "", "score": 80},
    ])

    candidate_toc = [{"chapterId": encode_chapter_id("third_party_src", "https://third.example/ch1.html"), "title": "第1章", "index": 1}]
    candidate_contents = {
        candidate_toc[0]["chapterId"]: "第三方源的简短预览。",
    }

    monkeypatch.setattr(
        "app.services.book_catalog.BookCatalog",
        lambda: MultiSourceCatalog(official_chapters, official_contents, candidate_book_id, candidate_toc, candidate_contents),
    )

    await processor.bootstrap_book_until_visible(book_id)

    row = _chapter_rows(db_path, book_id)[0]
    assert row["status"] == "fallback"
    assert row["previewOnly"] is True

    storage = SharedBookStorage(root=db_path.parent / "library")
    trace_text = storage.chapter_markdown_path(
        book_name="测试书", author="作者", chapter_index=row["chapterIndex"], title=row["title"]
    ).read_text(encoding="utf-8")
    trace = storage.parse_trace_block(trace_text)
    assert trace["alignment"]["selectedContentSource"] == "preview_fallback"


@pytest.mark.asyncio
async def test_candidate_empty_falls_back_to_official_preview(tmp_path, monkeypatch):
    db_path = _setup_db(tmp_path)
    book_id = "book:candidate_empty_fallback"
    official_chapters, official_contents = _make_chapters(1)
    official_contents[official_chapters[0]["chapterId"]] = PREVIEW_SNIPPET
    _insert_book(db_path, book_id)

    processor = AggregateProcessor(db_path)
    monkeypatch.setattr(processor, "_is_official_source", lambda sid: sid == "official_src")

    candidate_book_id = "third_party_src:https://third.example/book"
    LibraryBooksService(db_path=db_path).save_payload_sources(book_id, [
        {"sourceId": "official_src", "sourceName": "官方源", "bookId": f"official_src:{book_id}", "bookUrl": "https://official.example/book", "tocUrl": "", "score": 100},
        {"sourceId": "third_party_src", "sourceName": "第三方源", "bookId": candidate_book_id, "bookUrl": "https://third.example/book", "tocUrl": "", "score": 80},
    ])

    candidate_toc = [{"chapterId": encode_chapter_id("third_party_src", "https://third.example/ch1.html"), "title": "第1章", "index": 1}]
    candidate_contents = {candidate_toc[0]["chapterId"]: ""}

    monkeypatch.setattr(
        "app.services.book_catalog.BookCatalog",
        lambda: MultiSourceCatalog(official_chapters, official_contents, candidate_book_id, candidate_toc, candidate_contents),
    )

    await processor.bootstrap_book_until_visible(book_id)

    row = _chapter_rows(db_path, book_id)[0]
    assert row["status"] == "fallback"
    assert row["previewOnly"] is True


@pytest.mark.asyncio
async def test_candidate_toc_order_mismatch_matches_by_title(tmp_path, monkeypatch):
    db_path = _setup_db(tmp_path)
    book_id = "book:candidate_toc_mismatch"
    official_chapters, official_contents = _make_chapters(2)
    preview_a = "少年站在山巅望着远方，风吹动他的衣角，云层在脚下翻滚不止，远处的山脉连绵起伏，像一条沉睡的巨龙。"
    preview_b = "少女在庭院中散步，花香四溢，阳光透过树叶洒落下来，鸟儿在枝头轻声歌唱。"
    official_contents[official_chapters[0]["chapterId"]] = preview_a
    official_contents[official_chapters[1]["chapterId"]] = preview_b
    _insert_book(db_path, book_id)

    processor = AggregateProcessor(db_path)
    monkeypatch.setattr(processor, "_is_official_source", lambda sid: sid == "official_src")
    monkeypatch.setattr(
        processor,
        "_select_consistent_candidate",
        lambda candidates, **_: (candidates[0] if candidates else None, []),
    )

    candidate_book_id = "third_party_src:https://third.example/book"
    LibraryBooksService(db_path=db_path).save_payload_sources(book_id, [
        {"sourceId": "official_src", "sourceName": "官方源", "bookId": f"official_src:{book_id}", "bookUrl": "https://official.example/book", "tocUrl": "", "score": 100},
        {"sourceId": "third_party_src", "sourceName": "第三方源", "bookId": candidate_book_id, "bookUrl": "https://third.example/book", "tocUrl": "", "score": 80},
    ])

    # Candidate TOC is in reverse order but titles still map to the correct chapters.
    cand_ch1_id = encode_chapter_id("third_party_src", "https://third.example/ch1.html")
    cand_ch2_id = encode_chapter_id("third_party_src", "https://third.example/ch2.html")
    candidate_toc = [
        {"chapterId": cand_ch2_id, "title": "第2章", "index": 1},
        {"chapterId": cand_ch1_id, "title": "第1章", "index": 2},
    ]
    # Include the official preview snippet at the start so preview alignment passes.
    candidate_contents = {
        cand_ch1_id: preview_a + "\n" + "正文内容很长，" * 50,
        cand_ch2_id: preview_b,
    }

    catalog = MultiSourceCatalog(
        official_chapters,
        official_contents,
        candidate_book_id,
        candidate_toc,
        candidate_contents,
    )
    catalog._source_word_count = len(candidate_contents[cand_ch1_id].replace("\n", ""))

    monkeypatch.setattr(
        "app.services.book_catalog.BookCatalog",
        lambda: catalog,
    )

    await processor.bootstrap_book_until_visible(book_id)

    rows = _chapter_rows(db_path, book_id)
    ch1_row = next(r for r in rows if r["chapterIndex"] == 1)
    ch2_row = next(r for r in rows if r["chapterIndex"] == 2)
    # Chapter 1 found a full candidate via title matching in reversed TOC.
    assert ch1_row["status"] == "fallback"
    assert ch1_row["previewOnly"] is False
    # Chapter 2's candidate content is still preview-only.
    assert ch2_row["status"] == "fallback"
    assert ch2_row["previewOnly"] is True

    storage = SharedBookStorage(root=db_path.parent / "library")
    metadata_text = storage.metadata_path(book_name="测试书", author="作者").read_text(encoding="utf-8")
    assert "https://third.example" not in metadata_text


@pytest.mark.asyncio
async def test_candidate_source_discovery_cached_per_book(tmp_path, monkeypatch):
    db_path = _setup_db(tmp_path)
    book_id = "book:candidate_cache"
    official_chapters, official_contents = _make_chapters(3)
    for ch in official_chapters:
        official_contents[ch["chapterId"]] = PREVIEW_SNIPPET
    _insert_book(db_path, book_id)

    processor = AggregateProcessor(db_path)
    monkeypatch.setattr(processor, "_is_official_source", lambda sid: sid == "official_src")

    calls: list[Any] = []

    async def _counting_discover(*, keyword, author, existing_sources, max_candidates, max_sources):
        calls.append((keyword, author))
        return [
            {"sourceId": "third_party_src", "sourceName": "第三方源", "bookId": "third_party_src:https://third.example/book", "bookUrl": "https://third.example/book", "tocUrl": "", "score": 80},
        ]

    monkeypatch.setattr(processor, "_discover_third_party_candidates", _counting_discover)
    monkeypatch.setattr(
        "app.services.book_catalog.BookCatalog",
        lambda: FakeCatalog(official_chapters, official_contents),
    )

    await processor.bootstrap_book_until_visible(book_id)

    assert len(calls) == 1
    rows = _chapter_rows(db_path, book_id)
    assert len(rows) == 3
    assert all(r["status"] == "fallback" and r["previewOnly"] is True for r in rows)


@pytest.mark.asyncio
async def test_candidate_source_cache_invalidates_when_payload_sources_change(tmp_path, monkeypatch):
    db_path = _setup_db(tmp_path)
    book_id = "book:candidate_cache_payload_change"
    processor = AggregateProcessor(db_path)
    monkeypatch.setattr(processor, "_is_official_source", lambda sid: sid == "official_src")

    payload = {
        "name": "测试书",
        "author": "作者",
        "primarySourceId": "official_src",
        "primaryBookId": f"official_src:{book_id}",
        "sources": [
            {
                "sourceId": "official_src",
                "sourceName": "官方源",
                "bookId": f"official_src:{book_id}",
                "bookUrl": "https://official.example/book",
                "score": 100,
            }
        ],
    }

    calls: list[int] = []

    async def _discover(**kwargs):
        calls.append(1)
        return [
            {
                "sourceId": "third_party_src",
                "sourceName": "第三方源",
                "bookId": "third_party_src:https://third.example/book-a",
                "bookUrl": "https://third.example/book-a",
                "tocUrl": "",
                "score": 80,
            }
        ]

    monkeypatch.setattr(processor, "_discover_third_party_candidates", _discover)

    first = await processor._ensure_candidate_sources_for_book(book_id, payload)
    assert len(calls) == 1
    assert len(first["sources"]) == 2

    changed_payload = {
        **first,
        "sources": [
            *first["sources"],
            {
                "sourceId": "manual_src",
                "sourceName": "手动补充源",
                "bookId": "manual_src:https://manual.example/book",
                "bookUrl": "https://manual.example/book",
                "tocUrl": "",
                "score": 70,
            },
        ],
    }

    second = await processor._ensure_candidate_sources_for_book(book_id, changed_payload)
    assert len(calls) == 2
    assert any(src["sourceId"] == "manual_src" for src in second["sources"])
    assert second["sources"][-1]["bookId"] == "manual_src:https://manual.example/book"


@pytest.mark.asyncio
async def test_candidate_source_cache_lasts_for_process_lifetime(tmp_path, monkeypatch):
    db_path = _setup_db(tmp_path)
    book_id = "book:candidate_cache_process_lifetime"
    processor = AggregateProcessor(db_path)
    monkeypatch.setattr(processor, "_is_official_source", lambda sid: sid == "official_src")
    payload = {
        "name": "测试书",
        "author": "作者",
        "primarySourceId": "official_src",
        "primaryBookId": f"official_src:{book_id}",
        "sources": [
            {
                "sourceId": "official_src",
                "sourceName": "官方源",
                "bookId": f"official_src:{book_id}",
                "bookUrl": "https://official.example/book",
                "score": 100,
            }
        ],
    }
    calls: list[int] = []

    async def _discover(**kwargs):
        calls.append(1)
        return [
            {
                "sourceId": "third_party_src",
                "sourceName": "第三方源",
                "bookId": "third_party_src:https://third.example/book",
                "bookUrl": "https://third.example/book",
                "tocUrl": "",
                "score": 80,
            }
        ]

    monkeypatch.setattr(processor, "_discover_third_party_candidates", _discover)

    first = await processor._ensure_candidate_sources_for_book(book_id, payload)
    monkeypatch.setattr("app.services.aggregate_processor.time.monotonic", lambda: 10_000_000)
    second = await processor._ensure_candidate_sources_for_book(book_id, first)

    assert len(calls) == 1
    assert second == first


@pytest.mark.asyncio
async def test_source_map_refresh_replaces_candidate_cache_payload(tmp_path, monkeypatch):
    db_path = _setup_db(tmp_path)
    book_id = "book:source_map_refresh_cache"
    _insert_book(db_path, book_id)

    processor = AggregateProcessor(db_path)
    monkeypatch.setattr(processor, "_is_official_source", lambda sid: sid == "official_src")
    payload = {
        "name": "测试书",
        "author": "作者",
        "primarySourceId": "official_src",
        "primaryBookId": f"official_src:{book_id}",
        "sources": [
            {
                "sourceId": "official_src",
                "sourceName": "官方源",
                "bookId": f"official_src:{book_id}",
                "bookUrl": "https://official.example/book",
                "tocUrl": "",
                "score": 100,
            }
        ],
    }

    calls: list[str] = []

    async def _discover(**kwargs):
        calls.append("discover")
        return [
            {
                "sourceId": "third_party_src",
                "sourceName": "第三方源A",
                "bookId": "third_party_src:https://third.example/book-a",
                "bookUrl": "https://third.example/book-a",
                "tocUrl": "",
                "score": 80,
            }
        ]

    monkeypatch.setattr(processor, "_discover_third_party_candidates", _discover)

    first = await processor._ensure_candidate_sources_for_book(book_id, payload)
    assert len(calls) == 1
    assert any(src["bookId"] == "third_party_src:https://third.example/book-a" for src in first["sources"])

    refreshed_payload = {
        **payload,
        "sources": [
            payload["sources"][0],
            {
                "sourceId": "third_party_src",
                "sourceName": "第三方源B",
                "bookId": "third_party_src:https://third.example/book-b",
                "bookUrl": "https://third.example/book-b",
                "tocUrl": "",
                "score": 90,
            },
        ],
    }

    LibraryBooksService(db_path=db_path).save_payload_sources(book_id, refreshed_payload["sources"])
    second = await processor._ensure_candidate_sources_for_book(book_id, refreshed_payload)

    assert len(calls) == 2
    assert any(src["bookId"] == "third_party_src:https://third.example/book-b" for src in second["sources"])
