# SPEC-Z006 — POC fix: Blender route (r11) camera bug on Blender 5.2.3

Repo: tariq424/video-studio-test, branch `poc/media-routes`, file: `media-poc/routes.py`
(the BLENDER_SCRIPT string used by r11_blender_video). Single-issue fix; touch nothing else.

## The bug (observed live, Nov 3, 2026, after Blender was installed)
Blender is now installed (5.2.3 LTS, portable, at
`%LOCALAPPDATA%\Programs\Blender Foundation\blender-5.2.3-windows-x64\blender.exe`;
the POC's find_blender() locates it — the route RAN). The render then failed in
1.1 s with:

    scene.camera = cam; bpy.context.collection.objects.link(cam)
    RuntimeError: Error: Object 'Camera' already in collection 'Collection'

The script's cleanup keeps the default scene's existing Camera (and Light), then
creates a new camera object and links it into a collection it is already in.

## The fix
In BLENDER_SCRIPT, make camera (and light, if the same pattern applies) handling
idempotent on a factory-startup scene:
- Reuse the existing scene camera when one is present (set its location/rotation
  and point it at the subject as the script intends), OR guard every
  `objects.link(...)` with a membership check (`if ob.name not in collection.objects`).
- Keep the rest of the scene exactly as designed (primitive jet, ground, sun/sky,
  camera orbit, EEVEE, ~3–4 s mp4 at OUT/r11_blender_video.mp4).

## Acceptance — all reported in Z006-RESULT.md at the repo root of this branch
1. `python selfcheck.py` still passes (11 routes).
2. Restart the POC server from the updated code, then `POST /api/run/r11` and poll
   `/api/state`: r11 ends with status `ok` and `media-poc/output/r11_blender_video.mp4`
   exists (report its size and the render seconds from the state).
3. Commits + Z006-RESULT.md pushed to `poc/media-routes`. No other file changed.
