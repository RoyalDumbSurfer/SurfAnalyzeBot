"""Additive, transactional Coach Review schema, independent of account schema v1."""

STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS coach_reviews (
        id INTEGER PRIMARY KEY,
        job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
        reviewer_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        status TEXT NOT NULL CHECK(status IN ('draft','saved')),
        analysis_language TEXT,
        job_created_at TEXT NOT NULL,
        original_analysis_snapshot TEXT NOT NULL,
        frame_refs_snapshot TEXT NOT NULL,
        corrected_analysis TEXT NOT NULL,
        general_comment TEXT NOT NULL DEFAULT '',
        revision INTEGER NOT NULL DEFAULT 1 CHECK(revision > 0),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(job_id, reviewer_user_id)
    )""",
    """CREATE TABLE IF NOT EXISTS coach_frame_notes (
        id INTEGER PRIMARY KEY,
        review_id INTEGER NOT NULL REFERENCES coach_reviews(id) ON DELETE CASCADE,
        frame_index INTEGER NOT NULL CHECK(frame_index > 0),
        note TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(review_id, frame_index)
    )""",
    "CREATE INDEX IF NOT EXISTS coach_reviews_reviewer ON coach_reviews(reviewer_user_id)",
    """CREATE TRIGGER IF NOT EXISTS coach_review_snapshot_immutable
       BEFORE UPDATE OF original_analysis_snapshot, frame_refs_snapshot, job_id,
                        reviewer_user_id, analysis_language, job_created_at, created_at
       ON coach_reviews
       BEGIN SELECT RAISE(ABORT, 'Coach review snapshots are immutable'); END""",
)


def migrate(database):
    with database.connect(write=True) as db:
        version = db.execute("SELECT value FROM metadata WHERE key='coach_schema_version'").fetchone()
        if version and version[0] != '1':
            raise RuntimeError('Unsupported coach schema version')
        for statement in STATEMENTS:
            db.execute(statement)
        db.execute("INSERT OR IGNORE INTO metadata VALUES ('coach_schema_version','1')")
        if db.execute('PRAGMA foreign_key_check').fetchone():
            raise RuntimeError('Foreign key integrity check failed')
