# Surf Intelligence v1

## Architecture and audit

`coach/knowledge.py` reads saved Coach Reviews directly in a consistent SQLite read transaction. Existing reviews already contain immutable original six-field AI snapshots, corrected fields, general comments, frame indices/notes, original frame references, timestamps, revision, language, reviewer and job identity. `saved` is the final state; `draft` is never knowledge. No video or frame files are copied and the export contract stays unchanged.

Active admins' saved reviews on their own completed jobs are eligible by default. This includes Denis's admin reviews. An active coach's saved review requires explicit approval from an active admin through the private operator command below. Ordinary users never qualify, even with an approval record. Revocation, draft state, deletion, inactive/demoted users, incomplete jobs and ownership changes remove eligibility immediately on the next retrieval. Nonempty expert coaching content remains eligible even without recognized concept tags. Reviews with no changed corrections, nonblank general comment or frame notes are skipped.

Approval records use the existing `metadata` table and bind to revision plus immutable job/reviewer/creation identity, preventing approval reuse after deletion. An explicitly approved review must be approved again after editing. Revocation remains effective after editing. No SQL schema migration is required. Admin-created reviews without an explicit override remain automatically eligible after saving edits. Role administration and access architecture are unchanged.

## Retrieval and context

The worker retrieves when processing a new queued job, before its existing single provider call. New jobs have no semantic visual description. Concepts in the original filename are **weak, unverified hints**, never diagnosis. RU/EN normalization maps coaching terms to gaze, takeoff, stance, balance, compression, weight transfer, direction, line choice, bottom turn, rotation, timing and wave section. Historical features come from actual corrections, comments and notes, never historical AI alone.

When hints exist, candidates need a concept overlap and rank by Jaccard overlap (intersection / union), then matching language, then most recently updated review (descending ID breaks timestamp ties). No overlapping examples means no context. Without hints, up to three examples are supplied as `background_only_no_visual_match`: two recent distinct examples (matching language first), then one remaining distinct example ordered by a stable SHA-256 of target job ID and review ID. This third slot varies across jobs without random state; an offline query without a job ID uses recency for all slots. Exact expert-content duplicates are skipped after whitespace/Unicode normalization, ignoring original AI wording and historical frame indices. Shared tags never suppress distinct coaching text. Untagged examples participate fully in background selection. This is general guidance, not visual relevance ranking. A source job is excluded from its own retrieval.

At most four matched examples or three background examples fit inside a hard 12,000 UTF-8 byte context cap. Oversized examples are skipped intact to avoid cutting off negations. Context contains clearly separated ORIGINAL AI OBSERVATION (only corrected fields), EXPERT COACH CORRECTION, FRAME-SPECIFIC EXPERT NOTES and GENERAL COACH PRINCIPLE. The representation retains all original fields for offline inspection. Provider requests contain no historical media, source identifiers, usernames or timestamps. Review text may itself contain personal information; admins must curate content suitable for reuse.

Context goes from `build_coach_context` through the worker and `analyze_surf_frames` to the OpenAI provider as historical JSON in user content, after the unchanged chronological images. Higher-priority provider instructions reject embedded commands, prohibit copying/disclosure, preserve RU/EN and the six-field schema, and require independent evidence from current frames. These are layered model instructions, not a mathematical guarantee against model prompt injection. Empty context preserves the previous provider request shape. Saving reviews never invokes OpenAI. Retrieval database errors fall back to the original analyzer and record a safe error code.

## Observability and offline operations

Job payloads store retrieval version, normalized query tags, selected source IDs/revisions/tags, reason, selection basis (concept rank, recent or job rotation), score, context bytes, approximate tokens, and SHA-256 fingerprints of each supplied example and the full context. They store no duplicate historical text. Hashes identify exact supplied content but cannot reconstruct older text after a review is edited. Old jobs deserialize without this optional metadata. Only an authenticated admin/coach viewing their own completed result sees the compact knowledge section. Ordinary result and job API responses do not expose provenance.

Run from the repository root with private filesystem access:

```text
python -m coach.evaluate --database data/surfanalyze.sqlite3
python -m coach.evaluate --database data/surfanalyze.sqlite3 --query gaze --language en
python -m coach.evaluate --database data/surfanalyze.sqlite3 --job JOB_ID
python -m coach.evaluate --database data/surfanalyze.sqlite3 --review REVIEW_ID
python -m coach.evaluate --database data/surfanalyze.sqlite3 --approve REVIEW_ID --admin ADMIN_ID
python -m coach.evaluate --database data/surfanalyze.sqlite3 --revoke REVIEW_ID --admin ADMIN_ID
```

