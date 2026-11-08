"""SPEC-Z005 route registry: 11 standalone media routes. No Video Studio imports.

Each route is fn(desc, aspect, image_path, ctx) -> output Path | Blocker(reason).
Blocker = a precise reason the route cannot run right now (no token, not signed in,
not installed, unreachable). Per spec, a precise blocker is a PASS for the card's
plumbing — Tariq judges the outputs himself; there is no QC gate here.

SPEC-Z007 changes: shared sign-in detection (_signin_state: signed_in / login_wall /
unknown, with logged evidence on every card), best-effort first generation attempts on
each browser route, r3 robustness (thinking blocks, string content, Blocker passthrough),
and Chrome restore-bubble suppression in _browser (Preferences repair + launch flag).
"""
import base64
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
# Video Studio's own media routes (moved in from the media-poc setup page, 2026-11-06). Signed-in browser profiles, outputs and
# secrets live in a data folder, not in the code: VS_MEDIA_DATA (set by studio/mediaroutes.py; default <jobs_dir parent>\media_routes)
DATA = Path(os.environ.get("VS_MEDIA_DATA") or ROOT)
OUT = DATA / "output"
SECRETS = DATA / "secrets"
PROFILES = DATA / "profiles"

HOME_URLS = {
    "chatgpt": "https://chatgpt.com/",
    "bing": "https://www.bing.com/images/create",
    "meta": "https://meta.ai/",
    "flow": "https://flow.google.com/",
    "marble": "https://marble.worldlabs.ai/",
    "copilot": "https://copilot.com/chat",   # describes images for the Meta chain (Bing's chat; Microsoft sign-in)
}


class Blocker(Exception):
    pass


def _env(name):
    """Parse a secrets/<name>.env file (KEY=VALUE lines) -> dict. Never logged."""
    p = SECRETS / name
    if not p.is_file():
        return None
    d = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            d[k.strip()] = v.strip().strip('"').strip("'")
    return d


def _dims(aspect):
    return (768, 1344) if aspect == "9:16" else (1344, 768)


def _save(data: bytes, name: str) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / name
    p.write_bytes(data)
    return p


def _goto(page, url, wait="domcontentloaded"):
    """Navigate with one retry; a load timeout becomes a precise blocker, not a traceback."""
    for attempt in (1, 2):
        try:
            page.set_default_timeout(30000)
            page.goto(url, wait_until=wait, timeout=30000)
            return
        except Exception as e:
            if attempt == 2:
                raise Blocker(f"page did not load ({str(e).splitlines()[0][:110]}) — site unreachable or network too slow")


# ------------------------------------------------------------- Chrome crash-bubble (Z007 §D)
def _repair_prefs(site):
    """Flip a crashed exit to clean in profiles/<site>/Default/Preferences (raw text only).

    Headless exits record exit_type 'Crashed', which pops the 'Restore pages?' bubble on
    later launches. Same repair as Tariq's login-all-profiles.ps1 v2.3: raw-text flips,
    nothing else touched; skipped silently when missing or locked."""
    p = PROFILES / site / "Default" / "Preferences"
    try:
        raw = p.read_text(encoding="utf-8", errors="ignore")
        fixed = raw.replace('"exit_type":"Crashed"', '"exit_type":"Normal"').replace('"exit_type": "Crashed"', '"exit_type": "Normal"')
        fixed = re.sub(r'("exited_cleanly"\s*:\s*)false', r"\1true", fixed)
        if fixed != raw:
            p.write_text(fixed, encoding="utf-8")
            return "repaired"
        return "already clean"
    except PermissionError:
        return "locked (skipped)"
    except OSError:
        return "no Preferences file (skipped)"


def _browser(site, headless=False):
    """Playwright Chrome on this route's own profile (media-poc/profiles/<site>/).
    Headed but parked offscreen (publisher pattern): a real window avoids headless-only
    bot walls (Cloudflare challenges headless Chrome on chatgpt.com, verified Nov 3)."""
    from playwright.sync_api import sync_playwright
    prefs = _repair_prefs(site)
    args = ["--lang=en-US", "--hide-crash-restore-bubble", "--no-default-browser-check", "--no-first-run", "--disable-sync",
            "--disable-features=SigninInterception,ChromeSigninInterception,ExplicitBrowserSigninUIOnDesktop",   # Z007 §D: no Restore bubble, no "set as default" popup
            "--window-position=-32000,-32000", "--window-size=1440,1000"]
    token = {"pw": sync_playwright().start()}
    ctx = token["pw"].chromium.launch_persistent_context(
        str(PROFILES / site), channel="chrome", headless=headless, locale="en-US", args=args)
    page = ctx.new_page()
    page.set_default_timeout(20000)
    return token["pw"], ctx, page, prefs


# ------------------------------------------------------------- sign-in detection (Z007 §A)
# Strong login-wall URL evidence per site (a generic Log in button is NOT wall evidence).
WALL_URL_MARKERS = {
    "chatgpt": ("auth.openai.com", "auth0.openai.com", "/auth/login"),
    "bing": ("login.live.com", "signup.live.com", "login.microsoftonline.com"),
    "meta": ("login.facebook.com", "facebook.com/login"),
    "flow": ("accounts.google.com/SignIn", "accounts.google.com/ServiceLogin", "accounts.google.com/v3/signin",
             "flow.google.com/about"),   # signed out, flow.google.com/ redirects to the /about marketing page
    "marble": ("auth.worldlabs.ai", "accounts.google.com/SignIn", "accounts.google.com/ServiceLogin"),
    "copilot": ("login.live.com", "login.microsoftonline.com", "signup.live.com"),
}

# Positive signed-in signals per site: (evidence label, check fn -> bool). Two independent
# signals per site where the page offers them; ANY match = signed_in.
POSITIVE_SIGNALS = {
    "chatgpt": [
        ("composer/prompt box visible", lambda p: _any_visible(p, ["[placeholder*='Ask ChatGPT']", "#prompt-textarea", "textarea[data-id='root']", "div[contenteditable='true']"])),
        ("chat sidebar (New chat) present", lambda p: _any_visible(p, ["button:has-text('New chat')", "a:has-text('New chat')", "[data-testid*='new-chat']"])),
    ],
    "bing": [
        ("Rewards/account header visible", lambda p: _any_visible(p, ["header :text('Rewards')", "#rewardsHeaderFlyout", "a[href*='rewards']", "#sb_bguards"])),
        ("create composer visible", lambda p: _any_visible(p, ["input[placeholder*='Describe the image']", "textarea[placeholder*='Describe']", "#sb_form_i"])),
    ],
    "meta": [
        ("meta.ai composer visible", lambda p: _any_visible(p, ["textarea[placeholder*='Ask Meta']", "div[contenteditable='true']"])),
        ("signed-in account row present", lambda p: _any_visible(p, ["[data-testid*='profile']", "img[alt='']", "button[aria-label*='account']"])),
    ],
    "flow": [
        ("Flow editor/create UI visible", lambda p: _any_visible(p, ["button:has-text('New project')", "[contenteditable='true']"])),
        ("Google account avatar present", lambda p: _any_visible(p, ["img[alt*='Google Account']", "a[aria-label*='Google Account']", "img[src*='googleusercontent']"])),
    ],
    "marble": [
        ("world prompt input visible", lambda p: _any_visible(p, ["input[placeholder*='world']", "input[placeholder*='Imagine']", "[placeholder*='Imagine a world']"])),
        ("Marble world gallery visible", lambda p: _any_visible(p, ["img[src*='world']", "nav", "button:has-text('Create')"])),
    ],
    "copilot": [   # signed out, copilot.com is a marketing page with "Sign in" and no composer
        ("Copilot composer visible", lambda p: _any_visible(p, ["textarea#userInput", "textarea[placeholder*='Message']", "textarea", "[contenteditable='true']"])),
    ],
}


def _visible(page, locator_str, timeout=1200):
    try:
        return page.locator(locator_str).first.is_visible(timeout=timeout)
    except Exception:
        return False


def _any_visible(page, selectors, timeout=1200):
    """True when ANY individual selector is visible (comma-joined .first can hit a
    hidden template element before the real one — the meta.ai composer bug)."""
    for sel in selectors:
        if _visible(page, sel, timeout):
            return True
    return False


def _cloudflare_challenge(page):
    try:
        # the checkbox lives in a challenges.cloudflare.com iframe, so the page's own text often doesn't show it
        if any("challenges.cloudflare.com" in (f.url or "") for f in page.frames):
            return True
        if "just a moment" in (page.title() or "").lower():
            return True
        body = page.locator("body").inner_text()[:1200].lower()
        return ("verify you are human" in body) or ("cloudflare" in body and "verify" in body)
    except Exception:
        return False


