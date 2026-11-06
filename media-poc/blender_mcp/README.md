# r11 - Blender over MCP

Route r11 turns a text description into a photorealistic Cycles video, driving Blender **only through MCP**
(the `mcp-for-blender` server and the MCP for Blender add-on). There is no `blender.exe --background`.

```
description ─► qwen3:14b via Ollama (loaded on demand, unloaded right after) ─► shot plan (JSON schema)
                                                                                     │
uvx mcp-for-blender (stdio MCP, BLENDER_MCP_SAFE_MODE=1, DISABLE_TELEMETRY=true) ◄───┘
   │  search_assets / import_asset → Poly Haven HDRI sky, PBR ground, real models (true scale)
   │  execute_blender_code → scene_lib.py: layout, motion, camera, Cycles settings
   ▼
live Blender (started on demand, add-on on :9876) → Cycles GPU frames → Blender closed → ffmpeg → MP4
```

## GPU discipline
- Holds Video Studio's own lock (`app/studio/gpu_lock.py`, `F:\code\gpu.lock`) for the whole GPU phase.
- Checks free VRAM before rendering: 6 GB for preview, 10 GB for final
  (`BLENDER_VRAM_PREVIEW_MB` / `BLENDER_VRAM_FINAL_MB`). It waits up to 10 minutes, then fails with
  "GPU busy".
- Starts Blender only if it isn't already open. Closes it when the frames are done: the scene is saved,
  a polite close is tried, then it is force-closed after 5 s. Blender usually keeps a quit prompt open
  for its unsaved Render Result image, so the force close is normal and loses nothing. If Blender was
  already open, it is left open and only the scene is emptied.
- The planner model is unloaded before Blender starts (`keep_alive: 0`).

## Safe mode
Safe mode rejects scripts that import anything beyond bpy/bmesh/mathutils/pure stdlib, touch files or
`os`, register handlers or timers, or call `quit_blender`. `scene_lib.py` stays inside those rules:
- its text plus one call is sent per step, so nothing is imported inside Blender;
- state is kept as JSON on the scene;
- Blender is closed from outside.

`tests/test_blender_mcp_poc.py` runs the server's own validator over the library.

## Result
`pipeline.render()` returns `status` `ok`, or `partial` when a subject has no photoreal asset (Poly Haven
has no people, animals, aircraft or buildings; enable Sketchfab in Blender's MCP panel to cover them).
A `Blocked` error gives a precise reason (no Blender / uvx / ffmpeg / Ollama / model).

Files go to `output/r11_blender/`: `r11.log`, `still.png`, `frames/`, `scene.blend`, `video.mp4`,
`job.json` (plan, assets, VRAM peak and after). `BLENDER_QUALITY=final` switches r11 to 1080p, 256 samples.
