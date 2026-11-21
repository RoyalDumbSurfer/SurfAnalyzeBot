# SurfAnalyze Video Director — web-first roadmap

## Product decision (2026-11-21)

**Primary delivery:** responsive browser web application at surfanalyze.com, usable on Android and iPhone.
**Later:** native Android/iOS clients reusing the same authenticated API and backend.
**Optional:** Telegram bot/mini app as an alternative entry point, not the primary UX.

## Input and current architecture

A completed Job retains the uploaded original ride, ~15 chronological frames and
six structured coach-analysis fields. We must never synthesize or replace the
source surfer's movements when showing coaching evidence.

## Iterative delivery

### Stage 1 — Web Video Director Preview (this PR)

- Show original clip in an authenticated browser player on the result page.
- Coach/admin triggers one additional vision call over stored frames + analysis.
- Model produces **0–3** frame-anchored cues and optional static image arrows.
- Browser pauses near those frame timestamps, renders cue and resumes on request.
- Store immutable versioned `director_plan` in the existing Job JSON (no DB migration).
- AI cue placement is an **unreviewed draft**, NOT an expert-certified correction.
- No new background job, new framework, rendered video, or public API exposure.

**Manual acceptance:** coach can open a finished MP4 on Android Chrome/iOS Safari,
generate a timeline, review the placement, replay; another account cannot access
the source or its plan; original video bytes remain intact.

### Stage 2 — Coach verification and editing

- Editable cues: anchor frame/time, annotation title/note, arrow endpoints.
- Use corrected coach analysis/review notes rather than blindly trusting AI prose.
- Save `reviewed_plan` as separately versioned data; preserve original AI draft.
- Treat changes as expert labels for evaluating the director.
- Add seek/playhead UX, re-generation controls, and explicit per-job cost limits.

### Stage 3 — Render real annotated MP4

- Background render job with persistent status and retry/idempotency.
- FFmpeg render from **original** media, timeline, pause/slow-motion,
  composited 2D arrows, wave zones and captions.
- Preserve original aspect ratio, video fidelity and audio policy; normalize
  browser-incompatible formats for playback.
- Authenticated preview/download; storage quota and garbage collection policy.
- Explicitly test vertical, horizontal, short and variable-frame-rate clips.
- Do not claim anything is tracked between frames without visual tracking.

### Stage 4 — Moving overlays and better timing

- Extract exact source frame timestamps; don't interpolate from 15 samples alone.
- Optical-flow/surfer pose/board tracking when quality allows, with confidence gates.
- Draw arrows/trajectories only at locations backed by actual frames.
- Optional voiced AI narration and multilingual caption timing.

### Stage 5 — Smartphone distribution

- First polish mobile web UX and optionally PWA (installation, home screen).
- Only if justified by usage: Flutter/React Native native Android/iOS clients,
  shared backend auth, uploading and job APIs.
- Telegram remains optional, not a blocker.

## Safety and correctness invariants

- Every media/plan request must require owner authentication; mutations use CSRF.
- Never expose raw filesystem paths, OpenAI keys or private media publicly.
- Do not let untrusted model text become HTML or executable template content.
- AI feedback must be specific and evidence-based; when uncertain, no arrow/cue.
- Source video stays original; any rendered coaching clip is a derivative.
- Avoid deploying model experiments automatically; review UI + tests first.

## Stage 1 known limitations

- Static arrows only, and only at sample frames.
- Equidistant samples approximate timestamps using video duration; long/VFR clips
  may need the source's actual timing metadata.
- Browser decoding depends on uploaded container/codec.
- Extra model call costs API usage and may exceed reverse-proxy timeout.
- The preview is interactive HTML, **not** an exported annotated video.
- The AI plan currently uses saved analysis, not expert edit history.