def _signin_state(page, site):
    """-> (state, evidence). state in {signed_in, login_wall, unknown} (Z007 §A).
    login_wall ONLY on strong evidence: auth host/path in the final URL or a visible
    password input. Generic Log in / Sign up buttons are NOT wall evidence (the Bing bug)."""
    markers = WALL_URL_MARKERS.get(site, ())
    if any(m.lower() in page.url.lower() for m in markers):
        return "login_wall", f"final URL is an auth page: {page.url[:100]}"
    if _visible(page, "input[type='password']", 800):
        return "login_wall", "a visible password input on the page"
    matched, checked = [], []
    for label, fn in POSITIVE_SIGNALS.get(site, ()):
        checked.append(label)
        try:
            if fn(page):
                matched.append(label)
        except Exception:
            pass
    if matched:
        return "signed_in", "; ".join(matched)
    page.wait_for_timeout(4000)           # settle longer, then retry the checks once
    for label, fn in POSITIVE_SIGNALS.get(site, ()):
        try:
            if fn(page):
                matched.append(label)
        except Exception:
            pass
    if matched:
        return "signed_in", "; ".join(matched) + " (second pass)"
    if _cloudflare_challenge(page):
        return "unknown", "a Cloudflare 'Verify you are human' challenge is showing (bot wall, never bypassed); signals checked: " + ", ".join(checked)
    return "unknown", "no login wall and none of the positive signals matched: " + ", ".join(checked)


def _note(ctx, text):
    prev = ctx.get("card_note")
    ctx["card_note"] = (prev + " || " + text) if prev else text


def _blocker_unknown(site, page, ctx, rid, state, evidence):
    """The Z007 §A unknown path: screenshot + URL + page text into the card note."""
    try:
        page.screenshot(path=str(OUT / f"{rid}_state.png"))
        body = page.locator("body").inner_text()[:500].replace("\n", " ")
    except Exception:
        body = "(page text unavailable)"
    _note(ctx, f"signin={state}; evidence: {evidence}; url={page.url[:90]}; page: {body[:300]}")
    if "Cloudflare" in evidence:
        raise Blocker(f"Cloudflare 'Verify you are human' check (never clicked by the POC): use OPEN LOGIN "
                      f"to open profiles/{site}, tick the box yourself, close the window, then RUN again; "
                      f"screenshot {rid}_state.png")
    raise Blocker(f"state unknown — no login wall and no signed-in evidence on profiles/{site} "
                  f"(checked: {evidence}); screenshot {rid}_state.png; use OPEN LOGIN if the "
                  f"profile is actually signed out")


def _not_signed_in(site):
    raise Blocker(f"login wall — sign-in needed: use OPEN LOGIN (profiles/{site})")


# ---------------------------------------------------------------- image routes
def r1_cloudflare_flux(desc, aspect, image_path, ctx):
    """SPEC-Z009 §C: byte-for-byte the D142-proven call shape (Authorization header only;
    requests auto-sets the JSON content type; body = prompt + steps). Accepts a raw image
    body OR the JSON base64 wrapper. On failure, runs a standalone D142-shape probe in the
    same run and quotes BOTH raw responses (no token value anywhere)."""
    env = _env("cloudflare.env")
    if not env or not env.get("CLOUDFLARE_ACCOUNT_ID") or not env.get("CLOUDFLARE_API_TOKEN"):
        raise Blocker("no token — create media-poc/secrets/cloudflare.env with "
                      "CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN")
    url = (f"https://api.cloudflare.com/client/v4/accounts/{env['CLOUDFLARE_ACCOUNT_ID']}"
           "/ai/run/@cf/black-forest-labs/flux-1-schnell")
    headers = {"Authorization": "Bearer " + env["CLOUDFLARE_API_TOKEN"]}
    r = requests.post(url, headers=headers,
                      json={"prompt": desc[:2000], "steps": 4}, timeout=180)
    raw_route = f"HTTP {r.status_code}: {r.text[:180]}"
    data = None
    if r.status_code == 200:
        if r.content[:3] == bytes.fromhex("ffd8ff") or r.content[:4] == bytes.fromhex("89504e47"):
            data = r.content                       # raw image body
        else:
            img = (r.json().get("result") or {}).get("image")
            if img:
                data = base64.b64decode(img)
    if not data:
        probe = requests.post(url, headers={"Authorization": "Bearer " + env["CLOUDFLARE_API_TOKEN"]},
                              json={"prompt": "A red lighthouse on a rocky coast at sunset, photorealistic",
                                    "steps": 4}, timeout=180)
        raw_probe = f"HTTP {probe.status_code}: {probe.text[:180]}"
        raise Blocker(f"raw route response: {raw_route} || standalone D142-shape probe (same run, "
                      f"identical URL/method/headers/body-keys per cf_test_D142.py): {raw_probe} "
                      f"— if both are 401 code 10000, the env token is an EXPIRED wrangler OAuth "
                      f"access token (hours-long lifetime): refresh via wrangler login (D141-style "
                      f"dump) or supply a real REST API token")
    return _save(data, "r1_cloudflare_flux.jpg")


def r2_hf_flux(desc, aspect, image_path, ctx):
    try:
        from gradio_client import Client
    except ImportError:
        raise Blocker("gradio_client not installed in the POC venv")
    hf = _env("hf.env")
    token = (hf or {}).get("HF_TOKEN")
    w, h = _dims(aspect)
    prompt = re.sub(r"\s+", " ", desc).strip()[:700] + " Photorealistic. No text, no logos."
    client = Client("black-forest-labs/FLUX.1-schnell", token=token, verbose=False)
    res = client.predict(prompt, 0, True, w, h, 4, api_name="/infer")
    src = res[0] if isinstance(res, (list, tuple)) else res
    if not src or not Path(src).is_file():
        raise Blocker(f"space returned no file ({res!r}"[:160] + ")")
    return _save(Path(src).read_bytes(), "r2_hf_flux.jpg")


def r3_meta_describe(desc, aspect, image_path, ctx):
    """SPEC-Z009 §A: image -> description + image prompt, via the signed-in meta.ai
    profile (same _browser pattern as r6/r7). DeepSeek removed from the POC — its API
    kept returning thinking-only replies; per Tariq, Meta does this job."""
    if not image_path:
        raise Blocker("needs an image (upload one, or run R6/R1/R2 first)")
    pw, cctx, page, prefs = _browser("meta")
    ctx["_page"] = page
    try:
        _note(ctx, f"prefs: {prefs}")
        _goto(page, HOME_URLS["meta"])
        page.wait_for_timeout(4000)
        state, evidence = _signin_state(page, "meta")
        _note(ctx, f"signin={state}; evidence: {evidence}")
        if state == "login_wall":
            _not_signed_in("meta")
        if state == "unknown":
            _blocker_unknown("meta", page, ctx, "r3", state, evidence)
        box = _pick(page, ["textarea[placeholder*='Ask Meta']", "textarea[placeholder*='meta.ai']", "div[contenteditable='true']"])
        try:
            box.first.click()
            # attach the image through the composer's file input (the + control), then send the standing text
            page.set_input_files("input[type='file']", image_path, timeout=6000)
            page.wait_for_timeout(3000)
            _type_like_human(page, box, "Describe this image in detail. Then write one image-generation prompt that would recreate it.")
        except Exception:
            _gen_fail(ctx, "meta", evidence, "composer/attach not usable")
        # wait until a real answer streams in AFTER our prompt (marker-anchored, class-free)
        marker = "recreate it"
        full = ""
        deadline = time.time() + 120
        while time.time() < deadline:
            try:
                # scope to the thread region: <main> holds the conversation, not the sidebar history
                full = (page.locator("main").inner_text()
                        if page.locator("main").count() and page.locator("main").first.is_visible()
                        else page.locator("body").inner_text())
            except Exception:
                full = ""
            if marker in full:
                tail = full[full.index(marker) + len(marker):]
                if len(tail.strip()) > 400:
                    break
            page.wait_for_timeout(5000)
        reply = full[full.index(marker) + len(marker):] if marker in full else ""
        junk = ("Ask Meta AI", "Instant", "New chat", "Search", "Media", "Artifacts", "Topics",
                "Pinned", "History", "Create images", "Discover", "Ask anything", "Take action",
                "Scheduled", "Vibes", "Settings", "Privacy policy")
        lines = [l.strip() for l in reply.splitlines()
                 if l.strip() and len(l.strip()) > 1 and not any(j in l for j in junk)]
        reply = chr(10).join(lines).strip()
        out = _save(("DESCRIPTION + IMAGE PROMPT (via meta.ai profile — DeepSeek removed from the POC)\n\n"
                     + reply.strip()[:4000]).encode(), "r3_meta_describe.txt")
        _note(ctx, f"via meta.ai profile — DeepSeek removed from the POC; reply excerpt: {reply.strip()[:180]}")
        return out
    finally:
        cctx.close()
        pw.stop()


# --------------------------------------------------------------- browser routes (Z007 §A/§B)
def _pick(page, selectors):
    """First VISIBLE candidate locator (individual checks — no comma-joined .first)."""
    for sel in selectors:
        if _visible(page, sel, 1200):
            return page.locator(sel).first
    return page.locator(selectors[0]).first      # fall through: let the step-fail path report it


def _prompt(desc, extra):
    """desc + only the words of `extra` it doesn't already have ("photorealistic" was being sent twice)."""
    low = desc.lower()
    add = [w.strip() for w in extra.split(",") if w.strip() and w.strip().lower() not in low]
    return desc.rstrip(" .,") + (", " + ", ".join(add) if add else "")


def _type_like_human(page, locator, text, submit=True):
    locator.first.wait_for(state="visible", timeout=15000)
    locator.first.click()
    for chunk in text.split(" "):
        page.keyboard.type(chunk + " ", delay=40)
    if submit:
        page.keyboard.type("\n")


