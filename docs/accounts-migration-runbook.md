# Accounts v1: production migration and rollback runbook

This is a procedure for a later, explicitly approved deployment. None of these production commands were executed during review. Service names, filesystem paths, and the release commit must come from the actual deployment; no names or secrets are assumed below. Run application/CLI commands as the existing service account, using its Python environment. Keep one worker.

## 1. Identify the deployment and take a preliminary backup

Set these nonsecret shell variables interactively on the server:

```bash
read -r -p 'Existing application working directory: ' APP_DIR
read -r -p 'Existing virtualenv Python executable: ' APP_PYTHON
read -r -p 'Web systemd unit: ' WEB_UNIT
read -r -p 'Worker systemd unit: ' WORKER_UNIT
read -r -p 'Bot systemd unit (empty if none): ' BOT_UNIT
read -r -p 'New backup directory outside the application: ' BACKUP_DIR
read -r -p 'Approved release commit hash: ' RELEASE_COMMIT
cd "$APP_DIR"
umask 077
mkdir -m 700 -- "$BACKUP_DIR"
git rev-parse HEAD > "$BACKUP_DIR/previous-revision"
cp --preserve=all -- .env "$BACKUP_DIR/environment.before"
tar -cpf "$BACKUP_DIR/preliminary-media.tar" -- jobs_db.json data/uploads data/extracted_frames videos_processed downloads
```

The environment backup contains secrets: keep it private and never print or paste it. If environment values come from systemd rather than `.env`, securely back up that actual configuration too and ensure the CLI receives the same settings as the services. Include any additional media roots referenced by legacy jobs. Confirm the archive can be listed/read without printing its contents. This preliminary backup is not the authoritative migration snapshot because writers may still be running.

## 2. Stop writers and take the authoritative snapshot

Stop new upload sources first, then let the old worker finish queued/processing jobs:

```bash
sudo systemctl stop "$WEB_UNIT"
if [ -n "$BOT_UNIT" ]; then sudo systemctl stop "$BOT_UNIT"; fi
"$APP_PYTHON" -c 'import json; from pathlib import Path; jobs=json.loads(Path("jobs_db.json").read_text(encoding="utf-8-sig")); print("Pending jobs:", sum(j.get("status", "queued") in ("queued", "processing") for j in jobs))'
```

Do not proceed until the pending count is zero. Repeat that read-only count while the old worker finishes. A transient JSON read error during a write means retry the read; do not alter the JSON. If a job is stuck, resolve it before this migration. Statuses are preserved; the importer does not silently requeue interrupted paid analyses.

```bash
sudo systemctl stop "$WORKER_UNIT"
sudo systemctl is-active "$WEB_UNIT" "$WORKER_UNIT"
if [ -n "$BOT_UNIT" ]; then sudo systemctl is-active "$BOT_UNIT"; fi
```

Verify they report inactive (the nonzero exit code for inactive is expected). Also verify no manually started bot/worker/web process still writes jobs. Then:

```bash
tar -cpf "$BACKUP_DIR/quiescent-media.tar" -- jobs_db.json data/uploads data/extracted_frames videos_processed downloads
cp --preserve=all -- jobs_db.json "$BACKUP_DIR/jobs_db.json"
sha256sum -- jobs_db.json > "$BACKUP_DIR/legacy.sha256"
tar -tf "$BACKUP_DIR/quiescent-media.tar" > "$BACKUP_DIR/archive-members.txt"
```

If SQLite already exists, stop all its writers and back up the database plus any `-wal`/`-shm` files as a set, or use SQLite's backup API. Never copy only an active database's main file. Do not delete a previous SQLite store or reuse an unrelated one.

## 3. Install the approved release

Check for tracked local edits; stop for review if there are any. Do not discard them.

```bash
git diff --quiet
git diff --cached --quiet
git fetch origin
git switch --detach "$RELEASE_COMMIT"
"$APP_PYTHON" -m pip install -r requirements.txt
```

Retain the existing working directory and all existing media paths. This runbook does not relocate files or create a second working copy of production data.

## 4. Configure without displaying secrets

Edit the existing protected environment file with a local editor, not commands that echo its contents:

```bash
sudoedit "$APP_DIR/.env"
```

Required configuration:

- `DATABASE_PATH`: an absolute local persistent SQLite filename shared by web, worker, and CLI. Its parent directory must be writable only by the service account/administrators. Do not use a network filesystem or public nginx directory.
- `SESSION_SECRET`: the existing strong secret, or a securely provisioned secret of at least 32 characters; identical across web processes. Never put its value into a command argument or this runbook.
- `SESSION_COOKIE_SECURE=true` for production HTTPS.
- `MAX_FILE_SIZE=52428800` for 50 MiB.
- Retain existing Telegram/OpenAI configuration. The obsolete `PRIVATE_BETA_ACCESS_CODE` does not grant account access and may be removed.

Ensure service environment overrides do not point web, worker, and CLI at different databases. Runtime web/worker opens never create a missing SQLite file. They refuse an unimported legacy JSON or a legacy file whose fingerprint changed after import. Do not remove the JSON to bypass these checks.

## 5. Create the owner, preview, then apply

