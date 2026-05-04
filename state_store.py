import hashlib
import json
import sqlite3
from datetime import datetime

from site_scraper import Page


class StateDB:
    def __init__(self, db_path: str):
        self.conn = sqlite3.connect(db_path)
        self._init()

    def _init(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS pages (
                url TEXT PRIMARY KEY,
                content_hash TEXT NOT NULL,
                content TEXT NOT NULL,
                pages_data TEXT,
                updated_at TEXT NOT NULL
            )
        """)
        # 旧スキーマへの追加カラムマイグレーション
        try:
            self.conn.execute("ALTER TABLE pages ADD COLUMN pages_data TEXT")
        except sqlite3.OperationalError:
            pass
        self.conn.commit()

    def get(self, url: str) -> dict | None:
        row = self.conn.execute(
            "SELECT content_hash, content, pages_data, updated_at FROM pages WHERE url = ?",
            (url,),
        ).fetchone()
        if row is None:
            return None
        return {
            "hash": row[0],
            "content": row[1],
            "pages": json.loads(row[2]) if row[2] else None,
            "updated_at": row[3],
        }

    def save(self, url: str, pages: list[Page]):
        pages_data = {
            p.url: {
                "hash": hashlib.md5(p.text.encode()).hexdigest(),
                "content": p.text,
                "title": p.title,
            }
            for p in pages
        }
        combined = "\n\n".join(f"【{p.title}】\n{p.text}" for p in pages)
        content_hash = hashlib.md5(combined.encode()).hexdigest()

        self.conn.execute(
            "INSERT OR REPLACE INTO pages (url, content_hash, content, pages_data, updated_at) VALUES (?, ?, ?, ?, ?)",
            (url, content_hash, combined, json.dumps(pages_data, ensure_ascii=False), datetime.now().isoformat()),
        )
        self.conn.commit()

    def close(self):
        self.conn.close()