def _dismiss_popups(page, ctx):
    """Close 'what's new' / promo windows that cover the composer (ChatGPT's 'Create GIFs' card, Nov 6)."""
    closed = 0
    for _ in range(3):
        dlg = page.locator("[role='dialog']:visible")
        if not dlg.count():
            break
        for sel in ("[role='dialog'] button[aria-label='Close']", "[role='dialog'] button[aria-label*='close' i]",
                    "[role='dialog'] button:has-text('Maybe later')", "[role='dialog'] button:has-text('Not now')"):
            try:
                b = page.locator(sel).first
                if b.is_visible(timeout=500):
                    b.click(timeout=3000); closed += 1; break
            except Exception:
                continue
        else:
            page.keyboard.press("Escape"); closed += 1
        page.wait_for_timeout(700)
    if closed:
        _note(ctx, f"closed {closed} popup(s) over the page")


def _flow_close_news(page, ctx):
    """Flow shows a 'what's new' window (e.g. 'Introducing Omni 1.2' with Get started) that blocks the editor; close it
    in whichever frame it is in."""
    for fr in page.frames:
        for sel in ("button:has-text('Get started')", "button:has-text('Got it')", "button[aria-label='Close']",
                    "button:has-text('close')"):
            try:
                b = fr.locator(sel).first
                if b.is_visible(timeout=400):
                    b.click(timeout=3000)
                    _note(ctx, f"closed Flow news window ({sel})")
                    page.wait_for_timeout(1500)
                    return
            except Exception:
                continue
    _dismiss_popups(page, ctx)


def _is_image(data):
    """True only for real image bytes (JPEG/PNG/GIF/WebP). Bing once returned an HTML page that passed as 'ok'."""
    if not data or len(data) < 12:
        return False
    return (data[:3] == b"\xff\xd8\xff" or data[:8] == b"\x89PNG\r\n\x1a\n" or data[:6] in (b"GIF87a", b"GIF89a")
            or (data[:4] == b"RIFF" and data[8:12] == b"WEBP"))


def _is_video(data, min_bytes=50000):
    """True only for a real MP4/MOV ('ftyp' box) or WebM file. Nov 6: a 920 KB sign-in page was saved as r8's 'video'."""
    if not data or len(data) < min_bytes:
        return False
    return data[4:8] == b"ftyp" or data[:4] == bytes.fromhex("1a45dfa3")


def _img_srcs(page):
    """Every <img> src on the page now: taken BEFORE submitting, so images already on the page never count as results."""
    try:
        return set(page.evaluate("() => [...document.images].map(i => i.currentSrc || i.src).filter(Boolean)"))
    except Exception:
        return set()


def _submit(page, selectors, ctx, evidence, site, sent_check):
    """Click the send/generate button (Enter as a fallback), then confirm the prompt really went out."""
    how = "Enter key"
    for sel in selectors:
        try:
            b = page.locator(sel).first
            if b.is_visible(timeout=1500) and b.is_enabled():
                b.click(timeout=5000); how = f"clicked {sel}"; break
        except Exception:
            continue
    else:
        page.keyboard.press("Enter")
    for _ in range(20):
        page.wait_for_timeout(500)
        try:
            if sent_check(page):
                _note(ctx, f"prompt sent ({how})")
                return
        except Exception:
            pass
    _gen_fail(ctx, site, evidence, f"prompt typed but not sent ({how})")


def _first_image_bytes(page, url_hint=""):
    """Download the first sizeable image on the page (skip icons/avatars < 20 KB)."""
    for img in page.locator("img").all()[:40]:
        try:
            src = img.get_attribute("src") or ""
            if src.startswith("data:") or not src:
                continue
            if url_hint and url_hint not in src:
                continue
            data = requests.get(src, timeout=30).content
            if len(data) > 20000 and _is_image(data):
                return data
        except Exception:
            continue
    return None


def _poll_generation(page, ctx, rid, site, evidence, selectors, out_name, deadline_s=480, every=15, min_bytes=20000, baseline=None):
    """SPEC-Z008 §A/§B2: poll up to `deadline_s` for a generated image, ~every `every` s.
    Each poll logs (elapsed, img count) into the card note. Downloads via requests first;
    if that returns nothing usable, fetches the bytes inside the browser context, and as a
    last resort screenshots the img element. Fails only after the full window."""
    t0 = time.time()
    polls = []
    while time.time() - t0 < deadline_s:
        elapsed = int(time.time() - t0)
        data = None
        # every loaded, reasonably large image (absolute currentSrc: ChatGPT now serves results from relative
        # /backend-api/... addresses the old src filter never matched); known result hosts first
        try:
            found = page.evaluate("""() => [...document.images]
                .filter(i => i.complete && i.naturalWidth >= 200 && i.naturalHeight >= 200)
                .map(i => i.currentSrc || i.src).filter(s => s && !s.startsWith('data:'))""")
        except Exception:
            found = []
        n = len(found)
        known = ("oaiusercontent", "backend-api", "estuary", "scontent", "th.bing", "bing.net", "OIG")
        srcs = [s for s in dict.fromkeys(found) if not (baseline and s in baseline)]   # new since the prompt only
        srcs.sort(key=lambda s: not any(k in s for k in known))
        for s in srcs:
            if not s.startswith("http"):
                continue           # blob: URLs only work inside the browser (fetched below)
            try:
                d = requests.get(s, timeout=30).content
                if len(d) >= min_bytes and _is_image(d):
                    data = d
                    break
            except Exception:
                continue
        if data is None and srcs:
            # fetch inside the browser context (same-origin, cookies included)
            try:
                d_b64 = page.evaluate("""async (srcs) => {
                    for (const s of srcs) {
                        try {
                            const r = await fetch(s);
                            if (!r.ok) continue;
                            const b = new Uint8Array(await r.arrayBuffer());
                            if (b.length < 20000) continue;
                            let bin = '';
                            for (let i = 0; i < b.length; i += 32768)
                                bin += String.fromCharCode.apply(null, b.subarray(i, i + 32768));
                            return btoa(bin);
                        } catch (e) { continue; }
                    }
                    return null;
                }""", srcs[:10])
                if d_b64 and _is_image(base64.b64decode(d_b64)):
                    data = base64.b64decode(d_b64)
            except Exception:
                pass
        polls.append(f"{elapsed}s: {n} imgs, {len(srcs)} candidates, {'downloaded' if data else 'none usable'}")
        _note(ctx, "poll " + "; ".join(polls[-3:]))
        if data:
            _note(ctx, f"poll loop: success at {elapsed}s after {len(polls)} polls")
            return _save(data, out_name)
        page.wait_for_timeout(every * 1000)
    try:
        page.screenshot(path=str(OUT / f"gen_{site}_fail.png"))
    except Exception:
        pass
    raise Blocker(f"signed in OK (evidence: {evidence}); full {deadline_s}s poll window elapsed with no "
                  f"downloadable image ({len(polls)} polls; last: {polls[-1] if polls else 'none'}) — "
                  f"page state saved to output/gen_{site}_fail.png")


def _gen_fail(ctx, site, evidence, step):
    """Screenshot the page state; raise a precise blocker keeping the signed-in evidence."""
    shot = f"gen_{site}_fail.png"
    try:
        page = ctx.get("_page")
        if page:
            page.screenshot(path=str(OUT / shot))
    except Exception:
        shot = "(screenshot unavailable)"
    raise Blocker(f"signed in OK (evidence: {evidence}); failed at step '{step}' — "
                  f"page state saved to output/{shot}")


def r4_chatgpt_image(desc, aspect, image_path, ctx):
    pw, cctx, page, prefs = _browser("chatgpt")
    ctx["_page"] = page
    try:
        _note(ctx, f"prefs: {prefs}")
        _goto(page, HOME_URLS["chatgpt"])
        page.wait_for_timeout(4000)
        state, evidence = _signin_state(page, "chatgpt")
        _note(ctx, f"signin={state}; evidence: {evidence}")
        if state == "login_wall":
            _not_signed_in("chatgpt")
        if state == "unknown":
            _blocker_unknown("chatgpt", page, ctx, "r4", state, evidence)
        # Nov 6: #prompt-textarea is gone; the composer is a ProseMirror div labelled "Ask ChatGPT"
        sels = ["div.ProseMirror[contenteditable='true']", "div[contenteditable='true'][aria-label*='ChatGPT']",
                "#prompt-textarea", "div[contenteditable='true']", "textarea"]
        _dismiss_popups(page, ctx)
        box = None
        for _ in range(10):                       # the composer can render a few seconds after sign-in evidence
            box = next((page.locator(s).first for s in sels if _visible(page, s, 800)), None)
            if box:
                break
            page.wait_for_timeout(1500)
        if box is None:
            _gen_fail(ctx, "chatgpt", evidence, "prompt box not found (none of: " + ", ".join(sels) + ")")
        before = _img_srcs(page)
        start_url = page.url
        try:
            box.click()
            page.keyboard.press("Control+A")      # ChatGPT keeps an unsent draft: clear it so only this prompt goes out
            page.keyboard.press("Backspace")
            _type_like_human(page, box, "Create an image: " + _prompt(desc, "photorealistic, no text"), submit=False)
        except Exception as e:
            _gen_fail(ctx, "chatgpt", evidence, f"prompt box not usable ({type(e).__name__}: {str(e)[:120]})")
        page.wait_for_timeout(800)
        # sent = the chat moved to its own /c/ address, a Stop button appeared, or our message is in the thread
        _submit(page, ["button[data-testid='send-button']", "#composer-submit-button", "button[aria-label*='Send']"],
                ctx, evidence, "chatgpt",
                lambda p: (p.url != start_url and "/c/" in p.url)
                          or p.locator("button[data-testid='stop-button'], button[aria-label*='Stop']").count() > 0
                          or p.locator("[data-message-author-role='user']").count() > 0)
        # SPEC-Z008 §A: generation may simply take longer than one fixed wait — poll 480s
        return _poll_generation(page, ctx, "r4", "chatgpt", evidence,
                                ["img[src*='oaiusercontent']", "img[alt*='Generated']", "img[src*='blob']"],
                                "r4_chatgpt_image.jpg", deadline_s=480, baseline=before)
    finally:
        cctx.close()
        pw.stop()


