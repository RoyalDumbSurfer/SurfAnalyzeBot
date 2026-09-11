"""Transactional reviews and deterministic dataset records. No provider calls."""
from datetime import datetime, timezone
import json
import re

from storage.database import Database

FIELDS = ('level', 'main_issue', 'why_it_matters', 'how_to_fix', 'drill', 'coach_note')
ROLES = ('admin', 'coach')


class ConflictError(Exception):
    pass


def authorize(db, user_id, job_id):
    user = db.execute('SELECT role,is_active FROM users WHERE id=?', (user_id,)).fetchone()
    if not user or not user['is_active'] or user['role'] not in ROLES:
        raise PermissionError('Coach role required')
    job = db.execute('SELECT * FROM jobs WHERE id=? AND owner_user_id=?', (job_id, user_id)).fetchone()
    if not job:
        raise LookupError('Not found')
    if job['status'] != 'done':
        raise ValueError('Completed analysis required')
    return job


def snapshots(job):
    payload = json.loads(job['payload'])
    original = payload.get('analysis_result')
    if not isinstance(original, dict) or any(not isinstance(original.get(k), str) for k in FIELDS):
        raise ValueError('A complete six-field AI analysis is required')
    paths = payload.get('extracted_frame_paths') or []
    if not isinstance(paths, list) or len(paths) > 100:
        raise ValueError('Invalid frame sequence')
    pattern = r'/frames/' + re.escape(job['id']) + r'/[A-Za-z0-9_-][A-Za-z0-9_.-]*'
    if any(not isinstance(p, str) or not re.fullmatch(pattern, p) for p in paths):
        raise ValueError('Invalid frame reference')
    return {k: original[k] for k in FIELDS}, paths, payload.get('analysis_language')


def validate(data, frame_count):
    if not isinstance(data, dict) or set(data) != {'revision', 'status', 'corrections', 'general_comment', 'frame_notes'}:
        raise ValueError('Invalid review fields')
    if type(data['revision']) is not int or data['revision'] < 0 or data['status'] not in ('draft', 'saved'):
        raise ValueError('Invalid review state')
    corrections = data['corrections']
    if not isinstance(corrections, dict) or set(corrections) != set(FIELDS):
        raise ValueError('All six correction fields are required')
    for value in corrections.values():
        if value is not None and (not isinstance(value, str) or len(value) > 4000):
            raise ValueError('Correction is too long')
    comment = data['general_comment']
    if not isinstance(comment, str) or len(comment) > 8000:
        raise ValueError('Comment is too long')
    notes = data['frame_notes']
    if not isinstance(notes, list) or len(notes) > frame_count:
        raise ValueError('Invalid frame notes')
    indices = set()
    for item in notes:
        if not isinstance(item, dict) or set(item) != {'frame_index', 'note'}:
            raise ValueError('Invalid frame note')
        index, note = item['frame_index'], item['note']
        if type(index) is not int or not 1 <= index <= frame_count or index in indices:
            raise ValueError('Invalid frame index')
        if not isinstance(note, str) or not note.strip() or len(note) > 4000:
            raise ValueError('Invalid frame note text')
        indices.add(index)
    return {k: v if v and v.strip() else None for k, v in corrections.items()}


def decode(db, row):
    if row is None:
        return None
    return {
        'id': row['id'], 'job_id': row['job_id'], 'reviewer_id': row['reviewer_user_id'],
        'status': row['status'], 'revision': row['revision'],
        'analysis_language': row['analysis_language'], 'job_created_at': row['job_created_at'],
        'original_analysis': json.loads(row['original_analysis_snapshot']),
        'frame_references': [{'frame_index': i, 'url': url} for i, url in enumerate(json.loads(row['frame_refs_snapshot']), 1)],
        'corrections': json.loads(row['corrected_analysis']), 'general_comment': row['general_comment'],
        'created_at': row['created_at'], 'updated_at': row['updated_at'],
        'frame_notes': [dict(r) for r in db.execute('SELECT frame_index,note FROM coach_frame_notes WHERE review_id=? ORDER BY frame_index', (row['id'],))],
    }


