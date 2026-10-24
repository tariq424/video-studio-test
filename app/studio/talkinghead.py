"""Talking head for Shorts through a Hugging Face Space (no local GPU): a presenter photo + the hook beat's narration ->
a short lip-synced clip, laid over the Short as a round picture-in-picture for that beat.

Which Space: settings talking_head_spaces (in order; the first one that answers wins). Spaces change their inputs, so
the call is built from the Space's own API description: the image input gets the photo, the audio input gets the
narration, everything else keeps the Space's default. scripts/talking_head_probe.py finds Spaces that work today and
prints the list to put in settings. Optional: any failure leaves the Short as it was (never fails the job).

Engines (talking_head): "hf" = Hugging Face Spaces (default), "off". "wangp" exists in code but is NOT to be used: the owner
rejected WanGP talking heads (no lip sync, stutter, freezes) and does not want WanGP at all. It only runs for a Short with
"presenter" ticked.

Settings: talking_head ("wangp" | "hf" | "off"), talking_head_spaces, talking_head_max_secs (10), talking_head_timeout (600),
presenter_image ("" = one presenter photo made once with Hugging Face FLUX and kept next to the jobs folder)."""
import json
import re
import shutil
import time
from pathlib import Path

from . import media

SPACES = ["fffiloni/sonic", "fudan-generative-ai/hallo", "BadToBest/EchoMimic", "vinthony/SadTalker"]   # candidates; the probe refines
PRESENTER_PROMPT = ("Head and shoulders portrait of a friendly news presenter in his 40s looking straight at the camera, "
                    "neutral expression with lips closed, even studio lighting, plain dark blue background, sharp focus on the face, "
                    "photorealistic. No text, no logos.")
VIDEO_EXT = (".mp4", ".webm", ".mov", ".mkv")


def engine(cfg):
    return str(cfg.get("talking_head", "hf")).lower()


def enabled(cfg):
    return engine(cfg) in ("hf", "wangp")


def wangp_clip(img, audio, out, cfg, log, stop=lambda: False):
    """This PC's WanGP: presenter photo + narration (audio guide) -> lip-synced clip. Raises on failure."""
    import math
    from .wangp import WanGP
    wg = WanGP(cfg)
    if not wg.alive(): raise RuntimeError("WanGP is not installed or reachable on this computer")
    secs = media.dur(audio)
    frames = int(math.ceil(secs * 24 / 8)) * 8 + 1
    best, best_s = None, -1.0
    with wg.hold():
        for t in range(2):
            r = wg.gen({"model_type": cfg.get("talking_head_model") or cfg.get("video_model", "ltx2_distilled"),
                        "prompt": cfg.get("presenter_prompt", ""), "image_prompt_type": "S", "image_start": str(img),
                        "audio_prompt_type": "A", "audio_scale": 1, "audio_guide": str(audio), "resolution": "832x480",
                        "video_length": frames, "num_inference_steps": 8, "seed": 7100 + t}, log, "talking head", stop=stop)
            if not r.get("ok"): continue
            sc = media.mouth_score(r["file"])
            if sc > best_s: best, best_s = r["file"], sc
            if sc >= 10: break
            log(f"  talking head: mouth barely moves (score {sc:.1f}), re-rendering")
    if not best: raise RuntimeError(f"WanGP gave no clip ({str(r.get('err', ''))[:150]})")
    shutil.copy(best, out)
    log(f"  talking head: WanGP clip {secs:.1f}s, mouth score {best_s:.1f}")
    return out


def _client(space, cfg):
    from gradio_client import Client
    return Client(space, token=cfg.get("hf_token") or None, verbose=False)


def _kind(p):
    """'image' | 'audio' | 'video' | None for one API parameter (gradio_client view_api dict)."""
    comp = str(p.get("component") or "").lower()
    name = str(p.get("parameter_name") or p.get("label") or "").lower()
    for k in ("image", "audio", "video"):
        if k in comp: return k
    if comp in ("file", "uploadbutton"):
        if re.search(r"image|photo|portrait|face|source|ref", name): return "image"
        if re.search(r"audio|speech|voice|wav|driving", name): return "audio"
    return None


def endpoint(client):
    """-> (api_name, params) of the endpoint that takes an image and an audio file, or (None, None)."""
    api = client.view_api(return_format="dict", print_info=False) or {}
    best = None
    for name, ep in (api.get("named_endpoints") or {}).items():
        params = ep.get("parameters") or []
        kinds = [_kind(p) for p in params]
        if "image" in kinds and "audio" in kinds:
            score = -len(params) + (5 if re.search(r"generate|predict|infer|run|process|animate", name) else 0)
            if not best or score > best[0]: best = (score, name, params)
    return (best[1], best[2]) if best else (None, None)