def r5_bing_image(desc, aspect, image_path, ctx):
    pw, cctx, page, prefs = _browser("bing")
    ctx["_page"] = page
    try:
        _note(ctx, f"prefs: {prefs}")
        _goto(page, HOME_URLS["bing"])
        page.wait_for_timeout(4000)
        state, evidence = _signin_state(page, "bing")
        _note(ctx, f"signin={state}; evidence: {evidence}")
        if state == "login_wall":
            _not_signed_in("bing")
        if state == "unknown":
            _blocker_unknown("bing", page, ctx, "r5", state, evidence)
        # the redesigned create page: type into the composer, click Generate
        box = _pick(page, ["input[placeholder*='Describe the image']", "textarea[placeholder*='Describe']", "#sb_form_i"])
        before = _img_srcs(page)
        try:
            _type_like_human(page, box, desc[:900])
        except Exception:
            _gen_fail(ctx, "bing", evidence, "composer not usable")
        try:
            page.get_by_role("button", name="Generate").first.click(timeout=10000)
        except Exception:
            page.keyboard.press("Enter")
        # SPEC-Z008 §B2: poll up to 480s for the results grid / generated images
        return _poll_generation(page, ctx, "r5", "bing", evidence,
                                ["li img", "img[class*='mimg']", "div.gimg img", "img[src*='th.bing.com']"],
                                "r5_bing_image.jpg", deadline_s=480, baseline=before)
    finally:
        cctx.close()
        pw.stop()


def r6_meta_image(desc, aspect, image_path, ctx):
    pw, cctx, page, prefs = _browser("meta")
    ctx["_page"] = page
    try:
        _note(ctx, f"prefs: {prefs}")
        _goto(page, HOME_URLS["meta"])
        page.wait_for_timeout(4000)
        state, evidence = _signin_state(page, "meta")
        _note(ctx, f"signin={state}; evidence: {evidence}")
        if state == "login_wall":
            _not_signed_in("meta")
        if state == "unknown":
            _blocker_unknown("meta", page, ctx, "r6", state, evidence)
        box = _pick(page, ["textarea[placeholder*='Ask Meta']", "textarea[placeholder*='meta.ai']", "div[contenteditable='true']"])
        try:
            _type_like_human(page, box, _prompt(desc, "photorealistic, no text"))
        except Exception:
            _gen_fail(ctx, "meta", evidence, "prompt box not usable")
        try:
            page.wait_for_selector("img[src*='scontent'], img[alt*='Generated'], img[src*='blob']", timeout=180000)
        except Exception:
            _gen_fail(ctx, "meta", evidence, "no generated image within 180s")
        data = _first_image_bytes(page, "scontent") or _first_image_bytes(page)
        if not data:
            _gen_fail(ctx, "meta", evidence, "image download")
        return _save(data, "r6_meta_image.jpg")
    except Exception:
        try:                                  # NEW provider: always keep a page-state screenshot
            page.screenshot(path=str(OUT / "r6_meta_state.png"))
        except Exception:
            pass
        raise
    finally:
        cctx.close()
        pw.stop()


def r7_meta_video(desc, aspect, image_path, ctx):
    src = image_path
    if not src and not ctx.get("no_fallback"):   # the 42054 page reuses an earlier output; the studio ladder never does
        prev = sorted(OUT.glob("r6_meta_image.jpg")) + sorted(OUT.glob("r2_hf_flux.jpg")) + sorted(OUT.glob("r1_cloudflare_flux.jpg"))
        src = str(prev[-1]) if prev else None
    pw, cctx, page, prefs = _browser("meta")
    ctx["_page"] = page
    try:
        _note(ctx, f"prefs: {prefs}")
        _goto(page, HOME_URLS["meta"])
        page.wait_for_timeout(4000)
        state, evidence = _signin_state(page, "meta")
        _note(ctx, f"signin={state}; evidence: {evidence}")
        if state == "login_wall":
            _not_signed_in("meta")
        if state == "unknown":
            _blocker_unknown("meta", page, ctx, "r7", state, evidence)
        box = _pick(page, ["textarea[placeholder*='Ask Meta']", "div[contenteditable='true']"])
        prompt = ("Animate this image with a slow cinematic camera push-in. People stay still with their mouths closed: no talking, no lip movement. "
                  "Keep the image's art style exactly: a drawing or sketch stays a drawing in every frame. " + desc) if src else \
                 ("Create a short video: " + _prompt(desc, "photorealistic, slow cinematic camera move, no text"))
        try:
            box.first.click()
            if src:   # attach the source image if the composer offers a file input
                try:
                    page.set_input_files("input[type='file']", src, timeout=4000)
                    page.wait_for_timeout(4000)
                    box = _pick(page, ["div[contenteditable='true']", "textarea", "[role='textbox']"])   # placeholder gone now
                except Exception:
                    pass
            _type_like_human(page, box, prompt)
        except Exception:
            _gen_fail(ctx, "meta", evidence, "prompt box not usable")
        try:
            page.wait_for_selector("video[src*='scontent'], video[src*='blob'], video", timeout=240000)
        except Exception:
            _gen_fail(ctx, "meta", evidence, "no generated video within 240s")
        vidsrc = page.locator("video source, video").first.get_attribute("src") or ""
        if not vidsrc:
            _gen_fail(ctx, "meta", evidence, "video download")
        data = None
        try:
            data = requests.get(vidsrc, timeout=120).content if vidsrc.startswith("http") else None
        except Exception:
            data = None
        if not _is_video(data) and vidsrc.startswith("http"):
            try:
                data = cctx.request.get(vidsrc, timeout=120000).body()   # signed-in cookies
            except Exception:
                data = None
        if not _is_video(data):
            _gen_fail(ctx, "meta", evidence, "video download (not a video file)")
        _note(ctx, "image-to-video" if src else "text-to-video (no image given)")
        return _save(data, "r7_meta_video.mp4")
    finally:
        cctx.close()
        pw.stop()


