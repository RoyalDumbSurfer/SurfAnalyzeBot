# Accounts & Personal History v1

## Architecture

SQLite is the shared database for accounts, invites, revocable sessions, authentication attempt limits, and jobs. Set `DATABASE_PATH` to a persistent local path shared by the web app and worker. SQLite WAL and short write transactions avoid the lost-update races of the old whole-file JSON store. No external database, ORM, new package dependency, or analysis schema change is introduced.

`JobManager` keeps its existing worker-facing methods. Jobs retain their existing metadata and analysis JSON in a payload, with indexed job ID, status, creation time, and account ownership columns. The worker's sampling, analysis provider, result schema, and file generation are unchanged. Use one worker process, as before: claiming work across multiple workers is not implemented.

Account ownership uses `owner_user_id`, a foreign key to `users.id`. The existing `user_id`/`chat_id` retain their legacy or Telegram meaning; they never authorize web access. New web uploads set their authenticated owner explicitly. Telegram-created jobs remain unowned until an explicit account-linking feature is implemented; they cannot leak into an account with a coincidentally equal numeric ID.

## Schema version 1

- `users`: id, unique case-insensitive username, password_hash, role (`user`, `coach`, `admin`), created_at, is_active.
- `invites`: id, unique code_hash, nullable max_uses, used_count, is_active, created_at, optional label. Every registration creates `role=user`; roles cannot be selected through a request.
- `sessions`: hashed random token, user_id, absolute expires_at (seven days).
- `auth_attempts`: hashed limiter bucket, count, expires_at.
- `jobs`: id, nullable owner_user_id foreign key, status, created_at, complete existing job payload.
- `metadata`: schema version and completed legacy snapshot SHA-256.

Username authentication avoids an email delivery/verification dependency. Username rules are 3-40 ASCII letters, digits, dots, underscores, or hyphens, beginning with a letter or digit. Passwords are 15-128 characters and are never truncated.

## Security design

Passwords use Python's scrypt with N=131072, r=8, p=1, a random 16-byte salt, and a 32-byte derived key. This follows the scrypt configuration in the [OWASP Password Storage Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html). Each hash uses approximately 128 MiB; a two-slot semaphore bounds concurrent hashing per process. Provision memory for this plus OpenCV/the worker. An unknown username still runs the password hash. Hashes never appear in public user models or responses.

Invite codes must be generated with a cryptographically secure password manager (at least 24 characters), then entered into the CLI through a hidden prompt. Only their SHA-256 digests are stored. Codes are not rendered, logged, or recoverable. Invite consumption and account creation share one transaction. Failed/duplicate registration does not consume the invite.

The signed HttpOnly account cookie uses `SESSION_SECRET`, SameSite=Lax, and Secure by default. It contains a random opaque session token and a CSRF token, not a password, user role, or invite. The database stores only the session token hash. Login/registration rotate the session and CSRF token and revoke a previous session. Logout is POST-only and revokes the database session, so replaying the old signed cookie fails. Inactive users and expired sessions fail on every request. Cookie renewal cannot extend the server's absolute seven-day expiry.

HTML form submissions require a session-bound CSRF token. API-style requests may supply `X-CSRF-Token` instead. Supplied Origin headers must match the web request origin. Reverse proxy scheme/host forwarding must be configured correctly. Login and registration have persistent limits of 10 attempts per normalized username and 30 per client IP in 15 minutes, shared across web processes; both successes and failures count. Trust forwarded IP information only from the actual local reverse proxy, never arbitrary clients. These limits can temporarily affect people sharing an IP and can be used to temporarily lock out a username. A distributed abuse protection service and CAPTCHA are outside v1.

Every resource performs ownership checks. Another user's result, processing, job API, original file, frame, or download returns the same 404 as a missing resource. Admin/coach roles do not bypass ownership in v1. Frames must appear in that job's recorded frame list. Media files must resolve inside their allowed media root; symlinks below that root and traversal are rejected. Original upload URLs remain compatible; the lookup searches only the authenticated user's jobs. Protected responses use no-store and nosniff.

The shared `PRIVATE_BETA_ACCESS_CODE` no longer grants any access. It can be removed from the environment; the old setting is accepted but unused. `/beta` GET redirects to login, and POST no longer logs in. The unsigned `/telegram-auth` browser identity endpoint is removed. Telegram Mini App display setup remains, but web users must log in to a real account.

The reusable `accounts` services and ownership helper are independent of HTML templates. `/api/me` returns only id, username, and role. Mobile clients can reuse the same authenticated session and CSRF scheme; OAuth/bearer tokens, role-specific screens, subscriptions, quotas, training approval, and coach access are future work.

## Exact production cutover

Use the ordered commands and rollback boundaries in [the production migration runbook](accounts-migration-runbook.md). No production commands have been executed during implementation or review.

No production migration is automatic. Do not run old and new web/worker versions together.

