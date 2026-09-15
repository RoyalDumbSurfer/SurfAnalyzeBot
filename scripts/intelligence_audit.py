"""Run from repository root on production; prints aggregates only, no review text."""
import json

from config import settings
from storage.database import Database

database = Database(settings.DATABASE_PATH, initialize=False)
with database.connect() as db:
    db.execute('BEGIN')
    print(json.dumps({
        'counts': {table: db.execute('SELECT count(*) FROM ' + table).fetchone()[0]
                   for table in ('users', 'jobs', 'invites', 'coach_reviews', 'coach_frame_notes')},
        'reviews': [dict(row) for row in db.execute('''SELECT u.role,r.status,count(*) AS count
            FROM coach_reviews r JOIN users u ON u.id=r.reviewer_user_id GROUP BY u.role,r.status''')],
        'queued_processing': db.execute("SELECT count(*) FROM jobs WHERE status IN ('queued','processing')").fetchone()[0],
        'integrity': db.execute('PRAGMA integrity_check').fetchone()[0],
        'foreign_key_errors': len(db.execute('PRAGMA foreign_key_check').fetchall()),
    }))

try:
    from coach.knowledge import expert_examples, build_coach_context
except ImportError:
    pass  # Pre-deployment schema audit also works on the previous release.
else:
    examples = expert_examples(database)
    _, metadata = build_coach_context(examples)
    print(json.dumps({'eligible_examples': len(examples), 'concepts': sorted({t for e in examples for t in e['tags']}),
                      'background_context_bytes': metadata['context_bytes'], 'background_examples': len(metadata['examples'])}))