def r8_flow_video(desc, aspect, image_path, ctx):
    pw, cctx, page, prefs = _browser("flow")
    ctx["_page"] = page
    try:
        _note(ctx, f"prefs: {prefs}")
        _goto(page, HOME_URLS["flow"])
        page.wait_for_timeout(6000)
        state, evidence = _signin_state(page, "flow")
        _note(ctx, f"signin={state}; evidence: {evidence}")
        if state == "login_wall":
            _not_signed_in("flow")
        if state == "unknown":
            _blocker_unknown("flow", page, ctx, "r8", state, evidence)
        # SPEC-Z008 §B (D140 evidence): the landing page has NO composer - only a hidden 0x0
        # textarea and a visible "add / New project" button. Start a project first, then drive
        # the editor INSIDE its frame (Z008 found it in an iframe, not the top page).
        _flow_close_news(page, ctx)
        newproj = _pick(page, ["button:has-text('New project')", ":text('New project')", "button:has-text('add')"])
        try:
            newproj.first.click(timeout=10000)
            _note(ctx, "clicked New project (landing-page composer confirmed absent, per D140)")
        except Exception:
            _gen_fail(ctx, "flow", evidence, "'New project' button not found/clickable")
        page.wait_for_timeout(8000)
        _flow_close_news(page, ctx)      # the "Introducing Omni 1.2" window opens over the editor (Nov 6)
        # in-frame inventory (the D140 way, inside frames this time)
        inv = []
        box = None
        box_frame = None
        for fr in page.frames:
            ta = fr.locator("textarea")
            ce = fr.locator("[contenteditable='true']")
            tb = fr.locator("[role='textbox']")
            n = ta.count() + ce.count() + tb.count()
            if n:
                inv.append(f"frame={fr.url.split('/')[-1][:50] or fr.name[:30] or 'main'}: textarea={ta.count()} contenteditable={ce.count()} textbox={tb.count()}")
            if box is None:
                for loc in (ta, ce, tb):
                    for i in range(min(loc.count(), 5)):
                        cand = loc.nth(i)
                        try:
                            cand.click(timeout=3000)          # drive INSIDE the frame
                            cand.fill(_prompt(desc, "cinematic slow camera move, photorealistic, no text"))
                            box, box_frame = cand, fr
                            break
                        except Exception:
                            continue
                    if box:
                        break
            if box:
                break
        _note(ctx, "in-frame inventory: " + ("; ".join(inv) if inv else "no editors on any frame"))
        if box is None:
            shot = "gen_flow_composer.png"
            try:
                page.screenshot(path=str(OUT / shot))
            except Exception:
                shot = "(screenshot unavailable)"
            raise Blocker(f"signed in OK (evidence: {evidence}); New project clicked; in-frame composer "
                          f"still not drivable - IN-FRAME inventory: {'; '.join(inv) or 'none'}; "
                          f"iframes: {len(page.frames)}; screenshot output/{shot}")
        _note(ctx, f"composer driven inside frame {box_frame.url.split('/')[-1][:50] or box_frame.name[:30] or 'main'}")
        def _videos():
            out = []
            for fr in page.frames:
                try:
                    out += fr.evaluate("() => [...document.querySelectorAll('video')].map(v => v.currentSrc || v.src || (v.querySelector('source')||{}).src || '').filter(Boolean)")
                except Exception:
                    pass
            return out
        before = set(_videos())
        # Enter in the composer's own frame, then the send arrow if the text is still sitting there (Nov 6: Enter alone
        # left the prompt unsent and the route waited 480 s for nothing)
        try:
            box.press("Enter")
        except Exception:
            pass
        page.wait_for_timeout(1500)
        try:
            still = (box.input_value() if box.evaluate("e => 'value' in e") else box.inner_text()).strip()
        except Exception:
            still = ""
        # the arrow can ignore clicks while the agent is still writing its welcome message: retry for ~15 s
        for _try in range(8):
            if not still:
                break
            for sel in ("button[aria-label='Start generation']", "button[aria-label*='Send' i]", "button[aria-label*='Submit' i]", "button:has-text('arrow_forward')",
                        "button:has(i:text('arrow_forward'))", "button[type='submit']"):
                try:
                    b = box_frame.locator(sel).last
                    if b.is_visible(timeout=600) and b.is_enabled():
                        b.click(timeout=4000); _note(ctx, f"sent with {sel} (try {_try + 1})"); break
                except Exception:
                    continue
            page.wait_for_timeout(2000)
            try:
                still = (box.input_value() if box.evaluate("e => 'value' in e") else box.inner_text()).strip()
            except Exception:
                still = ""
        if still:
            _gen_fail(ctx, "flow", evidence, "prompt typed but not sent (send arrow ignored 8 tries)")
        _note(ctx, "prompt sent")
        def _approve_once():
            """Flow's agent asks "kick off this 1 video generation, costing 15 credits?" with Approve / Always approve /
            Reject. Tariq OK'd (Nov 6) clicking plain Approve once per run. Never 'Always approve': that is an account setting."""
            # the button's accessible name is "check Approve" (icon-font ligature), so match the visible label text
            # exactly: "Always approve" never matches
            for fr in page.frames:
                try:
                    b = fr.get_by_text("Approve", exact=True)
                    if b.count() and b.last.is_visible(timeout=500):
                        try:
                            m = re.search(r"costing\s+(\d+)\s+credits", fr.locator("body").inner_text())
                            ctx["_flow_cost"] = m.group(1) if m else "?"
                        except Exception:
                            ctx["_flow_cost"] = "?"
                        b.last.click(timeout=4000)
                        return True
                except Exception:
                    continue
            return False
        t0, vidsrc, approved = time.time(), "", False
        while time.time() - t0 < 480 and not vidsrc:          # Flow queues at busy times
            page.wait_for_timeout(5000 if not approved else 15000)
            if not approved and _approve_once():
                approved = True
                _note(ctx, f"approved Flow's 1-video generation ({ctx.get('_flow_cost', '?')} credits)")
            new = [s for s in _videos() if s not in before]
            if not new and approved:
                # a finished clip shows as a thumbnail; Flow only creates its <video> when the tile is hovered
                tiles = page.evaluate("""() => [...document.images].filter(i => i.naturalWidth >= 200)
                    .map(i => { const r = i.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; })""")
                for c in tiles[:4]:
                    try:
                        page.mouse.move(*c); page.wait_for_timeout(2500)
                    except Exception:
                        continue
                    new = [s for s in _videos() if s not in before]
                    if new:
                        break
            vidsrc = new[0] if new else ""
        if not vidsrc:
            _gen_fail(ctx, "flow", evidence, "no generated clip within 480s")
        data = None
        if vidsrc.startswith("http"):
            try:
                data = requests.get(vidsrc, timeout=180).content
            except Exception:
                data = None
        if (not _is_video(data)) and vidsrc.startswith("http"):
            try:                                              # flow.google.com/asb links need the signed-in cookies
                data = cctx.request.get(vidsrc, timeout=180000).body()
            except Exception:
                data = None
        if not _is_video(data):                     # blob links: fetch inside the page
            try:
                b64 = page.evaluate("""async (u) => { const r = await fetch(u); const b = new Uint8Array(await r.arrayBuffer());
                    let s = ''; for (let i = 0; i < b.length; i += 32768) s += String.fromCharCode.apply(null, b.subarray(i, i + 32768));
                    return btoa(s); }""", vidsrc)
                data = base64.b64decode(b64)
            except Exception:
                data = None
        if not _is_video(data):
            _gen_fail(ctx, "flow", evidence, f"video download ({vidsrc[:80]})")
        return _save(data, "r8_flow_video.mp4")
    finally:
        cctx.close()
        pw.stop()


# ------------------------------------------------------------------ Flow still (owner, 2026-11-07)
# Flow's agent makes STILLS without spending credits (owner's finding). Same project / in-frame composer / send steps as r8, but
# it asks for one image and NEVER approves a quote above 0 credits: a still that would cost credits is rejected and the route
# fails, so the ladder moves on. The picture can then go straight to Meta's free image-to-video (r7) or be described elsewhere.
FLOW_IMAGE_ASK = ("Generate ONE single still image (not a video, not a grid, not panels or a storyboard sheet). {shape} "
                  "No text, letters, logos, mastheads or brand names anywhere in the picture. The image: {desc}")


def _flow_frames_imgs(page, min_side=120):
    """{src: natural area} for every <img> of at least min_side in every frame (Flow's editor may live in an iframe; a new still
    first shows as a small grid thumbnail, Nov 7)."""
    out = {}
    for fr in page.frames:
        try:
            for src, a in fr.evaluate("(m) => [...document.images].filter(i => Math.min(i.naturalWidth, i.naturalHeight) >= m)"
                                      ".map(i => [i.currentSrc || i.src, i.naturalWidth * i.naturalHeight]).filter(x => x[0])", min_side):
                out[src] = max(a, out.get(src, 0))
        except Exception:
            pass
    return out


def _flow_send(page, ctx, evidence, text):
    """New project -> the composer inside its frame -> type -> send. -> the composer's frame. Raises Blocker."""
    _flow_close_news(page, ctx)
    newproj = _pick(page, ["button:has-text('New project')", ":text('New project')", "button:has-text('add')"])
    try:
        newproj.first.click(timeout=10000)
    except Exception:
        _gen_fail(ctx, "flow", evidence, "'New project' button not found/clickable")
    page.wait_for_timeout(8000)
    _flow_close_news(page, ctx)
    box = box_frame = None
    for fr in page.frames:
        for loc in (fr.locator("textarea"), fr.locator("[contenteditable='true']"), fr.locator("[role='textbox']")):
            for i in range(min(loc.count(), 5)):
                try:
                    cand = loc.nth(i); cand.click(timeout=3000); cand.fill(text); box, box_frame = cand, fr; break
                except Exception:
                    continue
            if box: break
        if box: break
    if box is None:
        _gen_fail(ctx, "flow", evidence, "composer not drivable after New project")
    try: box.press("Enter")
    except Exception: pass
    page.wait_for_timeout(1500)
    def left():
        try: return (box.input_value() if box.evaluate("e => 'value' in e") else box.inner_text()).strip()
        except Exception: return ""
    for _try in range(8):
        if not left(): break
        for sel in ("button[aria-label='Start generation']", "button[aria-label*='Send' i]", "button[aria-label*='Submit' i]",
                    "button:has-text('arrow_forward')", "button:has(i:text('arrow_forward'))", "button[type='submit']"):
            try:
                b = box_frame.locator(sel).last
                if b.is_visible(timeout=600) and b.is_enabled(): b.click(timeout=4000); break
            except Exception:
                continue
        page.wait_for_timeout(2000)
    if left():
        _gen_fail(ctx, "flow", evidence, "prompt typed but not sent")
    _note(ctx, "prompt sent")
    return box_frame


def _flow_quote(page):
    """Flow's agent approval card: -> (frame, cost) with cost an int, None when no number is shown, or (None, None) when no card."""
    for fr in page.frames:
        try:
            b = fr.get_by_text("Approve", exact=True)
            if b.count() and b.last.is_visible(timeout=500):
                m = re.search(r"costing\s+(\d+)\s+credits?", fr.locator("body").inner_text(), re.I)
                return fr, (int(m.group(1)) if m else None)
        except Exception:
            continue
    return None, None


