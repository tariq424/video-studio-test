"""Image generator rung (visual ladder v2, rung 3): Gemini, ChatGPT and Bing Image Creator in signed-in browser
profiles, via Playwright, with no visible window. ONE service per video, rotating between videos (Gemini -> ChatGPT ->
Bing -> ...), so each account carries a third of the load and a video keeps one look. If a service fails or hits a limit,
the beat moves to the next service (a limit or a human check cools that service down / skips it for the job).
  gemini : Chrome, the Flow profile (F:\\videos_test\\flow_profile); the describe -> prompt -> generate chat below
  chatgpt: Chrome, F:\\videos_test\\chatgpt_profile; screenshot (or narration) -> "create an image" in one chat
  bing   : Edge,   F:\\videos_test\\bing_profile; a text prompt (DeepSeek writes it from the beat); 4 images per request
  hf     : Hugging Face's free FLUX.1-schnell Space via gradio_client (no browser, no account; hf_token raises the quota)
Sign in once with scripts\\imagegen-login.ps1 -Site gemini|chatgpt|bing.

Gemini's workflow:

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
imagegen_cooldown_hours, imagegen_headless (true), imagegen_delay_secs ([15, 30]: human pacing between requests, per
service), imagegen_providers (["gemini", "chatgpt", "bing"]: the rotation), chatgpt_profile, bing_profile.
"""
import json
import re
import time
from pathlib import Path

URL = "https://gemini.google.com/app"
LABEL = "GEMINI"
DESCRIBE = "Describe this image in detail, then write a prompt to recreate it without brands or text."
FORMAT = "Put the final prompt on its own line, starting with PROMPT:"
# Never a real person's likeness (a "US president at a podium" came back looking like a former president, in a story
# about another one): people only as anonymous figures.
NO_PEOPLE = ("The prompt must not show any real or recognizable person, politician or celebrity: show people only as "
             "anonymous figures seen from behind, in silhouette, as hands, or out of focus.")
NARRATION = "Write a prompt for a photorealistic image that illustrates this narration, without brands or text: "
GENERATE = "Generate an image: "
VARIANTS = ["Generate a second image of the same scene from a different camera angle, same style and lighting.",
            "Generate another image of the same scene as a close-up of the main subject, same style and lighting."]

RATE = re.compile(r"(reached your (daily )?limit|usage limit|limit for (today|now)|try again (later|tomorrow|in \d+)|"
                  r"too many requests|out of (quota|credits)|(hit|reached) (the|your) [a-z ]{0,30}limit|limit resets)", re.I)
CAPTCHA = re.compile(r"(captcha|unusual traffic|verify (that )?you('| a)re (a )?human|are you a robot|not a robot)", re.I)
REFUSED = re.compile(r"(can.t (create|generate|make) (images|that|this)|couldn.t (create|generate)|i can.t help with (that|this)|"
                     r"against (my|our) (policies|guidelines)|unable to (create|generate))", re.I)

PROVIDERS = ("gemini", "chatgpt", "bing", "hf")
HF_SPACE = "black-forest-labs/FLUX.1-schnell"   # Hugging Face's free hosted FLUX (ZeroGPU): runs on their GPUs, not this PC
_job_skip = {}       # site -> why it's skipped for the rest of this job
_last = {}           # site -> when it last answered: each service is paced like a person, not a script
_site = {"cur": "gemini"}   # the service that made the images generate_many returned last (for tag())
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
UA_EDGE = UA + " Edg/141.0.0.0"
CHATGPT_URL = "https://chatgpt.com/"
BING_URL = "https://www.bing.com/images/create"


def _pause(cfg, log, why, site="gemini"):
    """Wait a human-looking 15-30 s (imagegen_delay_secs) since this service's last answer before the next request."""
    import random
    lo, hi = (cfg.get("imagegen_delay_secs") or [15, 30])[:2]
    wait = random.uniform(float(lo), float(hi)) - (time.time() - _last.get(site, 0.0))
    if wait > 0:
        log(f"  {site}: pausing {wait:.0f}s before {why} (human pacing)")
        time.sleep(wait)


def _answered(site="gemini"):
    _last[site] = time.time()


def reset():
    _job_skip.clear()


def last_site():
    return _site["cur"]


