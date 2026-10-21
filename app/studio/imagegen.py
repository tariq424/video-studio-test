"""Image generator rung (visual ladder v2, rung 3): Google Gemini in the signed-in Chrome profile, via Playwright.

Workflow, all in one Gemini chat:
  1. Open Gemini (https://gemini.google.com/app) in the Google-signed-in profile (default: the Flow profile, same account).
  2. Upload the source screenshot.
  3. "Describe this image in detail, then write a prompt to recreate it without brands or text."
     (+ one line asking Gemini to put the prompt on its own line after "PROMPT:", so it can be read back reliably)
  4. Paste that prompt back: "Generate an image: <prompt>" (with the frame shape, 9:16 or 16:9).
  5. Download the resulting image (Gemini's own download button, else the image source).
No source screenshot for the beat -> step 3 becomes "Write a prompt for a photorealistic image that illustrates this
narration, without brands or text: <narration>". No other model is used (no DeepSeek, Bing or Meta).
The image goes on to rung 4 (source parallax: rembg cut-out + Remotion 2.5D, depth.cutout_layers).

Failures are logged and the ladder moves on (Flow is next). Not signed in or a CAPTCHA / "unusual traffic" check skips
Gemini for the job (never automated); a usage-limit message cools it down for imagegen_cooldown_hours (default 6, saved
across jobs). Each failure saves <key>_gemini_<step>_fail.png/.html for selector fixes.
Settings: imagegen_on, gemini_profile ("" = the Flow profile), gemini_url, imagegen_timeout (240), imagegen_max_per_video (8),
imagegen_cooldown_hours, imagegen_headless.
"""
import json
import re
import time
from pathlib import Path

URL = "https://gemini.google.com/app"
LABEL = "GEMINI"
DESCRIBE = "Describe this image in detail, then write a prompt to recreate it without brands or text."
FORMAT = "Put the final prompt on its own line, starting with PROMPT:"
NARRATION = "Write a prompt for a photorealistic image that illustrates this narration, without brands or text: "
GENERATE = "Generate an image: "

RATE = re.compile(r"(reached your (daily )?limit|usage limit|limit for (today|now)|try again (later|tomorrow|in \d+)|"
                  r"too many requests|out of (quota|credits))", re.I)
CAPTCHA = re.compile(r"(captcha|unusual traffic|verify (that )?you('| a)re (a )?human|are you a robot|not a robot)", re.I)
REFUSED = re.compile(r"(can.t (create|generate|make) (images|that|this)|couldn.t (create|generate)|i can.t help with (that|this)|"
                     r"against (my|our) (policies|guidelines)|unable to (create|generate))", re.I)

_job_skip = {"why": ""}


def reset():
    _job_skip["why"] = ""


class Skip(Exception):
    def __init__(self, why, cool_secs=0):
        super().__init__(why)
        self.why, self.cool = why, cool_secs


def _state_path(cfg, sd):
    if cfg.get("imagegen_state"):
        return Path(cfg["imagegen_state"])
    return Path(cfg.get("jobs_dir") or Path(sd).parent.parent).parent / "imagegen_state.json"


def _cooling(cfg, sd):
    try: e = (json.loads(_state_path(cfg, sd).read_text(encoding="utf-8")) or {}).get("gemini") or {}
    except (OSError, ValueError): return None
    return e if float(e.get("until") or 0) > time.time() else None


def _cool(cfg, sd, secs, why):
    p = _state_path(cfg, sd)
    try: st = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError): st = {}
    st["gemini"] = {"until": time.time() + secs, "why": why, "set": time.strftime("%Y-%m-%d %H:%M")}
    try: p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps(st, indent=1), encoding="utf-8")
    except OSError: pass


def profile_dir(cfg):
    if cfg.get("gemini_profile"): return Path(cfg["gemini_profile"])
    from .flow import profile_dir as flow_profile
    return flow_profile(cfg)


# ---------------------------------------------------------------- page helpers
def _body(page):
    try: return page.locator("body").inner_text(timeout=3000)
    except Exception: return ""


