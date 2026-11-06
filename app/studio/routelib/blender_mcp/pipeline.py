"""One Blender-MCP job: text -> plan -> scene over MCP -> Cycles frames -> MP4.

GPU order (load on demand, unload at the end):
  take GPU lock -> plan with qwen3 -> unload qwen3 -> check free VRAM -> start Blender
  -> build + render over MCP -> close Blender -> release lock -> encode MP4 on the CPU.
Result status: "ok", or "partial" when subjects had no photoreal asset (the ladder can fall through).
"""
import asyncio
import json
import re
import shutil
import subprocess
import time
from pathlib import Path

from . import gpu, planner
from .layout import CAM_AZ_DEG, layout, parse_search, relevance

FPS = 24
ASSET_RES = {"preview": {"model": "2k", "hdri": "2k", "tex": "2k"},
             "final": {"model": "4k", "hdri": "4k", "tex": "4k"}}
INDOOR = re.compile(r"studio|indoor|interior|room|warehouse|garage|hall|kitchen|office", re.I)


class Blocked(Exception):
    """A precise reason the route cannot run right now (maps to the POC's Blocker)."""


def preflight():
    if not gpu.find_blender():
        raise Blocked("Blender not installed")
    if not shutil.which("uvx"):
        raise Blocked("uvx not found (needed to run the MCP for Blender server)")
    if not shutil.which("ffmpeg"):
        raise Blocked("ffmpeg not on PATH (needed to encode the frames)")
    up, has = planner.available()
    if not up:
        raise Blocked("Ollama is not running (planner model %s)" % planner.MODEL)
    if not has:
        raise Blocked(f"planner model {planner.MODEL} not pulled in Ollama")


async def _find(mcp, query, kind, source="polyhaven", min_size=None, strict=True, attributes=None):
    args = {"source": source, "query": query, "limit": 8}
    if source == "polyhaven":
        args["asset_type"] = kind
    if min_size:
        args["min_size_m"] = min_size
    found = []
    if attributes:
        try:
            found = parse_search((await mcp.tool("search_assets", dict(args, attributes=attributes)))[0])
        except Exception:
            found = []
    if not found:
        found = parse_search((await mcp.tool("search_assets", args))[0])
    if not found:
        return None
    if not strict or kind == "hdris":
        return found[0]
    best = max(found, key=lambda a: relevance(query, a))
    return best if relevance(query, best) >= 0.5 else None


