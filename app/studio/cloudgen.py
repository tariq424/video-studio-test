"""Cloud stills: Gemini (Pro) first, ChatGPT (Pro) second, driven by Playwright with fixed selectors in a persistent browser
profile on F: (config "cloud_profile"). You log in once by hand with  python -m studio.cloudgen login  (or Settings -> "Log in for
cloud stills"); that opens the normal browser on the same profile, so no password ever passes through this code.

Every generation runs in its own process (generate() starts  python -m studio.cloudgen gen ...), so a stuck page can never hang
the pipeline: each provider gets "cloud_timeout" seconds (default 90), the whole call a hard limit after which the process tree is
killed. A provider fails (and the next one is tried) on: timeout, CAPTCHA / "verify you are human" page, logged out, refusal (the
reply ends without an image), or a download that isn't a usable image. CAPTCHAs are never solved or bypassed; logins never automated.

CLI:  python -m studio.cloudgen login                      open the browser on the profile (Gemini + ChatGPT tabs) to sign in
      python -m studio.cloudgen status                     JSON: signed in? per provider (needs the login window closed)
      python -m studio.cloudgen gen --prompt "..." --out x.png --aspect 9:16 [--providers gemini,chatgpt] [--timeout 90]
"""
import argparse, base64, json, os, re, subprocess, sys, threading, time
from pathlib import Path

URLS = {"gemini": "https://gemini.google.com/app", "chatgpt": "https://chatgpt.com/"}
ASPECT_WORDS = {"9:16": "tall vertical 9:16 portrait format (taller than wide)", "16:9": "wide horizontal 16:9 landscape format (wider than tall)"}
_lock = threading.Lock()   # one browser on the profile at a time
_down = {}                 # provider -> time it reported "login expired": skipped for DOWN_SECS (no browser launch per beat)
DOWN_SECS = 600

# ---------------------------------------------------------------- fixed selectors
SEL = {
    "gemini": {
        "box": "rich-textarea div[contenteditable='true'], div.ql-editor[contenteditable='true']",
        "send": "button[aria-label*='Send' i]",
        "stop": "button[aria-label*='Stop' i]",
        "img": "generated-image img, single-image img, div.generated-image img, model-response img[src*='googleusercontent']",
        "reply": "model-response message-content, message-content",
        "logged_out": "a[href*='accounts.google.com/ServiceLogin'], a[href*='accounts.google.com/v3/signin'], a[aria-label='Sign in' i], "
                      "a:text-is('Sign in'), button:text-is('Sign in')",
    },
    "chatgpt": {
        "box": "#prompt-textarea",
        "send": "button[data-testid='send-button'], button[aria-label*='Send' i]",
        "stop": "button[data-testid='stop-button'], button[aria-label*='Stop' i]",
        "img": "img[alt*='Generated image' i], div[data-testid*='image'] img[src*='estuary'], img[src*='oaiusercontent']",
        "reply": "div[data-message-author-role='assistant']",
        "logged_out": "button[data-testid='login-button'], a[href*='auth/login'], button:text-is('Log in')",
    },
}
CAPTCHA = ("iframe[src*='challenges.cloudflare.com'], iframe[src*='recaptcha'], iframe[src*='hcaptcha'], #challenge-form, "
           "div#cf-challenge-running, form[action*='sorry/index']")
LOGGED_OUT_TEXT = ("sign in to connect to google apps", "sign in to save activity", "log in to get answers", "sign up for free")
CAPTCHA_TEXT = ("verify you are human", "unusual traffic", "are you a robot", "just a moment", "confirm you're not a robot")


def prompt_text(prompt, aspect):
    return (f"Generate an image (do not reply with text): a photorealistic, cinematic {ASPECT_WORDS.get(aspect, aspect)} picture. "
            f"{prompt.strip().rstrip('.')}. Absolutely no text, letters, numbers, logos, watermarks, airline or brand names, flags or "
            f"registrations anywhere in the image. Do not show the faces of real, identifiable people.")


