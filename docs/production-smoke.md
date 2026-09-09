# Production acceptance smoke

`scripts/production_smoke.py` retains the acceptance checks and secret-safe failure
diagnostics used during the accounts and bilingual UI rollout. It reports the
owner login HTTP status and, on failure, only the exception type, function, and
line number. It never prints passwords, cookies, response bodies, or exception
messages.

Run manually on the application host, using its virtual environment and the same
working directory, database, and environment as the web app and worker:

```sh
/opt/SurfAnalyzeBot/.venv/bin/python scripts/production_smoke.py \
  --app-dir /opt/SurfAnalyzeBot \
  --base-url https://surfanalyze.com \
  --owner denis \
  --report /root/smoke-report-new.json
```

Use a real TTY for the hidden owner password prompt. The report path must be new
and its parent directory must exist. Do not use Python optimization (`-O`), which
disables assertions. Run only against a deployment whose local database and media
correspond to the supplied HTTPS origin. The script expects the migrated
`jobs_db.json`, Russian default UI, a 50 MiB upload limit, accessible completed
owner jobs, and at least one real MP4 small enough to upload.

This is a **mutating acceptance test**, not a health probe. It creates an invite,
account, sessions, and a real upload; the worker performs a paid OpenAI analysis.
It checks migrated history, resource isolation in both directions, language
persistence, invalid-file and oversized-upload rejection, the Russian result and
15 frames, and logout cookie replay. It does not test invalid invite rejection.
The `finally` block disables the temporary account and invite, including when
registration succeeds but its response cannot be read. It retains the smoke job,
media, and database rows for inspection. Forced termination or cleanup failure
requires operator follow-up; do not interpret `complete` alone as cleanup success.
Require both `complete: true` and `temporary_account_and_invite_disabled: true`.

`--passwordless` is partial diagnosis only: it skips owner login, owner resource
access, and reverse isolation. Its `passwordless_complete` is not full acceptance.
A failed owner login is reported without attempting credential repair.

## Milestone closeout: 2026-09-09

The operator confirmed full production acceptance, including invalid invite
rejection, real Russian analysis with 15 frames, bidirectional isolation, and
temporary account/invite deactivation. The earlier owner login 401 was an
incorrectly entered password; no authentication behavior change was needed.

Read-only closeout verification confirmed all 14 migrated jobs retain their
original payloads and owner, the legacy JSON matches its backup, SQLite integrity
is `ok`, both services are active, `/login` returns 200, and unauthenticated
`/api/me` returns 401. The acceptance script was not rerun during closeout because
it writes production data. The one-off login/environment diagnostic was removed.
