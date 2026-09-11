# Coach Review v1

Coach Review is a private feedback layer. It never updates a job's AI analysis,
calls an AI provider, changes sampling, or translates saved coaching text.
Admins and coaches can review only jobs they own. Normal users cannot see the
controls or access either coach API method. There is no cross-owner review queue.

## Storage and migration

`coach_reviews` has a unique `(job_id, reviewer_user_id)` pair, draft/saved status,
language, job creation timestamp, immutable original six-field analysis and frame
sequence snapshots, corrected six-field JSON, general comment, revision, and UTC
creation/update timestamps. `coach_frame_notes` holds unique `(review_id,
frame_index)` notes with timestamps. Foreign keys cascade when the referenced job,
review, or reviewer is deleted. No binaries are stored in SQLite.

The first successful save (including a draft) freezes the original six fields,
language, and ordered frame URLs. A database trigger prohibits changing these
snapshots. The existing `jobs.payload` is never updated by Coach Review. Frames
are numbered **1 through N** in the UI, API, database, and export; Frame 8 refers
to element 7 of the existing extracted sequence. New extraction is not performed.
Saving after a frame sequence change is rejected to avoid reattaching notes to
different images. Snapshot URLs must be local `/frames/<job-id>/<filename>` URLs.

The migration is additive and transactional. It uses its own
`metadata.coach_schema_version=1`; the existing account/job `schema_version=1`
remains unchanged so the existing worker and rollback code remain compatible.
New explicit database bootstraps include the tables. Existing databases require:

```sh
python -m coach.cli migrate
# Rehearse against a COPY using an explicit path:
python -m coach.cli --database /private/rehearsal.sqlite3 migrate
```

Repeat runs are safe. The web app refuses startup without the coach migration;
it never silently migrates the production database during startup.

Before production migration, take a consistent SQLite backup with `Connection.backup`,
verify its integrity and all 14 legacy job payloads/owners, and rehearse on a second
copy. Compare all existing users, sessions, invites, auth attempts and jobs before
and after; run the migration twice and check `PRAGMA foreign_key_check` and
`PRAGMA integrity_check`. Keep the original backup untouched. Back up the deployed
code or retain its exact SHA. During deployment briefly stop web writes, back up
again, migrate the existing database in place, then restart the web service.
No database replacement or destructive migration is required. Roll back code if
needed, leaving the additive tables and any reviews intact; do not restore an old
database over newer production data.

## UI and API

On a completed six-field result, open **Coach Review / Review AI analysis**.
Each field shows the immutable original alongside a large correction textarea.
Blank corrections mean unchanged; arbitrary field erasure is not a v1 feature.
The general comment is separate. Review controls remain private even after saving.

In Frame Viewer, open **Coach note**, type a note, and press **Save frame note**.
This saves all current edits together, initially as a draft. **Save Coach Review**
marks the review saved and makes it eligible for dataset export. **Save draft**
keeps it out of the dataset. Stepping/swiping frames preserves unsaved notes in
the page. Removal, including clearing a previously saved note, asks for confirmation.
Dirty-page navigation warns before leaving. Validation, network, and stale-version
errors leave the entered text in place; copy edits before reloading a stale tab.

`GET /api/coach-reviews/{job_id}` returns only the current reviewer's review.
`POST` saves the full document, requires the existing session, authorized role,
CSRF header, origin check, owned completed job and expected revision. Payload:

```json
{
  "revision": 0,
  "status": "saved",
  "corrections": {"level": null, "main_issue": "Correction", "why_it_matters": null,
                  "how_to_fix": null, "drill": null, "coach_note": null},
  "general_comment": "Optional comment",
  "frame_notes": [{"frame_index": 8, "note": "Specific correction"}]
}
```

Revision 0 creates; updates require the last returned revision and increment it.
Concurrent stale saves return 409 instead of overwriting. Missing notes in the
full list are removed transactionally. Text limits are 4,000 characters per
correction/note, 8,000 for the general comment, and 512 KiB for the whole request.
Unknown fields, duplicate/out-of-range indices, and unfinished jobs are rejected.
Server errors do not echo submitted text. Templates escape text, embedded JSON
uses Jinja `tojson`, and browser status/note updates use text/value properties.

## Dataset and internal export

The maintenance CLI requires operating-system access to the private SQLite file;
there is **no web export endpoint** and no session/token workaround. Run only in a
trusted maintenance shell with a private output directory:

```sh
python -m coach.cli export-coach-dataset --output /private/coach_dataset.jsonl
```

Only saved reviews are included. UTF-8 JSONL is ordered by job ID, reviewer ID,
then review ID; fields are serialized with sorted keys. Export uses one consistent
read transaction. Empty datasets produce an empty file. Exclusive file creation
refuses overwrites and requests owner-only permissions on Unix; a failed export
removes its partial output. Treat all exported coaching text as private data.

`coach.store.dataset_record` provides schema version 1 records containing review,
job and reviewer IDs; job/review timestamps; revision; recorded analysis language;
all six original fields; all six effective coach fields; explicit `changed_fields`
booleans; general comment; ordered frame references; and ordered frame notes.
Null/blank corrections resolve deterministically to the immutable original text.
No passwords, account names, session/invite tokens, provider keys, original video
paths, filenames, or binaries are selected. Coach-entered free text is not an
automatic secret/PII scrubber; reviewers must avoid adding such material.

## Limits and next stages

One private review per owner/reviewer and job. No cross-owner permissions, review
sharing, autosave, approval workflow, or review deletion API. Legacy language can
be null when not recorded; UI language switches do not translate stored text.
Results without a complete six-field original are not reviewable. Frame binaries
remain in existing storage; the snapshot fixes references, not copies of files.
Normal storage backup/retention must preserve those media files for future use.

Future direction: **Coach Review dataset → retrieval/examples → evaluation suite
→ Surf Intelligence improvements**. Retrieval, prompt changes, model adaptation,
fine-tuning and automatic data submission are deliberately not implemented.

## Validation

```sh
python -m pytest -q tests/test_coach_review.py tests/test_accounts.py tests/test_accounts_adversarial.py tests/test_admin_invites.py tests/test_private_demo.py tests/test_i18n.py tests/test_job_worker_frame_extraction.py tests/test_surf_analysis_service.py tests/test_openai_surf_analysis_provider.py
```

Tests use temporary databases and mocked analysis providers. The production
acceptance smoke is not a Coach Review test: it creates jobs and incurs OpenAI
calls. Verify production with read-only health/schema/integrity checks and the
owner's authenticated phone session instead.
