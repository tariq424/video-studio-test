"""Narration engine switch: config "tts_engine" = "wanGP" (default: the cloned voice through WanGP, unchanged) | "kokoro".

Kokoro (hexgrad/Kokoro-82M, Apache-2.0) is a small dedicated TTS model: preset voices only (no cloning), tens of times faster
than real time on the GPU, so a Short's narration takes seconds instead of the 10-15 minutes WanGP needs.

It runs in its OWN Python environment (app/kenv, made by pinokio/install_kokoro.js) through app/kokoro_worker.py, never inside
Video Studio's env: Kokoro needs PyTorch (CUDA 12.8 build for the RTX 50-series), which Video Studio's env doesn't have, and
installing it there could shift numpy / other packages under the running app. One worker call per job (the model loads once)
renders every narration chunk; each comes back as a 24 kHz mono WAV that the callers convert to 48 kHz stereo exactly like
WanGP output, so everything downstream (word timings, splitting, captions, mixing) is unchanged.

Config:
  tts_engine      "wanGP" | "kokoro"   (default "wanGP")
  kokoro_voice    preset voice id      (default "am_michael"; any of Kokoro's voices, e.g. af_heart, am_fenrir, bm_george)
  kokoro_speed    0.5 - 2.0            (default 1.0)
  kokoro_wpm      words per minute used to size Shorts (default 140: am_michael at speed 1.0, measured 2026-10-12)
  kokoro_online   false = HF_HUB_OFFLINE for the worker (the model is cached at install); true if the cache is ever cleared
  kokoro_python   path to the Kokoro env's python ("" = app/kenv/Scripts/python.exe on Windows, app/kenv/bin/python elsewhere)
  kokoro_device   "cuda" | "cpu" | ""  ("" = cuda when available)
"""
import json, os, subprocess, sys, tempfile, time
from pathlib import Path
from . import config, media

APP = Path(__file__).resolve().parent.parent
WORKER = APP / "kokoro_worker.py"
DEFAULT_VOICE = "am_michael"


def engine(cfg):
    return "kokoro" if str(cfg.get("tts_engine", "kokoro")).strip().lower() == "kokoro" else "wanGP"


def try_kokoro(cfg, items, log, tag, stop):
    """Kokoro for these items. -> True when done; False when it failed and tts_fallback lets WanGP take over (logged).
    Raises when it failed and fallback is off (or the job was cancelled)."""
    try:
        kokoro_batch(cfg, items, log, tag, stop); return True
    except Exception as e:
        if str(e) == "cancelled" or not cfg.get("tts_fallback", True): raise
        log(f"  {tag}: Kokoro failed ({str(e)[:200]}); falling back to WanGP narration (tts_fallback)")
        return False


def wpm(cfg):
    """Speaking pace used to size a Short's script: the cloned narrator's measured voice_wpm, or kokoro_wpm for Kokoro."""
    return float(cfg.get("kokoro_wpm", 140) if engine(cfg) == "kokoro" else cfg.get("voice_wpm", 155))


def kokoro_python(cfg):
    p = (cfg.get("kokoro_python") or "").strip()
    if p: return Path(p)
    env = APP / "kenv"
    return env / "Scripts" / "python.exe" if os.name == "nt" else env / "bin" / "python"


def available(cfg):
    """-> "" when Kokoro can run, else why not (shown in the job log)."""
    py = kokoro_python(cfg)
    if not py.exists(): return f"the Kokoro environment isn't installed ({py} missing; run install_kokoro in Pinokio)"
    if not WORKER.exists(): return f"{WORKER.name} missing"
    return ""


def lang_of(voice):
    """Kokoro voice ids start with the language letter: a = American English, b = British English (af_/am_/bf_/bm_)."""
    return (voice or "a")[0] if (voice or "a")[0] in "abefhijpz" else "a"


def kokoro_batch(cfg, items, log, tag="voice", stop=lambda: False):
    """items: [(text, out_wav)]. Renders every item that isn't already there in ONE worker process, then converts each to
    48 kHz stereo in place (same format WanGP narration is normalised to). Raises RuntimeError on failure."""
    todo = [(t, Path(o)) for t, o in items if not media.ok(o)]
    if not todo: return
    why = available(cfg)
    if why: raise RuntimeError(f"tts_engine is kokoro but {why}")
    if stop(): raise RuntimeError("cancelled")
    voice = cfg.get("kokoro_voice") or DEFAULT_VOICE
    req = {"voice": voice, "lang": lang_of(voice), "speed": float(cfg.get("kokoro_speed", 1.0) or 1.0),
           "device": cfg.get("kokoro_device", ""), "items": [{"text": t, "out": str(o.with_suffix(".k24.wav"))} for t, o in todo]}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(req, f); jf = f.name
    t0 = time.time()
    try:
        env = dict(os.environ)
        if not cfg.get("kokoro_online", False): env["HF_HUB_OFFLINE"] = "1"   # model cached by the install: no Hugging Face check per job
        r = subprocess.run([str(kokoro_python(cfg)), str(WORKER), jf], capture_output=True, text=True, timeout=1800,
                           encoding="utf-8", errors="replace", env=env)
    finally:
        try: os.unlink(jf)
        except OSError: pass
    if r.returncode != 0:
        raise RuntimeError(f"Kokoro narration failed: {(r.stderr or r.stdout).strip()[-400:]}")
    for t, o in todo:
        raw = o.with_suffix(".k24.wav")
        if not media.ok(raw, 0.2): raise RuntimeError(f"Kokoro produced no audio for {o.name}")
        media.ff("-i", raw, "-ar", 48000, "-ac", 2, o)
        raw.unlink(missing_ok=True)
    secs = sum(media.dur(o) for _, o in todo)
    log(f"  {tag}: Kokoro ({voice}) rendered {secs:.0f}s of narration in {time.time() - t0:.0f}s ({len(todo)} part(s))")