def _video_in(res):
    """The first video file path anywhere in a Space's result."""
    if isinstance(res, str): return res if res.lower().endswith(VIDEO_EXT) and Path(res).exists() else None
    if isinstance(res, dict):
        for k in ("video", "path", "value", "name"):
            v = _video_in(res.get(k)) if k in res else None
            if v: return v
        for v in res.values():
            v = _video_in(v)
            if v: return v
    if isinstance(res, (list, tuple)):
        for v in res:
            v = _video_in(v)
            if v: return v
    return None


def call(space, img, audio, out, cfg, log, timeout=None):
    """One Space: photo + audio -> out (mp4). Raises on any failure."""
    from gradio_client import handle_file
    c = _client(space, cfg)
    api, params = endpoint(c)
    if not api: raise RuntimeError(f"{space}: no endpoint takes an image and an audio file")
    args = []
    for p in params:
        k = _kind(p)
        if k == "image": args.append(handle_file(str(img)))
        elif k == "audio": args.append(handle_file(str(audio)))
        elif p.get("parameter_has_default"): args.append(p.get("parameter_default"))
        else: args.append(None)
    log(f"  talking head: {space} {api} ({len(params)} inputs)")
    job = c.submit(*args, api_name=api)
    res = job.result(timeout=timeout or float(cfg.get("talking_head_timeout", 600)))
    v = _video_in(res)
    if not v: raise RuntimeError(f"{space}: no video in the result ({str(res)[:150]})")
    shutil.copy(v, out)
    if media.dur(out) < 0.5: raise RuntimeError(f"{space}: empty video")
    return out


def make(img, audio, out, cfg, log):
    """The configured engine: WanGP (falls back to the Spaces when WanGP isn't there), else the Spaces in order. -> (out, engine)."""
    errs = []
    if engine(cfg) == "wangp":
        t0 = time.time()
        try:
            wangp_clip(img, audio, out, cfg, log)
            log(f"  talking head: WanGP OK in {time.time() - t0:.0f}s")
            return out, "WanGP (this PC)"
        except Exception as e:
            msg = " ".join(str(e).split())[:200]; errs.append(f"WanGP: {msg}")
            log(f"  talking head: WanGP failed ({msg}); trying Hugging Face")
    for space in cfg.get("talking_head_spaces") or SPACES:
        t0 = time.time()
        try:
            call(space, img, audio, out, cfg, log)
            log(f"  talking head: {space} OK in {time.time() - t0:.0f}s")
            return out, space
        except Exception as e:
            msg = " ".join(str(e).split())[:200]
            errs.append(f"{space}: {msg}"); log(f"  talking head: {space} failed after {time.time() - t0:.0f}s ({msg})")
    raise RuntimeError("no talking-head engine worked: " + " | ".join(errs)[:600])


def reason(e):
    """One plain line for why there is no presenter (shown in the log and the Newsroom)."""
    t = " ".join(str(e).split())
    if re.search(r"ZeroGPU quota|exceeded your free|quota", t, re.I): return "Hugging Face's free GPU time for today is used up"
    if re.search(r"404|Repository Not Found|CONFIG_ERROR|invalid state|RUNTIME_ERROR|sleeping|paused", t, re.I): return "the Hugging Face talking-head apps are down or gone"
    if re.search(r"timed? ?out|timeout", t, re.I): return "the Hugging Face talking-head app took too long"
    return "no talking-head engine worked (" + t[:120] + ")"


