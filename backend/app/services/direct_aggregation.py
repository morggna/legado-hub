"""Personal multi-source books; metadata on add, aggregation only on chapter demand."""
from __future__ import annotations

import asyncio
import hashlib
import re
import time
from urllib.parse import urlsplit
from collections import Counter

from fastapi import HTTPException

from app.services.aggregate_alignment import (
    _normalize_chapter_title, chapter_name_similarity, chapter_title_similarity,
    classify_source_content,
)
from app.services.aggregate_selection import CandidateSelectionPolicy
from app.services.live_acceptance import group_candidates, normalize_author_key, normalize_text
from app.services.direct_reading import direct_reading
from app.services.text_convert import to_simplified
from app.storage.direct_reading import direct_repository


def identity(book):
    seed = normalize_text(to_simplified(book.get("name", ""))) + "\n" + normalize_author_key(to_simplified(book.get("author", "")))
    return "agg-" + hashlib.sha256(seed.encode()).hexdigest()[:32]


def safe_cover(value):
    try:
        url = urlsplit(str(value or ""))
        return str(value) if url.scheme in {"http", "https"} and url.hostname and not url.username and not url.password else ""
    except ValueError:
        return ""


def grouped_books(items, keyword):
    """Reuse upstream search ranking, with source-independent persistent identity."""
    result = []
    normalized = [{**b, "name": to_simplified(b.get("name", "")), "author": to_simplified(b.get("author", ""))} for b in items]
    for group in group_candidates(list({b['bookId']: b for b in normalized}.values()), to_simplified(keyword)):
        sources = group["items"]
        authors = {normalize_author_key(b.get("author", "")) for b in normalized
                   if normalize_text(b["name"]) == normalize_text(group["name"])} - {""}
        # Upstream arbitrarily assigns unknown authors when homonyms exist.
        # Do not silently combine those editions in a personal reading axis.
        if len(authors) > 1:
            unknown = [s for s in sources if not normalize_author_key(s.get("author", ""))]
            sources = [s for s in sources if normalize_author_key(s.get("author", ""))]
            if unknown:
                result.append(_book(unknown))
        if sources:
            result.append(_book(sources))
    return result


def _book(sources):
    best = next((s for s in sources if normalize_author_key(s.get("author", ""))), sources[0])
    return {**{k: best.get(k, "") for k in ("name", "author", "intro")},
            "bookId": identity(best), "sourceId": "aggregate", "sourceName": "多源聚合",
            "sourceCount": len({s['sourceId'] for s in sources}),
            "sourceBookIds": [s["bookId"] for s in sources],
            "coverUrl": next((safe_cover(s.get("coverUrl")) for s in sources if safe_cover(s.get("coverUrl"))), ""),
            "sources": [{k: s.get(k, "") for k in ("bookId", "sourceId", "sourceName", "name", "author", "coverUrl")} for s in sources]}