def _responses(page):
    """Text of each Gemini answer, oldest first."""
    for sel in ("model-response", "message-content", "[data-test-id*='response' i]", ".model-response-text"):
        try:
            loc = page.locator(sel)
            if loc.count(): return [loc.nth(i).inner_text(timeout=3000) for i in range(loc.count())]
        except Exception:
            continue
    return []


def _busy(page):
    """Gemini is still writing (a Stop button is showing)."""
    try: return page.locator("button[aria-label*='Stop' i]").first.is_visible(timeout=500)
    except Exception: return False


def _big_images(page):
    try:
        return page.evaluate("""() => Array.from(document.images).filter(i => i.complete && Math.min(i.naturalWidth, i.naturalHeight) >= 300
            && i.getBoundingClientRect().width > 120).map(i => i.currentSrc || i.src).filter(s => s && !s.startsWith('data:image/svg'))""")
    except Exception:
        return []


def _check(page, step):
    body = _body(page)
    if CAPTCHA.search(body):
        raise Skip("Gemini shows a human check (CAPTCHA / unusual traffic); not automated: open the profile with "
                   "scripts\\imagegen-login.ps1 and complete it")
    m = RATE.search(body)
    if m: raise Skip(f"Gemini usage limit (\"{m.group(0)}\")", -1)
    return body


def _box(page):
    from .flow import _first
    box = _first(page, ["rich-textarea [contenteditable=true]", "div.ql-editor[contenteditable=true]", "[contenteditable=true]",
                        "textarea", "[role=textbox]"], 15000)
    if not box:
        body = _body(page)
        if "accounts.google.com" in page.url or re.search(r"^\s*sign in\s*$", body, re.I | re.M):
            raise Skip("the Gemini profile is not signed in to Google; run scripts\\imagegen-login.ps1 -Site gemini")
        raise RuntimeError("Gemini's prompt box was not found (the page may have changed)")
    return box


def _send(page, box, text):
    from .flow import _first
    box.click()
    if box.evaluate("e => e.tagName") in ("TEXTAREA", "INPUT"): box.fill(text)
    else: page.keyboard.insert_text(text)
    page.wait_for_timeout(800)
    send = _first(page, ["button[aria-label*='Send message' i]", "button[aria-label*='Send' i]", "button[aria-label*='Submit' i]"], 3000)
    if send:
        try: send.click(); return
        except Exception: pass
    box.press("Enter")


def _upload(page, image):
    """Attach the screenshot: an existing file input, else the upload menu (+ / 'Open upload file menu' -> 'Upload files')."""
    from .flow import _first
    inp = page.locator("input[type=file]")
    if inp.count():
        inp.first.set_input_files(str(image)); return True
    menu = _first(page, ["button[aria-label*='upload file menu' i]", "button[aria-label*='Add files' i]", "button[aria-label*='Upload' i]",
                         "button[aria-label*='Add' i]", "uploader button"], 4000)
    if not menu: return False
    menu.click(); page.wait_for_timeout(1200)
    inp = page.locator("input[type=file]")
    if inp.count():
        inp.first.set_input_files(str(image)); return True
    item = _first(page, ["[role=menuitem]:has-text('Upload')", "button:has-text('Upload files')", "text=/^Upload (files|file|image)/i"], 4000)
    if not item: return False
    with page.expect_file_chooser(timeout=10000) as fc:
        item.click()
    fc.value.set_files(str(image)); return True


def _wait_answer(page, before, timeout, step):
    """Wait for a NEW answer to finish streaming. -> its text."""
    t0, last, stable = time.time(), "", 0
    while time.time() - t0 < timeout:
        page.wait_for_timeout(2500)
        _check(page, step)
        res = _responses(page)
        if len(res) > before:
            text = res[-1].strip()
            stable = stable + 1 if text and text == last and not _busy(page) else 0
            last = text
            if stable >= 2: return text
    if last: return last
    raise RuntimeError(f"no answer from Gemini after {timeout}s")