def browser_exe(cfg):
    """(playwright channel, exe path) of the browser the profile belongs to: Chrome if installed, else Edge (config cloud_browser)."""
    want = (cfg.get("cloud_browser") or "auto").lower()
    pf = [os.environ.get(k, "") for k in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
    cands = {"chrome": [Path(p) / "Google/Chrome/Application/chrome.exe" for p in pf if p],
             "msedge": [Path(p) / "Microsoft/Edge/Application/msedge.exe" for p in pf if p]}
    for ch in ([want] if want in cands else ["chrome", "msedge"]):
        for p in cands[ch]:
            if p.exists(): return ch, str(p)
    return ("msedge" if want == "msedge" else "chrome"), None


def profile_dir(cfg):
    from . import config
    p = Path(cfg.get("cloud_profile") or (config.ROOT / "cloud_profile")); p.mkdir(parents=True, exist_ok=True)
    return p


# ---------------------------------------------------------------- inside the child process
class Fail(Exception):
    pass


def _blocked(page, s):
    """'captcha' | 'logged out' | None."""
    try:
        if page.locator(CAPTCHA).count(): return "captcha"
        t = (page.title() or "").lower()
        body = (page.locator("body").inner_text(timeout=1500) or "")[:3000].lower()
        if any(x in t or x in body for x in CAPTCHA_TEXT): return "captcha"
        if "accounts.google.com" in page.url or "/auth/login" in page.url: return "logged out"
        if any(x in body for x in LOGGED_OUT_TEXT): return "logged out"
        lo = page.locator(s["logged_out"])
        if lo.count() and lo.first.is_visible(): return "logged out"
    except Exception:
        pass
    return None


def _image_bytes(page, img):
    """Full-size bytes of a generated <img>: the URL with the page's cookies, else fetch() in the page (blob:), else a screenshot."""
    src = img.get_attribute("src") or ""
    if src.startswith("http"):
        urls = [src]
        if "googleusercontent.com" in src and "=" in src.rsplit("/", 1)[-1]: urls.insert(0, src.rsplit("=", 1)[0] + "=s0")   # full size
        for u in urls:
            try:
                r = page.request.get(u, timeout=20000)
                if r.ok and r.headers.get("content-type", "").startswith("image"): return r.body(), "url"
            except Exception:
                pass
    try:
        b64 = page.evaluate("""async (el) => { const r = await fetch(el.src, {credentials: 'include'}); const b = await r.blob();
            return await new Promise(res => { const f = new FileReader(); f.onload = () => res(f.result.split(',')[1]); f.readAsDataURL(b); }); }""", img.element_handle())
        if b64: return base64.b64decode(b64), "fetch"
    except Exception:
        pass
    return img.screenshot(timeout=10000), "screenshot"


def _one(ctx, name, text, deadline, shot=None):
    """Generate on one provider -> (bytes, how). Raises Fail(reason). shot: where to save a screenshot if it fails."""
    s = SEL[name]; page = ctx.new_page()
    try:
        return _one_page(page, s, name, text, deadline)
    except Fail:
        if shot:
            try: page.screenshot(path=str(shot), timeout=5000)
            except Exception: pass
        raise
    finally:
        try: page.close()
        except Exception: pass


def _one_page(page, s, name, text, deadline):
    if True:
        left = lambda: max(1.0, deadline - time.time())
        try: page.goto(URLS[name], wait_until="domcontentloaded", timeout=int(min(30, left()) * 1000))
        except Exception as e: raise Fail(f"page didn't load ({str(e)[:60]})")
        box = page.locator(s["box"]).first
        t0 = time.time()
        while True:   # the input box, or a reason it isn't there
            b = _blocked(page, s)
            if b == "captcha": raise Fail("CAPTCHA / human check shown (not bypassed)")
            if b == "logged out": raise Fail("login expired: run the cloud login")
            try:
                if box.is_visible() and time.time() - t0 > 2.5: break   # give sign-in prompts a moment to render
            except Exception: pass
            if time.time() > deadline or time.time() - t0 > 25: raise Fail("prompt box not found (page changed or not signed in)")
            time.sleep(0.7)
        before = page.locator(s["img"]).count()
        box.click(); page.keyboard.insert_text(text); time.sleep(0.4)
        try:
            btn = page.locator(s["send"]).first
            if btn.is_visible() and btn.is_enabled(): btn.click()
            else: page.keyboard.press("Enter")
        except Exception: page.keyboard.press("Enter")
        quiet_since, img = None, None
        while time.time() < deadline:
            time.sleep(1.5)
            b = _blocked(page, s)
            if b == "captcha": raise Fail("CAPTCHA / human check shown (not bypassed)")
            if b == "logged out": raise Fail("login expired: run the cloud login")
            busy = page.locator(s["stop"]).count() > 0 and page.locator(s["stop"]).first.is_visible()
            imgs = page.locator(s["img"])
            n = imgs.count(); ready = None
            for i in range(before, n):
                el = imgs.nth(i)
                try:
                    w = el.evaluate("e => e.complete ? e.naturalWidth : 0")
                    if w and w >= 400: ready = el
                except Exception: pass
            if ready is not None and not busy:
                img = ready; time.sleep(2.0)   # let a progressive render settle on its final frame
                break
            replies = page.locator(s["reply"])
            if not busy and ready is None and replies.count():
                quiet_since = quiet_since or time.time()
                if time.time() - quiet_since > 12:   # the reply ended with no picture: a refusal or a text answer
                    try: msg = replies.last.inner_text(timeout=2000).strip().replace("\n", " ")[:120]
                    except Exception: msg = ""
                    if re.search(r"sign(ed)?[ -]?(in|out)|log(ged)?[ -]?(in|out)", msg, re.I): raise Fail("login expired: run the cloud login")
                    raise Fail(f"refused / no image ({msg or 'empty reply'})")
            else: quiet_since = None
        if img is None: raise Fail("timed out waiting for the image")
        return _image_bytes(page, img)


def _fit(data, out, aspect):
    """Decode, check, crop to fill the target aspect, save as PNG. -> (w, h). Raises Fail."""
    import io
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


def _launch(p, cfg):
    ch, exe = browser_exe(cfg)
    kw = dict(user_data_dir=str(profile_dir(cfg)), headless=bool(cfg.get("cloud_headless", False)),
              viewport={"width": 1280, "height": 900}, accept_downloads=True, args=["--no-first-run", "--no-default-browser-check"])
    try: return p.chromium.launch_persistent_context(executable_path=exe, **kw) if exe else p.chromium.launch_persistent_context(channel=ch, **kw)
    except Exception as e:
        m = str(e)
        if "ProcessSingleton" in m or "already in use" in m or "SingletonLock" in m: raise Fail("browser profile in use: close the cloud login window")
        raise Fail(f"browser didn't start ({m[:80]})")


def _child_gen(cfg, prompt, out, aspect, providers, timeout):
    from playwright.sync_api import sync_playwright
    text = prompt_text(prompt, aspect); tries = []
    with sync_playwright() as p:
        try: ctx = _launch(p, cfg)
        except Fail as e: return {"ok": False, "provider": None, "why": str(e), "tries": [{"provider": "browser", "why": str(e), "secs": 0}]}
        try:
            for name in providers:
                t0 = time.time()
                try:
                    data, how = _one(ctx, name, text, t0 + timeout, shot=Path(out).with_name(f"{Path(out).stem}_{name}_fail.png"))
                    w, h = _fit(data, out, aspect)
                    tries.append({"provider": name, "why": "ok", "secs": round(time.time() - t0, 1), "how": how, "size": f"{w}x{h}"})
                    return {"ok": True, "provider": name, "why": "", "tries": tries}
                except Fail as e: tries.append({"provider": name, "why": str(e), "secs": round(time.time() - t0, 1)})
                except Exception as e: tries.append({"provider": name, "why": f"error: {str(e)[:100]}", "secs": round(time.time() - t0, 1)})
        finally:
            try: ctx.close()
            except Exception: pass
    return {"ok": False, "provider": None, "why": "; ".join(f"{t['provider']}: {t['why']}" for t in tries) or "no provider", "tries": tries}


def _child_status(cfg):
    from playwright.sync_api import sync_playwright
    res = {}
    with sync_playwright() as p:
        try: ctx = _launch(p, cfg)
        except Fail as e: return {"error": str(e)}
        try:
            for name in providers_of(cfg):
                pg = ctx.new_page()
                try:
                    pg.goto(URLS[name], wait_until="domcontentloaded", timeout=30000); time.sleep(4)
                    b = _blocked(pg, SEL[name])
                    res[name] = b or ("signed in" if pg.locator(SEL[name]["box"]).count() else "prompt box not found")
                except Exception as e: res[name] = f"error: {str(e)[:80]}"
                finally: pg.close()
        finally: ctx.close()
    return res


# ---------------------------------------------------------------- the pipeline side
def providers_of(cfg):
    order = ["gemini", "chatgpt"]
    first = (cfg.get("cloud_primary") or "gemini").lower()
    if first in order: order.remove(first); order.insert(0, first)
    return order


def _kill_tree(proc):
    try:
        if os.name == "nt": subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, timeout=15)
        else: proc.kill()
    except Exception:
        pass