The CLI shows available expert references/tags, selected examples, scores/reasons and approximate context size without printing review prose. `--review` uses that eligible review's expert text as an offline diagnostic query, excludes its source job, and does not simulate visual understanding. Job mode uses the same filename hints as the worker. No option calls OpenAI. The database's OS permissions protect this maintenance interface; `--admin` identifies the approving administrator and is not a replacement for OS access control.

## Validation and rollout

Run the new deterministic fixtures plus existing provider, worker, coach, account, invite, upload and frame-viewer suites. No real AI calls are needed. Back up SQLite consistently before deployment, record immutable table/media fingerprints, deploy only a clean fast-forward commit, restart existing services, check health and unchanged data. No infrastructure or credential changes are needed. Existing users, jobs, invites, reviews and files must remain intact. Do not replay old jobs.

Manual acceptance: as Denis/admin, save a final review containing a clear gaze correction. Upload a new relevant surf clip named `gaze-check.mp4` with the desired RU/EN language. Confirm completion with six fields, chronological frames and working Frame Viewer. Expand the knowledge section and confirm the expected review ID/revision. Confirm the analysis independently describes the new clip, rather than copying the old correction. Use an ordinary account's existing session to confirm no knowledge section is visible. A second generic-name upload, if desired, exercises the explicitly marked background fallback. Each upload incurs the normal single analysis call; automated acceptance uses mocks.

## Intentionally deferred

No embeddings/vector database, visual semantic retrieval, fine-tuning, automatic training, model-weight changes, overlays, redesign, new upload description UI, replayable review revision archive, measured model-quality benchmark, or automatic paid comparison. The offline tests measure context selection/injection, not real-world coaching accuracy. Retrieval policy version 2 uses recency and deterministic job-based rotation, not semantic similarity or a trained quality score. Filename hints remain weak; untagged examples do not pretend to match a tagged query. The existing single-worker limitation remains.

## Implementation verification (2026-09-15)

- Broad regression: 187 passed, 3 skipped with media-handler, bot integration and the existing command-handler test excluded. The command-handler greeting mismatch was separately reproduced from an untouched `main` archive. The unrelated local media-handler edit was preserved byte-for-byte.
- Final focused retrieval/service checks: 17 passed, including approval-ID reuse, fallback on database errors, RU/EN, context limits, mocked single-call provider integration, original-result preservation and private provenance.
- WebKit mobile coach/frame-viewer and invite flows: 2 passed against a local Uvicorn server with CDN network access. The knowledge section is opened and checked at 320 px and 390 px. No production users or invites were created/consumed.
- Compile checks and diff whitespace checks passed. Existing pytest `python_paths` and Starlette template deprecation warnings remain.
- Independent cross-review found and closed the approval-ID reuse bug; no remaining blocking findings. Production preflight found 4 users, 20 jobs, 9 invites, one saved admin review, two frame notes, no active jobs, and 291 media files. Read-only retrieval confirmed the saved expert review is usable.

## Retrieval balancing verification (2026-09-23)

- Regression fixture reproduces six final reviews with overlapping tags and an untagged general comment. Recent reviews are selected, all six distinct lessons get an opportunity across target job IDs, and self-review exclusion remains enforced.
- Focused command: `python -m pytest tests/test_coach_knowledge.py -q -p no:cacheprovider` (20 passed). Coverage includes exact duplicates versus distinct same-topic lessons, timezone-aware update recency, untagged approval/revocation, full-content preservation and byte limits.
- Broader coach, worker, provider/service, account, invite, localization and upload/result suites: 190 passed, one optional browser test skipped. Separate local WebKit mobile acceptance passed at 320px and 390px after restoring the temporary browser test dependency. Existing pytest configuration and Starlette deprecation warnings remain.
- Independent retrieval and deployment cross-review passed. No six-field contract or provider-call changes. Compile and whitespace checks passed. Production preflight found 27 jobs, 7 reviews, 8 frame notes, 4 users, 9 invites and 417 media files, with no active jobs.

Rollout tool: `scripts/deploy_intelligence.py --old OLD_SHA --target TARGET_SHA` checks production only; add `--apply` to make a protected SQLite/media backup and deploy the already-pushed commit from `origin/main` (or an explicit `--target-ref origin/BRANCH`) in detached HEAD without merging main. It must run from the production repository with its Python environment. It refuses tracked local changes, an unexpected HEAD, a mismatched remote target, non-fast-forward history or active jobs. The SQLite backup is integrity-checked and every table digest is compared with the source; every archived media file is hashed and verified before checkout. All SQLite tables and media fingerprints must match across checkout before services restart. A post-check failure is a failed rollout, even if the services restart; investigate and explicitly recover rather than claiming acceptance.