class AggregateReadingService(CandidateSelectionPolicy):
    def __init__(self, reader=None, repository=None):
        self.reader = reader or direct_reading
        self.repository = repository or direct_repository
        self._locks = {}
        self._chapter_tasks = {}
        self._upgrades = {}

    def for_user(self, user_id):
        return PersonalAggregateReader(self, user_id)

    async def add(self, user_id, source_ids, expected_identity=None, existing_book_id=None):
        source_ids = list(dict.fromkeys(source_ids))
        if not source_ids or len(source_ids) > 64:
            raise HTTPException(400, "请选择 1 至 64 个来源")
        for book_id in source_ids:
            self.reader.book_target(book_id)
        async def detail(book_id):
            try:
                return await asyncio.wait_for(self.reader.detail(book_id), 20)
            except Exception:
                return None
        details = [d for d in await asyncio.gather(*(detail(b) for b in source_ids)) if d]
        if not details:
            raise HTTPException(502, "来源详情暂时不可用，请重试")
        groups = grouped_books(details, details[0]["name"])
        if expected_identity:
            groups = [g for g in groups if g["bookId"] == expected_identity]
        if len(groups) != 1:
            raise HTTPException(400, "来源详情与搜索书籍不符，请重新搜索")
        if existing_book_id and not self.repository.get(user_id, existing_book_id):
            raise HTTPException(404, "书籍已移出书库")
        book = groups[0]
        # Keep legacy book IDs/progress/downloads intact. Later discoveries enrich
        # the existing entry, rather than producing another shelf card.
        existing = next((b for b in self.repository.shelf(user_id)
                         if not b.get("imported") and identity(b) == book["bookId"]), None)
        if existing:
            book["bookId"] = existing["bookId"]
            if existing.get("legacyOrigin") or not existing.get("sources"):
                book["legacyOrigin"] = existing.get("legacyOrigin") or existing["bookId"]
            old = existing.get("sources") or ([existing] if existing.get("sourceId") != "aggregate" else [])
            merged = {s["bookId"]: s for s in [*old, *book["sources"]]}
            book["sources"] = list(merged.values())
            book["sourceBookIds"] = list(merged)
            book["sourceCount"] = len({s["sourceId"] for s in merged.values()})
            book["coverUrl"] = book["coverUrl"] or existing.get("coverUrl", "")
            book["preferredSourceBookId"] = existing.get("preferredSourceBookId")
        return self.repository.save(user_id, book)

    def select_source(self, user_id, book_id, source_book_id):
        book = self.repository.get(user_id, book_id)
        if not book:
            raise HTTPException(404, "书籍不在你的书库中")
        if book.get("imported") or (source_book_id and source_book_id not in book.get("sourceBookIds", [])):
            raise HTTPException(400, "线路不属于这本书")
        return self.repository.save(user_id, {**book, "preferredSourceBookId": source_book_id})

    async def refresh_sources(self, user_id, book_id):
        book = self.repository.get(user_id, book_id)
        if not book or book.get("imported"):
            raise HTTPException(404, "书籍没有可更新的在线来源")
        candidates = list(book.get("sourceBookIds") or [book_id])
        try:
            async with asyncio.timeout(12):
                async for result in self.reader.search(book["name"], [s["id"] for s in self.reader.sources()][:64]):
                    candidates.extend(item["bookId"] for item in result["items"] if identity(item) == identity(book))
        except TimeoutError:
            pass
        async with asyncio.timeout(22):
            result = await self.add(user_id, list(dict.fromkeys(candidates))[:64], expected_identity=identity(book), existing_book_id=book_id)
        return result

    def book(self, user_id, book_id):
        book = self.repository.get(user_id, book_id)
        if not book:
            if book_id.startswith(("agg-", "import-")):
                raise HTTPException(404, "书籍不在你的书库中")
            self.reader.book_target(book_id)
        return book

    async def upgrade_legacy(self, user_id, book):
        if book and book.get("imported"):
            raise HTTPException(409, "导入书籍的本地文件缺失，请重新导入附件")
        if not book or book.get("sources"):
            return book
        key = (user_id, book["bookId"])
        task = self._upgrades.get(key)
        if task is None:
            async def discover():
                candidates = [book["bookId"]]
                try:
                    async with asyncio.timeout(12):
                        async for result in self.reader.search(book["name"], [s["id"] for s in self.reader.sources()][:64]):
                            for item in result["items"]:
                                if identity(item) == identity(book):
                                    candidates.append(item["bookId"])
                except TimeoutError:
                    pass
                # Keep legacy first-open discovery below proxy request limits;
                # explicit search can later enrich the book with slower sources.
                async with asyncio.timeout(10):
                    return await self.add(user_id, candidates[:64], expected_identity=identity(book), existing_book_id=book["bookId"])
            task = asyncio.create_task(discover())
            self._upgrades[key] = task
            def done(t):
                self._upgrades.pop(key, None)
                if not t.cancelled():
                    t.exception()
            task.add_done_callback(done)
        try:
            return await asyncio.shield(task)
        except Exception:
            # Temporary discovery failures cannot take away a working old book.
            return book

    async def _catalogs(self, book):
        sources = book.get("sources") or [book]
        async def load(source):
            started = time.monotonic()
            try:
                toc = await asyncio.wait_for(self.reader.toc(source["bookId"]), 20)
                return {**source, "catalogStatus": "available" if toc["chapters"] else "unavailable", "latencyMs": round((time.monotonic()-started)*1000)}, toc["chapters"][:20000]
            except Exception:
                return {**source, "catalogStatus": "unavailable", "latencyMs": round((time.monotonic()-started)*1000)}, []
        return await asyncio.gather(*(load(s) for s in sources[:64]))

    @staticmethod
    def volume(title):
        from app.services.aggregate_alignment import _parse_chinese_number
        match = re.search(r"第\s*([零〇一二两三四五六七八九十百千万\d]+)\s*卷", to_simplified(title))
        return _parse_chinese_number(match.group(1)) if match else None

    def same_chapter(self, a, b):
        # Without an official preview, index/ordinal alone cannot establish
        # identity: a missing chapter otherwise silently shifts every later one.
        if not a or not b:
            return False
        a, b = to_simplified(a), to_simplified(b)
        va, vb = self.volume(a), self.volume(b)
        if va is not None and vb is not None and va != vb:
            return False
        # Volume ordinals are context, not chapter numbers.
        a = re.sub(r"第\s*[零〇一二两三四五六七八九十百千万\d]+\s*卷\s*", "", a)
        b = re.sub(r"第\s*[零〇一二两三四五六七八九十百千万\d]+\s*卷\s*", "", b)
        if not a.strip() or not b.strip():
            return False
        oa, ob = self._chapter_ordinal_from_title(a), self._chapter_ordinal_from_title(b)
        name_score = chapter_name_similarity(a, b)
        if oa is not None and ob is not None and oa != ob:
            return name_score >= .95
        return chapter_title_similarity(a, b) >= .8 or name_score >= .9

    def aligned_candidates(self, chapter, chapters):
        # A unique exact title can align despite a long preface or omitted volumes.
        # Repeated titles need neighboring anchors, never proximity alone.
        exact = _normalize_chapter_title(to_simplified(chapter["title"]))
        matches = []
        for position, item in enumerate(chapters):
            if not self.same_chapter(chapter["title"], item["title"]):
                continue
            anchors = sum(1 for offset, field in ((-1, "previousTitle"), (1, "nextTitle"))
                          if chapter.get(field) and 0 <= position+offset < len(chapters)
                          and self.same_chapter(chapter[field], chapters[position+offset]["title"]))
            title = _normalize_chapter_title(to_simplified(item["title"]))
            matches.append((anchors, title == exact, abs(position-chapter["index"]), item))
        if len(matches) > 1:
            anchored = [m for m in matches if m[0]]
            if not anchored:
                return []
            matches = anchored
            top = max((m[0], m[1]) for m in matches)
            if sum((m[0], m[1]) == top for m in matches) > 1:
                return []
        matches.sort(key=lambda m: (-m[0], -m[1], m[2]))
        return [m[3] for m in matches[:3]]

    def title_key(self, title):
        return (self.volume(title), _normalize_chapter_title(to_simplified(title)))

    def canonical(self, catalogs, previous=None):
        available = [(s, cs) for s, cs in catalogs if cs]
        if not available:
            if previous:
                return previous
            raise HTTPException(502, "所有来源目录暂时不可用")
        def entries(source, chapters):
            return [{**c, "originBookId": source["bookId"], "originIndex": c["index"]} for c in chapters]
        if previous:
            chapters = list(previous["chapters"])
        else:
            source, primary = max(available, key=lambda pair: len(pair[1]))
            chapters = entries(source, primary)
            # Insert an absent chapter only between two exact, adjacent anchors.
            # This happens once before any progress exists; later refreshes append.
            for source, candidates in available:
                counts = Counter(self.title_key(c["title"]) for c in chapters)
                candidate_counts = Counter(self.title_key(c["title"]) for c in candidates)
                lookup = {self.title_key(c["title"]): i for i, c in enumerate(chapters)
                          if counts[self.title_key(c["title"])] == 1 and candidate_counts[self.title_key(c["title"])] == 1}
                inserts = []
                for left in range(len(candidates)-2):
                    a = lookup.get(self.title_key(candidates[left]["title"]))
                    if a is None:
                        continue
                    right = left+1
                    while right < min(left+32, len(candidates)) and self.title_key(candidates[right]["title"]) not in lookup:
                        right += 1
                    if right < len(candidates) and right > left+1 and lookup.get(self.title_key(candidates[right]["title"])) == a+1:
                        inserts.append((a+1, entries(source, candidates[left+1:right])))
                for position, missing in reversed(inserts):
                    chapters[position:position] = missing
        # Append new chapters only after a unique exact tail anchor. Never
        # renumber an established progress axis or frozen download snapshot.
        for source, candidates in available:
            tail = self.title_key(chapters[-1]["title"])
            if sum(self.title_key(c["title"]) == tail for c in chapters) != 1:
                continue
            matches = [i for i,c in enumerate(candidates) if self.title_key(c["title"]) == tail]
            if len(matches) == 1:
                chapters.extend(entries(source, candidates[matches[0]+1:]))
        return {"chapters": [{**c, "index": i} for i,c in enumerate(chapters[:20000])]}

    async def toc(self, user_id, book_id, *, allow_empty=False, refresh=False):
        book = await self.upgrade_legacy(user_id, self.book(user_id, book_id))
        if not book or not book.get("sources"):
            return await self.reader.toc(book_id)
        key = (user_id, book_id)
        # Ref-counted locks prevent parallel first reads freezing different axes.
        lock, count = self._locks.get(key, (asyncio.Lock(), 0))
        self._locks[key] = (lock, count+1)
        try:
            async with lock:
                previous, updated = self.repository.aggregate_toc(*key)
                if not refresh and previous and previous.get("chapters") and previous.get("sources") and previous.get("sourceBookIds") == book.get("sourceBookIds") and time.time()-updated < 300:
                    return previous
                if previous is None and book.get("legacyOrigin"):
                    # Existing single-source progress uses this exact axis.
                    previous = await self.reader.toc(book["legacyOrigin"])
                    previous["chapters"] = [{**c, "originBookId": book["legacyOrigin"]} for c in previous["chapters"]]
                if refresh:
                    for source in book["sources"]:
                        self.reader._cache.pop(("toc", source["bookId"]), None)
                catalogs = await self._catalogs(book)
                axis = {"chapters": []} if allow_empty and not previous and not any(cs for _, cs in catalogs) else self.canonical(catalogs, previous)
                result = {"bookId": book_id, **axis, "checkedAt": time.time(), "sourceBookIds": book.get("sourceBookIds"),
                          "sources": [{"sourceId": source["sourceId"], "sourceName": source["sourceName"],
                                       "status": source.get("catalogStatus", "unknown"), "latencyMs": source.get("latencyMs"),
                                       "chapterCount": len(chapters), "lastChapter": chapters[-1]["title"] if chapters else ""}
                                      for source, chapters in catalogs]}
                if result["chapters"]:
                    self.repository.save_aggregate_toc(*key, result)
                return result
        finally:
            _, count = self._locks[key]
            if count == 1:
                self._locks.pop(key)
            else:
                self._locks[key] = (lock, count-1)

    async def chapter_at(self, user_id, book_id, chapter):
        book = await self.upgrade_legacy(user_id, self.book(user_id, book_id))
        if not book or not book.get("sources"):
            return await self.reader.chapter_at(book_id, chapter)
        cached = self.repository.aggregate_chapter(user_id, book_id, chapter["index"])
        if cached and cached["title"] == chapter["title"] and cached.get("aggregation", {}).get("sourceBookIds") == book.get("sourceBookIds") and cached.get("aggregation", {}).get("preferredSourceBookId") == book.get("preferredSourceBookId") and cached.get("aggregation", {}).get("policyVersion") == 2:
            return cached
        axis, _ = self.repository.aggregate_toc(user_id, book_id)
        if axis and chapter["index"] < len(axis["chapters"]) and axis["chapters"][chapter["index"]]["title"] == chapter["title"]:
            rows, index = axis["chapters"], chapter["index"]
            chapter = {**chapter, "previousTitle": rows[index-1]["title"] if index else "",
                       "nextTitle": rows[index+1]["title"] if index+1 < len(rows) else ""}
        key = (user_id, book_id, chapter["index"], chapter["title"], tuple(book.get("sourceBookIds", [])), book.get("preferredSourceBookId"))
        task = self._chapter_tasks.get(key)
        if task is None:
            task = asyncio.create_task(self._aggregate(book, chapter))
            self._chapter_tasks[key] = task
            def done(t):
                self._chapter_tasks.pop(key, None)
                if not t.cancelled():
                    t.exception()
            task.add_done_callback(done)
        result = await asyncio.shield(task)
        # User may have removed the shelf entry while the source was responding.
        if self.repository.get(user_id, book_id):
            self.repository.save_aggregate_chapter(user_id, book_id, chapter["index"], result)
        return result

    async def _aggregate(self, book, chapter):
        accepted, attempts = [], []
        preference = book.get("preferredSourceBookId")
        eligible = [s for s in book['sources'] if not preference or s['bookId'] == preference]
        sources = list({s['sourceId']: s for s in eligible}.values())
        budgets = {s['sourceId']: self._candidate_budget(s['sourceId']) for s in sources}
        deadline = time.monotonic() + max([45, *budgets.values()])
        async def candidate(source):
            source_id = source['sourceId']
            audit = {"sourceId": source_id, "sourceName": source["sourceName"]}
            try:
                async with asyncio.timeout(max(.01, min(budgets[source_id], deadline-time.monotonic()))):
                    origin = chapter.get('originBookId') or book.get('legacyOrigin')
                    if source['bookId'] == origin:
                        matches = [{**chapter, 'index': chapter.get('originIndex', chapter['index'])}]
                    else:
                        toc = await self.reader.toc(source['bookId'])
                        matches = self.aligned_candidates(chapter, toc['chapters'])
                    if not matches:
                        return None, {**audit, "status": "no_aligned_chapter"}
                    result = None
                    for match in matches:
                        try:
                            value = await self.reader.chapter_at(source['bookId'], match)
                        except HTTPException as exc:
                            if exc.status_code == 410:
                                raise
                            continue
                        if self.same_chapter(chapter['title'], value['title']):
                            result = value
                            break
                    if result is None:
                        return None, {**audit, "status": "title_mismatch"}
                    content = to_simplified(result['content'])
                    if not self.same_chapter(chapter['title'], result['title']):
                        return None, {**audit, "status": "title_mismatch"}
                    if len(content.encode()) > 2*1024*1024:
                        return None, {**audit, "status": "too_large"}
                    classification = classify_source_content(content, source_id=source_id, source_word_count=result.get('wordCount', 0), preview_only_hint=result.get('previewOnly', False), extra=result.get('extra') or {})
                    if classification['classification'] != 'full':
                        return None, {**audit, "status": "incomplete"}
                    return {"source_id": source_id, "content": content, "alignment_json": {"alignmentPassed": True, "alignmentReason": "title_matched"}}, {**audit, "status": "accepted"}
            except HTTPException as exc:
                if exc.status_code == 410:
                    return None, {**audit, "status": "removed", "message": str(exc.detail)[:500]}
                return None, {**audit, "status": "unavailable"}
            except Exception:
                return None, {**audit, "status": "unavailable"}
        selected, consensus = None, []
        # Compare 3 first, expanding only while agreement is insufficient. These
        # are candidates of THIS chapter, never preceding/following chapters.
        for start in range(0, len(sources), 3):
            if time.monotonic() >= deadline:
                break
            results = await asyncio.gather(*(candidate(s) for s in sources[start:start+3]))
            for value, audit in results:
                attempts.append(audit)
                if value:
                    accepted.append(value)
            selected, consensus = await asyncio.to_thread(self._select_consistent_candidate, accepted)
            if selected and len(accepted) >= 3 and self._has_stable_candidate_consensus(consensus, candidate_count=len(accepted), require_unanimous=start == 0):
                break
        if selected is None:
            selected, consensus = await asyncio.to_thread(self._select_consistent_candidate, accepted, allow_degraded=True)
        if selected is None:
            removed = [a for a in attempts if a["status"] == "removed"]
            if removed:
                message = "；".join(f"{a['sourceName']}：{a['message']}" for a in removed)
                raise HTTPException(410 if len(removed) == len(attempts) else 502, message)
            raise HTTPException(502, "当前章没有可靠的多源正文；来源不可用、缺章或正文互相冲突，请稍后重试")
        support = next((c['supportCount'] for c in consensus if c['sourceId'] == selected['source_id']), 0)
        return {"index": chapter['index'], "title": chapter['title'], "content": selected['content'],
                "aggregation": {"sourceBookIds": book.get("sourceBookIds"), "policyVersion": 2, "preferredSourceBookId": preference, "mode": "manual" if preference else "consensus" if support else "degraded", "selectedSourceId": selected['source_id'],
                    "selectedSourceName": next(s['sourceName'] for s in sources if s['sourceId'] == selected['source_id']),
                    "acceptedCount": len(accepted), "attemptedCount": len(attempts), "supportCount": support,
                    "consensus": consensus, "sources": attempts}}

    def _candidate_budget(self, source_id):
        """Honor the host's catalog and chapter budgets at the outer boundary.

        A fixed 20-second wrapper otherwise cancels a valid paced chapter even
        when its scheduler permits 35 seconds. Keep the combined wait bounded.
        """
        scheduler = self.reader.scheduler
        plugin = getattr(scheduler, '_plugins', {}).get(source_id)
        chapter_timeout = getattr(scheduler, 'timeout_for_plugin', None)
        toc_timeout = getattr(scheduler, 'toc_timeout_for_plugin', None)
        if not callable(chapter_timeout) or not callable(toc_timeout):
            return 20.0
        return min(120.0, max(20.0, chapter_timeout(plugin) + toc_timeout(plugin)))