def _count(job):
    f = Path(job) / "cloud_log.jsonl"
    if not f.exists(): return 0
    return sum(1 for l in f.read_text(encoding="utf-8").splitlines() if l.strip())


def generate(cfg, prompt, out, aspect, log, tag="cloud", job=None):
    """One cloud still -> {"ok", "provider", "why", "tries"}. Never raises; never takes longer than the hard limit.
    job: the job folder (attempts are logged to cloud_log.jsonl; "cloud_max_per_job" caps the attempts per video)."""
    if not cfg.get("cloud_on", True): return {"ok": False, "provider": None, "why": "cloud stills off", "tries": []}
    if job is not None and _count(job) >= int(cfg.get("cloud_max_per_job", 8)):
        return {"ok": False, "provider": None, "why": f"per-video cap of {cfg.get('cloud_max_per_job', 8)} cloud attempts reached", "tries": []}
    try: import playwright  # noqa: F401
    except ImportError: return {"ok": False, "provider": None, "why": "playwright not installed", "tries": []}
    provs = [p for p in providers_of(cfg) if time.time() - _down.get(p, 0) > DOWN_SECS]
    if not provs: return {"ok": False, "provider": None, "why": "not signed in to " + " or ".join(providers_of(cfg)) + " (skipped; log in from Settings)", "tries": []}
    timeout = int(cfg.get("cloud_timeout", 90))
    hard = timeout * len(provs) + 45
    from . import config
    cmd = [sys.executable, "-m", "studio.cloudgen", "gen", "--prompt", prompt, "--out", str(out), "--aspect", aspect,
           "--providers", ",".join(provs), "--timeout", str(timeout)]
    log(f"  {tag}: cloud still via {' -> '.join(provs)} ({timeout}s each)")
    t0 = time.time()
    with _lock:
        proc = subprocess.Popen(cmd, cwd=str(config.APP), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try: so, se = proc.communicate(timeout=hard)
        except subprocess.TimeoutExpired:
            _kill_tree(proc); so, se = "", ""
            res = {"ok": False, "provider": None, "why": f"hard time limit ({hard}s) hit; browser closed", "tries": []}
        else:
            res = None
            for line in reversed((so or "").splitlines()):
                if line.startswith("{"):
                    try: res = json.loads(line); break
                    except Exception: pass
            if res is None: res = {"ok": False, "provider": None, "why": f"cloud process failed ({(se or so or '').strip()[-160:]})", "tries": []}
    res["secs"] = round(time.time() - t0, 1)
    if res["ok"] and not Path(out).exists(): res.update(ok=False, why="image not saved")
    for t in res.get("tries", []):
        if t["why"] != "ok": log(f"  {tag}: {t['provider']} failed after {t['secs']}s: {t['why']}")
        if "login expired" in t["why"]:
            _down[t["provider"]] = time.time()
            log(f"  WARNING: {t['provider']} login expired. Settings -> 'Log in for cloud stills' (one time). Skipped for the next {DOWN_SECS // 60} min.")
    log(f"  {tag}: " + (f"cloud still from {res['provider']} in {res['secs']}s" if res["ok"] else f"no cloud still ({res['why'][:160]})"))
    if job is not None:
        try:
            with open(Path(job) / "cloud_log.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps({"t": time.strftime("%Y-%m-%d %H:%M:%S"), "tag": tag, "out": Path(out).name, **res}) + "\n")
        except Exception: pass
    return res


def login(cfg):
    """Open the normal browser (not automated) on the cloud profile with Gemini and ChatGPT, for a one-time manual sign-in."""
    _down.clear()
    ch, exe = browser_exe(cfg)
    if not exe: raise RuntimeError("Chrome / Edge not found (set cloud_browser in settings)")
    subprocess.Popen([exe, f"--user-data-dir={profile_dir(cfg)}", "--no-first-run", "--no-default-browser-check", URLS["gemini"], URLS["chatgpt"]])
    return {"browser": ch, "profile": str(profile_dir(cfg))}


def status(cfg):
    from . import config
    try:
        r = subprocess.run([sys.executable, "-m", "studio.cloudgen", "status"], cwd=str(config.APP), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=120, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        line = next((l for l in reversed(r.stdout.splitlines()) if l.startswith("{")), "")
        return json.loads(line) if line else {"error": (r.stderr or r.stdout)[-200:]}
    except Exception as e: return {"error": str(e)[:200]}


def has_person(text, ents):
    """True when the narration names a real person from the story's entity list (cloud is skipped for those beats)."""
    import re
    low = " " + re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower()) + " "
    for e in ents or []:
        if e.get("kind") != "person": continue
        parts = [w for w in re.sub(r"[^a-z0-9 ]+", " ", str(e.get("name", "")).lower()).split() if len(w) > 2]
        if parts and (f" {' '.join(parts)} " in low or f" {parts[-1]} " in low): return True
    return False


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from studio import config as _c
    a = argparse.ArgumentParser(); a.add_argument("cmd", choices=["gen", "login", "status"])
    a.add_argument("--prompt", default=""); a.add_argument("--out", default=""); a.add_argument("--aspect", default="9:16")
    a.add_argument("--providers", default=""); a.add_argument("--timeout", type=int, default=0)
    o = a.parse_args(); cfg = _c.load()
    if o.cmd == "login": print(json.dumps(login(cfg)))
    elif o.cmd == "status": print(json.dumps(_child_status(cfg)))
    else:
        provs = [x for x in o.providers.split(",") if x in URLS] or providers_of(cfg)
        print(json.dumps(_child_gen(cfg, o.prompt, o.out, o.aspect, provs, o.timeout or int(cfg.get("cloud_timeout", 90)))), flush=True)
