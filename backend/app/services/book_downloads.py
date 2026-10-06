"""Optional resumable full-book downloads, separate from adding/reading books."""
from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
from pathlib import Path

from fastapi import HTTPException

from app import config
from app.services.direct_reading import direct_reading
from app.storage.direct_reading import direct_repository


class BookDownloadService:
    def __init__(self, reader=None, repository=None, root=None):
        self.reader = reader or direct_reading
        self.repository = repository or direct_repository
        self.root = root
        self._workers = []
        self._wake = asyncio.Event()
        self._active = {}

    def directory(self, user_id, book_id):
        root = self.root or config.DATA_DIR / "direct_books"
        digest = lambda value: hashlib.sha256(value.encode()).hexdigest()
        return Path(root) / digest(user_id) / digest(book_id)

    @staticmethod
    def write_json(path, payload):
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        temp.replace(path)

    def cached(self, user_id, book_id, name):
        # State alone cannot grant access; the personal shelf is the ownership boundary.
        if not self.repository.get(user_id, book_id):
            return None
        path = self.directory(user_id, book_id) / name
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def file(self, user_id, book_id):
        job = self.repository.download(user_id, book_id)
        if not self.repository.get(user_id, book_id) or not job or job["state"] != "completed":
            raise HTTPException(404, "整本下载尚未完成")
        path = self.directory(user_id, book_id) / "book.txt"
        if not path.is_file():
            raise HTTPException(404, "下载文件不存在，请重试下载")
        return path

    async def start(self):
        if not self._workers:
            self.repository.recover_downloads()
            self._workers = [asyncio.create_task(self.worker()) for _ in range(2)]

    async def stop(self):
        for task in self._workers:
            task.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        self._active.clear()

    def enqueue(self, user_id, book_id):
        self.reader.book_target(book_id)
        active = self._active.get((user_id, book_id))
        if active and not active.done() and active.cancelling():
            raise HTTPException(409, "下载正在暂停，请稍后重试")
        result = self.repository.queue_download(user_id, book_id)
        self._wake.set()
        return result

    async def cancel(self, user_id, book_id):
        job = self.repository.download(user_id, book_id)
        if not job:
            raise HTTPException(404, "下载任务不存在")
        if job["state"] == "completed":
            return job
        self.repository.set_download(user_id, book_id, "paused", job["completed"], job["total"])
        task = self._active.get((user_id, book_id))
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        return self.repository.download(user_id, book_id)

    def remove(self, user_id, book_id):
        job = self.repository.download(user_id, book_id)
        if job and job["state"] in {"queued", "running"}:
            raise HTTPException(409, "请先暂停下载任务再移出书库")
        shutil.rmtree(self.directory(user_id, book_id), ignore_errors=True)
        self.repository.remove(user_id, book_id)
        with self.repository.connect() as conn:
            conn.execute("DELETE FROM direct_download_jobs WHERE user_id=? AND book_id=?", (user_id, book_id))

    async def worker(self):
        while True:
            self._wake.clear()
            item = self.repository.next_download()
            if not item:
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=15)
                except asyncio.TimeoutError:
                    pass
                continue
            task = asyncio.create_task(self.run(*item))
            self._active[item] = task
            try:
                await task
            except asyncio.CancelledError:
                # Distinguish cancelling one book from shutting down the worker.
                if asyncio.current_task().cancelling():
                    raise
            finally:
                self._active.pop(item, None)

    async def run(self, user_id, book_id):
        completed, total = 0, 0
        try:
            detail = await self.reader.detail(book_id)
            toc = await self.reader.toc(book_id)
            chapters = toc["chapters"]
            total = len(chapters)
            if total > 20000:
                raise HTTPException(400, "目录过大，超过整本下载限制")
            directory = self.directory(user_id, book_id)
            directory.mkdir(parents=True, exist_ok=True)
            # Keep a stable directory snapshot for offline reading.
            self.write_json(directory / "detail.json", detail)
            self.write_json(directory / "toc.json", toc)
            size = 0
            for chapter in chapters:
                index = chapter["index"]
                path = directory / f"chapter-{index}.json"
                cached = self.cached(user_id, book_id, path.name)
                if not cached or cached.get("url") != chapter["url"]:
                    # Use the frozen URL from this job's validated directory, not
                    # an index from a later refreshed TOC during a long download.
                    result = await self.reader.chapter_at(book_id, chapter)
                    result["url"] = chapter["url"]
                    if len(result["content"].encode()) > 2 * 1024 * 1024:
                        raise HTTPException(400, "单章正文过大")
                    self.write_json(path, result)
                size += path.stat().st_size
                if size > 256 * 1024 * 1024:
                    raise HTTPException(400, "整本缓存超过 256 MB")
                completed += 1
                self.repository.set_download(user_id, book_id, "running", completed, total)
                await asyncio.sleep(0)  # Allow stop/read requests between chapters.
            temp = directory / "book.tmp"
            with temp.open("w", encoding="utf-8") as output:
                output.write(f"{detail['name']}\n{detail.get('author', '')}\n\n")
                for chapter in chapters:
                    content = self.cached(user_id, book_id, f"chapter-{chapter['index']}.json")
                    output.write(f"{content['title']}\n\n{content['content']}\n\n")
            temp.replace(directory / "book.txt")
            self.repository.set_download(user_id, book_id, "completed", completed, total)
        except asyncio.CancelledError:
            job = self.repository.download(user_id, book_id)
            if job and job["state"] == "running":
                # A process shutdown leaves a resumable queued job.
                self.repository.set_download(user_id, book_id, "queued", completed, total)
            raise
        except Exception as exc:
            message = str(getattr(exc, "detail", exc))
            self.repository.set_download(user_id, book_id, "failed", completed, total, message)


book_downloads = BookDownloadService()