class PersonalAggregateReader:
    def __init__(self, service, user_id):
        self.service, self.user_id = service, user_id

    def book_target(self, book_id):
        return self.service.book(self.user_id, book_id)

    async def detail(self, book_id):
        book = self.service.book(self.user_id, book_id)
        return book or await self.service.reader.detail(book_id)

    async def toc(self, book_id, *, allow_empty=False, refresh=False):
        return await self.service.toc(self.user_id, book_id, allow_empty=allow_empty, refresh=refresh)

    async def full_book(self, book_id, toc):
        book = self.service.book(self.user_id, book_id)  # ownership before any network work
        if not book:
            raise HTTPException(404, "书籍不在你的书库中")
        if not book.get("sources"):
            return await self.service.reader.full_book(book_id, toc)
        results = {}
        for source in book["sources"]:
            source_book = source["bookId"]
            targets = [c for c in toc["chapters"]
                       if (c.get("originBookId") or book.get("legacyOrigin")) == source_book]
            if not targets:
                continue
            try:
                source_id, _ = self.service.reader.book_target(source_book)
                if "full_book" not in self.service.reader.plugin(source_id).capabilities:
                    continue
                source_toc = await self.service.reader.toc(source_book)
                native = await self.service.reader.full_book(source_book, source_toc)
                for chapter in targets:
                    item = native.get(chapter["url"])
                    if item and item["title"] == chapter["title"]:
                        results[chapter["url"]] = {**item, "index": chapter["index"]}
            except Exception:
                # One unavailable native file must not block other owned sources.
                continue
        return results

    async def chapter_at(self, book_id, chapter):
        return await self.service.chapter_at(self.user_id, book_id, chapter)

    async def chapter(self, book_id, index):
        toc = await self.toc(book_id)
        if not 0 <= index < len(toc['chapters']):
            raise HTTPException(404, "章节不存在")
        return await self.chapter_at(book_id, toc['chapters'][index])


aggregate_reading = AggregateReadingService()
