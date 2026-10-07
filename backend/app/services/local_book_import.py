"""Bounded TXT/archive import into the existing personal offline reader."""
import hashlib
import re
import shutil
import tempfile
from pathlib import Path

from fastapi import HTTPException

from app.services.book_downloads import book_downloads

MAX_TEXT_BYTES = 32 * 1024 * 1024


def unpack_text(payload: bytes) -> tuple[str, str]:
    """Read archive members in memory; never extract paths or execute files."""
    import libarchive

    if len(payload) > 8 * 1024 * 1024:
        raise HTTPException(400, "附件超过 8 MB 限制")
    if payload.startswith((b"Rar!", b"PK\x03\x04", b"7z\xbc\xaf\x27\x1c")):
        texts = []
        total = 0
        try:
            with libarchive.memory_reader(payload) as entries:
                for count, entry in enumerate(entries):
                    if count >= 100:
                        raise HTTPException(400, "压缩包文件过多")
                    if entry.size < 0 or entry.size > MAX_TEXT_BYTES:
                        raise HTTPException(400, "压缩包包含过大的文件")
                    if not entry.isfile or not entry.pathname.lower().endswith(".txt"):
                        continue
                    data = bytearray()
                    for chunk in entry.get_blocks():
                        total += len(chunk)
                        if total > MAX_TEXT_BYTES:
                            raise HTTPException(400, "解压后的 TXT 超过 32 MB")
                        data.extend(chunk)
                    texts.append((entry.pathname, bytes(data)))
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(400, "附件无法解压，可能损坏或需要密码") from exc
        if len(texts) != 1:
            raise HTTPException(400, "目前只支持包含一份 TXT 的附件")
        filename, data = texts[0]
    else:
        filename, data = "book.txt", payload
    if b"\x00" in data:
        raise HTTPException(400, "附件不是可识别的 TXT 文本")
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeError:
            continue
    else:
        raise HTTPException(400, "TXT 编码无法识别")
    if len(text.strip()) < 100 or text.lstrip().lower().startswith(("<!doctype", "<html")):
        raise HTTPException(400, "下载内容不是小说正文")
    return filename, text.replace("\r\n", "\n").replace("\r", "\n")


def split_chapters(text: str, name: str) -> list[dict]:
    lines = text.splitlines()
    numbered = re.compile(r"^(?:第[零〇一二三四五六七八九十百千万两\d]+[章节回卷部集篇](?:[\s：:、.].{0,65})?|chapter\s+\d+(?:[\s:.-].{0,65})?)$", re.I)
    short_numbers = re.compile(r"^[零〇一二三四五六七八九十百千万两\d]{1,10}$")
    # Bare numbers are headings only when multiple isolated lines establish a
    # consistent pattern. Paragraph numbers inside prose are never split.
    isolated = lambda i: (i == 0 or not lines[i-1].strip()) and (i+1 == len(lines) or not lines[i+1].strip())
    bare = {i for i, line in enumerate(lines) if short_numbers.fullmatch(line.strip()) and isolated(i)}
    headings = {i for i, line in enumerate(lines) if numbered.fullmatch(line.strip()) or (len(bare) >= 3 and i in bare)}
    chapters = []
    starts = sorted(headings | {0})
    for pos, start in enumerate(starts):
        end = starts[pos+1] if pos+1 < len(starts) else len(lines)
        is_heading = start in headings
        content = "\n".join(lines[start+1 if is_heading else start:end]).strip()
        if not content:
            continue
        title = lines[start].strip() if is_heading else "前言" if headings else name
        chapters.append({"index": len(chapters), "title": title, "content": content})
    if not chapters or len(chapters) > 20000 or any(len(c['content'].encode()) > 2*1024*1024 for c in chapters):
        raise HTTPException(400, "TXT 无法分章或单章超过 2 MB")
    return chapters


def import_book(user_id, metadata, payload, downloads=None):
    downloads = downloads or book_downloads
    _, text = unpack_text(payload)
    chapters = split_chapters(text, metadata['name'])
    book_id = "import-" + hashlib.sha256(payload).hexdigest()[:32]
    repo = downloads.repository
    if repo.get(user_id, book_id) and downloads.cached(user_id, book_id, "toc.json"):
        return repo.get(user_id, book_id)
    book = {**metadata, "bookId": book_id, "sourceCount": 1, "imported": True,
            "chapterCount": len(chapters), "sources": []}
    directory = downloads.directory(user_id, book_id)
    directory.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix="import-", dir=directory.parent))
    try:
        toc = {"bookId": book_id, "chapters": [{"index": c['index'], "title": c['title'], "url": f"local:{book_id}:{c['index']}"} for c in chapters],
               "sources": [{"sourceId": book['sourceId'], "sourceName": book['sourceName'], "status": "available", "chapterCount": len(chapters), "lastChapter": chapters[-1]['title'], "latencyMs": 0}]}
        downloads.write_json(temp / "detail.json", book)
        downloads.write_json(temp / "toc.json", toc)
        for chapter in chapters:
            downloads.write_json(temp / f"chapter-{chapter['index']}.json", chapter)
        (temp / "book.txt").write_text(text, encoding="utf-8")
        if directory.exists():
            shutil.rmtree(directory)
        temp.rename(directory)
        repo.save_import(user_id, book, len(chapters))
        return book
    finally:
        shutil.rmtree(temp, ignore_errors=True)