async def _build_and_render(mcp, plan, job, frames, quality, aspect, frames_dir, log):
    res = ASSET_RES[quality]
    text, _ = await mcp.tool("get_addon_status")
    st = json.loads(text)
    log(f"Blender {st.get('blender_version')}, add-on {'.'.join(map(str, st.get('addon_version', [])))}, "
        f"telemetry {'ON' if st.get('telemetry_consent') else 'off'}")
    await mcp.py("import bpy\nbpy.context.scene.blendermcp_use_polyhaven = True\nprint('{\"ok\": true}')")
    sketchfab = (st.get("libraries") or {}).get("sketchfab") == "on"
    for i in range(600):
        if not (await mcp.scene("render_status")).get("running"):
            break
        if i == 0:
            log("Blender is busy with another render - waiting")
        await asyncio.sleep(3)

    await mcp.scene("reset", FPS, frames)

    tod = plan["sky"]["time_of_day"]
    attrs = None if INDOOR.search(plan["sky"]["query"]) else (
        {"weather": "overcast"} if tod == "overcast" else {"time_of_day": {"golden hour": "sunset"}.get(tod, tod)})
    sky = await _find(mcp, plan["sky"]["query"], "hdris", attributes=attrs)
    if sky:
        await mcp.tool("import_asset", {"source": "polyhaven", "id": sky["id"], "asset_type": "hdris", "resolution": res["hdri"]})
        await mcp.scene("sky_adjust", plan["sky"]["strength"], 0)
        job["assets"]["sky"] = sky["id"]
        log(f"Sky: {sky['name']} ({sky['id']})")
    else:
        await mcp.scene("sky_fallback", tod)
        log("Sky: no HDRI matched - procedural physical sky")

    if plan["water"]:
        await mcp.scene("make_water", 200, frames, FPS)
        log("Water: ocean surface")
    elif plan["ground"]["query"]:
        g = await _find(mcp, plan["ground"]["query"], "textures", min_size=2, strict=False)
        tex = (g or {}).get("size") or [2.0]
        await mcp.scene("make_ground", 200, tex[0])
        if g:
            await mcp.tool("import_asset", {"source": "polyhaven", "id": g["id"], "asset_type": "textures",
                                            "apply_to": ["BV_Ground"], "resolution": res["tex"]})
            job["assets"]["ground"] = g["id"]
            log(f"Ground: {g['name']} ({g['id']}), {tex[0]} m tiles")

    dims, by_id = {}, {}
    for o in plan["objects"]:
        a, source = await _find(mcp, o["query"], "models"), "polyhaven"
        if not a and sketchfab:
            a, source = await _find(mcp, o["query"], "models", source="sketchfab"), "sketchfab"
        if not a:
            job["missing"].append(o["name"])
            log(f"No photoreal model for '{o['query']}' - skipped")
            continue
        key = f"{source}:{a['id']}"
        if key in by_id:
            got = await mcp.scene("alias", o["name"], by_id[key])
        else:
            await mcp.scene("snapshot")
            args = {"source": source, "id": a["id"]}
            if source == "polyhaven":  # Poly Haven models are already true to scale
                args.update(asset_type="models", resolution=res["model"] if o["name"] == plan["hero"] else "2k")
            else:
                args["target_size"] = o["size_m"]
            await mcp.tool("import_asset", args)
            got = await mcp.scene("adopt", o["name"])
            by_id[key] = o["name"]
        dims[o["name"]] = got["dims"]
        job["assets"]["objects"][o["name"]] = key
        log(f"Model: {o['name']} <- {a['name']} ({a['id']}), " + " x ".join(f"{v:.2f}" for v in got["dims"]) + " m")
    if plan["hero"] not in dims:
        plan["hero"] = next(iter(dims), "")

    spots = layout(plan, dims)
    for o in plan["objects"]:
        if o["name"] in spots:
            await mcp.scene("place", o["name"], spots[o["name"]])
            if o["motion"] != "none":
                await mcp.scene("animate", o["name"], o["motion"], o["motion_speed"], frames, FPS)
    await mcp.scene("fog", plan["fog"], 200)
    cam = await mcp.scene("camera", plan["hero"], plan["camera"]["move"], plan["camera"]["lens_mm"],
                          plan["camera"]["handheld"], plan["camera"]["depth_of_field"], frames,
                          plan["camera"]["speed"], aspect, CAM_AZ_DEG)
    log(f"Camera: {plan['camera']['move']}, {cam['lens']} mm, {cam['distance']} m from {cam.get('hero') or 'scene centre'}")
    rs = await mcp.scene("render_setup", quality, frames_dir.as_posix(), plan["exposure"], aspect)
    log(f"Render: Cycles on {rs['device']}, {rs['samples']} samples, {rs['res'][0]}x{rs['res'][1]}, {frames} frames")

    try:
        await mcp.scene("still", (frames_dir.parent / "still.png").as_posix(), max(1, frames // 2))
        job["still"] = str(frames_dir.parent / "still.png")
        log("Preview still rendered")
    except Exception as e:
        log(f"Preview still skipped: {str(e)[:160]}")
    await mcp.scene("save_blend", (frames_dir.parent / "scene.blend").as_posix())

    for f in frames_dir.glob("*.png"):
        f.unlink()
    await mcp.scene("start_render")
    t0, idle, peak = time.time(), 0, 0
    while True:
        await asyncio.sleep(3)
        done = len(list(frames_dir.glob("frame_*.png")))
        v = gpu.vram()
        if v:
            peak = max(peak, v[0])
        try:
            running = (await mcp.scene("render_status")).get("running", True)
        except Exception:
            running = True
        if done >= frames and not running:
            break
        if not running:
            idle += 1
            if idle >= 3:
                raise RuntimeError(f"render stopped at frame {done}/{frames} (cancelled in Blender?)")
        else:
            idle = 0
    job["vram_peak_mb"] = peak
    log(f"Rendered {frames} frames in {time.time() - t0:.0f} s (GPU memory peak {peak} MB in use, whole card)")
    # Rendering marks the file changed again; save so Blender can close without a "save changes?" prompt.
    await mcp.scene("save_blend", (frames_dir.parent / "scene.blend").as_posix())


def _encode(frames_dir, out_mp4, log):
    log("Encoding MP4 (H.264, CRF 17)")
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS),
                        "-i", str(frames_dir / "frame_%04d.png"), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-crf", "17", "-preset", "slow", "-movflags", "+faststart", str(out_mp4)],
                       capture_output=True, text=True)
    if r.returncode != 0 or not out_mp4.is_file():
        raise RuntimeError("ffmpeg failed: " + (r.stderr or "")[-300:])