def r14_flow_image(desc, aspect, image_path, ctx):
    pw, cctx, page, prefs = _browser("flow")
    ctx["_page"] = page
    try:
        _goto(page, HOME_URLS["flow"])
        page.wait_for_timeout(6000)
        state, evidence = _signin_state(page, "flow")
        _note(ctx, f"signin={state}; evidence: {evidence}")
        if state == "login_wall":
            _not_signed_in("flow")
        if state == "unknown":
            _blocker_unknown("flow", page, ctx, "r14", state, evidence)
        shape = "Tall vertical 9:16 portrait image." if aspect == "9:16" else "Wide horizontal 16:9 landscape image."
        before = set(_flow_frames_imgs(page))
        _flow_send(page, ctx, evidence, FLOW_IMAGE_ASK.format(shape=shape, desc=str(desc)[:1200]))
        t0, src, handled = time.time(), "", False
        while time.time() - t0 < 300 and not src:
            page.wait_for_timeout(5000)
            if not handled:
                fr, cost = _flow_quote(page)
                if fr is not None:
                    handled = True
                    if cost == 0:
                        fr.get_by_text("Approve", exact=True).last.click(timeout=4000); _note(ctx, "approved Flow's still (0 credits)")
                    else:   # never spend credits on a still: reject, and the ladder moves on
                        try: fr.get_by_text("Reject", exact=True).last.click(timeout=4000)
                        except Exception: pass
                        _gen_fail(ctx, "flow", evidence, f"Flow quoted {cost if cost is not None else 'an unknown number of'} "
                                                         "credits for the still; rejected (stills must be free)")
            new = [s for s in _flow_frames_imgs(page) if s not in before]
            src = new[0] if new else ""
        if not src:
            _gen_fail(ctx, "flow", evidence, "no still within 300s")
        page.wait_for_timeout(4000)
        try:   # the grid shows a thumbnail: open it, so the full-size image loads, and take the largest new image
            for fr in page.frames:
                t = fr.locator(f"img[src='{src}']")
                if t.count():
                    t.first.click(timeout=4000); page.wait_for_timeout(5000); break
        except Exception:
            pass
        new = {k: a for k, a in _flow_frames_imgs(page).items() if k not in before}
        if new: src = max(new, key=new.get)
        _note(ctx, f"still found ({new.get(src, 0) // 1000} k pixels)")
        data = None
        if src.startswith("http"):
            try: data = cctx.request.get(src, timeout=120000).body()   # signed-in cookies
            except Exception: data = None
        if not _is_image(data):
            try:
                for fr in page.frames:
                    try:
                        b64 = fr.evaluate("""async (u) => { const r = await fetch(u); const b = new Uint8Array(await r.arrayBuffer());
                            let s = ''; for (let i = 0; i < b.length; i += 32768) s += String.fromCharCode.apply(null, b.subarray(i, i + 32768));
                            return btoa(s); }""", src)
                        data = base64.b64decode(b64)
                        if _is_image(data): break
                    except Exception:
                        continue
            except Exception:
                data = None
        if not _is_image(data):
            _gen_fail(ctx, "flow", evidence, f"still download ({src[:80]})")
        _note(ctx, f"still {len(data) // 1024} KB")
        return _save(data, "r14_flow_image.jpg")
    finally:
        cctx.close()
        pw.stop()


# ------------------------------------------------------------------ local/GPU
WANGP_DIR = Path(os.environ.get("WANGP_DIR") or "C:/pinokio/api/wan.git") / "app"   # where wgp.py lives; the Pinokio app is not used


def _wangp_urls():
    """A WanGP MCP server someone already started (usual ports). No Pinokio lookup: the route starts its own if none."""
    return ["http://127.0.0.1:8000/mcp", "http://127.0.0.1:42004/mcp"]


def _wangp_start(ctx, limit=300):
    """Start WanGP's MCP server directly (python wgp.py --mcp) on a free port. -> (process, url). Raises Blocker."""
    import socket
    py = WANGP_DIR / "env" / "Scripts" / "python.exe"
    if not py.is_file():
        py = WANGP_DIR / "env" / "bin" / "python"
    if not (WANGP_DIR / "wgp.py").is_file() or not py.is_file():
        raise Blocker(f"WanGP is not installed at {WANGP_DIR} (set WANGP_DIR to the folder that holds wgp.py)")
    with socket.socket() as so:
        so.bind(("127.0.0.1", 0)); port = so.getsockname()[1]
    env = dict(os.environ)
    venv = WANGP_DIR / "env"
    env["PATH"] = os.pathsep.join(str(x) for x in (venv / "Scripts", venv / "Library" / "bin", venv / "bin")) + os.pathsep + env.get("PATH", "")
    env["VIRTUAL_ENV"] = str(venv); env.pop("PYTHONHOME", None); env["PYTHONUNBUFFERED"] = "1"
    # WanGP's FastMCP (mcp 1.10) rejects host/port in run() and silently falls back to 127.0.0.1:8000, ignoring --mcp-port;
    # its settings do read FASTMCP_HOST / FASTMCP_PORT
    env["FASTMCP_HOST"], env["FASTMCP_PORT"] = "127.0.0.1", str(port)
    logf = OUT / "wangp_on_demand.log"; OUT.mkdir(parents=True, exist_ok=True)
    flags = (getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)) if os.name == "nt" else 0
    p = subprocess.Popen([str(py), "wgp.py", "--mcp", "--mcp-transport", "streamable-http", "--mcp-host", "127.0.0.1",
                          "--mcp-port", str(port)], cwd=str(WANGP_DIR), env=env, stdout=open(logf, "a", encoding="utf-8"),
                         stderr=subprocess.STDOUT, creationflags=flags)
    url, t0 = f"http://127.0.0.1:{port}/mcp", time.time()
    while time.time() - t0 < limit:
        if p.poll() is not None:
            raise Blocker(f"WanGP exited while starting (code {p.returncode}); see output/{logf.name}")
        try:
            c = _WanMCP(url); c.init()
            _note(ctx, f"started WanGP on demand (MCP port {port}, ready in {time.time() - t0:.0f}s)")
            return p, c
        except Exception:
            time.sleep(3)
    _wangp_stop(p)
    raise Blocker(f"WanGP did not answer within {limit}s of starting; see output/{logf.name}")


