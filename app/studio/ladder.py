"""The visual ladder for Short beats that stock footage / real photos didn't cover (step 1 runs in short_stock / photos):
  2a. Cloud still (Gemini, then ChatGPT; cloudgen.py) -> coherence check; skipped for beats naming a real person
  2b. WanGP still (from the beat's still_prompt) - only when 2a gave nothing usable -> coherence check
  3. WanGP image-to-video of that still           -> coherence + garble check on 3 frames      => tag GENERATED
  4. Parallax of the still (depth layers)         -> used when step 3 fails but the still passed => tag PARALLAX
  5. 3D reconstruction (subject beats) / headline card (other beats)                            => tag RECONSTRUCTION (in Recon.tsx)
No visual is used just because it exists: a step whose output fails the check escalates to the next one.
GPU work is batched (all stills, then all checks, then all animations, then all checks) so WanGP and the Ollama vision
model don't keep pushing each other out of video memory."""
import json, shutil
from pathlib import Path
from . import media
from .llm import parse_json

CHECK = """This {what} will be shown full-screen in a news Short while the narrator says:
"{narration}"
{subject}
First look at the picture and describe what it ACTUALLY shows, then judge it. Reply with ONLY JSON, in this order:
{{"seen": "max 15 words: what the picture actually shows - the subject, the setting, and where it is (in the air, landing, on the
  ground, inside) and, for an aircraft, its attitude (nose up/climbing, level, nose down/descending)",
 "fits": "yes" or "no" - does it show what this sentence describes: the same kind of subject, the same moment and action
  (e.g. a plane diving if the narration says it dropped, on the ground if it says it landed or sat on the tarmac) and the same mood
  (tense for an emergency, never cheerful)?,
 "marks": true or false - any readable text, letters, numbers, logo, brand name, airline name or livery lettering, flag or registration,
  or anything that looks like a screenshot, video thumbnail, TV-channel logo or another channel's watermark?,
 "garbled": true or false - melted or deformed objects, broken shapes, extra or missing limbs, warped faces, impossible geometry{extra}?,
 "why": "max 12 words: what the narration needs that the picture does NOT show - it must agree with \"seen\""{worst}}}"""

def space(sd):
    """Frame of the workspace: Shorts are portrait (default); the long-video edit workspace has short/space.json = landscape."""
    sp = {"orient": "portrait", "still_res": "1088x1920", "i2v_res": "720x1280", "w": 1080, "h": 1920}
    f = Path(sd) / "space.json"
    if f.exists():
        try: sp.update(json.loads(f.read_text(encoding="utf-8")))
        except Exception: pass
    return sp

def _yes(v): return str(v).strip().lower() in ("true", "yes", "1")

def check(cfg, img, narration, subject=None, video=False, info=None):
    """-> (ok, reason). Fails closed: if the vision model can't judge it, the visual isn't used.
    info (dict) receives extras: "worst" (1-3, the worst frame of a video strip)."""
    from .footage import _vision
    if cfg.get("vet_provider", "local") == "off": return True, "unchecked (vetting off)"
    subj = ""
    if subject:
        subj = (f"The story is about {subject.get('name')}. The picture should show the same kind of thing (same type, shape and colours), "
                f"but it must NOT show its name or logo.")
    prompt = CHECK.format(what="video clip (three frames from it, left to right)" if video else "AI-generated picture",
                          narration=narration[:500].replace('"', "'"), subject=subj,
                          extra=", or the subject changing shape between the frames" if video else "",
                          worst=',\n "worst_frame": 1, 2 or 3 - the frame that looks worst' if video else "")
    try: j = parse_json(_vision(cfg, img, prompt))
    except Exception as e: return False, f"check unavailable ({str(e)[:50]})"
    seen = str(j.get("seen", "")).strip().rstrip(".")[:90]
    why = str(j.get("why", "")).strip().rstrip(".")[:80]
    if seen: why = f"shows {seen[0].lower() + seen[1:]}" + (f"; needs: {why}" if why else "")   # the reason quotes what the model saw
    if info is not None:
        try: info["worst"] = max(1, min(3, int(j.get("worst_frame", 2))))
        except (TypeError, ValueError): info["worst"] = 2
    if _yes(j.get("garbled", False)): return False, "garbled" + (f": {why}" if why else "")
    if _yes(j.get("marks", False)): return False, "shows text/logo/flag"
    if str(j.get("fits", "no")).strip().lower() != "yes": return False, "doesn't fit the narration" + (f": {why}" if why else "")
    return True, why