async def _run(desc, aspect, work, quality, duration_s, log):
    frames = int(round(duration_s * FPS))
    frames_dir = work / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    job = {"status": "failed", "assets": {"sky": None, "ground": None, "objects": {}}, "missing": [],
           "quality": quality, "aspect": aspect, "frames": frames}

    with gpu.gpu_lock("media-poc r11 blender-mcp", log):
        v = gpu.vram()
        if v:
            log(f"VRAM at start: {v[0]} MB used, {v[1]} MB free")
        log(f"Planning with {planner.MODEL} (loaded on demand)")
        job["plan"] = plan = await asyncio.to_thread(planner.plan_shot, desc)
        await asyncio.to_thread(planner.unload)
        log(f"Plan: '{plan['title']}' - {len(plan['objects'])} object(s), camera {plan['camera']['move']}, "
            f"sky '{plan['sky']['query']}'; planner unloaded")
        await asyncio.to_thread(gpu.wait_for_vram, quality, log)

        proc = None
        if gpu.port_open():
            log("Blender is already open - using it, and leaving its window open afterwards")
        else:
            proc = await asyncio.to_thread(gpu.start_blender, log)
        try:
            from .client import BlenderMCP
            async with BlenderMCP(errlog_path=work / "mcp-server.log") as mcp:
                try:
                    await _build_and_render(mcp, plan, job, frames, quality, aspect, frames_dir, log)
                finally:
                    if proc is None:
                        try:
                            await mcp.scene("free_memory")
                            log("Emptied the scene so its GPU memory is released")
                        except Exception:
                            pass
        finally:
            if proc is not None:
                await asyncio.to_thread(gpu.close_blender, proc, log)
            v = gpu.vram()
            if v:
                job["vram_after_mb"] = v[0]
                log(f"VRAM after Blender: {v[0]} MB used, {v[1]} MB free")

    out_mp4 = work / "video.mp4"
    await asyncio.to_thread(_encode, frames_dir, out_mp4, log)
    job["video"] = str(out_mp4)
    job["status"] = "partial" if job["missing"] else "ok"
    log(f"Done: {job['status']}" + (f" (no model for: {', '.join(job['missing'])})" if job["missing"] else ""))
    return job


def render(desc, aspect="16:9", work_dir=None, quality="preview", duration_s=4, log=print):
    """Synchronous entry point. Returns the job dict; raises Blocked for precise blockers."""
    preflight()
    work = Path(work_dir) if work_dir else Path.cwd() / "blender_job"
    work.mkdir(parents=True, exist_ok=True)
    logf = work / "r11.log"
    logf.write_text("", encoding="utf-8")

    def _log(m):
        line = time.strftime("%H:%M:%S ") + m
        with open(logf, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        log(line)
    job = asyncio.run(_run(desc, aspect, work, quality, duration_s, _log))
    (work / "job.json").write_text(json.dumps(job, indent=1), encoding="utf-8")
    return job
