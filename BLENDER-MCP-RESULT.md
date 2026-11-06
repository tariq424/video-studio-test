# BLENDER-MCP RESULT - POC route r11 rewired to Blender over MCP (2026-11-05, Claude)

Branch `feature/blender-mcp` (from main ca4cfb0). Tariq's requirement: Blender must be driven through MCP.

## What changed
- `media-poc/routes.py` r11: the direct `blender.exe -b` script (keyword -> primitives, Nishita sky) is gone.
  r11 now calls `media-poc/blender_mcp/` and returns an MP4. The route contract is unchanged; Blocker is
  raised for precise blockers.
- `media-poc/blender_mcp/`: planner (local qwen3:14b via Ollama, JSON schema), MCP client
  (`uvx mcp-for-blender`, Python MCP SDK, `BLENDER_MCP_SAFE_MODE=1`, `DISABLE_TELEMETRY=true`), safe-mode-clean
  Blender scene library, layout, GPU discipline, pipeline. See `media-poc/blender_mcp/README.md`.
- `media-poc/requirements.txt`: + `mcp>=1.20`.
- `tests/test_blender_mcp_poc.py`: layout, parsing, plan normalising, and the MCP server's own safe-mode
  validator run over every script r11 sends.

## Proof (live runs on the PC, RTX 5060 Ti 16 GB, Blender 5.2.3, add-on 1.8, safe mode ON)
| Run | Prompt | Result |
|---|---|---|
| 1 | vintage camera on a wooden table, studio, dolly in (16:9) | ok - 1280x720, 96 frames H.264; camera sits on the table, nothing blocks the lens; render 554 s |
| 2 | mossy boulders and ferns, misty forest, sunrise, crane up (9:16) | partial (one boulder query had no model) - 720x1280, 96 frames; render 186 s |

Run 1 was slow because Cycles persistent data was off (the scene was re-uploaded every frame). It was
turned on for run 2, giving about 3x the speed. That is safe because Blender is closed after the job.

GPU memory (whole card, nvidia-smi):

| Point | Used |
|---|---|
| Baseline (other apps) | ~3.0-3.1 GB |
| Planner | loaded and unloaded (`ollama ps` empty afterwards) |
| Peak during render | 6.7 GB (run 1), 5.8 GB (run 2) |
| After Blender closed | 3.2 GB |

So nothing from r11 stays in VRAM. Video Studio's GPU lock (`F:\code\gpu.lock`) was held from planning
until Blender was closed, and released before the MP4 encode.

Safe mode facts found on the way:
- it blocks `quit_blender`, so Blender is closed from outside after saving;
- it blocks reaching Cycles device preferences through a subscript (`addons["cycles"].preferences`);
  `addons.get("cycles").preferences` passes.

Suite: 157 passed, 4 skipped, 1 failed - the known WSL `test_bash_syntax` environment failure only.

## Open / not done
- 1080p `final` quality has not been run live yet (`BLENDER_QUALITY=final`).
- Blender still shows its quit prompt after saving (probably the unsaved Render Result image), so the close
  is forced after 5 s. Nothing is lost.
- Distant ground shows texture tiling. The Poly Haven library has no people, animals, aircraft or buildings
  (reported as `partial`); Sketchfab can be enabled in Blender's MCP panel to cover them.
- Not wired into Video Studio's ladder yet. That waits for the merger order.
