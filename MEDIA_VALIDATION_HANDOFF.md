# Isolated Remotion media guard

## Isolation

- Source: `https://github.com/tariq424/video-studio`.
- Independent private copy: `https://github.com/tariq424/video-studio-test`.
  GitHub cannot fork a repository back into the same owning account. The copy
  preserves Git history; `upstream` points to the source and `origin` to the copy.
- Test checkout: `F:\code\video-studio-test`.
- Test server: `127.0.0.1:42021`; test jobs: `F:\videos_test\jobs`.
- No edits or dependency reads from `F:\code\video-studio`. The main listener on
  port 42020 was not restarted. Original job files were read only, never linked
  into writable test fixtures. Copies were used instead.

## Findings

The original log puts the quoted `b2_1.mp4` error in `short_render` at 19:25:21;
the Short then succeeded on retry. The later explainer attempts fail in `assemble`
but their retained error tails do not identify a specific source clip.

The saved `short/public/media/fb/b2_1.mp4` is an 8-second H.264 video: 1080×1920,
30 fps, all 240 frames readable. Strict decoding succeeds. Therefore the saved
file is not proven corrupt; an intermittent compositor failure or an earlier
transient asset state cannot be excluded.

The explainer's saved timeline does expose a deterministic EOF hazard: 36 video
slots can play beyond their source duration when the additional 0.4-second
transition overlap in `remotion/src/Teaser.tsx` is included. For example,
`vid/s1_0.mp4` is 8 seconds, but its timeline can request through 8.389 seconds.
Those backgrounds lack `freezeAt` because the old calculation considers only
the nominal slot. Evidence: `F:\videos_test\evidence\timing-audit.json`.

## Change

New `app/studio/render_media.py` validates the exact staged public-dir files just
before timeline JSON is serialized, covering both normal and edited backgrounds.
Both `explainer.build` and `short.build` call it. It:

- probes the video stream and strictly decodes every frame, with bounded timeouts;
- rejects missing/empty files, decoder errors, missing advertised frames and
  materially truncated duration;
- replaces an invalid video with a headline card, retaining timeline start/slot;
- clamps valid videos' hold/loop timing before EOF, accounting for source start
  and playback rate, so transition overlap cannot seek past the available frames;
- checks repeated files once per timeline build, not via a persistent stale cache;
- logs decisions and never repairs, deletes or changes source media.

If ffprobe/ffmpeg is unavailable or validation times out, the affected video is
replaced with a card. Validation costs one full video decode per unique clip per
build. This is a fail-closed media check, not a guarantee against every Remotion
browser/compositor failure. Original narration and credits are unchanged.

## Reproduce the isolated smoke

Completed result (October 16, 2026): **PASS**. The HTTP-resumed job reached
`status=finished`, `stage=done`. The 1920×1080 output is 26.6 seconds / 798 frames
at 30 fps and passes a strict full decode. Empty and truncated clips became
headline cards; the healthy 8-second source held safely through the longer slot.
Six focused tests pass. Source log/plan/clip SHA256 fingerprints are unchanged.
The test server was shut down; 42021 has no listener. Main 42020 remains PID 4868.

Output: `F:\videos_test\jobs\media_fallback_smoke\output\Media_validation_smoke_explainer_1080p.mp4`.
Evidence: `output-validation.json`, `finished-job.json`, `unit-tests.txt`, before/after
SHA256 files, `fallback-frame.png`, `held-frame.png` and server logs under
`F:\videos_test\evidence`.

The first render attempt hit a fresh-clone setup issue (missing `tsconfig.json`),
then the same fixture was resumed after adding `remotion/tsconfig.json`. That
file is included for standalone-clone setup; it is not required in the code-only
production patch. A local ignored `remotion.config.ts` selected installed Chrome
for this test. No main checkout configuration was copied or read. An earlier
incomplete fixture seed is retained as `media_fallback_seed_incomplete` for audit.

Use a fresh test job directory; the fixture generator refuses to overwrite existing
evidence. Install the app's normal dependencies into the isolated `app/env` and
run `npm ci` inside its own `remotion` directory. Then:

```powershell
cd F:\code\video-studio-test
.\app\env\Scripts\python.exe -m unittest discover -s tests -v
.\app\env\Scripts\python.exe scripts\smoke_media_fallback.py
.\scripts\start-isolated-test.ps1
Invoke-RestMethod -Method Post http://127.0.0.1:42021/api/jobs/media_fallback_smoke/resume
Invoke-RestMethod http://127.0.0.1:42021/api/jobs/media_fallback_smoke
```

This is a real assemble-stage resume through the running server and pipeline,
using deterministic cached narration/captions so AI generation and network services
are not needed. It contains zero-byte and truncated videos plus a copy of the
original 8-second `b2_1.mp4` in a longer slot. It renders a short landscape explainer,
not the full 14-minute original. State/logs/output are in
`F:\videos_test\jobs\media_fallback_smoke`; server logs and source fingerprints
are in `F:\videos_test\evidence`.

Stop only the PID belonging to the isolated server (recorded in evidence/server.pid).
Confirm its command line belongs to this checkout before stopping it. Never stop
the main port 42020 process.

## Manual application to main (user action only)

The production code change is exactly these three files:

1. `app/studio/render_media.py` (new)
2. `app/studio/explainer.py` (one import/call before timeline serialization)
3. `app/studio/short.py` (one import/call before timeline serialization)

No new Python or npm dependencies are required. The main application already uses
ffmpeg/ffprobe. Do not copy test `settings.json` or test startup configuration to
production. A code-only patch is provided in `F:\videos_test\evidence\media-validation.patch`.

After backing up/committing any local production changes, manually run:

```powershell
git -C F:\code\video-studio apply --check F:\videos_test\evidence\media-validation.patch
git -C F:\code\video-studio apply F:\videos_test\evidence\media-validation.patch
```

If the check reports conflicts, reconcile those files manually; do not force/reset
the production checkout. Restart production only when its current jobs are safely
stopped, then resume/re-render through its normal UI. The guard runs again when
the timeline is rebuilt. None of these production commands were executed here.
