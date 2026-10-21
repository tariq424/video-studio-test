"""Free image generators (visual ladder v2, rung 3): Bing Image Creator, then Meta AI.

Vision-to-image workflow (the owner's manual proof, automated):
  1. Upload the source screenshot and ask "Describe this image in detail."  -> the site's text description
  2. Ask "Generate an image based on this description, no brands or text: <description>"
  3. Download the generated image.
Without a source screenshot for the beat, step 2 uses the beat's own visual prompt.
The image then goes to rung 4 (source parallax: rembg cut-out + Remotion 2.5D, depth.cutout_layers).

Each site runs in its own signed-in Chrome profile (Playwright), set up once with scripts\\imagegen-login.ps1 -Site bing|meta.
The describe step tries Bing first, then Meta AI; the generate step likewise. Any failure is logged and the next site
runs; a rate-limit / quota message cools that site down for imagegen_cooldown_hours (default 6, saved across jobs); not
signed in or a CAPTCHA skips it for the job (CAPTCHAs are never automated). Failure screenshots + page HTML are saved as
<key>_<site>_<step>_fail.png/.html for selector fixes.

Settings: imagegen_order (["bing", "meta"]), imagegen_<site>_on, <site>_profile, imagegen_bing_url, imagegen_meta_url,
imagegen_timeout (240), imagegen_max_per_video (per site, default 8), imagegen_cooldown_hours, imagegen_headless.
"""
import json
import re
import time
from pathlib import Path

SITES = {
    "bing": {"label": "BING", "url": "https://www.bing.com/images/create"},
    "meta": {"label": "META AI", "url": "https://www.meta.ai/"},
}
ORDER = ["bing", "meta"]
DESCRIBE = "Describe this image in detail."
GENERATE = "Generate an image based on this description, no brands or text: "
BING_MAX = 480   # Bing Image Creator's prompt limit (characters)

RATE = re.compile(r"(rate limit|too many requests|limit reached|reached (your|the) (daily |free )?(limit|quota)|daily limit|"
                  r"try again (later|tomorrow|in \d+)|out of (credits|boosts|coins)|no (credits|boosts) left)", re.I)
CAPTCHA = re.compile(r"(captcha|verify (that )?you('| a)re (a )?human|are you a robot|unusual (activity|traffic)|"
                     r"confirm you're not a robot)", re.I)
REFUSED = re.compile(r"(content warning|can.t (create|generate|make) (that|this)|couldn.t (create|generate)|violat|"
                     r"content policy|against our (policies|guidelines)|unable to generate|was blocked|unsafe image content)", re.I)
SIGNIN = re.compile(r"^\s*(log in|sign in|join & create|continue with (facebook|instagram|google|microsoft))\s*$", re.I | re.M)

_job_skip = {}


def reset():
    _job_skip.clear()


class Skip(Exception):
    def __init__(self, why, cool_secs=0):
        super().__init__(why)
        self.why, self.cool = why, cool_secs


# ---------------------------------------------------------------- state (cooldowns survive jobs)
def _state_path(cfg, sd):
    if cfg.get("imagegen_state"):
        return Path(cfg["imagegen_state"])
    return Path(cfg.get("jobs_dir") or Path(sd).parent.parent).parent / "imagegen_state.json"


def _cooling(cfg, sd, site):
    try:
        st = json.loads(_state_path(cfg, sd).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    e = st.get(site) or {}
    return e if float(e.get("until") or 0) > time.time() else None


def _cool(cfg, sd, site, secs, why):
    p = _state_path(cfg, sd)
    try: st = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError): st = {}
    st[site] = {"until": time.time() + secs, "why": why, "set": time.strftime("%Y-%m-%d %H:%M")}
    try:
        p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps(st, indent=1), encoding="utf-8")
    except OSError:
        pass


def profile_dir(cfg, site):
    p = cfg.get(f"{site}_profile")
    return Path(p) if p else Path(cfg.get("jobs_dir") or ".").parent / f"{site}_profile"


def enabled(cfg, site):
    return bool(cfg.get(f"imagegen_{site}_on", True))


# ---------------------------------------------------------------- page helpers
def _body(page):
    try: return page.locator("body").inner_text(timeout=3000)
    except Exception: return ""


