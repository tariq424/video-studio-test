"""AI video generators, cheapest first (visual ladder v2, after the source rungs):

    4 Bing Video Creator (free)  ->  5 Meta AI video (free)  ->  6 Sora (free tier)  ->  7 Google Flow (paid credits, last)

Each free site is driven like Flow: Playwright in a dedicated, signed-in Chrome profile (one per site; set up once with
scripts\\vidgen-login.ps1 -Site meta). A failure is logged with its reason and the next generator runs, so Flow credits are
spent only when every free generator failed, is rate-limited or is unavailable.

- Rate limit / quota text on the page -> that site cools down for vidgen_cooldown_hours (default 6), saved across jobs.
- Site gone / no generator on the page -> unavailable for 7 days (saved), so a dead service costs one probe a week.
- Not signed in, or a CAPTCHA / "verify you are human" check -> skipped for this job. CAPTCHAs are never automated:
  open the site's window with the login script and complete it yourself.
- Prompt: the OCR'd prompt from the source snapshot when there is one (with the snapshot as the anchor image where the
  site accepts an upload), else the beat's own visual prompt.

Settings: vidgen_order (["bing", "meta", "sora", "flow"]), vidgen_<site>_on, <site>_profile, <site>_url, <site>_timeout,
vidgen_max_per_video (per free site, default 6), vidgen_cooldown_hours, vidgen_headless.
"""
import json
import re
import time
from pathlib import Path

from . import media

SITES = {
    "bing": {"label": "BING", "url": "https://www.bing.com/images/create?ctype=video", "on": True, "upload": False,
             "prefix": "", "notice": "Microsoft announced that Bing Video Creator ends on July 31, 2026"},
    "meta": {"label": "META AI", "url": "https://www.meta.ai/", "on": True, "upload": True,
             "prefix": "Create a video: ", "prefix_image": "Animate this image: ", "notice": ""},
    "sora": {"label": "SORA", "url": "https://sora.chatgpt.com/", "on": False, "upload": True,
             "prefix": "", "notice": "OpenAI discontinued the Sora app and website on April 26, 2026"},
}
ORDER = ["bing", "meta", "sora", "flow"]

RATE = re.compile(r"(rate limit|too many requests|limit reached|reached (your|the) (daily |free )?(limit|quota)|daily limit|"
                  r"try again (later|tomorrow|in \d+)|out of (credits|boosts|generations)|no (credits|generations) left|"
                  r"used (all|up) (your )?(free )?(generations|credits))", re.I)
CAPTCHA = re.compile(r"(captcha|verify (that )?you('| a)re (a )?human|are you a robot|unusual (activity|traffic)|"
                     r"confirm you're not a robot|security check)", re.I)
GONE = re.compile(r"(no longer available|has been discontinued|is discontinued|has ended|been retired|is retired|"
                  r"service (has )?ended|not available in your (country|region)|isn.t available in your (country|region))", re.I)
REFUSED = re.compile(r"(can.t (create|generate|make) (that|this)|couldn.t (create|generate)|violat|content policy|"
                     r"against our (policies|guidelines)|unable to generate|try a different prompt)", re.I)
SIGNIN = re.compile(r"^\s*(log in|sign in|continue with (facebook|instagram|google|microsoft))\s*$", re.I | re.M)

_job_skip = {}   # site -> reason (this job only)


def reset():
    _job_skip.clear()


def _state_path(cfg, sd):
    if cfg.get("vidgen_state"):
        return Path(cfg["vidgen_state"])
    base = Path(cfg.get("jobs_dir") or Path(sd).parent.parent)
    return base.parent / "vidgen_state.json"


def _state(cfg, sd):
    p = _state_path(cfg, sd)
    try:
        return p, (json.loads(p.read_text(encoding="utf-8")) if p.exists() else {})
    except (OSError, ValueError):
        return p, {}


def _cool(cfg, sd, site, secs, why):
    p, st = _state(cfg, sd)
    st[site] = {"until": time.time() + secs, "why": why, "set": time.strftime("%Y-%m-%d %H:%M")}
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(st, indent=1), encoding="utf-8")
    except OSError:
        pass


def _cooling(cfg, sd, site):
    _, st = _state(cfg, sd)
    e = st.get(site) or {}
    return e if float(e.get("until") or 0) > time.time() else None


def profile_dir(cfg, site):
    p = cfg.get(f"{site}_profile")
    return Path(p) if p else Path(cfg.get("jobs_dir") or ".").parent / f"{site}_profile"


def enabled(cfg, site):
    if site == "flow":
        return bool(cfg.get("flow_on", True))
    return bool(cfg.get(f"vidgen_{site}_on", SITES[site]["on"]))


