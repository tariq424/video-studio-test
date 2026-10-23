"""Google Flow rung (visual ladder v2, rung 5: the last resort for AI video, after the free image generators; paid credits).

Drives Google Flow (labs.google) in a dedicated, signed-in Chrome profile with Playwright: types a visual prompt for the
beat, waits for the generated clip and downloads it. Any failure (Playwright missing, profile not signed in, the page
changed, generation refused or slow) is logged and the ladder falls through to the next rung. After a failure that would
repeat for every beat (no profile / not signed in / page not recognised) the rung is skipped for the rest of the job.

One-time setup on the PC: run scripts\\flow-login.ps1 (opens Chrome with the Flow profile; sign in to Google, open Flow
once, close Chrome). Settings: flow_on, flow_profile, flow_url, flow_timeout, flow_max_per_video, flow_chrome.
"""
import base64
import json
import re
import time
from pathlib import Path

from . import media

URL = "https://labs.google/fx/tools/flow"
_down = {"why": ""}   # job-wide: a failure that would repeat for every beat


def reset():
    _down["why"] = ""


def profile_dir(cfg):
    p = cfg.get("flow_profile")
    if p:
        return Path(p)
    return Path(cfg.get("jobs_dir") or ".").parent / "flow_profile"


def _ledger(sd):
    f = Path(sd) / "flow" / "usage.json"
    try:
        return f, (json.loads(f.read_text(encoding="utf-8")) if f.exists() else {})
    except (ValueError, OSError):
        return f, {}


PROMPT = """Write ONE prompt for an AI video generator (Google Flow / Veo) for an 8-second clip that illustrates this beat of
a news explainer. Narration: "{vo}"
{hint}
Rules: describe a single concrete, filmable scene (subject, action, setting, camera move, lighting). Photorealistic,
documentary look. No text, captions, logos, brand names, real people's names or likenesses, and no screens showing words.
Max 60 words. Reply with JSON only: {{"prompt": "..."}}"""


def _style(cfg):
    from . import style
    return style.text(cfg, ("visuals", "general"))


def visual_prompt(cfg, sec, log):
    """A Flow prompt for the beat: the script's own still prompt / motion when present, else one short model call."""
    base = str(sec.get("still_prompt") or "").strip()
    motion = str(sec.get("motion") or "").strip()
    if base:
        p = base + (". " + motion if motion else ". Slow cinematic camera move")
        return re.sub(r"\s+", " ", p)[:600] + ". Photorealistic, no text, no logos, no real or recognizable people."
    hint = ("Stock-search ideas for the beat: " + "; ".join(sec.get("queries") or [])) if sec.get("queries") else ""
    try:
        from .llm import LLM
        with LLM(dict(cfg), log, lambda: False) as llm:
            j = llm.chat_json("You write prompts for AI video generators. Reply with JSON only.",
                              PROMPT.format(vo=str(sec.get("vo", ""))[:600].replace('"', "'"), hint=hint) + _style(cfg), max_tokens=300,
                              check=lambda j: None if len(str(j.get("prompt") or "").split()) >= 8 else (_ for _ in ()).throw(ValueError("prompt too short")))
        return str(j["prompt"]).strip()[:600]
    except Exception as e:
        q = "; ".join(sec.get("queries") or []) or str(sec.get("vo", ""))[:160]
        log(f"  flow: prompt model unavailable ({str(e)[:80]}); using the beat's stock ideas")
        return f"Cinematic documentary shot: {q}. Slow camera move, natural light, photorealistic, no text, no logos."


def _first(page, selectors, timeout=4000):
    for sel in selectors:
        loc = page.locator(sel).first
        try:
            loc.wait_for(state="visible", timeout=timeout)
            return loc
        except Exception:
            continue
    return None


def _videos(page):
    try:
        return page.eval_on_selector_all("video", "els => els.map(e => e.currentSrc || e.src || (e.querySelector('source')||{}).src || '').filter(Boolean)")
    except Exception:
        return []


def _tiles(page):
    """Number of media thumbnails in Flow's grid (the main area, left of the session panel)."""
    try:
        return page.evaluate("""() => Array.from(document.querySelectorAll('img, video')).filter(e => {
            const r = e.getBoundingClientRect(); return r.left > 240 && r.right < 1080 && r.width > 80 && r.height > 120; }).length""")
    except Exception:
        return 0


def _save(context, page, src, out):
    if src.startswith("blob:") or src.startswith("data:"):
        b64 = page.evaluate("""async (u) => { const r = await fetch(u); const b = new Uint8Array(await r.arrayBuffer());
            let s = ''; for (let i = 0; i < b.length; i += 32768) s += String.fromCharCode.apply(null, b.subarray(i, i + 32768));
            return btoa(s); }""", src)
        out.write_bytes(base64.b64decode(b64))
    else:
        r = context.request.get(src, timeout=120000)
        if not r.ok:
            raise RuntimeError(f"download HTTP {r.status}")
        out.write_bytes(r.body())