def _wangp_stop(p):
    """Stop the WanGP this route started: unloads every model and frees the VRAM."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True, timeout=30)
        else:
            p.kill()
        p.wait(timeout=30)
    except Exception:
        pass


class _WanMCP:
    """Minimal WanGP MCP client (streamable HTTP), same calls as the studio's wangp.py: initialize -> wangp_generate ->
    poll wangp_get_job."""
    def __init__(self, url):
        self.url, self.sid = url, None

    def _post(self, body, timeout=120):
        h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if self.sid:
            h["mcp-session-id"] = self.sid
        r = requests.post(self.url, headers=h, data=json.dumps(body), timeout=(5, timeout))
        if r.headers.get("mcp-session-id"):
            self.sid = r.headers["mcp-session-id"]
        return r

    def init(self):
        r = self._post({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26",
                        "capabilities": {}, "clientInfo": {"name": "media-poc", "version": "1"}}}, timeout=6)
        if r.status_code >= 400 or not (r.headers.get("mcp-session-id") or "jsonrpc" in r.text):
            raise RuntimeError(f"HTTP {r.status_code}")
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def call(self, name, args):
        r = self._post({"jsonrpc": "2.0", "id": int(time.time() * 1000), "method": "tools/call",
                        "params": {"name": name, "arguments": args}})
        data = [l[6:] for l in r.text.splitlines() if l.startswith("data: ")]
        j = json.loads(data[-1] if data else r.text)
        res = j.get("result") or {}
        if "structuredContent" in res:
            return res["structuredContent"]
        if res.get("isError"):
            return {"error": (res.get("content") or [{}])[0].get("text", "error")}
        return res if "error" not in j else {"error": str(j["error"])}


def r9_wangp(desc, aspect, image_path, ctx):
    """One WanGP still (the studio's rung 6 settings: flux2_klein_9b, 4 steps) over WanGP's MCP server. Starts WanGP
    directly (no Pinokio) when none is running and stops it as soon as the still is saved."""
    wg, own = None, None
    for url in _wangp_urls():                    # one already running (started by hand): use it, leave it running
        try:
            c = _WanMCP(url); c.init(); wg = c; break
        except Exception:
            continue
    if wg is None:                                # usual case: start WanGP's MCP server for this one still, stop it after
        own, wg = _wangp_start(ctx)
    else:
        _note(ctx, f"using the WanGP already running at {wg.url} (left running)")
    try:
        res = {"16:9": "1920x1088", "9:16": "1088x1920", "1:1": "1024x1024"}.get(aspect, "1920x1088")
        src = {"model_type": "flux2_klein_9b", "prompt": _prompt(desc, "photorealistic, no text"), "resolution": res,
               "num_inference_steps": 4, "seed": 1001}
        t0 = time.time()
        while True:                               # WanGP runs one job at a time: wait for a busy queue (max 10 min)
            r = wg.call("wangp_generate", {"source": src, "wait": False})
            if r.get("job_id"):
                break
            if "in progress" in str(r) and time.time() - t0 < 600:
                time.sleep(15); continue
            raise Blocker(f"WanGP refused the job: {str(r)[:300]}")
        jid, t0 = r["job_id"], time.time()
        while time.time() - t0 < 900:             # first run loads the model from disk: allow 15 min
            time.sleep(5)
            j = wg.call("wangp_get_job", {"job_id": jid, "event_limit": 1})
            if not j.get("done"):
                continue
            result = j.get("result") or {}
            files = result.get("generated_files") or []
            if not (result.get("success") and files):
                raise Blocker(f"WanGP job {jid} failed: {json.dumps(result.get('errors'))[:300]}")
            f = Path(files[0])
            data = f.read_bytes()
            if not _is_image(data):
                raise Blocker(f"WanGP returned {f.name}, which is not an image")
            _note(ctx, f"generated in {time.time() - t0:.0f}s ({src['model_type']}, {res})")
            return _save(data, "r9_wangp_still" + (f.suffix.lower() or ".png"))
        wg.call("wangp_cancel_job", {"job_id": jid})
        raise Blocker(f"WanGP job {jid} did not finish within 15 min (cancelled)")
    finally:
        if own is not None:
            _wangp_stop(own)
            _note(ctx, "WanGP stopped; models unloaded, VRAM freed")


def r10_marble_video(desc, aspect, image_path, ctx):
    """World Labs Marble: ONE attempt only — no retry loops (few free generations)."""
    pw, cctx, page, prefs = _browser("marble")
    ctx["_page"] = page
    try:
        _note(ctx, f"prefs: {prefs}")
        _goto(page, HOME_URLS["marble"])
        page.wait_for_timeout(6000)
        state, evidence = _signin_state(page, "marble")
        _note(ctx, f"signin={state}; evidence: {evidence}")
        if state == "login_wall":
            _not_signed_in("marble")
        if state == "unknown":
            _blocker_unknown("marble", page, ctx, "r10", state, evidence)
        try:
            page.locator("button[aria-label='Close'], :text('X')").first.click(timeout=2500)   # ToS popup
        except Exception:
            pass
        box = _pick(page, ["input[placeholder*='world']", "input[placeholder*='Imagine']", "textarea", "[contenteditable='true']"])
        try:
            _type_like_human(page, box, desc)             # single submit — no retries
        except Exception:
            _gen_fail(ctx, "marble", evidence, "world prompt box not usable")
        try:
            page.wait_for_selector("canvas", timeout=300000)
            page.wait_for_timeout(8000)                   # let the world settle
        except Exception:
            _gen_fail(ctx, "marble", evidence, "world did not load within 300s")
        # hide all page chrome so only the 3D view shows, then record a slow walk-forward
        try:
            page.evaluate("""() => {
              const keep = new Set();
              document.querySelectorAll('canvas').forEach(c => { let e = c; while (e) { keep.add(e); e = e.parentElement; } });
              document.querySelectorAll('body *').forEach(e => {
                if (keep.has(e) || e.tagName === 'CANVAS' || e.closest('canvas')) return;
                e.style.setProperty('visibility', 'hidden', 'important');
              });
            }""")
        except Exception:
            pass
        vid = page.screenshot(path=str(OUT / "r10_marble_world.png"))   # world state evidence
        # page-video recording: reopen the same world URL with recording enabled is not
        # possible in the same context; record the live page via CDP screencast is out of
        # scope for this first pass — deliver the world state PNG as this attempt's output
        # and a precise note that mp4 recording lands in the next pass.
        _note(ctx, "first-generation pass: world loaded; walk-forward mp4 recording lands in a "
                   "follow-up pass (world state PNG saved)")
        return OUT / "r10_marble_world.png"
    finally:
        cctx.close()
        pw.stop()


# ------------------------------------------------------------------ local/GPU (blender over MCP)
def r11_blender_video(desc, aspect, image_path, ctx):
    """Blender driven ONLY through MCP (mcp-for-blender, safe mode on): the description is planned by
    a local model, the scene is built in a live Blender from Poly Haven assets, Cycles renders on the
    GPU, Blender is closed afterwards. Quality: env BLENDER_QUALITY=preview|final (default preview)."""
    from .blender_mcp import pipeline
    quality = os.environ.get("BLENDER_QUALITY", "preview")
    work = OUT / "r11_blender"
    try:
        job = pipeline.render(desc, aspect, work, quality=quality, duration_s=4, log=lambda m: None)
    except pipeline.Blocked as b:
        raise Blocker(str(b))
    out_mp4 = OUT / "r11_blender_video.mp4"
    shutil.copyfile(job["video"], out_mp4)
    plan = job.get("plan") or {}
    _note(ctx, f"MCP route ({quality}, {aspect}); plan '{plan.get('title', '')}', camera "
               f"{(plan.get('camera') or {}).get('move', '?')}; sky {job['assets'].get('sky')}, "
               f"ground {job['assets'].get('ground')}, models {', '.join(job['assets']['objects'].values()) or 'none'}")
    if job["status"] == "partial":
        _note(ctx, "PARTIAL - no photoreal model for: " + ", ".join(job["missing"]))
    _note(ctx, f"GPU memory peak {job.get('vram_peak_mb', '?')} MB (whole card), "
               f"after Blender closed {job.get('vram_after_mb', '?')} MB; log output/r11_blender/r11.log")
    return out_mp4


# ------------------------------------------------------------------ describe -> Meta image -> Meta video (Tariq, 2026-11-06)
# For a beat whose source has no public media: a snapshot of the source video is described by Copilot (Bing's chat), Meta
# makes an image from that description and then animates THAT image in the same conversation. Never for a known person
# (owner, 2026-11-07: nobody is anonymised; the screen layout is never rebuilt - see studio/people.py).
DESCRIBE_COPILOT = ("Describe this image so I can recreate it with an AI image generator. Describe people as they look (age, hair, "
                    "clothing, expression, what they are doing). Ignore the screen layout: no split screens, video-call panels, "
                    "picture-in-picture boxes, lower thirds or studio graphics - describe ONE real-world scene with the main person. "
                    "Cover the setting, objects, lighting, colours, camera angle and framing. No brands, logos or text. "
                    "Put the final prompt on its own line starting with PROMPT:")
_COPILOT_MSGS = "[data-content='ai-message'], [class*='ai-message'], div[role='article'], [data-testid*='message']"


def _copilot_answer(page, before_n, timeout_s=150):
    """Wait for Copilot's reply to stop growing and carry a PROMPT: line. -> the reply text. Read from the page text AFTER our
    own message (Copilot's element names change; our instruction itself also contains "PROMPT:")."""
    tail = DESCRIBE_COPILOT[-60:]
    last, stable, t0 = "", 0, time.time()
    while time.time() - t0 < timeout_s:
        page.wait_for_timeout(2500)
        try:
            body = page.locator("main").first.inner_text() if page.locator("main").count() else page.locator("body").inner_text()
        except Exception:
            body = ""
        txt = body.split(tail)[-1] if tail in body else ""
        if txt and txt == last:
            stable += 1
            if stable >= 2 and re.search(r"PROMPT:\s*\S", txt, re.I):
                return txt
        else:
            stable = 0
        last = txt
    return last


def r12_copilot_describe(desc, aspect, image_path, ctx):
    """Copilot (signed-in Microsoft profile) describes an image -> a recreate prompt (saved as text). Needs --image."""
    if not image_path or not Path(image_path).is_file():
        raise Blocker("needs an image to describe (upload one, or the studio passes the source snapshot)")
    pw, cctx, page, prefs = _browser("copilot")
    ctx["_page"] = page
    try:
        _goto(page, HOME_URLS["copilot"]); page.wait_for_timeout(6000)
        if not _visible(page, "textarea, [contenteditable='true']", 1500):
            # signed out of Copilot itself but signed in to Microsoft: Copilot's own Sign In finishes through that session
            # (no credentials are ever typed here)
            try:
                page.get_by_role("button", name="Sign In").first.click(timeout=5000); page.wait_for_timeout(10000)
                _note(ctx, "Copilot Sign In clicked (Microsoft session)")
            except Exception:
                pass
        _dismiss_popups(page, ctx)
        state, evidence = _signin_state(page, "copilot")
        _note(ctx, f"signin={state}; evidence: {evidence}")
        if state == "login_wall":
            _not_signed_in("copilot")
        if state == "unknown":
            raise Blocker("Copilot is not signed in on profiles/copilot: use OPEN LOGIN (copilot), sign in, close the window, RUN again")
        before_n = page.locator(_COPILOT_MSGS).count()
        def _consent(wait_ms=800):
            # Copilot's image consent ("you confirm that you have the permission of any people in the images"): Tariq approved
            # clicking "Confirm and continue" for this route, always (2026-11-06). Never "Not now"; nothing else is accepted here.
            try:
                b = page.locator("button:has-text('Confirm and continue')").first
                b.wait_for(state="visible", timeout=wait_ms)
                b.click(timeout=3000); page.wait_for_timeout(1500); _note(ctx, "Copilot image consent confirmed (approved by Tariq)")
            except Exception:
                pass
        _consent()
        try:
            page.set_input_files("input[type='file']", image_path, timeout=8000)
        except Exception:
            try:
                page.locator("button[aria-label*='Upload' i], button[aria-label*='Add' i], button[title*='Upload' i]").first.click(timeout=4000)
                page.wait_for_timeout(1000)
                page.set_input_files("input[type='file']", image_path, timeout=8000)
            except Exception:
                _gen_fail(ctx, "copilot", evidence, "no way to attach the image")
        _consent(6000)   # the box appears a moment after the image is attached
        page.wait_for_timeout(2000)
        _consent(1500)
        box = _pick(page, ["#m365-chat-editor-target-element", "[contenteditable='true'][aria-label*='Message' i]", "textarea", "[contenteditable='true']"])
        try:
            box.click(); page.keyboard.insert_text(DESCRIBE_COPILOT); page.wait_for_timeout(1500)
        except Exception:
            _gen_fail(ctx, "copilot", evidence, "prompt box not usable")
        # Enter alone left the message in the box (Nov 6): click the send arrow, retrying while the image is still uploading
        sent = False
        for _try in range(10):
            _consent()
            for sel in ("button[aria-label='Send']", "button[type='submit'][aria-label*='Send' i]", "button[aria-label*='Send' i]",
                        "button[data-testid*='submit' i]"):
                try:
                    b = page.locator(sel).last
                    if b.is_visible(timeout=500) and b.is_enabled():
                        b.click(timeout=3000); break
                except Exception:
                    continue
            else:
                page.keyboard.press("Enter")
            page.wait_for_timeout(2000)
            try:
                left = box.inner_text() if box.evaluate("e => !('value' in e)") else box.input_value()
            except Exception:
                left = ""
            if "PROMPT:" not in (left or ""):
                sent = True; break
            human_check = any(fr.locator("text=/verify you are human|verification required/i").count() for fr in page.frames)
            if human_check:
                # a CAPTCHA: never clicked by the POC (same rule as Cloudflare checks)
                raise Blocker("Copilot shows 'Verification required - Verify you are human' on automated sends (never clicked "
                              "by the POC). Use OPEN LOGIN (copilot) and tick it yourself; the studio falls back to Meta describing")
        if not sent:
            _gen_fail(ctx, "copilot", evidence, "message typed but not sent")
        txt = _copilot_answer(page, before_n)
        m = re.search(r"PROMPT:\s*(.+)", txt or "", re.I | re.S)
        prompt = re.sub(r"\s+", " ", (m.group(1) if m else txt or "")).strip(" *\"")[:1500]
        if len(prompt.split()) < 12:
            _gen_fail(ctx, "copilot", evidence, f"no usable description (got: {prompt[:120]!r})")
        _note(ctx, f"described: {prompt[:160]}")
        return _save(prompt.encode("utf-8"), "r12_copilot_describe.txt")
    finally:
        cctx.close()
        pw.stop()


def r13_meta_chain(desc, aspect, image_path, ctx):
    """meta.ai, ONE conversation: make an image from the description, then animate that image. -> the video (the image is
    saved too as output/r13_meta_chain.jpg). `desc` is the description (from r12 / the studio)."""
    pw, cctx, page, prefs = _browser("meta")
    ctx["_page"] = page
    try:
        _goto(page, HOME_URLS["meta"]); page.wait_for_timeout(4000)
        state, evidence = _signin_state(page, "meta")
        _note(ctx, f"signin={state}; evidence: {evidence}")
        if state == "login_wall":
            _not_signed_in("meta")
        if state == "unknown":
            _blocker_unknown("meta", page, ctx, "r13", state, evidence)
        if image_path and Path(image_path).is_file() and desc.strip().lower() in ("", "describe"):
            # fallback describer (Copilot blocked by its human check): Meta describes the snapshot first, in this same chat
            box = _pick(page, ["textarea[placeholder*='Ask Meta']", "div[contenteditable='true']"])
            try:
                box.first.click()
                page.set_input_files("input[type='file']", image_path, timeout=8000); page.wait_for_timeout(4000)
                # with an image attached the "Ask Meta" placeholder is gone: find the editor again
                box = _pick(page, ["div[contenteditable='true']", "textarea", "[role='textbox']"])
                _type_like_human(page, box, DESCRIBE_COPILOT)
            except Exception:
                _gen_fail(ctx, "meta", evidence, "could not attach the snapshot to describe")
            tail, txt, t0 = DESCRIBE_COPILOT[-60:], "", time.time()
            while time.time() - t0 < 150:
                page.wait_for_timeout(4000)
                body = page.locator("body").inner_text()
                after = body.split(tail)[-1] if tail in body else ""
                m = re.search(r"PROMPT:\s*\**\s*(.+)", after, re.I)
                if m and len(m.group(1).split()) >= 12 and after == txt:
                    break
                txt = after
            m = re.search(r"PROMPT:\s*\**\s*(.+)", txt, re.I)
            desc = re.sub(r"\s+", " ", m.group(1)).strip(" *\"") if m else ""
            if len(desc.split()) < 12:
                _gen_fail(ctx, "meta", evidence, "Meta gave no usable description of the snapshot")
            _note(ctx, f"described by Meta: {desc[:160]}")
            OUT.mkdir(parents=True, exist_ok=True); (OUT / "r13_meta_chain.prompt.txt").write_text(desc, encoding="utf-8")
        imgs0 = _img_srcs(page)
        box = _pick(page, ["textarea[placeholder*='Ask Meta']", "div[contenteditable='true']"])
        try:
            from .. import people   # a person in the snapshot is a real person: a sketch, never a photo-real look-alike (owner, 2026-11-07)
            real_person = people.shows_person(desc) and "sketch" not in desc.lower()
            drawn = real_person or "sketch" in desc.lower()   # the still will be a drawing: the animation must keep it one
            _type_like_human(page, box, "Imagine: " + (_prompt(desc + " " + people.SNAP_RULE, "no text") if real_person
                                                       else _prompt(desc, "photorealistic, no text")))
        except Exception:
            _gen_fail(ctx, "meta", evidence, "prompt box not usable")
        img_data, t0 = None, time.time()
        while time.time() - t0 < 180 and not img_data:   # step 1: the image
            page.wait_for_timeout(5000)
            for s in [x for x in _img_srcs(page) if x not in imgs0 and x.startswith("http")]:
                try:
                    d = cctx.request.get(s, timeout=60000).body()
                except Exception:
                    continue
                if _is_image(d) and len(d) > 30000:
                    img_data = d; break
        if not img_data:
            _gen_fail(ctx, "meta", evidence, "no image within 180s")
        _save(img_data, "r13_meta_chain.jpg")
        _note(ctx, f"image made in {time.time() - t0:.0f}s")
        vids0 = set(page.evaluate("() => [...document.querySelectorAll('video')].map(v => v.currentSrc || v.src).filter(Boolean)"))
        try:                                         # step 2: animate THAT image, same conversation
            box = _pick(page, ["textarea[placeholder*='Ask Meta']", "div[contenteditable='true']"])
            _type_like_human(page, box, "Animate this image with a slow cinematic camera move. People stay still with their mouths closed: no talking, no lip movement. Keep everything else exactly the same."
                             + (" " + people.KEEP_DRAWN if drawn else ""))
        except Exception:
            _gen_fail(ctx, "meta", evidence, "follow-up box not usable")
        data, t0 = None, time.time()
        while time.time() - t0 < 300 and not data:
            page.wait_for_timeout(8000)
            srcs = page.evaluate("() => [...document.querySelectorAll('video')].map(v => v.currentSrc || v.src).filter(Boolean)")
            for s in [x for x in srcs if x not in vids0 and x.startswith("http")]:
                try:
                    d = cctx.request.get(s, timeout=120000).body()
                except Exception:
                    continue
                if _is_video(d):
                    data = d; break
        if not data:
            _gen_fail(ctx, "meta", evidence, "image made, but no video within 300s")
        _note(ctx, f"video made in {time.time() - t0:.0f}s (image-to-video, same chat)")
        return _save(data, "r13_meta_chain.mp4")
    finally:
        cctx.close()
        pw.stop()


# ------------------------------------------------------------------ registry
ROUTES = [
    {"id": "r1", "name": "cloudflare-flux", "proves": "Cloudflare Workers AI REST image (FLUX.1-schnell)", "fn": r1_cloudflare_flux},
    {"id": "r2", "name": "hf-flux", "proves": "Hugging Face FLUX.1-schnell via gradio_client (free; HF_TOKEN raises quota)", "fn": r2_hf_flux},
    {"id": "r3", "name": "meta-describe", "proves": "meta.ai describe: image -> description + image prompt (via meta.ai profile - DeepSeek removed from the POC)", "fn": r3_meta_describe, "needs_image": True},
    {"id": "r4", "name": "chatgpt-image", "proves": "ChatGPT browser profile image generation (paid account)", "fn": r4_chatgpt_image},
    {"id": "r5", "name": "bing-image", "proves": "Bing Image Creator browser profile", "fn": r5_bing_image},
    {"id": "r6", "name": "meta-image", "proves": "meta.ai image generation (NEW provider, defensive selectors)", "fn": r6_meta_image},
    {"id": "r7", "name": "meta-video", "proves": "meta.ai image-to-video (uses R6/uploaded image)", "fn": r7_meta_video, "needs_image": True},
    {"id": "r8", "name": "flow-video", "proves": "Google Flow prompt -> short video", "fn": r8_flow_video},
    {"id": "r9", "name": "wangp", "proves": "local WanGP still -> image-to-video (incumbent baseline)", "fn": r9_wangp},
    {"id": "r10", "name": "marble-video", "proves": "World Labs Marble world -> recorded walk mp4. WARNING: uses one of the few free generations", "fn": r10_marble_video},
    {"id": "r11", "name": "blender-video", "proves": "Blender over MCP (safe mode): text -> plan -> Poly Haven scene -> Cycles GPU -> mp4; Blender closed after", "fn": r11_blender_video},
    {"id": "r12", "name": "copilot-describe", "proves": "Copilot (Bing chat) describes an image -> recreate prompt, people kept anonymous", "fn": r12_copilot_describe, "needs_image": True},
    {"id": "r13", "name": "meta-chain", "proves": "meta.ai one chat: image from the description, then animate that image -> video", "fn": r13_meta_chain},
    {"id": "r14", "name": "flow-image", "proves": "Google Flow agent -> one still, approved only at 0 credits", "fn": r14_flow_image},
]

assert len(ROUTES) == 14