```bash
"$APP_PYTHON" -m accounts.cli create-admin --username owner
"$APP_PYTHON" -m accounts.cli import-legacy --source jobs_db.json --owner owner
```

The owner password is entered twice using hidden prompts. The CLI refuses terminals that cannot hide input. Check the preview job count against the backed-up JSON. Preview creates no jobs and requires an existing bootstrapped SQLite store. Stop on any error.

```bash
"$APP_PYTHON" -m accounts.cli import-legacy --source jobs_db.json --owner owner --apply
sha256sum -c "$BACKUP_DIR/legacy.sha256"
"$APP_PYTHON" -m accounts.cli import-legacy --source jobs_db.json --owner owner --apply
```

The last command must report `already imported: True`, with no duplicate jobs. The first apply assigns every legacy job to the chosen active admin and records the JSON fingerprint atomically. All original keys/values are preserved except the deliberate `owner_user_id` assignment. IDs, status, timestamps, analysis, filenames, thumbnails, frame references, and unknown metadata are retained. Later worker updates alter only their requested fields and `updated_at`, preserving the rest of the payload.

Create an invite only after the import succeeds:

```bash
"$APP_PYTHON" -m accounts.cli create-invite --max-uses 5 --label family
```

Paste a securely generated invitation through hidden prompts. The CLI prints only the invite ID. Do not put the code in shell history, logs, documentation, or a template.

## 6. Start services and smoke-test while access is controlled

Confirm nginx routes `/frames/*`, `/uploads/*`, `/download/*`, and application routes through FastAPI; direct file aliases would bypass ownership. Protected responses must not be cached. Verify HTTPS, trusted proxy scheme/Host/client IP handling, and a request limit of at least 51 MiB.

```bash
sudo systemctl start "$WORKER_UNIT" "$WEB_UNIT"
sudo systemctl is-active "$WORKER_UNIT" "$WEB_UNIT"
curl --silent --output /dev/null --write-out '%{http_code}\n' https://surfanalyze.com/login
curl --silent --output /dev/null --write-out '%{http_code}\n' https://surfanalyze.com/api/jobs/nonexistent
```

Expected HTTP statuses: 200 for login, 401 for the unauthenticated API. Do not print cookies or response headers containing session values.

In separate browser sessions:

1. Log in as owner; verify the imported job count, original filenames, statuses, dates, analysis, frames, and downloads. Check representative old IDs from the backup privately.
2. Register a second account using an invite. Its history must be empty. Exact owner result/processing/API/frame/upload/download URLs must return 404. Nonexistent IDs must have the same response. Guests must get login redirects or API 401.
3. Verify logout and subsequent access denial. Log in again and verify page-to-page persistence.
4. After the checks above, upload a real surf video; verify validation, worker completion, analysis, 15-frame target/short-video resilience, Frame Viewer, and failure/retry paths. This step crosses the simple rollback boundary below.

Do not restart an old bot binary: any bot restarted later must use the new SQLite-backed code. New Telegram jobs remain unowned by web accounts in v1. Verify no old JSON writer remains and reopen the private demo only after these checks pass.

## Rollback before new production jobs

Stop the new web/worker and any new bot. Archive the entire SQLite store and sidecars while stopped, even if it only contains the owner, invitations, sessions, and smoke-test accounts. Do not delete it. Verify `sha256sum -c "$BACKUP_DIR/legacy.sha256"` succeeds and that no SQLite job beyond the imported set exists. Also ensure the new worker has not processed/revised legacy jobs: draining before cutover is what makes this safe.

```bash
sudo systemctl stop "$WEB_UNIT" "$WORKER_UNIT"
if [ -n "$BOT_UNIT" ]; then sudo systemctl stop "$BOT_UNIT"; fi
sha256sum -c "$BACKUP_DIR/legacy.sha256"
PREVIOUS_COMMIT=$(cat "$BACKUP_DIR/previous-revision")
git switch --detach "$PREVIOUS_COMMIT"
"$APP_PYTHON" -m pip install -r requirements.txt
cp --preserve=all -- "$BACKUP_DIR/environment.before" "$APP_DIR/.env"
```

Restore the actual systemd environment backup too if it was changed. The original JSON/media were never overwritten by migration, so normally no media restoration is needed. If checksums or files differ, stop and investigate; do not blindly overwrite data with the archive. Restore missing/corrupt data from the quiescent backup only after that review. Restart the old worker/web only against the preserved original JSON and its original private-beta configuration. Keep public/demo access controlled while verifying the rollback.

## Rollback after SQLite has accepted new jobs or changed legacy jobs

A code-only rollback is unsafe. New jobs/accounts and ownership exist only in SQLite; original JSON does not contain them, and exporting them to the old shared history would break account isolation. Stop writers, take a consistent backup of SQLite/sidecars and all old/new media, and keep both stores. Prefer a forward fix. Any rollback requires an explicitly reviewed reconciliation/export plan that preserves new job IDs, outputs, metadata, timestamps, media, and account privacy. Do not automatically copy new jobs into anonymous JSON or reopen the old shared interface to account-owned data.

The same caution applies to new real registrations even if they have not uploaded yet: keep their SQLite identities and do not pretend the old application supports their accounts.
