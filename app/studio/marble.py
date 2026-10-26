"""World Labs Marble (world model) as a QC-repair rung: the website, driven in its own signed-in Chrome profile
(F:\\videos_test\\marble_profile, made with scripts\\imagegen-login.ps1 -Site marble), never the paid API.
  generate(): type a scene prompt into "Imagine a world", wait until the new world has loaded -> its /world/<id> URL
  record():   open a world, hide the page chrome so only the 3D view shows, record a slow walk-forward (W held, a gentle mouse
              pan) with Playwright's page video, then cut the load time off and encode an MP4 of the wanted length and size
  scene():    narration -> prompt (script model) -> generate -> record. Used sparingly: the free plan has few generations.
Every failure raises; qc_repair treats any error as "no scene" and moves to the next rung."""
import json, re, shutil, time
from pathlib import Path

from . import media

HOME = "https://marble.worldlabs.ai/"
HIDE_CHROME = """() => {
  const keep = new Set();
  document.querySelectorAll('canvas').forEach(c => { let e = c; while (e) { keep.add(e); e = e.parentElement; } });
  document.querySelectorAll('body *').forEach(e => {
    if (keep.has(e) || e.tagName === 'CANVAS' || e.closest('canvas')) return;
    if ([...keep].some(k => e.contains(k))) return;
    e.style.setProperty('visibility', 'hidden', 'important');
  });
  document.querySelectorAll('canvas').forEach(c => { c.style.setProperty('visibility', 'visible', 'important'); });
}"""


def _log(log, m): (log or print)(m)


def _launch(pw, cfg, size=None):
    from .imagegen import profile_dir, Skip
    prof = profile_dir(cfg, "marble")
    if not prof.exists() or not any(prof.iterdir()):
        raise Skip(f"no signed-in Marble profile at {prof}; run scripts\\imagegen-login.ps1 -Site marble once")
    W, H = size or (1280, 720)
    kw = dict(user_data_dir=str(prof), headless=False, channel="chrome", viewport={"width": W, "height": H},
              args=["--disable-blink-features=AutomationControlled", "--enable-webgl", "--ignore-gpu-blocklist"])
    ctx = pw.chromium.launch_persistent_context(**kw)
    return ctx, (ctx.pages[0] if ctx.pages else ctx.new_page())


def _dismiss(page):
    for sel in ["button[aria-label='Dismiss notification']", "button[aria-label='Dismiss announcement']"]:
        try:
            b = page.locator(sel)
            if b.count(): b.first.click(timeout=2000)
        except Exception: pass


def _loaded(page, timeout):
    t0 = time.time()
    while time.time() - t0 < timeout:
        body = page.inner_text("body")
        if "Loading world" not in body and page.locator("canvas").count(): return True
        page.wait_for_timeout(2000)
    return False