class Skip(Exception):
    def __init__(self, why, cool_secs=0):
        super().__init__(why)
        self.why, self.cool = why, cool_secs


def _state_path(cfg, sd):
    if cfg.get("imagegen_state"):
        return Path(cfg["imagegen_state"])
    return Path(cfg.get("jobs_dir") or Path(sd).parent.parent).parent / "imagegen_state.json"


def _cooling(cfg, sd, site="gemini"):
    try: e = (json.loads(_state_path(cfg, sd).read_text(encoding="utf-8")) or {}).get(site) or {}
    except (OSError, ValueError): return None
    return e if float(e.get("until") or 0) > time.time() else None


def _cool(cfg, sd, secs, why, site="gemini"):
    p = _state_path(cfg, sd)
    try: st = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError): st = {}
    st[site] = {"until": time.time() + secs, "why": why, "set": time.strftime("%Y-%m-%d %H:%M")}
    try: p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps(st, indent=1), encoding="utf-8")
    except OSError: pass


def profile_dir(cfg, site="gemini"):
    if site != "gemini":
        if cfg.get(f"{site}_profile"): return Path(cfg[f"{site}_profile"])
        return Path(cfg.get("jobs_dir") or ".").parent / f"{site}_profile"
    if cfg.get("gemini_profile"): return Path(cfg["gemini_profile"])
    from .flow import profile_dir as flow_profile
    return flow_profile(cfg)


def _job_provider(cfg, sd, order):
    """One service per video, rotating between videos. Remembered in <sd>/imagegen/provider.txt."""
    f = Path(sd) / "imagegen" / "provider.txt"
    try:
        cur = f.read_text(encoding="utf-8").strip()
        if cur in order: return cur
    except OSError:
        pass
    p = _state_path(cfg, sd)
    try: st = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError): st = {}
    n = int(st.get("rotation", 0) or 0)
    cur = order[n % len(order)]
    st["rotation"] = n + 1
    try: p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps(st, indent=1), encoding="utf-8")
    except OSError: pass
    try: f.parent.mkdir(parents=True, exist_ok=True); f.write_text(cur, encoding="utf-8")
    except OSError: pass
    return cur


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
def _session(cfg, image, aspect, vo, out, timeout, log, evidence, extras=()):
    prof = profile_dir(cfg)
    if not prof.exists() or not any(prof.iterdir()):
        raise Skip(f"no signed-in Google profile at {prof}; run scripts\\imagegen-login.ps1 -Site gemini once")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise Skip("Playwright is not installed in this environment")
    with sync_playwright() as pw:
        headless = bool(cfg.get("imagegen_headless", True))   # no visible window (owner's choice 2026-10-21)
        kw = dict(user_data_dir=str(prof), headless=headless, accept_downloads=True,
                  viewport={"width": 1440, "height": 900}, args=["--disable-blink-features=AutomationControlled"])
        if headless:   # headless Chrome announces itself in its user agent; present as normal Chrome
            kw["user_agent"] = UA
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
            _pause(cfg, log, "this beat's first request")
            if image:
                if not _upload(page, image): raise RuntimeError("Gemini's upload control was not found")
                page.wait_for_timeout(4000)
                log(f"  gemini: screenshot uploaded ({Path(image).name}); asking for a description and a prompt")
                _send(page, box, DESCRIBE + " " + NO_PEOPLE + " " + FORMAT)
            else:
                log("  gemini: no source screenshot; asking for a prompt from the narration")
                _send(page, box, NARRATION + vo[:1200] + " " + NO_PEOPLE + " " + FORMAT)
            answer = _wait_answer(page, n0, timeout, step); _answered()
            prompt = extract_prompt(answer)
            if not prompt: raise RuntimeError("no prompt found in Gemini's answer")
            log(f"  gemini: prompt ({len(prompt.split())} words): \"{prompt[:160]}...\"")
            # 4: generate the image from that prompt, in the same chat
            step = "generate"
            shape = "Tall vertical 9:16 portrait image." if aspect == "9:16" else "Wide horizontal 16:9 landscape image."
            box = _box(page)
            _pause(cfg, log, "the image request")
            src = _ask_image(page, box, f"{GENERATE}{prompt} {shape} No text, letters, logos or brand names. No real or recognizable people.", timeout, step)
            # 5: download (Gemini's full-size download button first, else the image source)
            step = "download"
            _download(context, page, src, out)
            # extra images for a beat that needs more than one visual: same scene, another angle / a close-up (saves Flow credits)
            for k, extra in enumerate(extras):
                try:
                    _pause(cfg, log, f"image {k + 2}")
                    log(f"  gemini: image {k + 2}: {VARIANTS[k % len(VARIANTS)].split(',')[0].lower()}")
                    src = _ask_image(page, _box(page), f"{VARIANTS[k % len(VARIANTS)]} {shape} No text, letters, logos or brand names. No real or recognizable people.",
                                     timeout, "generate")
                    _download(context, page, src, extra)
                except Exception as e:   # the first image is already saved: keep it, report the extra one (a limit hit here is
                                         # seen again, and cooled down, on the next beat)
                    log(f"  gemini: image {k + 2} failed ({str(e).splitlines()[0][:150]})"); Path(extra).unlink(missing_ok=True)
                    evidence(page, f"extra{k + 2}")
                    break
            return prompt
        except Exception:
            evidence(page, step)
            raise
        finally:
            context.close()


