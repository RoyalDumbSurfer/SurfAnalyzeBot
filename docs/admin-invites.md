# Admin invites

Admins open **Admin → Invites**, press **Create invite**, then **Copy link**.
Each press creates a new active invitation with one permitted registration using
the existing invite store. Only the SHA-256 token hash is stored in SQLite.
An optional label identifies the invitation. Expiry defaults to seven days;
one day, 30 days, and explicitly selected no-expiry are available. Share privately
and copy before leaving the page: raw links cannot be recovered from the list.

The mobile list shows status, creation/expiry in UTC, usage, enabled state, and the
activating username/time. An unused invitation can be disabled after checking its
confirmation box. Used invitations remain visible and cannot be disabled in the UI.
History is paginated, newest first. Non-admin users receive 403; guests go to login.

`POST /api/invites` requires an active admin session, CSRF token, and the existing
same-origin check. It returns only `{"url": "https://surfanalyze.com/register?invite=..."}`
with HTTP 201 and `Cache-Control: no-store`. It ignores client-supplied roles,
usage limits, and hosts. No password or raw token is logged by this endpoint.
Form fields are `label` (up to 100 characters), `expiry` (`1`, `7`, `30`, or `none`),
and `csrf`. Management uses `GET /admin/invites` and
`POST /admin/invites/{id}/disable` (`confirmed=yes`, `csrf`). Both enforce admin role;
mutations enforce CSRF and origin. The list contains no token hashes or raw codes.

Opening the link saves the invitation in the existing signed HttpOnly session
cookie and immediately redirects to `/register` without a query string or HTML.
The token-bearing redirect uses `Referrer-Policy: no-referrer`. The clean GET form
uses `same-origin`, so browser form POSTs supply the expected Origin. Applying
`no-referrer` to the form itself caused browsers to send `Origin: null`, rejecting
legitimate mobile registration. Those POST error documents also replayed on refresh.
All registration POST errors now redirect 303 to a clean GET with a safe localized
message; success redirects 303 to the dashboard. Origin/CSRF checks remain strict.
The invitation is applied on
registration without manual entry and survives validation errors and language
changes. Successful registration clears the pending invitation as the session
rotates. An explicitly entered manual code takes precedence. Validation and atomic
single-use consumption remain in `AccountStore.register`.
An authenticated visitor to registration returns to the dashboard. Pending invites
are rechecked inside `BEGIN IMMEDIATE` at submission: opening a link reserves
nothing. User insertion, usage increment, activator, and activation time commit
together. Expiry is invalid at `expires_at <= now`. Revocation uses the same write
lock and only updates unused invites, so activation versus disable has one winner.
Username collisions roll back without consuming the invite. Invalid, used, expired,
and disabled invitations have distinct RU/EN messages on GET and after POST.

Copy uses the Clipboard API; if unsupported or denied, the link is selected for
manual copying with localized instructions. There is no automatic retry of invite
creation after a network error, as the original request might have succeeded.

## Deployment

The repeatable additive migration adds nullable `expires_at` (UTC Unix seconds),
`used_by_user_id` (foreign key to users), and `used_at` (UTC ISO timestamp) to the
existing invites table, plus `invite_schema_version=1` metadata. It preserves
every existing column and row. Existing invites keep no expiry; old activations
show "Not recorded" because their identity/time cannot be reconstructed. Existing
CLI multi-use invites retain their semantics; the fields show the **last** activation.
The CLI now defaults to seven days and accepts `--expiry-days` or `--no-expiry`.

Rehearse on a consistent SQLite production copy twice, comparing all original
columns in all tables and checking integrity/foreign keys. Stop web writes briefly,
take and verify a fresh SQLite backup, preserve the old code archive/SHA, then
fast-forward the checkout and run:

```sh
.venv/bin/python -m accounts.invite_migration
```

Compare preserved data before starting the web service. The app refuses startup
without this migration. No dependency, worker, analysis, or base schema version
changes. Retain the previous code SHA for emergency code rollback; never restore
an old database over newer production data. Old code can read the additive schema,
but would not enforce expiry, so stop registrations if a rollback becomes necessary.
Do not run the production acceptance script; it creates jobs and calls OpenAI.

Before enabling invite URLs, configure the SurfAnalyze nginx access log to omit
query strings and referrers (both can contain bearer tokens). In the HTTP context:

```nginx
log_format surfanalyze_private '$remote_addr - $remote_user [$time_local] '
    '"$request_method $uri $server_protocol" $status $body_bytes_sent';
```

Set `access_log /var/log/nginx/surfanalyze-access.log surfanalyze_private;` in both
SurfAnalyze server blocks. Back up the existing site config, run `nginx -t`, then
reload nginx. Uvicorn's application-installed access filter also removes the query
from `/register` request targets. Do not enable request body/cookie logging or
proxy debug logging. Verify redaction with a synthetic invalid token, never a real
invitation. Preserve existing backups and all production data during deployment.

Verify `/login` is 200, guest `/api/me` and `POST /api/invites` are 401, both services
are active, SQLite integrity is OK, and the 14 migrated jobs still match their
legacy payloads and owner. Creating an actual invite requires an existing admin
browser session; do not mint a session or change credentials for deployment tests.

## Tests

`python -m pytest -q tests/test_invite_management.py tests/test_admin_invites.py tests/test_accounts.py tests/test_accounts_adversarial.py tests/test_i18n.py tests/test_private_demo.py`

All invite creation and registration tests use temporary local databases. The
JavaScript interaction test covers create, copy, clipboard fallback, and failures.
`tests/test_invite_mobile.py` starts an isolated loopback app and runs
`tests/invite_mobile.cjs` with temporary accounts. Set `SURFANALYZE_PLAYWRIGHT_MODULE`
to a local Playwright installation, optionally `SURFANALYZE_BROWSER_EXECUTABLE`,
or `SURFANALYZE_BROWSER_ENGINE=webkit`. It covers 320/390px layouts, create/copy,
disable, expiry, RU/EN, clean URLs/referrers, the actual browser Origin header,
POST/redirect/GET, refresh/back/forward, and two-device replay. Clipboard is mocked
to avoid placing test links in the operator's clipboard. No production smoke or
OpenAI call is involved. Browser extensions and a recipient's deliberate copying
of the original shared URL remain outside application control; no application
HTML or analytics receives the bearer query.