def _lines(text):
    return [l.strip() for l in str(text).splitlines() if l.strip()]


def _big_images(page):
    """Rendered images at least 300 px on their short side: [src, ...] (generated results, not icons / thumbnails)."""
    try:
        return page.evaluate("""() => Array.from(document.images).filter(i => i.complete && Math.min(i.naturalWidth, i.naturalHeight) >= 300
            && i.getBoundingClientRect().width > 120).map(i => i.currentSrc || i.src).filter(s => s && !s.startsWith('data:image/svg'))""")
    except Exception:
        return []


def _check(page, site, step):
    body = _body(page)
    if CAPTCHA.search(body):
        raise Skip(f"{SITES[site]['label']} shows a human check (CAPTCHA); not automated: complete it in its window "
                   f"(scripts\\imagegen-login.ps1 -Site {site})")
    m = RATE.search(body)
    if m:
        raise Skip(f"{SITES[site]['label']} rate limit / quota (\"{m.group(0)}\")", -1)
    m = REFUSED.search(body)
    if m and step == "generate":
        raise RuntimeError(f"{SITES[site]['label']} refused the prompt (\"{m.group(0)}\")")
    return body


def _box(page, site):
    from .flow import _first
    box = _first(page, ["textarea", "[contenteditable=true]", "[role=textbox]", "input[type=text]"], 10000)
    if not box:
        body = _body(page)
        if SIGNIN.search(body) or re.search(r"/(login|signin|auth)", page.url, re.I):
            raise Skip(f"the {SITES[site]['label']} profile is not signed in; run scripts\\imagegen-login.ps1 -Site {site}")
        raise RuntimeError(f"no prompt box on {SITES[site]['label']}'s page")
    return box


def _type_and_send(page, box, text):
    from .flow import _first
    box.click()
    if box.evaluate("e => e.tagName") in ("TEXTAREA", "INPUT"):
        box.fill(text)
    else:
        page.keyboard.insert_text(text)
    page.wait_for_timeout(700)
    send = _first(page, ["button[aria-label*='Send' i]", "button[aria-label*='Submit' i]", "button[aria-label*='Create' i]",
                         "button[aria-label*='Generate' i]", "button:has-text('Create')", "[role=button][aria-label*='Send' i]"], 1500)
    if send:
        try: send.click(); return
        except Exception: pass
    box.press("Enter")


def _upload(page, site, image):
    """Attach the screenshot: a file input, else the site's upload button (file chooser)."""
    from .flow import _first
    inp = page.locator("input[type=file]")
    if inp.count():
        inp.first.set_input_files(str(image)); page.wait_for_timeout(4000); return True
    btn = _first(page, ["button[aria-label*='Upload' i]", "button:has-text('Upload image')", "[aria-label*='Add image' i]",
                        "[aria-label*='attach' i]", "button[aria-label*='Add' i]"], 3000)
    if btn:
        with page.expect_file_chooser(timeout=8000) as fc:
            btn.click()
        fc.value.set_files(str(image)); page.wait_for_timeout(4000); return True
    return False


class _Browser:
    def __init__(self, cfg, site):
        self.cfg, self.site = cfg, site

    def __enter__(self):
        prof = profile_dir(self.cfg, self.site)
        if not prof.exists() or not any(prof.iterdir()):
            raise Skip(f"no signed-in {SITES[self.site]['label']} profile at {prof}; run scripts\\imagegen-login.ps1 -Site {self.site} once")
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise Skip("Playwright is not installed in this environment")
        self.pw = sync_playwright().start()
        kw = dict(user_data_dir=str(prof), headless=bool(self.cfg.get("imagegen_headless", False)), accept_downloads=True,
                  viewport={"width": 1440, "height": 900}, args=["--disable-blink-features=AutomationControlled"])
        if self.cfg.get("flow_chrome"): kw["executable_path"] = self.cfg["flow_chrome"]
        else: kw["channel"] = "chrome"
        try:
            self.context = self.pw.chromium.launch_persistent_context(**kw)
        except Exception:
            self.pw.stop(); raise
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        return self

    def open(self):
        url = self.cfg.get(f"imagegen_{self.site}_url") or SITES[self.site]["url"]
        self.page.goto(url, wait_until="domcontentloaded", timeout=60000)
        self.page.wait_for_timeout(5000)
        _check(self.page, self.site, "open")

    def evidence(self, path_prefix):
        try:
            Path(f"{path_prefix}.png").write_bytes(self.page.screenshot(full_page=False))
            Path(f"{path_prefix}.html").write_text(self.page.content(), encoding="utf-8")
        except Exception:
            pass

    def __exit__(self, *a):
        try: self.context.close()
        finally: self.pw.stop()