def _ask_image(page, box, text, timeout, step):
    """Send a generate request in the chat and wait for the new image. -> its src."""
    before = set(_big_images(page)); n1 = len(_responses(page))
    _send(page, box, text)
    t0 = time.time()
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
            _answered()
            return fresh[-1]
    raise RuntimeError(f"no generated image after {timeout}s")


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


# ---------------------------------------------------------------- ChatGPT and Bing
def _launch(pw, cfg, site):
    prof = profile_dir(cfg, site)
    if not prof.exists() or not any(prof.iterdir()):
        raise Skip(f"no signed-in {site} profile at {prof}; run scripts\\imagegen-login.ps1 -Site {site} once")
    headless = bool(cfg.get("imagegen_headless", True))
    kw = dict(user_data_dir=str(prof), headless=headless, accept_downloads=True, channel="msedge" if site == "bing" else "chrome",
              viewport={"width": 1440, "height": 900}, args=["--disable-blink-features=AutomationControlled"])
    if headless: kw["user_agent"] = UA_EDGE if site == "bing" else UA
    context = pw.chromium.launch_persistent_context(**kw)
    return context, (context.pages[0] if context.pages else context.new_page())


def _check_site(page, site, step):
    body = _body(page)
    if CAPTCHA.search(body):
        raise Skip(f"{site} shows a human check; not automated: open the profile with scripts\\imagegen-login.ps1 -Site {site} and complete it")
    m = RATE.search(body)
    if m: raise Skip(f"{site} usage limit (\"{m.group(0)}\")", -1)
    return body


def _new_images(page, before, pattern=None, min_side=400):
    js = """([before, pat, minSide]) => Array.from(document.images).filter(i => i.complete && Math.min(i.naturalWidth, i.naturalHeight) >= minSide
        && !before.includes(i.currentSrc || i.src) && (!pat || new RegExp(pat).test(i.currentSrc || i.src)))
        .map(i => i.currentSrc || i.src)"""
    try: return page.evaluate(js, [list(before), pattern, min_side])
    except Exception: return []


