"""Authenticated on-demand reading. Never schedules subscription/download jobs."""
from __future__ import annotations

import asyncio
import copy
import ipaddress
import os
import time
from collections import OrderedDict
from urllib.parse import urlsplit, urljoin

from fastapi import HTTPException

from app.source_plugins.id_codec import decode_book_id, encode_book_id
from app.source_plugins.scheduler import get_plugin_scheduler


class DirectReadingService:
    def __init__(self, scheduler=None):
        self._scheduler = scheduler
        self._cache = OrderedDict()
        self._inflight = {}
        self._slots = asyncio.Semaphore(8)

    @property
    def scheduler(self):
        return self._scheduler or get_plugin_scheduler()

    @staticmethod
    def eligible(plugin):
        meta = plugin.metadata
        return (meta.enabled and not meta.is_official_source()
                and meta.auth.get("mode", "none") == "none"
                and meta.content.get("access") == "free"
                and {"search", "detail", "toc", "chapter"}.issubset(plugin.capabilities))

    def sources(self):
        return sorted([
            {"id": p.metadata.id, "name": p.metadata.name,
             "default": p.metadata.id in os.getenv("LEGADOHUB_DIRECT_DEFAULT_SOURCES", "").split(",")}
            for p in self.scheduler._plugins.values() if self.eligible(p)
        ], key=lambda p: p["name"])

    def plugin(self, source_id):
        plugin = self.scheduler._plugins.get(source_id)
        if not plugin or not self.eligible(plugin):
            raise HTTPException(400, "书源未启用或不支持匿名直接阅读")
        return plugin

    def validate_url(self, source_id, url):
        plugin = self.plugin(source_id)
        try:
            parsed = urlsplit(url)
            host = (parsed.hostname or "").lower().rstrip(".")
            if (parsed.scheme not in {"http", "https"} or not host
                    or parsed.username or parsed.password or parsed.port not in {None, 80, 443}
                    or len(url) > 4096):
                raise ValueError()
            try:
                ipaddress.ip_address(host)
            except ValueError:
                pass
            else:
                raise ValueError()
            domains = set(d.lower().rstrip(".") for d in plugin.metadata.domains)
            domains.update(urlsplit(u).hostname for u in plugin.metadata.base_urls)
            if not any(d and (host == d or host.endswith("." + d)) for d in domains):
                raise ValueError()
        except (ValueError, TypeError):
            raise HTTPException(400, "地址不属于该书源") from None
        return url

    def book_target(self, book_id):
        try:
            if len(book_id) > 6000:
                raise ValueError()
            source_id, url = decode_book_id(book_id)
        except Exception:
            raise HTTPException(400, "无效书籍标识") from None
        self.validate_url(source_id, url)
        return source_id, url

    @staticmethod
    def check_result(result):
        error = result.get("error") or result.get("debug", {}).get("error")
        if error:
            message = error.get("message", "书源请求失败") if isinstance(error, dict) else str(error)
            raise HTTPException(502, str(message)[:500])

    async def cached(self, key, operation):
        now = time.monotonic()
        entry = self._cache.get(key)
        if entry and entry[0] > now:
            self._cache.move_to_end(key)
            return copy.deepcopy(entry[1])
        # Shared operations survive one client's cancellation but remain bounded
        # by plugin timeouts. Completed failures are never cached.
        task = self._inflight.get(key)
        if task is None:
            async def run():
                try:
                    result = await operation()
                    self._cache[key] = (time.monotonic() + 300, result)
                    self._cache.move_to_end(key)
                    while len(self._cache) > 128:
                        self._cache.popitem(last=False)
                    return result
                finally:
                    self._inflight.pop(key, None)
            task = asyncio.create_task(run())
            task.add_done_callback(lambda t: None if t.cancelled() else t.exception())
            self._inflight[key] = task
        return copy.deepcopy(await asyncio.shield(task))

    async def detail(self, book_id):
        source_id, url = self.book_target(book_id)
        async def load():
            async with self._slots:
                result = await self.scheduler.detail(source_id, url)
            self.check_result(result)
            raw = result.get("data") or {}
            if not raw.get("name"):
                raise HTTPException(502, "书源未返回书籍详情")
            return {"bookId": book_id, "sourceId": source_id,
                    "sourceName": self.plugin(source_id).metadata.name,
                    "name": str(raw.get("name", "")), "author": str(raw.get("author", "")),
                    "intro": str(raw.get("intro", "")), "coverUrl": urljoin(url, str(raw.get("coverUrl") or "")) if raw.get("coverUrl") else "",
                    "tocUrl": self.validate_url(source_id, raw.get("tocUrl") or url)}
        return await self.cached(("detail", book_id), load)

    async def toc(self, book_id):
        source_id, _ = self.book_target(book_id)
        async def load():
            detail = await self.detail(book_id)
            async with self._slots:
                result = await self.scheduler.toc(source_id, detail["tocUrl"])
            self.check_result(result)
            chapters = []
            for raw in result.get("chapters", []):
                url = raw.get("rawChapterUrl")
                self.validate_url(source_id, url)
                chapters.append({"index": len(chapters), "title": str(raw.get("title", "")), "url": url})
            if not chapters:
                raise HTTPException(502, "书源未返回章节目录")
            return {"bookId": book_id, "chapters": chapters}
        return await self.cached(("toc", book_id), load)

    async def chapter(self, book_id, index):
        source_id, _ = self.book_target(book_id)
        toc = await self.toc(book_id)
        if not 0 <= index < len(toc["chapters"]):
            raise HTTPException(404, "章节不存在")
        return await self.chapter_at(book_id, toc["chapters"][index])

    async def chapter_at(self, book_id, chapter):
        source_id, _ = self.book_target(book_id)
        self.validate_url(source_id, chapter["url"])
        index = chapter["index"]
        async with self._slots:
            result = await self.scheduler.chapter(source_id, chapter["url"])
        self.check_result(result)
        if result.get("authRequired") or result.get("isPaid"):
            raise HTTPException(403, "该章节需要在原站授权")
        if not result.get("content"):
            raise HTTPException(502, "书源未返回正文")
        return {"index": index, "title": result.get("title") or chapter["title"],
                "content": str(result["content"]),
                "wordCount": result.get("sourceWordCount") or result.get("wordCount", 0),
                "previewOnly": any(result.get(k) or (result.get("debug") or {}).get(k) for k in ("previewOnly", "isPreview", "preview_only")),
                "extra": result.get("extra") if isinstance(result.get("extra"), dict) else {}}

    async def search(self, keyword, source_ids, page=1):
        for source_id in source_ids:
            self.plugin(source_id)
        limit = asyncio.Semaphore(4)
        async def one(source_id):
            try:
                async with limit, self._slots:
                    result = await asyncio.wait_for(self.scheduler.search_one(source_id, keyword, page), 25)
            except Exception:
                result = {"items": [], "error": {"message": "书源搜索暂时不可用"}}
            items = []
            for raw in result.get("items", [])[:200]:
                url = raw.get("bookUrl", "")
                try:
                    self.validate_url(source_id, url)
                except HTTPException:
                    continue
                items.append({"bookId": encode_book_id(source_id, url), "sourceId": source_id,
                              "sourceName": self.plugin(source_id).metadata.name,
                              "name": str(raw.get("name", "")), "author": str(raw.get("author", "")),
                              "coverUrl": urljoin(url, str(raw.get("coverUrl") or "")) if raw.get("coverUrl") else "",
                              "intro": str(raw.get("intro") or "")})
            return {"sourceId": source_id, "items": items, "error": result.get("error"),
                    "latencyMs": result.get("latencyMs", 0)}
        tasks = [asyncio.create_task(one(s)) for s in source_ids]
        try:
            for future in asyncio.as_completed(tasks):
                yield await future
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


direct_reading = DirectReadingService()