def presenter_photo(cfg, log):
    """The presenter photo: settings presenter_image if it exists, else one FLUX portrait made once on Hugging Face."""
    p = Path(cfg.get("presenter_image") or "")
    if p.is_file(): return p
    keep = Path(cfg.get("jobs_dir") or ".").parent / "presenter_hf.jpg"
    if keep.is_file(): return keep
    from PIL import Image
    keep.parent.mkdir(parents=True, exist_ok=True)
    try:
        from gradio_client import Client
        from .imagegen import HF_SPACE
        log("  talking head: making the presenter photo once (Hugging Face FLUX)")
        c = Client(cfg.get("hf_space") or HF_SPACE, token=cfg.get("hf_token") or None, verbose=False)
        res = c.predict(PRESENTER_PROMPT, 7, False, 768, 768, 4, api_name="/infer")
        f = res[0] if isinstance(res, (list, tuple)) else res
        with Image.open(f.get("path") if isinstance(f, dict) else f) as im: im.convert("RGB").save(keep, "JPEG", quality=94)
    except Exception as e:   # e.g. the free ZeroGPU quota is spent: Bing Image Creator once (Edge profile, not Google)
        log(f"  talking head: FLUX unavailable ({' '.join(str(e).split())[:100]}); making the presenter photo with Bing once")
        from .imagegen import _session_bing
        tmp = keep.with_name("presenter_bing.jpg")
        _session_bing(cfg, {"still_prompt": PRESENTER_PROMPT}, "16:9", tmp, 240, log, lambda page, step: None)
        with Image.open(tmp) as im:   # centre square around the face
            w, h = im.size; side = min(w, h)
            im.convert("RGB").crop(((w - side) // 2, (h - side) // 2, (w + side) // 2, (h + side) // 2)).resize((768, 768)).save(keep, "JPEG", quality=94)
    return keep


def early(job, cfg, log):
    """First claim on the free Hugging Face GPU time: the talking head is made right after the narration, BEFORE the image
    generators use up the day's quota. overlay_short then reuses it. Never raises; a failure is written down (the reason shows
    in the log and the Newsroom) and the end of the job tries once more."""
    job = Path(job); td = job / "short" / "talkinghead"; td.mkdir(parents=True, exist_ok=True)
    head = td / "head.mp4"
    if head.exists() and media.dur(head) > 0.5: return head
    try:
        src = job / "short" / "voice" / "b0.wav"
        if not src.exists(): raise RuntimeError("the hook's narration isn't there yet")
        d = min(media.dur(src), float(cfg.get("talking_head_max_secs", 10)))
        wav = td / "hook_early.wav"
        media.ff("-t", f"{d:.3f}", "-i", src, "-ac", 1, "-ar", 16000, wav)
        log("Talking head: made first, before the image generators use the day's Hugging Face GPU time")
        clip, eng = make(presenter_photo(cfg, log), wav, head, cfg, log)
        (td / "early.json").write_text(json.dumps({"ok": True, "engine": eng, "secs": round(d, 2)}, indent=1), encoding="utf-8")
        return head
    except Exception as e:
        head.unlink(missing_ok=True)
        (td / "early.json").write_text(json.dumps({"ok": False, "error": " ".join(str(e).split())[:600]}, indent=1), encoding="utf-8")
        log(f"  talking head (early) not made ({' '.join(str(e).split())[:200]}); tried again at the end")
        return None


def overlay_short(job, plan, cfg, short_mp4, log):
    """Round talking-head picture-in-picture over the Short's hook beat. -> the Short (changed in place) or unchanged."""
    job, short_mp4 = Path(job), Path(short_mp4)
    td = job / "short" / "talkinghead"; td.mkdir(parents=True, exist_ok=True)
    try:
        tl = json.loads((job / "short" / "public" / "teaser.json").read_text(encoding="utf-8"))
        b0 = (tl.get("beats") or [{}])[0]
        a, d = float(b0.get("start", 0)), min(float(b0.get("dur", 6)), float(cfg.get("talking_head_max_secs", 10)))
        wav = td / "hook.wav"
        media.ff("-ss", f"{a:.3f}", "-t", f"{d:.3f}", "-i", short_mp4, "-vn", "-ac", 1, "-ar", 16000, wav)
        pre = td / "head.mp4"
        if pre.exists() and media.dur(pre) > 0.5:
            clip, space = pre, (json.loads((td / "early.json").read_text(encoding="utf-8")).get("engine", "early") if (td / "early.json").exists() else "early")
        else:
            clip, space = make(presenter_photo(cfg, log), wav, td / "head.mp4", cfg, log)
        size, x, y = 380, 40, 260   # top-left, clear of the captions
        flt = (f"[1:v]scale={size}:{size}:force_original_aspect_ratio=increase,crop={size}:{size},format=rgba,"
               f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='if(lte(pow(X-{size / 2},2)+pow(Y-{size / 2},2),pow({size / 2 - 2},2)),255,0)',"
               f"setpts=PTS-STARTPTS+{a:.3f}/TB[h];"
               f"[0:v][h]overlay={x}:{y}:eof_action=pass:enable='between(t,{a:.3f},{a + d:.3f})'[v]")
        tmp = short_mp4.with_name("_short_head.mp4")
        media.ff("-i", short_mp4, "-i", clip, "-filter_complex", flt, "-map", "[v]", "-map", "0:a", "-c:v", "libx264", "-crf", 16,
                 "-preset", "medium", "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", tmp)
        if media.dur(tmp) < media.dur(short_mp4) - 0.5: raise RuntimeError("the result came out shorter")
        tmp.replace(short_mp4)
        (td / "talkinghead.json").write_text(json.dumps({"ok": True, "space": space, "start": a, "secs": d}, indent=1), encoding="utf-8")
        log(f"Talking head added over the hook ({d:.1f}s, {space})")
        try:
            from . import edit; edit.ensure_keyframes(job, log)
        except Exception as e: log(f"  couldn't prepare the talking-head version for editing ({str(e)[:120]})")
    except Exception as e:
        why = reason(e)
        (td / "talkinghead.json").write_text(json.dumps({"ok": False, "error": str(e)[:600], "reason": why}, indent=1), encoding="utf-8")
        log(f"Talking head skipped: {why}. The Short goes out without a presenter.")
    return short_mp4
