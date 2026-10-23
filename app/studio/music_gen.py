"""Original music from Gemini (the Google-signed-in profile the Gemini image rung uses), kept in the music library.

Like the stills: we describe the track, Gemini makes it, we download it once and reuse it. Used sparingly (owner's rule:
Google tools are a last resort): a seed run makes a small library once (scripts/music_seed.py); after that a video only
asks for a new track when no track in the library fits its mood, at most music_generate_per_day times a day.
Instrumental only; descriptions name a mood, tempo and instruments, never an existing song or artist."""
import json
import re
import time
from pathlib import Path

from . import media

ASK = ("Create an original instrumental music track (no vocals, no lyrics): {desc} "
       "Do not imitate any existing song or artist. I want to download it.")
AUDIO_EXT = (".mp3", ".m4a", ".wav", ".ogg", ".aac", ".mp4", ".webm")


def _usage(cfg):
    from .music import folder
    f = folder(cfg) / "generated_today.json"
    try: d = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError): d = {}
    return f, d


def allowed(cfg):
    if not cfg.get("music_generate", True): return False
    _, d = _usage(cfg)
    cap = int(cfg.get("music_generate_per_day", 0) or 0)
    return cap <= 0 or d.get(time.strftime("%Y-%m-%d"), 0) < cap   # 0 = on demand, no daily cap (owner 2026-10-23)


def _count(cfg):
    f, d = _usage(cfg); day = time.strftime("%Y-%m-%d")
    d = {day: d.get(day, 0) + 1}; f.parent.mkdir(parents=True, exist_ok=True); f.write_text(json.dumps(d), encoding="utf-8")


def generate(cfg, desc, out_mp3, log, timeout=300, evidence_dir=None):
    """One track from Gemini -> out_mp3. Raises on failure (with a screenshot in evidence_dir)."""
    from playwright.sync_api import sync_playwright
    from . import imagegen as ig
    from .flow import _save, _first
    prof = ig.profile_dir(cfg)
    if not prof.exists() or not any(prof.iterdir()):
        raise RuntimeError(f"no signed-in Google profile at {prof}")
    out_mp3 = Path(out_mp3); out_mp3.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_mp3.with_suffix(".dl")
    _count(cfg)   # counted when tried, so a failing page can't be hammered
    with sync_playwright() as pw:
        kw = dict(user_data_dir=str(prof), headless=bool(cfg.get("imagegen_headless", True)), accept_downloads=True,
                  viewport={"width": 1440, "height": 900}, args=["--disable-blink-features=AutomationControlled"])
        if kw["headless"]: kw["user_agent"] = ig.UA
        if cfg.get("flow_chrome"): kw["executable_path"] = cfg["flow_chrome"]
        else: kw["channel"] = "chrome"
        context = pw.chromium.launch_persistent_context(**kw)
        page = context.pages[0] if context.pages else context.new_page()
        step = "open"
        try:
            page.goto(cfg.get("gemini_url") or ig.URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(5000)
            ig._check(page, step)
            box = ig._box(page)
            step = "ask"
            ig._pause(cfg, log, "a music track", "gemini")
            n_audio = page.locator("audio").count()
            ig._send(page, box, ASK.format(desc=desc))
            log(f"  music: asked Gemini for \"{desc[:100]}\"")
            t0, got = time.time(), False
            while time.time() - t0 < timeout and not got:
                page.wait_for_timeout(4000)
                ig._check(page, "generate")
                body = ig._body(page)
                if re.search(r"can.t (create|make|generate) (music|that)|isn.t available|not available in your", body[-3000:], re.I) and time.time() - t0 > 30:
                    raise RuntimeError("Gemini says it can't make music here: " + body[-300:].replace("\n", " "))
                # 1) a download button on the newest answer
                btn = _first(page, ["button[aria-label*='Download track' i]", "button[aria-label*='Download audio' i]",
                                    "button[aria-label*='Download music' i]", "button:has-text('Download')"], 500)
                if btn and not ig._busy(page):
                    try:
                        with page.expect_download(timeout=60000) as dl:
                            btn.click()
                            page.wait_for_timeout(1500)
                            menu = _first(page, ["[role=menuitem]:has-text('MP3')", "[role=menuitem]:has-text('Audio')", "[role=menuitem]:has-text('Download')"], 1500)
                            if menu: menu.click()
                        dl.value.save_as(str(tmp)); got = True; break
                    except Exception:
                        pass
                # 2) an audio player: read its source inside the page
                if page.locator("audio").count() > n_audio and not ig._busy(page):
                    src = page.locator("audio").last.get_attribute("src") or page.locator("audio source").last.get_attribute("src") or ""
                    if src:
                        if src.startswith(("blob:", "data:")): _save(context, page, src, tmp)
                        else:
                            r = context.request.get(src, timeout=120000)
                            if not r.ok: raise RuntimeError(f"audio download HTTP {r.status}")
                            tmp.write_bytes(r.body())
                        got = True
            if not got: raise RuntimeError(f"no music from Gemini after {timeout}s")
            ig._answered("gemini")
            step = "convert"
            media.ff("-i", tmp, "-vn", "-ac", 2, "-ar", 44100, "-b:a", "192k", out_mp3)
            tmp.unlink(missing_ok=True)
            d = media.dur(out_mp3)
            if d < 5: raise RuntimeError(f"the track is only {d:.1f}s")
            log(f"  music: got a {d:.0f}s track -> {out_mp3.name}")
            return out_mp3
        except Exception:
            if evidence_dir:
                try: page.screenshot(path=str(Path(evidence_dir) / f"music_{step}_{int(time.time())}.png"))
                except Exception: pass
            raise
        finally:
            context.close()
