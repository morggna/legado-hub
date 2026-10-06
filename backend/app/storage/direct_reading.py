"""Personal shelf/progress storage with atomic optimistic concurrency."""
from contextlib import contextmanager
import json
import sqlite3

from fastapi import HTTPException

from app import config


class DirectReadingRepository:
    def __init__(self, db_path=None):
        self.db_path = db_path

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.db_path or config.DB_PATH, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def shelf(self, user_id):
        with self.connect() as conn:
            rows = conn.execute("SELECT metadata_json FROM direct_bookshelf WHERE user_id=? ORDER BY updated_at DESC", (user_id,)).fetchall()
        return [json.loads(r[0]) for r in rows]

    def save(self, user_id, detail):
        # TOC URLs are runtime-owned and need not be returned from personal storage.
        metadata = {k: v for k, v in detail.items() if k != "tocUrl"}
        with self.connect() as conn:
            conn.execute("""INSERT INTO direct_bookshelf(user_id,book_id,metadata_json) VALUES(?,?,?)
                ON CONFLICT(user_id,book_id) DO UPDATE SET metadata_json=excluded.metadata_json,updated_at=datetime('now')""",
                (user_id, detail["bookId"], json.dumps(metadata, ensure_ascii=False)))
        return metadata

    def remove(self, user_id, book_id):
        with self.connect() as conn:
            conn.execute("DELETE FROM direct_bookshelf WHERE user_id=? AND book_id=?", (user_id, book_id))

    def progress(self, user_id, book_id):
        with self.connect() as conn:
            row = conn.execute("SELECT chapter_index,position,revision FROM direct_progress WHERE user_id=? AND book_id=?", (user_id, book_id)).fetchone()
        return {"chapterIndex": row[0], "position": row[1], "revision": row[2]} if row else {"chapterIndex": 0, "position": 0, "revision": 0}

    def update_progress(self, user_id, book_id, chapter_index, position, revision):
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT revision FROM direct_progress WHERE user_id=? AND book_id=?", (user_id, book_id)).fetchone()
            current = row[0] if row else 0
            if current != revision:
                raise HTTPException(409, "阅读进度已在其他页面更新，请重新载入")
            conn.execute("""INSERT INTO direct_progress(user_id,book_id,chapter_index,position,revision) VALUES(?,?,?,?,?)
                ON CONFLICT(user_id,book_id) DO UPDATE SET chapter_index=excluded.chapter_index,position=excluded.position,
                revision=excluded.revision,updated_at=datetime('now')""", (user_id, book_id, chapter_index, position, current + 1))
        return {"chapterIndex": chapter_index, "position": position, "revision": current + 1}

    def get(self, user_id, book_id):
        with self.connect() as conn:
            row = conn.execute("SELECT metadata_json FROM direct_bookshelf WHERE user_id=? AND book_id=?", (user_id, book_id)).fetchone()
        return json.loads(row[0]) if row else None

    def downloads(self, user_id):
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM direct_download_jobs WHERE user_id=?", (user_id,)).fetchall()
        return [_download_payload(row) for row in rows]

    def download(self, user_id, book_id):
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM direct_download_jobs WHERE user_id=? AND book_id=?", (user_id, book_id)).fetchone()
        return _download_payload(row) if row else None

    def queue_download(self, user_id, book_id):
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if not conn.execute("SELECT 1 FROM direct_bookshelf WHERE user_id=? AND book_id=?", (user_id, book_id)).fetchone():
                raise HTTPException(404, "请先加入书库")
            existing = conn.execute("SELECT state FROM direct_download_jobs WHERE user_id=? AND book_id=?", (user_id, book_id)).fetchone()
            if existing and existing[0] in {"queued", "running", "completed"}:
                return self.download(user_id, book_id)
            active = conn.execute("SELECT COUNT(*) FROM direct_download_jobs WHERE user_id=? AND state IN ('queued','running')", (user_id,)).fetchone()[0]
            global_active = conn.execute("SELECT COUNT(*) FROM direct_download_jobs WHERE state IN ('queued','running')").fetchone()[0]
            if active >= 2 or global_active >= 20:
                raise HTTPException(429, "下载队列已满，请等待或暂停已有任务")
            conn.execute("""INSERT INTO direct_download_jobs(user_id,book_id,state) VALUES(?,?,'queued')
                ON CONFLICT(user_id,book_id) DO UPDATE SET state='queued',error='',updated_at=datetime('now')""", (user_id, book_id))
        return self.download(user_id, book_id)

    def set_download(self, user_id, book_id, state, completed=0, total=0, error=""):
        with self.connect() as conn:
            conn.execute("UPDATE direct_download_jobs SET state=?,completed=?,total=?,error=?,updated_at=datetime('now') WHERE user_id=? AND book_id=?",
                         (state, completed, total, error[:500], user_id, book_id))

    def recover_downloads(self):
        with self.connect() as conn:
            conn.execute("UPDATE direct_download_jobs SET state='queued' WHERE state='running'")

    def next_download(self):
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT user_id,book_id FROM direct_download_jobs WHERE state='queued' ORDER BY updated_at LIMIT 1").fetchone()
            if row:
                conn.execute("UPDATE direct_download_jobs SET state='running' WHERE user_id=? AND book_id=?", tuple(row))
        return tuple(row) if row else None


direct_repository = DirectReadingRepository()


def _download_payload(row):
    return {"bookId": row["book_id"], "state": row["state"], "completed": row["completed"], "total": row["total"], "error": row["error"]}
