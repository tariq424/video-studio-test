# Z006 RESULT — POC fix: Blender route (r11) camera bug on Blender 5.2.3

**Status: DONE — r11 ends `ok`, mp4 rendered. Pushed to `poc/media-routes`.**
Date: 2026-11-03. Only file changed: `media-poc/routes.py` (the BLENDER_SCRIPT string) + this RESULT.

## The fix (per the spec's option 1 + 2, both)
- Camera handling is now idempotent on a factory-startup scene: reuse the existing scene camera
  when present (`scene.camera or new`), set `scene.camera = cam`, and guard the collection link with
  a membership check (`if cam.name not in bpy.context.collection.objects`). The original
  "Object 'Camera' already in collection" RuntimeError is gone.
- The light pattern did not need the same guard (ops `light_add` links its own new object); the
  default scene light stays, exactly as the original design kept it.

## Two further Blender 5.2.3 API-drift fixes inside the same BLENDER_SCRIPT (found live during the acceptance run)
1. `scene.render.image_settings.file_format = 'FFMPEG'` → TypeError on 5.2.3: movie output moved
   behind a new `image_settings.media_type` switch. Fix: set `media_type = 'VIDEO'` when the enum
   offers it (try/except TypeError on older Blender), then `file_format = 'FFMPEG'`.
2. Engine id: `'BLENDER_EEVEE_NEXT'` is rejected by 5.2.3 (probe: BLENDER_EEVEE_NEXT fails,
   BLENDER_EEVEE works). Fix: try `('BLENDER_EEVEE_NEXT', 'BLENDER_EEVEE', 'CYCLES')` in order.

## Acceptance
1. `python selfcheck.py` → **PASS** — server imports clean, 11 routes registered (unchanged registry).
2. Server restarted from the updated code (`/healthz` ok, port 42054), then `POST /api/run/r11`:
   - Status: **`ok`** in **45.8 s** (blender located at
     `C:\Users\Tarri\AppData\Local\Programs\Blender Foundation\blender-5.2.3-windows-x64\blender.exe`
     via `find_blender()`, logged on the card)
   - Output: `media-poc/output/r11_blender_video.mp4` exists — **52,183 bytes** (4 s, 1280×720, 24 fps,
     96 frames, EEVEE orbit of the primitive jet). Left on disk for Tariq to judge (no QC gate in the POC).
3. This commit + RESULT pushed to `poc/media-routes`. No other file touched; route registry unchanged;
   the Z007 commits already on the branch were pulled before the fix was applied (no conflict — they
   touch browser routes and the deepseek parser, not BLENDER_SCRIPT).

## Git
- `poc/media-routes`: fix commit on top of 27ffb88 (SPEC-Z007 amendment), RESULT file at repo root.
