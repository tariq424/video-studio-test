"""Cloud stills: the ladder rung between real photos and WanGP (Shorts: ladder.run step 2a; long videos: render.cloud_still).

Provider-neutral. A provider is a function  fn(prompt, aspect, timeout) -> image bytes  that raises Fail(reason) when it can't
deliver; it is registered in PROVIDERS and switched on by listing its name in config "cloud_providers" (tried in that order;
the first image wins). Each attempt runs in a worker thread with a hard per-provider timeout ("cloud_timeout", 60 s), so a
stuck provider never hangs the pipeline; any failure falls through to the next provider, then to WanGP.

2026-10-10 (second spec): Gemini / ChatGPT browser automation removed (account-suspension risk). Of the four providers named
in that spec, none is wired in yet - see WORKFLOW_HANDOFF.md "Cloud stills" for why each was left out. With no provider
configured the rung logs one line and the ladder goes straight to WanGP, exactly as before cloud stills existed.
"""
import io, json, re, threading, time
from pathlib import Path

ASPECTS = ("9:16", "16:9")
PROVIDERS = {}   # name -> fn(prompt, aspect, timeout) -> bytes


class Fail(Exception):
    pass


def prompt_text(prompt, aspect):
    shape = "tall vertical 9:16 portrait" if aspect == "9:16" else "wide horizontal 16:9 landscape"
    return (f"Photorealistic, cinematic {shape} image. {prompt.strip().rstrip('.')}. No text, letters, numbers, logos, watermarks, "
            f"airline or brand names, flags or registrations. No identifiable real people.")


def providers_of(cfg):
    return [p for p in (cfg.get("cloud_providers") or []) if p in PROVIDERS]


def _fit(data, out, aspect):
    """Decode, check, crop to fill the target aspect, save as PNG. -> (w, h). Raises Fail."""
    from PIL import Image
    try: im = Image.open(io.BytesIO(data)).convert("RGB")
    except Exception: raise Fail("download isn't an image")
    if min(im.size) < 400: raise Fail(f"image too small ({im.width}x{im.height})")
    aw, ah = (9, 16) if aspect == "9:16" else (16, 9)
    W, H = im.size
    if W * ah > H * aw: nw = int(H * aw / ah); im = im.crop(((W - nw) // 2, 0, (W - nw) // 2 + nw, H))
    else: nh = int(W * ah / aw); im = im.crop((0, (H - nh) // 2, W, (H - nh) // 2 + nh))
    Path(out).parent.mkdir(parents=True, exist_ok=True); im.save(out, "PNG")
    return im.size


def _timed(fn, args, timeout):
    """Run fn(*args) in a daemon thread; -> result, or raises Fail on timeout / the provider's own failure."""
    box = {}
    def run():
        try: box["v"] = fn(*args)
        except Exception as e: box["e"] = e
    t = threading.Thread(target=run, daemon=True); t.start(); t.join(timeout)
    if t.is_alive(): raise Fail(f"timed out after {timeout}s")
    if "e" in box: raise box["e"] if isinstance(box["e"], Fail) else Fail(f"error: {str(box['e'])[:120]}")
    return box["v"]


def _count(job):
    f = Path(job) / "cloud_log.jsonl"
    if not f.exists(): return 0
    return sum(1 for l in f.read_text(encoding="utf-8").splitlines() if l.strip())


def generate(cfg, prompt, out, aspect, log, tag="cloud", job=None):
    """One cloud still -> {"ok", "provider", "why", "tries"}. Never raises; each provider gets "cloud_timeout" seconds.
    job: the job folder (attempts logged to cloud_log.jsonl; "cloud_max_per_job" caps attempts per video)."""
    if not cfg.get("cloud_on", True): return {"ok": False, "provider": None, "why": "cloud stills off", "tries": []}
    provs = providers_of(cfg)
    if not provs: return {"ok": False, "provider": None, "why": "no cloud provider configured", "tries": []}
    cap = int(cfg.get("cloud_max_per_job", 8))
    if job is not None and _count(job) >= cap:
        return {"ok": False, "provider": None, "why": f"per-video cap of {cap} cloud attempts reached", "tries": []}
    timeout = int(cfg.get("cloud_timeout", 60)); text = prompt_text(prompt, aspect); tries = []; res = None; t0 = time.time()
    for name in provs:
        t1 = time.time()
        try:
            data = _timed(PROVIDERS[name], (text, aspect, timeout), timeout)
            w, h = _fit(data, out, aspect)
            tries.append({"provider": name, "why": "ok", "secs": round(time.time() - t1, 1), "size": f"{w}x{h}"})
            res = {"ok": True, "provider": name, "why": "", "tries": tries}; break
        except Fail as e:
            tries.append({"provider": name, "why": str(e), "secs": round(time.time() - t1, 1)})
            log(f"  {tag}: {name} failed after {tries[-1]['secs']}s: {e}")
    if res is None: res = {"ok": False, "provider": None, "why": "; ".join(f"{t['provider']}: {t['why']}" for t in tries), "tries": tries}
    res["secs"] = round(time.time() - t0, 1)
    log(f"  {tag}: " + (f"cloud still from {res['provider']} in {res['secs']}s" if res["ok"] else f"no cloud still ({res['why'][:160]})"))
    if job is not None:
        try:
            with open(Path(job) / "cloud_log.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps({"t": time.strftime("%Y-%m-%d %H:%M:%S"), "tag": tag, "out": Path(out).name, **res}) + "\n")
        except Exception: pass
    return res


def has_person(text, ents):
    """True when the narration names a real person from the story's entity list (cloud is skipped for those beats)."""
    low = " " + re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower()) + " "
    for e in ents or []:
        if e.get("kind") != "person": continue
        parts = [w for w in re.sub(r"[^a-z0-9 ]+", " ", str(e.get("name", "")).lower()).split() if len(w) > 2]
        if parts and (f" {' '.join(parts)} " in low or f" {parts[-1]} " in low): return True
    return False