def _session_chatgpt(cfg, image, aspect, vo, out, timeout, log, evidence, extras=()):
    from playwright.sync_api import sync_playwright
    from .flow import _first
    shape = "Tall vertical 9:16 portrait image." if aspect == "9:16" else "Wide horizontal 16:9 landscape image."
    rules = "Photorealistic. No text, letters, logos or brand names. " + NO_PEOPLE.replace("The prompt must", "It must")
    with sync_playwright() as pw:
        context, page = _launch(pw, cfg, "chatgpt")
        step = "open"
        try:
            page.goto(CHATGPT_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(5000)
            _check_site(page, "chatgpt", step)
            box = _first(page, ["#prompt-textarea", "div.ProseMirror[contenteditable=true]", "div[contenteditable=true][role=textbox]",
                                "textarea[placeholder*='Ask' i]"], 20000)
            if not box:
                if re.search(r"\b(log in|sign up)\b", _body(page), re.I):
                    raise Skip("the ChatGPT profile is not signed in; run scripts\\imagegen-login.ps1 -Site chatgpt")
                raise RuntimeError("ChatGPT's prompt box was not found (the page may have changed)")
            step = "generate"
            _pause(cfg, log, "this beat's image", "chatgpt")
            used = False
            if image:
                try:
                    inp = page.locator("input[type=file]")
                    if inp.count():
                        inp.first.set_input_files(str(image)); page.wait_for_timeout(5000); used = True
                except Exception:
                    used = False
            if used:
                prompt = ("Create a new, original image inspired by the scene in this screenshot: keep its subject and mood, "
                          f"use a fresh composition. {shape} {rules}")
                log(f"  chatgpt: screenshot attached ({Path(image).name}); asking for an image of that scene")
            else:
                prompt = f"Create an image that illustrates this narration: {vo[:900]} {shape} {rules}"
                log("  chatgpt: asking for an image from the narration")
            before = set(_big_images(page))
            box.click(); page.keyboard.insert_text(prompt); page.wait_for_timeout(600); page.keyboard.press("Enter")
            src = _wait_chatgpt(page, before, timeout, step)
            step = "download"
            _download(context, page, src, out)
            for k, extra in enumerate(extras):
                try:
                    _pause(cfg, log, f"image {k + 2}", "chatgpt")
                    log(f"  chatgpt: image {k + 2}: {VARIANTS[k % len(VARIANTS)].split(',')[0].lower()}")
                    before = set(_big_images(page))
                    box = _first(page, ["#prompt-textarea", "div.ProseMirror[contenteditable=true]", "div[contenteditable=true][role=textbox]"], 10000)
                    box.click(); page.keyboard.insert_text(f"{VARIANTS[k % len(VARIANTS)]} {shape} {rules}"); page.keyboard.press("Enter")
                    _download(context, page, _wait_chatgpt(page, before, timeout, "generate"), extra)
                except Exception as e:
                    log(f"  chatgpt: image {k + 2} failed ({str(e).splitlines()[0][:150]})"); Path(extra).unlink(missing_ok=True)
                    evidence(page, f"extra{k + 2}"); break
            return prompt
        except Exception:
            evidence(page, step); raise
        finally:
            context.close()


def _wait_chatgpt(page, before, timeout, step):
    t0, last, stable = time.time(), None, 0
    while time.time() - t0 < timeout:
        page.wait_for_timeout(3000)
        body = _check_site(page, "chatgpt", step)
        busy = page.locator("[data-testid='stop-button']").count() or re.search(r"Creating image|Generating image", body)
        fresh = [x for x in _big_images(page) if x not in before]
        if fresh and not busy:
            stable = stable + 1 if fresh[-1] == last else 0
            last = fresh[-1]
            if stable >= 2:   # the same final image three checks in a row (not the blurred preview)
                _answered("chatgpt"); return last
        elif not busy and REFUSED.search(body[-1500:]) and time.time() - t0 > 20:
            raise RuntimeError("ChatGPT declined to generate the image")
    raise RuntimeError(f"no image from ChatGPT after {timeout}s")


LOCAL_DESCRIBE = """Describe this image in detail (setting, objects, people's roles but not who they are, light, mood), then write a
prompt of 40-80 words to recreate it as a new photorealistic image. No brands, no logos, no text, no real or recognisable people.
The narration it will illustrate: "{vo}"
Reply with JSON only: {{"description": "...", "prompt": "..."}}"""


def describe_local(cfg, image, vo, log):
    """The source screenshot described by this PC's own vision model (Ollama, no account) -> a recreate prompt, or "".
    The backup for the Gemini describe step, and how Bing / Hugging Face get a prompt from the screenshot."""
    if not image or not cfg.get("imagegen_describe_local", True): return ""
    try:
        from . import footage
        from .llm import parse_json
        c = dict(cfg)
        if c.get("vet_provider", "local") in ("off", "", None): c["vet_provider"] = "local"
        j = parse_json(footage._vision(c, image, LOCAL_DESCRIBE.format(vo=str(vo or "")[:300].replace('"', "'"))))
        pr = re.sub(r"\s+", " ", str(j.get("prompt") or "")).strip()
        if len(pr.split()) >= 12:
            log(f"  screenshot described by the local vision model: \"{pr[:120]}...\"")
            return pr
    except Exception as e:
        log(f"  local describe failed ({str(e)[:100]}); the prompt comes from the narration")
    return ""


def _session_bing(cfg, sec, aspect, out, timeout, log, evidence, extras=()):
    from playwright.sync_api import sync_playwright
    from .flow import visual_prompt
    prompt = re.sub(r"(?i)slow (cinematic )?camera move[^.]*\.?", "", sec.get("described_prompt") or visual_prompt(cfg, sec, log))
    prompt = re.sub(r"\s+", " ", prompt).strip()[:420] + " No text, no logos. No real or recognizable people."
    with sync_playwright() as pw:
        context, page = _launch(pw, cfg, "bing")
        step = "open"
        try:
            page.goto(BING_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(5000)
            _check_site(page, "bing", step)
            box = page.get_by_placeholder("Describe the image", exact=False).first
            try: box.wait_for(state="visible", timeout=20000)
            except Exception: raise RuntimeError("Bing's prompt box was not found (the page may have changed)")
            if page.locator("a#id_l, a:has-text('Sign in'), button:has-text('Join & Create')").count() and \
                    not page.locator("#id_n, [aria-label*='Account' i], #id_p").count():
                log("  bing: the page shows a Sign in link (it often does even when signed in); trying anyway")
            # the aspect ratio control (9:16 for Shorts); best effort
            try:
                want = "9:16" if aspect == "9:16" else "16:9"
                page.get_by_text("Aspect Ratio", exact=False).first.click(timeout=3000); page.wait_for_timeout(600)
                page.get_by_text(want, exact=True).first.click(timeout=3000)
            except Exception:
                pass
            step = "generate"
            _pause(cfg, log, "this beat's image", "bing")
            box.click(); page.keyboard.insert_text(prompt); page.wait_for_timeout(500)
            log(f"  bing: prompt ({len(prompt.split())} words): \"{prompt[:140]}...\"")
            page.get_by_role("button", name="Generate").first.click()
            t0, got = time.time(), []
            while time.time() - t0 < timeout:
                page.wait_for_timeout(3000)
                body = _check_site(page, "bing", step)
                got = _new_images(page, [], r"/th/id/OIG|OIG\d", 200)
                if got:
                    page.wait_for_timeout(4000)
                    got = _new_images(page, [], r"/th/id/OIG|OIG\d", 200); break
                if re.search(r"content warning|unsafe image|can.t create|blocked", body, re.I):
                    raise RuntimeError("Bing declined the prompt")
            if not got: raise RuntimeError(f"no image from Bing after {timeout}s")
            _answered("bing")
            step = "download"
            seen = []
            for u in got:
                full = u.split("?")[0]
                if full not in seen: seen.append(full)
            _download(context, page, seen[0], out)
            for k, extra in enumerate(extras):   # Bing returns several versions per request: the extras cost no extra request
                if k + 1 < len(seen):
                    try: _download(context, page, seen[k + 1], extra)
                    except Exception as e: log(f"  bing: image {k + 2} failed ({str(e)[:120]})"); Path(extra).unlink(missing_ok=True)
            return prompt
        except Exception:
            evidence(page, step); raise
        finally:
            context.close()


def _session_hf(cfg, sec, aspect, out, timeout, log, evidence, extras=()):
    """Hugging Face Space (FLUX.1-schnell) through the official gradio client: no browser, no Google/OpenAI/Microsoft
    account. Free quota per day (more with a free HF token: settings hf_token)."""
    try:
        from gradio_client import Client
    except ImportError:
        raise Skip("gradio_client is not installed (pip install gradio_client)")
    from .flow import visual_prompt
    import shutil
    prompt = re.sub(r"(?i)slow (cinematic )?camera move[^.]*\.?", "", sec.get("described_prompt") or visual_prompt(cfg, sec, log))
    prompt = re.sub(r"\s+", " ", prompt).strip()[:700] + " Photorealistic. No text, no logos. No real or recognizable people."
    w, h = (768, 1344) if aspect == "9:16" else (1344, 768)
    _pause(cfg, log, "this beat's image", "hf")
    log(f"  hf: prompt ({len(prompt.split())} words): \"{prompt[:140]}...\"")
    try:
        client = Client(cfg.get("hf_space") or HF_SPACE, token=cfg.get("hf_token") or None, verbose=False)
        files = []
        for k in range(1 + len(extras)):
            if k: _pause(cfg, log, f"image {k + 1}", "hf")
            res = client.predict(prompt, 0, True, w, h, 4, api_name="/infer")
            files.append(res[0] if isinstance(res, (list, tuple)) else res)
    except Exception as e:
        msg = str(e)
        if re.search(r"quota|rate limit|too many|exceeded", msg, re.I): raise Skip(f"Hugging Face quota ({msg[:120]})", -1)
        raise RuntimeError(f"Hugging Face: {msg[:200]}")
    _answered("hf")
    from PIL import Image
    for k, (f, dest) in enumerate(zip(files, [out] + list(extras))):
        src = f.get("path") if isinstance(f, dict) else f
        with Image.open(src) as im: im.convert("RGB").save(dest, "JPEG", quality=93)
        why = _has_text(cfg, dest, log)
        if why and k == 0:   # an obvious physical mistake: one more try with a new seed, then the next service
            log(f"  hf: image looks wrong ({why}); one more try")
            try:
                _pause(cfg, log, "a retry", "hf")
                res = client.predict(prompt, 0, True, w, h, 4, api_name="/infer"); _answered("hf")
                f2 = res[0] if isinstance(res, (list, tuple)) else res
                with Image.open(f2.get("path") if isinstance(f2, dict) else f2) as im: im.convert("RGB").save(dest, "JPEG", quality=93)
                why = _has_text(cfg, dest, log)
            except Exception as e:
                why = why or str(e)[:80]
            if why:
                Path(dest).unlink(missing_ok=True)
                raise RuntimeError(f"Hugging Face images kept coming out wrong ({why})")
        elif why:
            log(f"  hf: image {k + 1} looks wrong ({why}); dropped"); Path(dest).unlink(missing_ok=True)
    return prompt


TEXT_CHECK = ('Check this AI-generated image for obvious physical mistakes only: an object with the wrong number of parts (a plane '
              'with extra wings or engines, a car with extra wheels, a bike with three pedals), malformed hands or limbs, or impossible, '
              'melted or fused structures. Ignore any text, lettering, signs or license plates. Reply with JSON only: '
              '{"broken": "yes" or "no", "what": "<the mistake, a few words>"}')


def _has_text(cfg, image, log):
    """Local vision check (Ollama on this PC, no account usage): -> short reason if the image has an obvious physical mistake
    (a four-winged plane, extra wheels, mangled hands), else "". Text and fake plates are fine."""
    if cfg.get("vet_provider", "local") != "local" or not cfg.get("imagegen_text_check", True): return ""
    try:
        from .footage import _vision
        from .llm import parse_json
        j = parse_json(_vision(cfg, image, TEXT_CHECK))
        return str(j.get("what") or "a physical mistake")[:60] if str(j.get("broken", "no")).strip().lower() in ("yes", "true", "1") else ""
    except Exception as e:
        log(f"  text check unavailable ({str(e)[:80]}); keeping the image"); return ""


# ---------------------------------------------------------------- ladder entry
def generate(cfg, sd, sec, key, log, aspect="9:16", image=None, count=1):
    """Rung 3. -> (image_path, site, prompt) or (None, None, None). Never raises (cancel aside)."""
    res = generate_many(cfg, sd, sec, key, log, aspect, image, count)
    return (res[0][0], _site["cur"], res[0][1]) if res else (None, None, None)


def generate_many(cfg, sd, sec, key, log, aspect="9:16", image=None, count=1):
    """-> [(image_path, prompt), ...] (first = the scene, then variants), or []. Never raises (cancel aside).
    The video's service first (rotation), then the others if it fails; last_site() says which one made them."""
    count = max(1, min(int(count), 1 + len(VARIANTS), int(cfg.get("imagegen_per_beat", 1))))
    if not cfg.get("imagegen_on", True):
        return []
    order = [x for x in (cfg.get("imagegen_providers") or PROVIDERS) if x in PROVIDERS] or ["gemini"]
    d = Path(sd) / "imagegen"; d.mkdir(parents=True, exist_ok=True)
    led = d / "gemini_usage.json"   # (name kept from when Gemini was the only service: one ledger per video)
    try: used = json.loads(led.read_text(encoding="utf-8")) if led.exists() else {}
    except (OSError, ValueError): used = {}
    if key in used:   # already made (a resumed job)
        site = used[key].get("site", "gemini")
        files = [d / f for f in used[key].get("files", [])] or [d / f"{key}_gemini.jpg"] + [d / f"{key}_gemini_{k + 2}.jpg" for k in range(count - 1)]
        files = [x for x in files if x.is_file()]
        if files:
            _site["cur"] = site
            return [(x, used[key].get("prompt", "")) for x in files]
    cap = int(cfg.get("imagegen_max_per_video", 8))
    if len(used) >= cap:
        log(f"  image generators: {cap} images already made for this video; next rung"); return []
    if not cfg.get("imagegen_rotate", False):   # fixed priority (default): the list order, every beat
        pref, first, tries = None, order[0], list(order)
    else:   # rotation: one service per video, taking turns (imagegen_first tried before it)
        pref = cfg.get("imagegen_first") if cfg.get("imagegen_first") in order else None
        first = _job_provider(cfg, sd, [x for x in order if x != pref] or order)
        tries = ([pref] if pref else []) + [first] + [x for x in order if x not in (first, pref)]
    image = str(image) if image and Path(image).is_file() else None
    timeout = int(cfg.get("imagegen_timeout", 240))
    vo = str(sec.get("vo") or sec.get("still_prompt") or "")
    described = None   # the screenshot described once by the local vision model, for the services that take a text prompt
    for site in tries:
        if _job_skip.get(site):
            log(f"  {site} skipped ({_job_skip[site][:140]})"); continue
        cool = _cooling(cfg, sd, site)
        if cool:
            _job_skip[site] = f"cooling down until {time.strftime('%H:%M', time.localtime(cool['until']))}: {cool['why'][:100]}"
            log(f"  {site} skipped ({_job_skip[site]})"); continue
        out = d / f"{key}_{site}.jpg"
        extras = [d / f"{key}_{site}_{k + 2}.jpg" for k in range(count - 1)]
        def evidence(page, step, site=site):
            try:
                (d / f"{key}_{site}_{step}_fail.png").write_bytes(page.screenshot(full_page=False))
                (d / f"{key}_{site}_{step}_fail.html").write_text(page.content(), encoding="utf-8")
            except Exception:
                pass
        t0 = time.time()
        try:
            if site == "gemini":
                prompt = _session(cfg, image, aspect, vo, out, timeout, log, evidence, extras)
            elif site == "chatgpt":
                prompt = _session_chatgpt(cfg, image, aspect, vo, out, timeout, log, evidence, extras)
            elif site in ("hf", "bing"):
                if image and described is None: described = describe_local(cfg, image, vo, log)
                s2 = dict(sec, described_prompt=described) if described else sec
                prompt = (_session_hf if site == "hf" else _session_bing)(cfg, s2, aspect, out, timeout, log, evidence, extras)
        except Skip as s_:
            cool = int(float(cfg.get("imagegen_cooldown_hours", 6)) * 3600) if s_.cool == -1 else s_.cool
            _job_skip[site] = s_.why
            if cool: _cool(cfg, sd, cool, s_.why, site)
            log(f"  {site} skipped: {s_.why}" + (f" (retried after {cool // 3600} h)" if cool else " (rest of this job)") + "; next service")
            continue
        except Exception as e:
            if str(e) == "cancelled": raise
            out.unlink(missing_ok=True)
            fails = sorted(d.glob(f"{key}_{site}_*_fail.png"))
            log(f"  {site} failed ({str(e).splitlines()[0][:200]})" + (f"; screenshot {fails[-1]}" if fails else "") + "; next service")
            continue
        got = [out] + [x for x in extras if x.is_file()]
        if cfg.get("imagegen_rotate", False) and site not in (first, pref):   # the video's service is out: the rest of this video uses the one that worked (one look per video)
            try: (d / "provider.txt").write_text(site, encoding="utf-8")
            except OSError: pass
        used[key] = {"prompt": prompt, "site": site, "files": [x.name for x in got], "from_screenshot": bool(image),
                     "made": time.strftime("%Y-%m-%d %H:%M")}
        led.write_text(json.dumps(used, indent=1), encoding="utf-8")
        out.with_suffix(".prompt.txt").write_text(prompt, encoding="utf-8")
        _site["cur"] = site
        log(f"  {site}: {len(got)} image(s) ready ({time.time() - t0:.0f}s)")
        return [(x, prompt) for x in got]
    return []


def tag(site=None):
    return f"GENERATED · {(site or _site['cur']).upper()}"