# ---------------------------------------------------------------- the two steps
def _describe_on(b, image, timeout):
    page = b.page
    b.open()
    box = _box(page, b.site)
    if not _upload(page, b.site, image):
        raise RuntimeError("no upload control found")
    before = set(_lines(_body(page)))
    imgs0 = set(_big_images(page))
    _type_and_send(page, box, DESCRIBE)
    t0, last, stable = time.time(), "", 0
    while time.time() - t0 < timeout:
        page.wait_for_timeout(3000)
        body = _check(page, b.site, "describe")
        new = [l for l in _lines(body) if l not in before and DESCRIBE not in l and len(l.split()) >= 6]
        text = " ".join(new)
        if len(text.split()) >= 30:
            stable = stable + 1 if text == last else 0   # wait until the streamed answer stops growing
            last = text
            if stable >= 2:
                return re.sub(r"\s+", " ", text).strip()
        elif set(_big_images(page)) - imgs0 and time.time() - t0 > 20:
            raise RuntimeError("the site generated images instead of describing the upload")
    if len(last.split()) >= 30:
        return re.sub(r"\s+", " ", last).strip()
    raise RuntimeError(f"no description after {timeout}s")


def _generate_on(b, prompt, out, aspect, timeout):
    page = b.page
    b.open()
    box = _box(page, b.site)
    if b.site == "bing" and aspect:   # best effort: Bing's aspect-ratio dropdown
        try:
            want = "9:16" if aspect == "9:16" else "16:9"
            combo = page.locator("[role=combobox][aria-label*='Aspect' i], select[aria-label*='Aspect' i]").first
            if combo.count():
                if combo.evaluate("e => e.tagName") == "SELECT":
                    combo.select_option(label=re.compile(want.replace(":", r"\s*:\s*")))
                else:
                    combo.click(); page.wait_for_timeout(600)
                    opt = page.get_by_role("option", name=re.compile(want.replace(":", r"\s*:\s*")))
                    if not opt.count(): opt = page.get_by_text(re.compile(r"^\s*" + want.replace(":", r"\s*:\s*") + r"\s*$"))
                    if opt.count(): opt.first.click()
                    else: page.keyboard.press("Escape")
                page.wait_for_timeout(500)
        except Exception:
            pass
    before = set(_big_images(page))
    _type_and_send(page, box, prompt)
    t0 = time.time()
    while time.time() - t0 < timeout:
        page.wait_for_timeout(5000)
        _check(page, b.site, "generate")
        fresh = [s for s in _big_images(page) if s not in before]
        if fresh:
            page.wait_for_timeout(3000)   # all results finished loading
            fresh = [s for s in _big_images(page) if s not in before] or fresh
            _save_image(b.context, page, fresh[0], out)
            return out
    raise RuntimeError(f"no generated image after {timeout}s")


def _save_image(context, page, src, out):
    from .flow import _save
    tmp = Path(out).with_suffix(".dl")
    if src.startswith("blob:") or src.startswith("data:"):
        _save(context, page, src, tmp)
    else:
        big = re.sub(r"([?&])w=\d+&h=\d+", r"\1", src)   # Bing thumbnails: ask for the full-size image
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
def _sites(cfg, sd, log, step):
    for site in [s for s in (cfg.get("imagegen_order") or ORDER) if s in SITES]:
        if not enabled(cfg, site): continue
        if site in _job_skip: continue
        cool = _cooling(cfg, sd, site)
        if cool:
            log(f"  {site}: cooling down until {time.strftime('%H:%M', time.localtime(cool['until']))} ({cool['why'][:100]}); next site")
            _job_skip[site] = "cooling down"; continue
        yield site