def extract_prompt(text):
    """The recreate-prompt from Gemini's answer: the PROMPT: line (and what follows it), else a quoted / fenced block, else
    the last paragraph. -> text or ""."""
    t = str(text or "").replace("\r", "")
    m = re.search(r"PROMPT\s*[:\-]\s*(.+)", t, re.I | re.S)
    if m:
        p = m.group(1).strip()
    else:
        fence = re.findall(r"```(?:\w+)?\s*(.+?)```", t, re.S)
        quoted = re.findall(r"[\"“](.{80,}?)[\"”]", t, re.S)
        paras = [x.strip() for x in re.split(r"\n\s*\n", t) if len(x.split()) >= 15]
        p = (fence or quoted or paras[-1:] or [""])[-1].strip()
    p = re.sub(r"^\W+|[*_`#>]+", "", p)
    p = re.sub(r"\s+", " ", p).strip().strip('"“”')
    return p[:1500] if len(p.split()) >= 10 else ""


# ---------------------------------------------------------------- the browser session
def _session(cfg, image, aspect, vo, out, timeout, log, evidence):
    prof = profile_dir(cfg)
    if not prof.exists() or not any(prof.iterdir()):
        raise Skip(f"no signed-in Google profile at {prof}; run scripts\\imagegen-login.ps1 -Site gemini once")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise Skip("Playwright is not installed in this environment")
    with sync_playwright() as pw:
        kw = dict(user_data_dir=str(prof), headless=bool(cfg.get("imagegen_headless", False)), accept_downloads=True,
                  viewport={"width": 1440, "height": 900}, args=["--disable-blink-features=AutomationControlled"])
        if cfg.get("flow_chrome"): kw["executable_path"] = cfg["flow_chrome"]
        else: kw["channel"] = "chrome"
        context = pw.chromium.launch_persistent_context(**kw)
        page = context.pages[0] if context.pages else context.new_page()
        step = "open"
        try:
            page.goto(cfg.get("gemini_url") or URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(5000)
            _check(page, step)
            box = _box(page)
            # 2-3: describe the screenshot and write the recreate prompt (or a prompt from the narration)
            step = "describe"
            n0 = len(_responses(page))
            if image:
                if not _upload(page, image): raise RuntimeError("Gemini's upload control was not found")
                page.wait_for_timeout(4000)
                log(f"  gemini: screenshot uploaded ({Path(image).name}); asking for a description and a prompt")
                _send(page, box, DESCRIBE + " " + FORMAT)
            else:
                log("  gemini: no source screenshot; asking for a prompt from the narration")
                _send(page, box, NARRATION + vo[:1200] + " " + FORMAT)
            answer = _wait_answer(page, n0, timeout, step)
            prompt = extract_prompt(answer)
            if not prompt: raise RuntimeError("no prompt found in Gemini's answer")
            log(f"  gemini: prompt ({len(prompt.split())} words): \"{prompt[:160]}...\"")
            # 4: generate the image from that prompt, in the same chat
            step = "generate"
            shape = "Tall vertical 9:16 portrait image." if aspect == "9:16" else "Wide horizontal 16:9 landscape image."
            before = set(_big_images(page)); n1 = len(_responses(page))
            box = _box(page)
            _send(page, box, f"{GENERATE}{prompt} {shape} No text, letters, logos or brand names.")
            t0 = time.time(); src = None
            while time.time() - t0 < timeout:
                page.wait_for_timeout(4000)
                _check(page, step)
                res = _responses(page)
                if len(res) > n1 and REFUSED.search(res[-1]) and not _busy(page):
                    raise RuntimeError("Gemini declined to generate the image: " + res[-1].strip()[:160])
                fresh = [s for s in _big_images(page) if s not in before]
                if fresh and not _busy(page):
                    page.wait_for_timeout(3000)
                    fresh = [s for s in _big_images(page) if s not in before] or fresh
                    src = fresh[-1]; break
            if not src: raise RuntimeError(f"no generated image after {timeout}s")
            # 5: download (Gemini's full-size download button first, else the image source)
            step = "download"
            _download(context, page, src, out)
            return prompt
        except Exception:
            evidence(page, step)
            raise
        finally:
            context.close()


def _download(context, page, src, out):
    from .flow import _save
    tmp = Path(out).with_suffix(".dl")
    got = False
    try:   # hover the image so its toolbar shows, then "Download full size image"
        page.locator(f"img[src='{src}']").first.hover(timeout=3000); page.wait_for_timeout(800)
        btn = page.locator("button[aria-label*='Download' i]").last
        if btn.count():
            with page.expect_download(timeout=60000) as dl:
                btn.click()
            dl.value.save_as(str(tmp)); got = True
    except Exception:
        got = False
    if not got:
        if src.startswith("blob:") or src.startswith("data:"):
            _save(context, page, src, tmp)
        else:
            big = re.sub(r"=s\d+(-[a-z0-9-]+)?$", "=s0", src) if "googleusercontent" in src else src
            r = context.request.get(big, timeout=120000)
            if not r.ok: r = context.request.get(src, timeout=120000)
            if not r.ok: raise RuntimeError(f"image download HTTP {r.status}")
            tmp.write_bytes(r.body())
    from PIL import Image
    with Image.open(tmp) as im:
        im = im.convert("RGB")
        if min(im.size) < 300: raise RuntimeError(f"downloaded image is too small ({im.size[0]}x{im.size[1]})")
        im.save(out, "JPEG", quality=93)
    tmp.unlink(missing_ok=True)


# ---------------------------------------------------------------- ladder entry
def generate(cfg, sd, sec, key, log, aspect="9:16", image=None):
    """Rung 3. -> (image_path, "gemini", prompt) or (None, None, None). Never raises (cancel aside)."""
    if not cfg.get("imagegen_on", True):
        return None, None, None
    if _job_skip["why"]:
        log(f"  gemini skipped ({_job_skip['why'][:140]})"); return None, None, None
    cool = _cooling(cfg, sd)
    if cool:
        _job_skip["why"] = f"cooling down until {time.strftime('%H:%M', time.localtime(cool['until']))}: {cool['why'][:100]}"
        log(f"  gemini skipped ({_job_skip['why']})"); return None, None, None
    d = Path(sd) / "imagegen"; d.mkdir(parents=True, exist_ok=True)
    led = d / "gemini_usage.json"
    try: used = json.loads(led.read_text(encoding="utf-8")) if led.exists() else {}
    except (OSError, ValueError): used = {}
    cap = int(cfg.get("imagegen_max_per_video", 8))
    if len(used) >= cap and key not in used:
        log(f"  gemini: {cap} images already made for this video; next rung"); return None, None, None
    out = d / f"{key}_gemini.jpg"
    if out.is_file() and key in used:
        return out, "gemini", used[key].get("prompt", "")
    image = str(image) if image and Path(image).is_file() else None
    timeout = int(cfg.get("imagegen_timeout", 240))
    def evidence(page, step):
        try:
            (d / f"{key}_gemini_{step}_fail.png").write_bytes(page.screenshot(full_page=False))
            (d / f"{key}_gemini_{step}_fail.html").write_text(page.content(), encoding="utf-8")
        except Exception:
            pass
    t0 = time.time()
    try:
        prompt = _session(cfg, image, aspect, str(sec.get("vo") or sec.get("still_prompt") or ""), out, timeout, log, evidence)
    except Skip as s:
        cool = int(float(cfg.get("imagegen_cooldown_hours", 6)) * 3600) if s.cool == -1 else s.cool
        _job_skip["why"] = s.why
        if cool: _cool(cfg, sd, cool, s.why)
        log(f"  gemini skipped: {s.why}" + (f" (saved: retried after {cool // 3600} h)" if cool else " (rest of this job)") + "; next rung")
        return None, None, None
    except Exception as e:
        if str(e) == "cancelled": raise
        out.unlink(missing_ok=True)
        fails = sorted(d.glob(f"{key}_gemini_*_fail.png"))
        log(f"  gemini failed ({str(e).splitlines()[0][:200]})" + (f"; screenshot {fails[-1]}" if fails else "") + "; next rung")
        return None, None, None
    used[key] = {"prompt": prompt, "from_screenshot": bool(image), "made": time.strftime("%Y-%m-%d %H:%M")}
    led.write_text(json.dumps(used, indent=1), encoding="utf-8")
    out.with_suffix(".prompt.txt").write_text(prompt, encoding="utf-8")
    log(f"  gemini: image ready ({time.time() - t0:.0f}s)")
    return out, "gemini", prompt


def tag(site="gemini"):
    return f"GENERATED · {LABEL}"
