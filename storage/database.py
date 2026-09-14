from contextlib import contextmanager
from pathlib import Path
import sqlite3


SCHEMA = """
CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user' CHECK(role IN ('user', 'coach', 'admin')),
    created_at TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1))
);
CREATE TABLE IF NOT EXISTS invites (
    id INTEGER PRIMARY KEY,
    code_hash TEXT NOT NULL UNIQUE,
    max_uses INTEGER CHECK(max_uses IS NULL OR max_uses > 0),
    used_count INTEGER NOT NULL DEFAULT 0 CHECK(used_count >= 0),
    is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
    created_at TEXT NOT NULL,
    label TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS auth_attempts (
    bucket TEXT PRIMARY KEY, count INTEGER NOT NULL, expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    owner_user_id INTEGER REFERENCES users(id),
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS jobs_owner_created ON jobs(owner_user_id, created_at);
CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status);
INSERT OR IGNORE INTO metadata VALUES ('schema_version', '1');
"""


class Database:
    def __init__(self, path, *, initialize=True):
        self.path = Path(path).resolve()
        if initialize:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.connect(create=True) as db:
                db.execute("PRAGMA journal_mode=WAL")
                db.executescript(SCHEMA)
            # Explicit bootstrap includes the additive coach schema. Existing
            # production stores use `python -m coach.cli migrate` before deploy.
            from coach.migration import migrate
            migrate(self)
            from accounts.invite_migration import migrate as migrate_invites
            migrate_invites(self)
        else:
            if not self.path.is_file():
                raise RuntimeError("Database is missing. Bootstrap and import legacy jobs before starting services.")
            with self.connect() as db:
                version = db.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
                if version is None or version["value"] != "1":
                    raise RuntimeError("Unsupported database schema. Review migration before starting services.")

    @contextmanager
    def connect(self, *, write=False, create=False):
        # Only explicit initialization may create a file. A lost/mistyped runtime
        # database path must never silently turn into an empty database.
        uri = self.path.as_uri() + ("?mode=rwc" if create else "?mode=rw")
        db = sqlite3.connect(uri, uri=True, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
