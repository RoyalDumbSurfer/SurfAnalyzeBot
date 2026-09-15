"""Private operator CLI. Offline only: never imports/calls an analysis provider."""
import argparse
import json

from coach.knowledge import build_coach_context, expert_examples, set_eligibility
from storage.database import Database


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True)
    parser.add_argument('--query', default='')
    parser.add_argument('--job')
    parser.add_argument('--review', type=int)
    parser.add_argument('--language', choices=['ru', 'en'])
    parser.add_argument('--approve', type=int, metavar='REVIEW_ID')
    parser.add_argument('--revoke', type=int, metavar='REVIEW_ID')
    parser.add_argument('--admin', type=int, metavar='ADMIN_ID')
    args = parser.parse_args()
    database = Database(args.database, initialize=False)
    if args.approve is not None or args.revoke is not None:
        if not args.admin or (args.approve is not None and args.revoke is not None):
            parser.error('Specify one approval/revocation and an active --admin ID')
        set_eligibility(database, args.approve if args.approve is not None else args.revoke,
                        args.admin, args.approve is not None)
    examples = expert_examples(database)
    query, job_id, language = args.query, args.job, args.language
    if args.job:
        with database.connect() as db:
            row = db.execute('SELECT payload FROM jobs WHERE id=?', (args.job,)).fetchone()
        if not row:
            parser.error('Job not found')
        payload = json.loads(row[0])
        query = query or payload.get('original_filename') or ''
        language = language or payload.get('analysis_language')
    if args.review:
        review = next((e for e in examples if e['review_id'] == args.review), None)
        if not review:
            parser.error('Eligible expert review not found')
        query = query or ' '.join([*review['corrections'].values(), review['general_comment'], *[n['note'] for n in review['frame_notes']]])
        job_id = review['job_id']
    _, metadata = build_coach_context(examples, query, job_id=job_id, language=language)
    print(json.dumps({'available': [{k: e[k] for k in ('review_id', 'job_id', 'revision', 'tags')} for e in examples],
                      'retrieval': metadata}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