def generate(cfg, sd, sec, key, log, aspect="9:16", prompt=None):
    """-> path of the downloaded clip, or None (logged) so the ladder falls through. prompt: use this text (e.g. the OCR'd
    prompt from a source snapshot) instead of the beat's own visual prompt."""
    if not cfg.get("flow_on", True):
        return None
    if _down["why"]:
        log(f"  flow skipped ({_down['why']})")
        return None
    f, used = _ledger(sd)
    cap = int(cfg.get("flow_max_per_video", 4))
    if len(used) >= cap and key not in used:
        log(f"  flow: {cap} clips already made for this video; next rung")
        return None
    out = Path(sd) / "flow" / f"{key}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    if media.ok(out):
        return out
    prof = profile_dir(cfg)
    if not prof.exists() or not any(prof.iterdir()):
        _down["why"] = f"no signed-in Flow profile at {prof}; run scripts\\flow-login.ps1 once"
        log(f"  flow: {_down['why']}; next rung")
        return None
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        _down["why"] = "Playwright is not installed in this environment"
        log(f"  flow: {_down['why']}; next rung")
        return None
    prompt = prompt or visual_prompt(cfg, sec, log)
    timeout = int(cfg.get("flow_timeout", 360))
    t0 = time.time()
    log(f"  flow: generating ({prompt[:90]}...)")
    try:
        with sync_playwright() as pw:
            kw = dict(user_data_dir=str(prof), headless=bool(cfg.get("flow_headless", False)), accept_downloads=True,
                      viewport={"width": 1440, "height": 900}, args=["--disable-blink-features=AutomationControlled"])
            if cfg.get("flow_chrome"):
                kw["executable_path"] = cfg["flow_chrome"]
            else:
                kw["channel"] = "chrome"
            context = pw.chromium.launch_persistent_context(**kw)
            try:
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(cfg.get("flow_url") or URL, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(4000)
                if "accounts.google.com" in page.url or _first(page, ["text=/sign in/i"], 1500) and not _first(page, ["textarea", "[contenteditable=true]"], 1500):
                    _down["why"] = "the Flow profile is not signed in to Google; run scripts\\flow-login.ps1"
                    raise RuntimeError(_down["why"])
                box0 = _first(page, ["textarea", "[contenteditable=true]", "[role=textbox]"], 3000)
                if not box0:   # landing page: open a new project (its prompt panel has the text box)
                    new = _first(page, ["button:has-text('New project')", "a:has-text('New project')", "[aria-label*='New project' i]"], 8000)
                    if new:
                        new.click()
                        page.wait_for_timeout(4000)
                box = _first(page, ["textarea", "[contenteditable=true]", "[role=textbox]"], 15000)
                if not box:
                    _down["why"] = "Flow's prompt box was not found (the page may have changed)"
                    raise RuntimeError(_down["why"])
                if aspect and cfg.get("flow_set_aspect", True):   # best effort: portrait for Shorts
                    try:
                        sel = _first(page, ["button:has-text('16:9')", "button:has-text('Landscape')", "[aria-label*='aspect' i]"], 1500)
                        if sel and aspect == "9:16":
                            sel.click(); page.wait_for_timeout(800)
                            opt = _first(page, ["text=/9:16|Portrait/"], 2000)
                            if opt: opt.click(); page.wait_for_timeout(800)
                    except Exception:
                        pass
                before = set(_videos(page))
                tiles0 = _tiles(page)
                box.click()
                box.fill(prompt) if box.evaluate("e => e.tagName") == "TEXTAREA" else page.keyboard.insert_text(prompt)
                send = _first(page, ["button[aria-label*='Send' i]", "button[aria-label*='Submit' i]", "button[aria-label*='Generate' i]",
                                     "button[aria-label*='Create' i]", "button:has-text('arrow_forward')", "button:has-text('arrow_upward')"], 2000)
                if not send:   # the 2026 UI: a round arrow button at the bottom-right of the prompt panel; take the panel's last button
                    try:
                        panel = box.locator("xpath=ancestor::*[.//button][1]")
                        cand = panel.locator("button:not([disabled])")
                        send = cand.nth(cand.count() - 1) if cand.count() else None
                    except Exception:
                        send = None
                if send:
                    send.click()
                page.wait_for_timeout(2500)
                try:
                    still = box.input_value() if box.evaluate("e => e.tagName") == "TEXTAREA" else box.inner_text()
                except Exception:
                    still = ""
                if prompt[:40] in (still or ""):   # not sent yet: Enter, then Ctrl+Enter
                    box.press("Enter"); page.wait_for_timeout(2000)
                    try:
                        still = box.input_value() if box.evaluate("e => e.tagName") == "TEXTAREA" else box.inner_text()
                    except Exception:
                        still = ""
                    if prompt[:40] in (still or ""): box.press("Control+Enter")
                log("  flow: prompt submitted; waiting for the clip")
                src = None
                approved = False
                while time.time() - t0 < timeout:
                    page.wait_for_timeout(5000)
                    body = ""
                    try:
                        body = page.locator("body").inner_text(timeout=3000)
                    except Exception:
                        pass
                    if not approved and cfg.get("flow_auto_approve", True):
                        # Flow's agent asks before spending credits ("costing 15 credits? Approve / Always approve / Reject").
                        # The owner chose: click Approve each time (never "Always approve", which changes the account setting).
                        btn = page.get_by_role("button", name=re.compile(r"^\s*(check\s*)?Approve\s*$"))
                        if not btn.count():   # the 2026 panel renders the choices as plain elements: exact text "Approve" only
                            btn = page.get_by_text("Approve", exact=True)
                        if btn.count():
                            cost = re.search(r"costing\s+(\d+)\s+credits", body, re.I)
                            btn.first.click()
                            approved = True
                            log(f"  flow: approved the generation ({cost.group(1) + ' credits' if cost else 'credits as quoted'})")
                            continue
                    if re.search(r"(couldn.t generate|violat|policy|try a different prompt|out of credits|not enough credits|limit reached)", body, re.I):
                        m = re.search(r"[^\n]*(couldn.t generate|violat|policy|try a different prompt|credits|limit reached)[^\n]*", body, re.I)
                        if m and re.search("credit|limit", m.group(0), re.I):
                            _down["why"] = "Flow credits / daily limit reached"
                        raise RuntimeError("Flow refused: " + (m.group(0)[:140] if m else "generation failed"))
                    if approved and not [v for v in _videos(page) if v not in before]:
                        # the media grid shows thumbnails (img), not <video>: open the newest new tile so its player loads
                        if _tiles(page) > tiles0 and time.time() - t0 > 45:
                            try:
                                page.evaluate("""() => { const t = Array.from(document.querySelectorAll('img, video')).filter(e => {
                                    const r = e.getBoundingClientRect(); return r.left > 240 && r.right < 1080 && r.width > 80 && r.height > 120; });
                                    if (t.length) (t[0].closest('a,button,[role=button],[tabindex]') || t[0]).click(); }""")
                                page.wait_for_timeout(5000)
                                if not [v for v in _videos(page) if v not in before]:
                                    try:
                                        page.mouse.move(318, 200); page.wait_for_timeout(2500)   # hover can start a preview <video>
                                    except Exception:
                                        pass
                                if not [v for v in _videos(page) if v not in before]:
                                    page.keyboard.press("Escape")   # no player yet (still being made): close and look again later
                            except Exception:
                                pass
                    fresh = [v for v in _videos(page) if v not in before]
                    if fresh:
                        page.wait_for_timeout(3000)   # let the element settle on its final source
                        fresh = [v for v in _videos(page) if v not in before] or fresh
                        src = fresh[-1]
                        break
                if not src:
                    raise RuntimeError(f"no clip after {timeout}s")
                tmp = out.with_suffix(".dl")
                _save(context, page, src, tmp)
                media.ff("-i", tmp, "-an", "-c:v", "libx264", "-crf", 18, "-pix_fmt", "yuv420p", "-r", 30, out, timeout=180)
                tmp.unlink(missing_ok=True)
            except Exception:
                try:   # evidence for the next fix: what Flow's page looked like when it failed (+ its HTML for selectors)
                    (out.parent / f"{key}_fail.png").write_bytes(page.screenshot(full_page=False))
                    (out.parent / f"{key}_fail.html").write_text(page.content(), encoding="utf-8")
                except Exception:
                    pass
                raise
            finally:
                context.close()
        if not (media.ok(out) and media.dur(out) >= 1):
            raise RuntimeError("downloaded clip is not a usable video")
        used[key] = {"prompt": prompt, "secs": round(media.dur(out), 2), "made": time.strftime("%Y-%m-%d %H:%M")}
        f.write_text(json.dumps(used, indent=1), encoding="utf-8")
        (out.with_suffix(".prompt.txt")).write_text(prompt, encoding="utf-8")
        log(f"  flow: clip ready ({media.dur(out):.1f}s, {time.time() - t0:.0f}s)")
        return out
    except Exception as e:
        out.unlink(missing_ok=True)
        shot = out.parent / f"{key}_fail.png"
        log(f"  flow failed ({str(e).splitlines()[0][:200]})" + (f"; screenshot {shot}" if shot.exists() else "") + "; next rung")
        return None