def generate(cfg, prompt, log=None, timeout=900):
    """-> the new world's URL. Raises when the page has no prompt box, the account is out of generations, or it times out."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        ctx, page = _launch(pw, cfg)
        try:
            page.goto(HOME, wait_until="domcontentloaded", timeout=60000); page.wait_for_timeout(6000); _dismiss(page)
            box = page.locator("textarea[placeholder='Imagine a world']")
            if not box.count():
                if re.search(r"\b(log in|sign in|sign up)\b", page.inner_text("body"), re.I): raise RuntimeError("Marble profile is not signed in")
                raise RuntimeError("Marble's prompt box was not found (the page may have changed)")
            start = page.url
            box.first.click(); page.keyboard.insert_text(prompt[:900]); page.wait_for_timeout(800); page.keyboard.press("Enter")
            _log(log, f"    marble: prompt sent ({len(prompt)} chars); waiting for the world")
            t0 = time.time(); url = ""
            while time.time() - t0 < timeout:
                page.wait_for_timeout(5000)
                body = page.inner_text("body")
                if re.search(r"(out of|no) (generations|credits)|upgrade to (continue|generate)|limit reached", body, re.I):
                    raise RuntimeError("Marble: no generations left on this plan")
                if "/world/" in page.url and page.url != start:
                    url = page.url
                    if _loaded(page, 30): break
            if not url: raise RuntimeError(f"Marble made no world in {timeout}s")
            _log(log, f"    marble: world ready {url} ({time.time() - t0:.0f}s)")
            return url
        except Exception:
            try: page.screenshot(path=str(Path(cfg.get("jobs_dir") or ".").parent / "marble_fail.png"))
            except Exception: pass
            raise
        finally:
            ctx.close()


def record(cfg, world_url, out, secs, size=(1280, 720), log=None, load_timeout=240):
    """Walk slowly through a loaded world and capture it -> MP4 of `secs` seconds at `size`. Frames are page screenshots
    taken while W is held (no Playwright video, which needs its own ffmpeg download), timed and re-encoded at 30 fps.
    Raises if the world never finishes loading."""
    from playwright.sync_api import sync_playwright
    out = Path(out); out.parent.mkdir(parents=True, exist_ok=True)
    W, H = size; r = min(1.0, 1280 / max(W, H)); RW, RH = int(W * r) // 2 * 2, int(H * r) // 2 * 2
    fdir = out.parent / (out.stem + "_frames")
    if fdir.exists(): shutil.rmtree(fdir, ignore_errors=True)
    fdir.mkdir(exist_ok=True)
    n = 0
    with sync_playwright() as pw:
        ctx, page = _launch(pw, cfg, (RW, RH))
        try:
            page.goto(world_url, wait_until="domcontentloaded", timeout=60000); page.wait_for_timeout(3000); _dismiss(page)
            if not _loaded(page, load_timeout): raise RuntimeError(f"the world did not finish loading in {load_timeout}s")
            page.wait_for_timeout(4000)   # splats settle
            page.evaluate(HIDE_CHROME); page.wait_for_timeout(500)
            page.mouse.move(RW / 2, RH / 2)
            page.keyboard.down("w"); t0 = time.time()
            while time.time() - t0 < secs:   # walk forward with a slow pan, one screenshot per frame
                page.mouse.move(RW / 2 + 30 * (time.time() - t0), RH / 2)
                page.screenshot(path=str(fdir / f"f{n:05d}.jpg"), type="jpeg", quality=90); n += 1
            took = time.time() - t0
            page.keyboard.up("w")
        finally:
            ctx.close()
    if n < 2: raise RuntimeError("no frames captured")
    rate = n / took
    media.ff("-framerate", f"{rate:.3f}", "-i", fdir / "f%05d.jpg", "-t", f"{secs:.2f}", "-vf",
             f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps=30,format=yuv420p",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", out, timeout=600)
    if not media.ok(out): raise RuntimeError("recording could not be encoded")
    _log(log, f"    marble: {n} frames ({rate:.1f}/s) -> {media.dur(out):.1f}s walk-through {out.name}")
    return out


def prompt_for(cfg, vo, log=None):
    from .llm import LLM
    c = dict(cfg)
    if c.get("script_provider") == "claude" and not c.get("anthropic_api_key"): c["script_provider"] = "deepseek" if c.get("deepseek_api_key") else "local"
    with LLM(c, log, lambda: False) as llm:
        j = llm.chat_json("You write prompts for a 3D world generator. Reply with JSON only.",
                          "Narration:\n" + vo[:800] + "\n\nDescribe ONE realistic place (a room, street, landscape or facility) where this "
                          "narration could be filmed: materials, light, weather, objects. No people, no text, no logos. 2-3 sentences.\n"
                          '{"prompt": "..."}', max_tokens=300)
    return str(j.get("prompt") or vo[:400]).strip()


def scene(cfg, vo, out, secs, size, log=None):
    """The rung: -> MP4 path, or raises. Each call spends one Marble generation."""
    p = prompt_for(cfg, vo, log) if vo else "A quiet realistic landscape at dusk"
    _log(log, f"    marble prompt: {p[:160]}")
    url = generate(cfg, p, log, timeout=int(cfg.get("marble_timeout", 900)))
    Path(out).with_suffix(".world.json").write_text(json.dumps({"url": url, "prompt": p}, indent=1), encoding="utf-8")
    return record(cfg, url, out, secs, size, log)