def nose_side(cfg, img):
    """'left' or 'right': the side of the picture the aircraft's nose points to (a blind look; default right)."""
    from .footage import _vision
    try:
        j = parse_json(_vision(cfg, img, 'Look only at the aircraft. Reply with ONLY JSON: {"nose": "left" or "right" - the side of the picture its nose points toward}'))
        return "left" if str(j.get("nose", "")).lower().startswith("l") else "right"
    except Exception: return "right"

def _rel(p, sd): return str(Path(p).relative_to(sd)).replace("\\", "/")

def run(cfg, wg, sd, fd, slots, log, stop, gpu, seed=5100, full=False, animate=False, pause=None):
    """slots: [{"key", "beat", "vo", "still_prompt", "motion", "subject"}] -> {key: {"still": path|None, "still_ok", "still_why",
    "clip": path|None, "clip_ok", "clip_why", "clip_secs", "clip_worst"}}. State is kept in fallback/ladder.json so Resume doesn't redo work.
    full=True (Review every beat / Show all options): animate every still, also the ones that failed their check, so the
    reviewer sees every treatment; otherwise the ladder stops at the first step that passes.
    pause: called at each safe point (between generations / checks); raises debug.Paused when 'Pause now' was pressed."""
    pause = pause or (lambda: None)
    from . import render, footage
    sf = fd / "ladder.json"
    st = json.loads(sf.read_text(encoding="utf-8")) if sf.exists() else {}
    def save(): sf.write_text(json.dumps(st, indent=1), encoding="utf-8")
    for s in slots: st.setdefault(s["key"], {})
    def check_all():
        todo = [s for s in slots if st[s["key"]].get("still") and "still_ok" not in st[s["key"]]]
        if not todo: return
        try: footage.ensure_vet_model(cfg, log)
        except Exception as e: log(f"  {str(e)[:160]}")
        for s in todo:
            try: pause()
            except Exception: footage.unload_vet_model(cfg); raise
            r = st[s["key"]]; ok, why = check(cfg, sd / r["still"], s["vo"], s.get("subject"))
            r["still_ok"], r["still_why"] = ok, why
            if s.get("rotate") and r.get("src") != "cloud": r["nose"] = nose_side(cfg, sd / r["still"])   # which way to turn it (WanGP, directional beats)
            save()
        footage.unload_vet_model(cfg)
    # step 2a: cloud still (Gemini -> ChatGPT); skipped for beats that name a real person
    from . import cloudgen
    if cfg.get("cloud_on", True) and cloudgen.providers_of(cfg):
        aspect = "9:16" if space(sd)["orient"] == "portrait" else "16:9"
        for s in slots:
            if stop(): raise RuntimeError("cancelled")
            r = st[s["key"]]
            if "cloud" in r: continue
            pause()
            if s.get("person"): r["cloud"] = None; r["cloud_why"] = "names a real person: cloud skipped"; save(); continue
            if not s.get("still_prompt"): r["cloud"] = None; r["cloud_why"] = "no scene prompt"; save(); continue
            dst = fd / f"cloud_{s['key']}.png"
            res = cloudgen.generate(cfg, s["still_prompt"], dst, aspect, log, f"cloud {s['key']}", job=sd.parent)
            r["cloud"] = _rel(dst, sd) if res["ok"] else None
            r["cloud_provider"], r["cloud_why"], r["cloud_tries"] = res.get("provider"), res.get("why", ""), res.get("tries", [])
            if res["ok"]:
                r["still"], r["src"] = r["cloud"], "cloud"
                for k in ("still_ok", "still_why", "nose"): r.pop(k, None)
            save()
        check_all()
        for s in slots:   # a cloud still that fails its check goes to WanGP (its reason is kept for the chain)
            r = st[s["key"]]
            if r.get("src") == "cloud" and r.get("still_ok") is False:
                r["cloud_why"] = f"check: {r.get('still_why', '')}"; r["src"] = "cloud_rejected"
                for k in ("still", "still_ok", "still_why"): r.pop(k, None)
                save()
    if not gpu:
        for s in slots:
            if not st[s["key"]].get("still_ok"): st[s["key"]].setdefault("still_why", "WanGP not available")
        save(); return st
    # step 2b: WanGP stills (only where the cloud gave nothing usable)
    from . import wangp as _wg; is_down = getattr(_wg, "is_down", lambda: False); UNREACHABLE = getattr(_wg, "UNREACHABLE", "WanGP not reachable")   # tolerate an older wangp already loaded in a running server
    for i, s in enumerate(slots):
        if stop(): raise RuntimeError("cancelled")
        r = st[s["key"]]; img = fd / f"{s['key']}.jpg"
        if r.get("src") == "cloud": continue
        if s.get("wan") is False:   # illustrations come first; WanGP only for atmospheric filler (see illustrate.wangp_lock)
            r["still_why"] = f"WanGP skipped: {s.get('wan_why')}"; save(); continue
        pause()
        if "still" in r and (r["still"] is None or img.exists()): continue
        if not s.get("still_prompt"): r["still"] = None; r["still_why"] = "no scene prompt"; save(); continue
        why = "WanGP failed"
        if not img.exists() and is_down():
            why = "WanGP not reachable: skipped"
        elif not img.exists():
            try:
                g = wg.gen({"model_type": cfg["still_model"], "prompt": s["still_prompt"] + render.STYLE, "resolution": space(sd)["still_res"],
                            "num_inference_steps": 4, "seed": seed + i}, log, f"still {s['key']}", stop=stop)
                if g["ok"]: shutil.copy(g["file"], img)
                elif UNREACHABLE in str(g.get("err")):
                    why = "WanGP not reachable: skipped"; log("  WanGP is not reachable: skipping WanGP for the remaining slots")
            except Exception as e: log(f"  still {s['key']} failed ({str(e)[:100]})")
        r["still"] = _rel(img, sd) if img.exists() else None
        if r["still"] is not None: r["src"] = "wangp"
        if r["still"] is None: r["still_why"] = why
        save()
    check_all()
    # step 3: image-to-video of the stills that passed
    # animation (step 3) only on an explicit click (Show all options / Add animation -> animate=True); never in the
    # pipeline, Review every beat, Approve auto or Approve all remaining
    if animate and cfg.get("short_i2v", True):
        for i, s in enumerate(slots):
            if stop(): raise RuntimeError("cancelled")
            r = st[s["key"]]; mp = fd / f"{s['key']}_i2v.mp4"
            if not (r.get("still_ok") or (full and r.get("still"))) or "clip" in r and (r["clip"] is None or mp.exists()): continue
            if not media.ok(mp):
                try:
                    g = wg.gen({"model_type": cfg.get("short_i2v_model") or cfg["video_model"], "prompt": (s.get("motion") or s["still_prompt"]) + render.STYLE,
                                "image_prompt_type": "S", "image_start": str((sd / r["still"]).resolve()), "resolution": space(sd)["i2v_res"],
                                "video_length": int(cfg.get("short_i2v_frames", 169)), "num_inference_steps": int(cfg.get("short_i2v_steps", 8)), "seed": seed + 400 + i},
                               log, f"animate {s['key']}", stop=stop)
                    if g["ok"]: shutil.copy(g["file"], mp)
                except Exception as e: log(f"  animation {s['key']} failed ({str(e)[:100]})")
            r["clip"] = _rel(mp, sd) if media.ok(mp) else None
            if r["clip"] is None: r["clip_why"] = "WanGP image-to-video failed"
            else: r["clip_secs"] = round(media.dur(mp), 2)
            save()
        todo = [s for s in slots if st[s["key"]].get("clip") and "clip_ok" not in st[s["key"]]]
        if todo:
            try: footage.ensure_vet_model(cfg, log)
            except Exception as e: log(f"  {str(e)[:160]}")
            for s in todo:
                r = st[s["key"]]; strip = fd / f"{s['key']}_i2v_strip.jpg"
                info = {}
                try: media.frames_strip(sd / r["clip"], strip); ok, why = check(cfg, strip, s["vo"], s.get("subject"), video=True, info=info)
                except Exception as e: ok, why = False, f"frame check failed ({str(e)[:50]})"
                r["clip_ok"], r["clip_why"], r["clip_worst"] = ok, why, info.get("worst", 2); save()
            footage.unload_vet_model(cfg)
    else:
        for s in slots: st[s["key"]].setdefault("clip_why", "not animated (on demand: Add animation)")
    save()
    return st
