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
OUT = ROOT / "output"
SECRETS = ROOT / "secrets"
PROFILES = ROOT / "profiles"

HOME_URLS = {
    "chatgpt": "https://chatgpt.com/",
    "bing": "https://www.bing.com/images/create",
    "meta": "https://meta.ai/",
    "flow": "https://flow.google.com/",
    "marble": "https://marble.worldlabs.ai/",
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
    args = ["--lang=en-US", "--hide-crash-restore-bubble", "--no-default-browser-check",   # Z007 §D: no Restore bubble, no "set as default" popup
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
        box = _pick(page, ["#prompt-textarea", "[placeholder*='Ask ChatGPT']", "textarea[data-id='root']", "div[contenteditable='true']"])
        before = _img_srcs(page)
        start_url = page.url
        _dismiss_popups(page, ctx)
        try:
            box.first.click()
            page.keyboard.press("Control+A")      # ChatGPT keeps an unsent draft: clear it so only this prompt goes out
            page.keyboard.press("Backspace")
            _type_like_human(page, box, "Create an image: " + _prompt(desc, "photorealistic, no text"), submit=False)
        except Exception:
            _gen_fail(ctx, "chatgpt", evidence, "prompt box not usable")
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
    if not src:
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
        prompt = "Animate this image with a slow cinematic camera push-in. " + desc
        try:
            box.first.click()
            # attach the source image if the composer offers a file input, else describe it
            try:
                page.set_input_files("input[type='file']", src, timeout=4000)
                page.wait_for_timeout(4000)
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
        return _save(requests.get(vidsrc, timeout=120).content, "r7_meta_video.mp4")
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
        if still:
            for sel in ("button[aria-label='Start generation']", "button[aria-label*='Send' i]", "button[aria-label*='Submit' i]", "button:has-text('arrow_forward')",
                        "button:has(i:text('arrow_forward'))", "button[type='submit']"):
                try:
                    b = box_frame.locator(sel).last
                    if b.is_visible(timeout=600):
                        b.click(timeout=4000); _note(ctx, f"sent with {sel}"); break
                except Exception:
                    continue
            page.wait_for_timeout(1500)
            try:
                still = (box.input_value() if box.evaluate("e => 'value' in e") else box.inner_text()).strip()
            except Exception:
                still = ""
            if still:
                _gen_fail(ctx, "flow", evidence, "prompt typed but not sent")
        _note(ctx, "prompt sent")
        t0, vidsrc = time.time(), ""
        while time.time() - t0 < 480 and not vidsrc:          # Flow queues at busy times
            page.wait_for_timeout(15000)
            new = [s for s in _videos() if s not in before]
            vidsrc = new[0] if new else ""
        if not vidsrc:
            _gen_fail(ctx, "flow", evidence, "no generated clip within 480s")
        data = None
        if vidsrc.startswith("http"):
            try:
                data = requests.get(vidsrc, timeout=180).content
            except Exception:
                data = None
        if not data or len(data) < 50000:                     # signed/blob links: fetch inside the browser
            try:
                b64 = page.evaluate("""async (u) => { const r = await fetch(u); const b = new Uint8Array(await r.arrayBuffer());
                    let s = ''; for (let i = 0; i < b.length; i += 32768) s += String.fromCharCode.apply(null, b.subarray(i, i + 32768));
                    return btoa(s); }""", vidsrc)
                data = base64.b64decode(b64)
            except Exception:
                data = None
        if not data or len(data) < 50000:
            _gen_fail(ctx, "flow", evidence, f"video download ({vidsrc[:80]})")
        return _save(data, "r8_flow_video.mp4")
    finally:
        cctx.close()
        pw.stop()


# ------------------------------------------------------------------ local/GPU
def _wangp_urls():
    """Same discovery order as the studio's wangp client: setting -> Pinokio log -> usual ports."""
    urls = []
    logdir = Path("C:/pinokio/api/wan.git/logs/api/start.js")
    for name in ("latest", "events"):
        try:
            txt = (logdir / name).read_text(encoding="utf-8", errors="ignore")[-200000:]
        except Exception:
            continue
        for m in re.findall(r"Uvicorn running on (http://[0-9.]+:\d+)", txt):
            urls.append(m.rstrip("/") + "/mcp")
        for m in re.findall(r'"mcp_url":\s*"(http://[0-9.]+:\d+/mcp/?)"', txt):
            urls.append(m.rstrip("/") + "/mcp")
    urls += ["http://127.0.0.1:8000/mcp", "http://127.0.0.1:42004/mcp"]
    return list(dict.fromkeys(urls))


def r9_wangp(desc, aspect, image_path, ctx):
    import socket
    for url in _wangp_urls():
        host_port = url.split("//")[1].split("/")[0]
        host, _, port = host_port.partition(":")
        try:
            with socket.create_connection((host, int(port)), timeout=2):
                pass
        except Exception:
            continue
        raise Blocker(f"WanGP MCP found at {url} but the still+i2v MCP calls are not wired in this "
                      f"POC build; endpoint pattern proven (see wangp.py reference)")
    raise Blocker("WanGP not reachable (probed Pinokio log URLs + ports 8000/42004; "
                  "start it in Pinokio to use this route)")


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
    from blender_mcp import pipeline
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
]

assert len(ROUTES) == 11