1. Before the maintenance window, back up `jobs_db.json`, `data/uploads/`, `data/extracted_frames/`, `videos_processed/`, and any additional original media directories. Retain ownership and permissions. If SQLite already exists, make a consistent SQLite backup (or stop all writers before copying the database and its WAL files).
2. Pause new uploads and let queued/processing jobs finish under the old worker. Stop the old web app, worker, and any bot process writing jobs. Do not import while the old JSON writer is active.
3. After code approval, install the new code. Keep the existing application working directory so all saved relative media paths still resolve. Do not change media paths as part of this migration.
4. Configure `DATABASE_PATH` to an absolute persistent local SQLite filename shared by the web app/worker/CLI. Default: `data/surfanalyze.sqlite3`. Restrict the database directory, SQLite/WAL files, and backups to the service account. Do not expose it through nginx or place it on a network filesystem.
5. Configure `SESSION_SECRET` to a strong random secret of at least 32 characters, identical across web processes/restarts. Keep `SESSION_COOKIE_SECURE=true` for HTTPS. Keep `MAX_FILE_SIZE=52428800` (50 MiB) and existing API/OpenAI settings. Remove the obsolete `PRIVATE_BETA_ACCESS_CODE` when convenient. No credentials are seeded automatically.
6. Create the first admin in the new SQLite store (password entered twice through hidden prompts):

   ```text
   python -m accounts.cli create-admin --username owner
   ```

   This refuses if any admin already exists. It does not modify any legacy job or media file.
7. Preview the legacy import, then apply it to that admin:

   ```text
   python -m accounts.cli import-legacy --source jobs_db.json --owner owner
   python -m accounts.cli import-legacy --source jobs_db.json --owner owner --apply
   ```

   Every source job, including old anonymous/default/Telegram IDs, is assigned to this chosen owner. IDs, status, timestamps, analysis, frame URLs, original file paths, and files are retained. The old `user_id` is retained as metadata. The JSON source is never rewritten or deleted. The first command validates/counts without inserting jobs; the second imports all jobs and records the snapshot digest in one transaction. Duplicate IDs, malformed records, collisions with existing SQLite jobs, or a missing/inactive admin fail without a partial import. Rerunning the same snapshot does nothing; a different snapshot after import is refused for manual review. Do not delete or rename the source to bypass the startup guard: web/worker startup refuses a missing SQLite database, an existing `jobs_db.json` without its recorded import, or a JSON fingerprint that changed after import. Runtime connections use SQLite `mode=rw` and cannot silently create a replacement database. Dry-run/import and invite administration also require an existing store; the create-admin CLI performs initial bootstrap.

   For a genuinely fresh installation with no legacy JSON, bootstrap the admin/database first; no import is needed. Empty existing JSON lists can also be imported to record the cutover. Jobs left `processing` retain that state, so drain them before cutover rather than silently re-running paid analyses.
8. Create an invite (paste a securely generated code twice through hidden prompts):

   ```text
   python -m accounts.cli create-invite --max-uses 5 --label family
   ```

   Store/share the code privately; stdout reports only the invite ID. Default max uses is one; `--unlimited` allows unlimited uses. Disable an invite with `python -m accounts.cli disable-invite --id INVITE_ID`.
9. Verify nginx forwards all application and media URLs, including `/frames/*`, `/uploads/*`, `/download/*`, through FastAPI. Direct aliases/CDN caches bypass ownership and must not expose these resources. Keep HTTPS and trusted proxy scheme/Host/client-IP forwarding correct. Maintain `client_max_body_size` at least 51 MiB for the default upload limit. No server config is changed by this implementation.
10. Start the new worker and web app using the same database and working directory. Log in as the owner, verify the imported job count/history and older results/frames/downloads, register a second account, and verify it has empty history and cannot access an owner's known URLs. Upload one real surf clip and verify processing, feedback, 15-frame target, Frame Viewer, retry, logout, and session persistence on mobile.

## Rollback and data impact

The existing JSON and media backups are the rollback point. Before allowing new writes, rollback can stop new processes and restore the previous code/config against the unchanged JSON. Once accounts or jobs are created in SQLite, reverting code alone would hide those new records: preserve/back up SQLite and reconcile them before rollback. Do not discard either store. No production records have been imported by the implementation task; all automated migration tests use temporary databases.

Passwords/invites have no browser reset/recovery UI yet. Operators need a separately reviewed recovery action if a password is lost. There is no email verification, MFA, account deletion, admin dashboard, automatic linking of new Telegram jobs, retention policy, or multi-worker job claiming. SQLite suits one machine and a small private audience. Media codecs and the existing analysis worker retain their existing limitations; original files outside `data/uploads` are retained but are not exposed by `/uploads`.

## Validation commands

```text
python -m pytest -q --ignore=tests/test_media_handler.py --ignore=tests/test_integration_bot.py
python -m compileall -q config.py accounts storage jobs/job_manager.py jobs/job_model.py webapp tests/conftest.py tests/test_accounts.py tests/test_private_demo.py
```

The upload regression tests now authenticate as an account. The obsolete shared-beta login tests are replaced by account/invite/ownership tests. Generated-video decoding, the existing worker with only its external AI call mocked, Frame Viewer rendering, upload JavaScript, processing JavaScript, and a local Uvicorn HTTP server are included. Real OpenAI billing calls, live server migration, nginx configuration, and visual mobile/browser QA must be checked separately.
