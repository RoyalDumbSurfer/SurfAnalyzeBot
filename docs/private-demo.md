# Private Demo Readiness v1

> Historical documentation: the shared beta gate and JSON job storage below are superseded by [Accounts & Personal History v1](accounts-v1.md). Use that document for current production setup and migration.

The browser demo uses the existing upload -> JSON job -> worker -> frame extraction -> OpenAI -> result flow. Frame sampling still targets 15 frames, with fewer when only fewer frames are readable. No accounts or job-storage migration are introduced.

## Environment

Configure these on the web application before sharing the demo; do not commit secrets:

| Variable | Default | Purpose |
| --- | --- | --- |
| `PRIVATE_BETA_ACCESS_CODE` | unset | A nonempty value enables the gate. Use a long, randomly generated invitation code. Unset or empty disables it. |
| `SESSION_SECRET` | unset | Set an independent random secret of at least 32 characters. Required when the gate is enabled; startup fails otherwise. Use the same value across web processes/restarts. |
| `SESSION_COOKIE_SECURE` | `true` | Secure cookies for production HTTPS. Set `false` only for local HTTP testing. |
| `MAX_FILE_SIZE` | `52428800` | Existing byte limit, now enforced by web uploads and shown on the upload page (default 50 MiB). Must be positive. |

Sessions use the existing Starlette signed-cookie middleware, with HttpOnly, SameSite=Lax, Secure by default, and a seven-day rolling lifetime. Cookies contain a signed authorization marker, never the access code. Changing either the access code or signing secret invalidates beta access. Without a configured signing secret when beta is disabled, sessions use a random process-local key and do not survive restarts or work reliably across multiple web processes. Existing sessions using the old hardcoded key/cookie will be replaced.

The only gate exception is `/beta` (GET/POST). Protection covers `/`, `/upload`, `/dashboard`, `/dashboard-data`, `/processing/{id}`, `/result/{id}`, `/api/jobs/{id}`, `/download/{id}`, `/telegram-auth`, `/uploads/*`, `/frames/*`, and FastAPI documentation/schema URLs. Unauthenticated API calls receive 401; other protected requests redirect to the gate. Successful login returns to the upload page. Protected responses are marked no-store.

## Upload rules

- Containers: AVI, MKV, MOV, MP4, WebM, matching the existing worker.
- Case-insensitive extension plus matching known MIME type. Missing or `application/octet-stream` MIME is allowed because clients do not always supply it; decoding is still required.
- Nonempty file, at most `MAX_FILE_SIZE` bytes. Exact file size is checked before saving and while copying in 1 MiB chunks.
- Multipart request parsing is bounded to the file limit plus 1 MiB for request overhead, including requests without Content-Length.
- OpenCV must open the file and decode its first frame before a job is created. Actual codec support depends on the installed OpenCV build. This is a basic readability check, not a guarantee that every later frame is valid.
- Rejected uploads do not create jobs; temporary application files are cleaned up. Storage failures and malformed uploads receive safe HTML messages.
- Clip length of 10-30 seconds and one visible ride are recommendations, not enforced duration or content restrictions.

## Deployment checks before sharing

No nginx configuration is version-controlled here, and the live server configuration was not inspected or changed. The actual proxy limit is therefore unknown. Check `client_max_body_size`: it must allow at least `MAX_FILE_SIZE + 1048576` bytes of multipart data (51 MiB for the default limit). A lower proxy limit will reject requests before FastAPI can show its styled error. A larger proxy limit lets the application enforce its own cap. Review any proxy 413 error page separately.

Ensure nginx/CDN routes `/uploads/*`, `/frames/*`, `/download/*` and all application routes through FastAPI. Direct nginx aliases or public object storage for those files would bypass application middleware; remove that bypass or apply equivalent access checks before sharing. Do not cache protected responses. Keep HTTPS enabled and the existing job worker running.

## Scope and limitations

This is shared invitation access, not per-person authorization. Browser visitors retain the existing anonymous user ID 0 and can see shared browser history and known job URLs after entering the code. The existing Telegram identity endpoint is unchanged. Do not use this gate as account isolation.

Wrong-code responses have a short delay, but there is no distributed brute-force limiter. Use a high-entropy code for this small demo. Uploaded media still depends on local OpenCV codecs and available disk space. The JSON job manager and its existing concurrency limitations are unchanged. Live OpenAI billing calls and production nginx behavior are not exercised by local tests.

## Validation

Run:

```text
python -m pytest tests/test_private_demo.py tests/test_job_worker_frame_extraction.py tests/test_surf_analysis_service.py tests/test_openai_surf_analysis_provider.py -q
python -m compileall -q config.py utils/video_formats.py jobs/job_worker.py webapp tests/test_private_demo.py
```

Tests include a generated real video, upload-to-worker-to-result execution with only the external analysis call mocked, route/session checks, failure sanitization, a local Uvicorn HTTP smoke test, and rendered upload JavaScript interactions using Node and a minimal DOM double. The Node test skips if Node is absent. These do not replace visual mobile/browser QA.

The full suite currently cannot collect the two tests importing the unrelated locally modified `handlers/media_handler.py`, because of its existing syntax error at line 25. That file is outside this task and must remain untouched.
