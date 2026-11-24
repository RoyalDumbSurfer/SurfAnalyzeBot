# FFmpeg Video Rendering Engine — first usable export

## Plan and implementation

1. Integrate PR #4 and PR #5 on `codex/ffmpeg-video-rendering`. Their merge conflict is limited to the CI test list; retain both suites.
2. Verify Director generation, coach editing, owner isolation, CSRF and revision conflicts. Exercise the real page at desktop and mobile widths.
3. Add a separate renderer consuming only the persisted coach review. Keep the original AI plan, upload and existing analysis worker unchanged.
4. Render normal-speed sections, up to one source second at 0.5x before each cue, and a three-second sampled still with arrow and Unicode comment. Encode a silent H.264/yuv420p MP4 with fast-start metadata.
5. Expose coach-only export and owner-only download. Require the saved revision, cache by review content/revision and engine version, and reject stale downloads after another save.
6. Verify actual encoded duration, codec, pixels, source preservation, failures and the complete browser download flow before opening the PR. No production deployment or main merge.

## Runtime

Install `ffmpeg` and `ffprobe` on PATH with libx264 and drawtext support. Install DejaVu Sans Mono (`fonts-dejavu-core` on Debian/Ubuntu), or set `VIDEO_RENDER_FONT` to a Unicode monospace TTF. Windows defaults to Consolas. No Python dependencies or database migrations are added.

POST `/api/video-director/{job_id}/render/{revision}` requires coach/admin role, ownership and CSRF. It returns the authenticated `/coaching-video/{job_id}/{key}` URL. The download also works for an owner whose coach role was later removed. No direct public filesystem URL is exposed.

Exports live under the existing results directory in `coaching/{job_id}/{key}.mp4`. Temporary segments are cleaned up on ordinary failure and the final file is atomically published. Editing a review makes previous export URLs inaccessible; old files remain on disk pending a future explicit retention policy.

## Deliberate MVP limits

- Videos up to 180 seconds; fixed 3-second pauses and 0.5x slowdown. Export is silent (also stated in the page); source audio remains in the original download.
- At most one active FFmpeg export **per web process**, with a shared 300-second deadline covering probing and encoding. The POST waits in a thread pool; this is not a durable queue. Keep the page open. Reverse proxy timeouts may need attention before any future deployment. A process crash requires a retry and may leave its temporary directory.
- Requires the complete existing `min(15, source frame count)` sample. Legacy/incomplete samples fail closed rather than inventing positions. Sampled JPEGs are the exact visual evidence for arrows. Position in moving video is estimated from frame index and duration; variable frame rate can make this timing approximate. Tracking and exact timestamp persistence are future work.
- Output uses a 960x720 picture area plus a 200px comment panel, with letterboxing for portrait and widescreen sources. Arrows are drawn only on still images.
- No AI request occurs during export. Unsaved browser edits cannot be exported. Repeated requests reuse the saved version; changes during encoding return a conflict.

## Validation commands

Use test-only `API_TOKEN`, `SESSION_SECRET` and `DATABASE_PATH`. Bootstrap the isolated SQLite database before importing legacy Telegram modules:

```sh
python -c "from config import settings; from storage.database import Database; Database(settings.DATABASE_PATH)"
python -m pytest -q
python -m compileall -q services jobs webapp tests
```

For real browser coverage, install Playwright outside the repository and set `SURFANALYZE_PLAYWRIGHT_MODULE` and `SURFANALYZE_BROWSER_EXECUTABLE` (Chromium/Edge). Run `python -m pytest -q tests/test_director_browser.py`. The fixture starts loopback Uvicorn with synthetic video and temporary accounts; no production data or OpenAI calls are used.

## Review findings and local results (2026-11-24)

- Resolved the PR #4/#5 workflow conflict in this integration branch only.
- Fixed SVG arrow visibility: assigning `.hidden` on SVG did not remove the HTML attribute. Browser tests now assert actual visibility.
- Preview pauses now display the exact stored JPEG instead of relying on approximate browser seeking for arrow evidence.
- Disable editor controls during a save to prevent edits from disappearing beneath the returned saved revision.
- Repaired five obsolete Telegram test expectations/mocks without changing Telegram handlers, and corrected the unsupported pytest `python_paths` option.
- Full suite: **223 passed, 4 optional browser tests skipped**. Subsequent focused run after the final fixes and an additional portrait case: **33 passed** (renderer, Director, review, web and i18n). Python compilation passed; no repository lint/type configuration was found.
- Real Edge/Chromium browser flow passed at **1280, 390 and 320px**: sampled pause and visible arrow, text edit/save/reload, add/delete, dirty-export guard, actual MP4 export and download. Page and encoded-frame screenshots were visually inspected; this caught and fixed Windows CRLF caption clipping.
- Actual FFmpeg tests cover landscape and portrait, first/middle/final cues, encoded duration, H.264/yuv420p, visible arrow/comment pixels, source preservation, cache reuse, ownership/role/CSRF, stale reviews, failure cleanup and probe limits.
- Remaining verification: physical Android/iOS devices, live paid model generation and production proxy behavior were not exercised. Existing Starlette deprecation warnings remain. Main and production were not modified.
