# Admin invites

Admins can press **Create invite** on any authenticated page, then **Copy link**.
Each press creates a new active invitation with one permitted registration using
the existing invite store. Only the SHA-256 token hash is stored in SQLite. The
model has no expiry field; no schema migration is required. Share the link privately.
The existing CLI can disable an invite if needed.

`POST /api/invites` requires an active admin session, CSRF token, and the existing
same-origin check. It returns only `{"url": "https://surfanalyze.com/register?invite=..."}`
with HTTP 201 and `Cache-Control: no-store`. It ignores client-supplied roles,
usage limits, and hosts. No password or raw token is logged by this endpoint.

Opening the link saves the invitation in the existing signed HttpOnly session
cookie and immediately redirects to `/register` without a query string or HTML.
The redirect uses `Referrer-Policy: no-referrer`. The invitation is applied on
registration without manual entry and survives validation errors and language
changes. Successful registration clears the pending invitation as the session
rotates. An explicitly entered manual code takes precedence. Validation and atomic
single-use consumption remain in `AccountStore.register`.

Copy uses the Clipboard API; if unsupported or denied, the link is selected for
manual copying with localized instructions. There is no automatic retry of invite
creation after a network error, as the original request might have succeeded.

## Deployment

No dependency, worker, schema, or analysis changes. Fast-forward the application
checkout and restart `surfanalyze-web`. Retain the previous code SHA for rollback.
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

`python -m pytest -q tests/test_admin_invites.py tests/test_accounts.py tests/test_accounts_adversarial.py tests/test_i18n.py tests/test_private_demo.py`

All invite creation and registration tests use temporary local databases. The
JavaScript interaction test covers create, copy, clipboard fallback, and failures.