def _run(cfg, sd, site, step, key, log, fn):
    """Run one step on one site with its own browser; Skip -> job skip / saved cooldown. -> result or None."""
    d = Path(sd) / "imagegen"; d.mkdir(parents=True, exist_ok=True)
    try:
        with _Browser(cfg, site) as b:
            try:
                return fn(b)
            except Exception:
                b.evidence(d / f"{key}_{site}_{step}_fail")
                raise
    except Skip as s:
        cool = int(float(cfg.get("imagegen_cooldown_hours", 6)) * 3600) if s.cool == -1 else s.cool
        _job_skip[site] = s.why
        if cool: _cool(cfg, sd, site, cool, s.why)
        log(f"  {site} skipped: {s.why}" + (f" (saved: retried after {cool // 3600} h)" if cool else " (rest of this job)") + "; next site")
    except Exception as e:
        if str(e) == "cancelled": raise
        shot = d / f"{key}_{site}_{step}_fail.png"
        log(f"  {site} {step} failed ({str(e).splitlines()[0][:200]})" + (f"; screenshot {shot}" if shot.exists() else "") + "; next site")
    return None


def describe(cfg, sd, key, image, log):
    """-> (description, site) or (None, None)."""
    timeout = int(cfg.get("imagegen_timeout", 240))
    for site in _sites(cfg, sd, log, "describe"):
        log(f"  {site}: describing the source screenshot ({Path(image).name})")
        text = _run(cfg, sd, site, "describe", key, log, lambda b: _describe_on(b, image, timeout))
        if text:
            log(f"  {site}: description ({len(text.split())} words): \"{text[:160]}...\"")
            return text, site
    return None, None


def generate(cfg, sd, sec, key, log, aspect="9:16", image=None):
    """Rung 3. -> (image_path, site, prompt) or (None, None, None). image: the source screenshot to describe first."""
    from . import flow
    out_dir = Path(sd) / "imagegen"; out_dir.mkdir(parents=True, exist_ok=True)
    if not any(True for _ in _sites(cfg, sd, log, "check")):
        log("  image generators: none available (" + "; ".join(f"{k}: {v[:60]}" for k, v in _job_skip.items()) + ")")
        return None, None, None
    desc = None
    if image and Path(image).is_file():
        desc, _ = describe(cfg, sd, key, image, log)
    base = desc or flow.visual_prompt(cfg, sec, log)
    if not desc:
        log(f"  {key}: no description of a source screenshot; using the beat's visual prompt")
    timeout = int(cfg.get("imagegen_timeout", 240))
    for site in _sites(cfg, sd, log, "generate"):
        led = out_dir / f"{site}_usage.json"
        try: used = json.loads(led.read_text(encoding="utf-8")) if led.exists() else {}
        except (OSError, ValueError): used = {}
        cap = int(cfg.get("imagegen_max_per_video", 8))
        if len(used) >= cap and key not in used:
            log(f"  {site}: {cap} images already made for this video; next site"); continue
        prompt = GENERATE + base
        if site == "bing" and len(prompt) > BING_MAX:
            cut = base[:BING_MAX - len(GENERATE)]
            prompt = GENERATE + (cut.rsplit(". ", 1)[0] + "." if ". " in cut else cut)
        out = out_dir / f"{key}_{site}.jpg"
        log(f"  {site}: generating an image ({'from the description' if desc else 'from the beat prompt'}, {len(prompt)} chars)")
        t0 = time.time()
        res = _run(cfg, sd, site, "generate", key, log, lambda b: _generate_on(b, prompt, out, aspect, timeout))
        if res and Path(res).is_file():
            used[key] = {"prompt": prompt, "described": bool(desc), "made": time.strftime("%Y-%m-%d %H:%M")}
            led.write_text(json.dumps(used, indent=1), encoding="utf-8")
            Path(res).with_suffix(".prompt.txt").write_text(prompt, encoding="utf-8")
            log(f"  {site}: image ready ({time.time() - t0:.0f}s)")
            return Path(res), site, prompt
    return None, None, None


def tag(site):
    return f"GENERATED · {SITES[site]['label']}"