def _ledger(sd, site):
    f = Path(sd) / "vidgen" / f"{site}_usage.json"
    try:
        return f, (json.loads(f.read_text(encoding="utf-8")) if f.exists() else {})
    except (OSError, ValueError):
        return f, {}


def _body(page):
    try:
        return page.locator("body").inner_text(timeout=3000)
    except Exception:
        return ""


class Skip(Exception):
    """A failure that would repeat for every beat (job-wide skip), or a cooldown (saved)."""
    def __init__(self, why, cool_secs=0):
        super().__init__(why)
        self.why, self.cool = why, cool_secs


def run_site(cfg, site, sd, key, prompt, image, aspect, log):
    """Drive one free site. -> path of the downloaded, re-encoded clip. Raises Skip / RuntimeError (logged by the caller)."""
    from .flow import _first, _videos, _save
    spec = SITES[site]
    out = Path(sd) / "vidgen" / f"{key}_{site}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    if media.ok(out):
        return out
    prof = profile_dir(cfg, site)
    if not prof.exists() or not any(prof.iterdir()):
        raise Skip(f"no signed-in {spec['label']} profile at {prof}; run scripts\\vidgen-login.ps1 -Site {site} once")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise Skip("Playwright is not installed in this environment")
    timeout = int(cfg.get(f"{site}_timeout", 300))
    t0 = time.time()
    with sync_playwright() as pw:
        kw = dict(user_data_dir=str(prof), headless=bool(cfg.get("vidgen_headless", False)), accept_downloads=True,
                  viewport={"width": 1440, "height": 900}, args=["--disable-blink-features=AutomationControlled"])
        if cfg.get("flow_chrome"):
            kw["executable_path"] = cfg["flow_chrome"]
        else:
            kw["channel"] = "chrome"
        context = pw.chromium.launch_persistent_context(**kw)
        page = None
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(cfg.get(f"{site}_url") or spec["url"], wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(5000)
            body = _body(page)
            if CAPTCHA.search(body):
                raise Skip(f"{spec['label']} shows a human check (CAPTCHA); not automated: complete it in its window "
                           f"(scripts\\vidgen-login.ps1 -Site {site})")
            if GONE.search(body):
                m = GONE.search(body)
                raise Skip(f"{spec['label']} says the service is unavailable (\"{m.group(0)}\")"
                           + (f"; {spec['notice']}" if spec["notice"] else ""), 7 * 86400)
            box = _first(page, ["textarea", "[contenteditable=true]", "[role=textbox]", "input[type=text]"], 8000)
            if not box:
                if SIGNIN.search(body) or re.search(r"/(login|signin|auth)", page.url, re.I):
                    raise Skip(f"the {spec['label']} profile is not signed in; run scripts\\vidgen-login.ps1 -Site {site}")
                raise Skip(f"no prompt box on {spec['label']}'s page (generator not offered here"
                           + (f"; {spec['notice']}" if spec["notice"] else "") + ")", 7 * 86400 if spec["notice"] else 0)
            if site == "bing":   # the page must offer VIDEO creation, not only images
                if not re.search(r"\bvideo\b", body, re.I):
                    raise Skip(f"Bing's create page offers no video option ({spec['notice']})", 7 * 86400)
                tab = _first(page, ["[role=tab]:has-text('Video')", "button:has-text('Video')", "a:has-text('Video')"], 2000)
                if tab:
                    try: tab.click(); page.wait_for_timeout(1500)
                    except Exception: pass
            text = prompt
            if image and spec["upload"]:
                try:
                    inp = page.locator("input[type=file]").first
                    if inp.count():
                        inp.set_input_files(str(image)); page.wait_for_timeout(4000)
                        text = spec.get("prefix_image", "") + prompt
                        log(f"  {site}: anchor image attached ({Path(image).name})")
                    else:
                        log(f"  {site}: no upload control found; text prompt only")
                except Exception as e:
                    log(f"  {site}: anchor image upload failed ({str(e)[:80]}); text prompt only")
            if text == prompt:
                text = spec["prefix"] + prompt
            before = set(_videos(page))
            box.click()
            if box.evaluate("e => e.tagName") in ("TEXTAREA", "INPUT"):
                box.fill(text)
            else:
                page.keyboard.insert_text(text)
            page.wait_for_timeout(800)
            send = _first(page, ["button[aria-label*='Send' i]", "button[aria-label*='Create' i]", "button[aria-label*='Generate' i]",
                                 "button[aria-label*='Submit' i]", "button:has-text('Create')", "button:has-text('Generate')",
                                 "[role=button][aria-label*='Send' i]"], 2000)
            if send:
                try: send.click()
                except Exception: box.press("Enter")
            else:
                box.press("Enter")
            log(f"  {site}: prompt submitted; waiting for the clip (up to {timeout}s)")
            src = None
            while time.time() - t0 < timeout:
                page.wait_for_timeout(5000)
                body = _body(page)
                if CAPTCHA.search(body):
                    raise Skip(f"{spec['label']} asked for a human check (CAPTCHA); not automated")
                m = RATE.search(body)
                if m:
                    raise Skip(f"{spec['label']} rate limit / quota (\"{m.group(0)}\")",
                               int(float(cfg.get("vidgen_cooldown_hours", 6)) * 3600))
                m = REFUSED.search(body)
                if m:
                    raise RuntimeError(f"{spec['label']} refused this prompt (\"{m.group(0)}\")")
                fresh = [v for v in _videos(page) if v not in before]
                if fresh:
                    page.wait_for_timeout(4000)   # let the player settle on its final source
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
            try:   # evidence for selector fixes when a site changes
                if page is not None:
                    (out.parent / f"{key}_{site}_fail.png").write_bytes(page.screenshot(full_page=False))
                    (out.parent / f"{key}_{site}_fail.html").write_text(page.content(), encoding="utf-8")
            except Exception:
                pass
            raise
        finally:
            context.close()
    if not (media.ok(out) and media.dur(out) >= 1):
        out.unlink(missing_ok=True)
        raise RuntimeError("downloaded clip is not a usable video")
    return out


def generate(cfg, sd, sec, key, log, aspect="9:16", prompt=None, image=None):
    """Walk the generators in order. -> (path, site) or (None, None). Never raises (cancel aside)."""
    from . import flow
    order = [s for s in (cfg.get("vidgen_order") or ORDER) if s in ORDER]
    base = prompt or None
    tried = []
    for site in order:
        if not enabled(cfg, site):
            if site in SITES and SITES[site]["notice"] and site not in _job_skip:
                _job_skip[site] = f"off ({SITES[site]['notice']})"
                log(f"  {site}: off ({SITES[site]['notice']})")
            continue
        if site == "flow":
            if tried:
                log(f"  free generators gave nothing ({'; '.join(tried)}); Google Flow (paid credits) is the last resort")
            try:
                clip = flow.generate(cfg, sd, sec, f"{key}" if key.endswith("_flow") else f"{key}_flow", log, aspect=aspect, prompt=base)
            except RuntimeError as e:
                if str(e) == "cancelled": raise
                log(f"  flow failed ({str(e)[:150]}); next rung"); clip = None
            if clip:
                return clip, "flow"
            continue
        if site in _job_skip:
            tried.append(f"{site}: skipped"); continue
        cool = _cooling(cfg, sd, site)
        if cool:
            log(f"  {site}: cooling down until {time.strftime('%H:%M', time.localtime(cool['until']))} ({cool['why'][:120]}); next generator")
            _job_skip[site] = "cooling down"; tried.append(f"{site}: cooling down"); continue
        f, used = _ledger(sd, site)
        cap = int(cfg.get("vidgen_max_per_video", 6))
        if len(used) >= cap and key not in used:
            log(f"  {site}: {cap} clips already made for this video; next generator"); tried.append(f"{site}: cap"); continue
        p = base or flow.visual_prompt(cfg, sec, log)
        log(f"  {site}: generating ({'OCR prompt' if prompt else 'beat prompt'}: {p[:90]}...)")
        t0 = time.time()
        try:
            clip = run_site(cfg, site, sd, key, p, image, aspect, log)
        except Skip as s:
            _job_skip[site] = s.why
            if s.cool:
                _cool(cfg, sd, site, s.cool, s.why)
            log(f"  {site} skipped: {s.why}" + (f" (saved: retried after {s.cool // 3600} h)" if s.cool else " (rest of this job)") + "; next generator")
            tried.append(f"{site}: {s.why[:60]}"); continue
        except Exception as e:
            if str(e) == "cancelled": raise
            shot = Path(sd) / "vidgen" / f"{key}_{site}_fail.png"
            log(f"  {site} failed ({str(e).splitlines()[0][:200]})" + (f"; screenshot {shot}" if shot.exists() else "") + "; next generator")
            tried.append(f"{site}: failed"); continue
        used[key] = {"prompt": p, "secs": round(media.dur(clip), 2), "made": time.strftime("%Y-%m-%d %H:%M"), "ocr": bool(prompt)}
        f.write_text(json.dumps(used, indent=1), encoding="utf-8")
        clip.with_suffix(".prompt.txt").write_text(p, encoding="utf-8")
        log(f"  {site}: clip ready ({media.dur(clip):.1f}s, {time.time() - t0:.0f}s)")
        return clip, site
    return None, None


def tag(site):
    return "GENERATED · FLOW" if site == "flow" else f"GENERATED · {SITES[site]['label']}"