class CoachStore:
    def __init__(self, path):
        self.database = Database(path, initialize=False)

    def get(self, job_id, user_id):
        with self.database.connect() as db:
            db.execute('BEGIN')
            authorize(db, user_id, job_id)
            return decode(db, db.execute('SELECT * FROM coach_reviews WHERE job_id=? AND reviewer_user_id=?', (job_id, user_id)).fetchone())

    def save(self, job_id, user_id, data):
        with self.database.connect(write=True) as db:
            job = authorize(db, user_id, job_id)
            original, paths, language = snapshots(job)
            existing = db.execute('SELECT * FROM coach_reviews WHERE job_id=? AND reviewer_user_id=?', (job_id, user_id)).fetchone()
            corrections = validate(data, len(paths))
            if data['revision'] != (existing['revision'] if existing else 0):
                raise ConflictError('Review changed in another tab')
            if existing and json.loads(existing['frame_refs_snapshot']) != paths:
                raise ConflictError('Frame sequence changed')
            now = datetime.now(timezone.utc).isoformat()
            if existing:
                review_id = existing['id']
                db.execute('UPDATE coach_reviews SET status=?,corrected_analysis=?,general_comment=?,revision=revision+1,updated_at=? WHERE id=?',
                           (data['status'], json.dumps(corrections, ensure_ascii=False), data['general_comment'], now, review_id))
            else:
                review_id = db.execute('''INSERT INTO coach_reviews
                    (job_id,reviewer_user_id,status,analysis_language,job_created_at,original_analysis_snapshot,
                     frame_refs_snapshot,corrected_analysis,general_comment,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                    (job_id, user_id, data['status'], language, job['created_at'], json.dumps(original, ensure_ascii=False),
                     json.dumps(paths), json.dumps(corrections, ensure_ascii=False), data['general_comment'], now, now)).lastrowid
            keep = {n['frame_index'] for n in data['frame_notes']}
            for row in db.execute('SELECT frame_index FROM coach_frame_notes WHERE review_id=?', (review_id,)).fetchall():
                if row['frame_index'] not in keep:
                    db.execute('DELETE FROM coach_frame_notes WHERE review_id=? AND frame_index=?', (review_id, row['frame_index']))
            for note in data['frame_notes']:
                db.execute('''INSERT INTO coach_frame_notes(review_id,frame_index,note,created_at,updated_at) VALUES (?,?,?,?,?)
                    ON CONFLICT(review_id,frame_index) DO UPDATE SET note=excluded.note,updated_at=excluded.updated_at''',
                    (review_id, note['frame_index'], note['note'], now, now))
            return decode(db, db.execute('SELECT * FROM coach_reviews WHERE id=?', (review_id,)).fetchone())


def dataset_record(review):
    return {
        'schema_version': 1, 'review_id': review['id'], 'job_id': review['job_id'],
        'reviewer_id': review['reviewer_id'], 'job_created_at': review['job_created_at'],
        'analysis_language': review['analysis_language'], 'original_analysis': review['original_analysis'],
        'coach_correction': {k: review['corrections'][k] if review['corrections'][k] is not None else review['original_analysis'][k] for k in FIELDS},
        'changed_fields': {k: review['corrections'][k] is not None and review['corrections'][k] != review['original_analysis'][k] for k in FIELDS},
        'general_comment': review['general_comment'], 'frames': review['frame_references'],
        'frame_notes': review['frame_notes'], 'review_created_at': review['created_at'],
        'review_updated_at': review['updated_at'], 'revision': review['revision'],
    }


def export_records(database):
    with database.connect() as db:
        # Keep review rows and notes in one consistent read snapshot.
        db.execute('BEGIN')
        for row in db.execute("SELECT * FROM coach_reviews WHERE status='saved' ORDER BY job_id,reviewer_user_id,id").fetchall():
            yield dataset_record(decode(db, row))
