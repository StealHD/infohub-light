"""Dedicated relay metadata, separate from the Service database and transcripts."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class Ownership:
    def __init__(self, root: Path, user: str):
        self.path = root / 'ownership.sqlite3'
        self.user = user
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS sessions (key TEXT PRIMARY KEY, owner TEXT NOT NULL)')
        self.path.chmod(0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        try:
            with db:
                yield db
        finally:
            db.close()

    def owns(self, key: object) -> bool:
        if not isinstance(key, str) or not key:
            return False
        with self.connect() as db:
            return db.execute('SELECT 1 FROM sessions WHERE key=? AND owner=?', (key, self.user)).fetchone() is not None

    def add(self, key: str):
        with self.connect() as db:
            db.execute('INSERT INTO sessions(key, owner) VALUES (?, ?)', (key, self.user))
