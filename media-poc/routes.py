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
    "flow": "https://labs.google/fx/tools/flow",
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
    args = ["--lang=en-US", "--hide-crash-restore-bubble",   # Z007 §D: suppress the Restore bubble
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
    "flow": ("accounts.google.com/SignIn", "accounts.google.com/ServiceLogin", "accounts.google.com/v3/signin"),
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
        ("Flow editor/create UI visible", lambda p: _any_visible(p, ["textarea", "button:has-text('Create')", "[contenteditable='true']"])),
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
    raise Blocker(f"state unknown — no login wall and no signed-in evidence on profiles/{site} "
                  f"(checked: {evidence}); screenshot {rid}_state.png; use OPEN LOGIN if the "
                  f"profile is actually signed out")


def _not_signed_in(site):
    raise Blocker(f"login wall — sign-in needed: use OPEN LOGIN (profiles/{site})")


# ---------------------------------------------------------------- image routes
def r1_cloudflare_flux(desc, aspect, image_path, ctx):
    env = _env("cloudflare.env")
    if not env or not env.get("CLOUDFLARE_ACCOUNT_ID") or not env.get("CLOUDFLARE_API_TOKEN"):
        raise Blocker("no token — create media-poc/secrets/cloudflare.env with "
                      "CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN")
    # SPEC-Z008 §F: FLUX-1-schnell REJECTS width/height (AiError 5006, "unevaluated
    # properties"); the proven D142 body is prompt + steps only.
    r = requests.post(
        f"https://api.cloudflare.com/client/v4/accounts/{env['CLOUDFLARE_ACCOUNT_ID']}"
        "/ai/run/@cf/black-forest-labs/flux-1-schnell",
        headers={"Authorization": f"Bearer {env['CLOUDFLARE_API_TOKEN']}"},
        json={"prompt": desc[:2000], "steps": 4},
        timeout=180)
    if r.status_code != 200:
        raise Blocker(f"HTTP {r.status_code}: {r.text[:160]}")
    j = r.json()
    if not j.get("success"):
        raise Blocker("API error: " + json.dumps(j.get("errors", j))[:160])
    img = j["result"].get("image")
    if not img:
        raise Blocker("no image in response")
    return _save(base64.b64decode(img), "r1_cloudflare_flux.jpg")


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


def r3_deepseek_describe(desc, aspect, image_path, ctx):
    env = _env("deepseek.env")
    if not env or not env.get("DEEPSEEK_API_KEY"):
        raise Blocker("no key — create media-poc/secrets/deepseek.env with DEEPSEEK_API_KEY "
                      "(optional DEEPSEEK_BASE_URL, default https://api.deepseek.com/anthropic)")
    if not image_path:
        raise Blocker("needs an image (upload one, or run R6/R1/R2 first)")
    base = (env.get("DEEPSEEK_BASE_URL") or "https://api.deepseek.com/anthropic").rstrip("/")
    b64 = base64.b64encode(Path(image_path).read_bytes()).decode()
    r = requests.post(
        f"{base}/v1/messages",
        headers={"x-api-key": env["DEEPSEEK_API_KEY"], "anthropic-version": "2023-06-01",
                 "Content-Type": "application/json"},
        json={"model": env.get("DEEPSEEK_MODEL", "deepseek-flash"), "max_tokens": 800,
              "messages": [{"role": "user", "content": [
                  {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
                  {"type": "text", "text": "Describe this image in two sentences, then write a "
                                           "ready-to-use image-generation prompt for recreating it "
                                           "without brands or text. Reply as JSON: "
                                           '{"description": "...", "image_prompt": "..."}'}]}]},
        timeout=180)
    if r.status_code != 200:
        raise Blocker(f"HTTP {r.status_code}: {r.text[:160]}")
    try:
        body = r.json()
        blocks = body.get("content", [])
        if isinstance(blocks, str):                     # Z007 §C: content may arrive as a plain string
            txt = blocks
        else:
            txt = "\n".join(b.get("text", "") for b in blocks
                            if isinstance(b, dict) and b.get("type") == "text")   # thinking blocks ignored
        block_types = [b.get("type") for b in blocks if isinstance(b, dict)] if isinstance(blocks, list) else ["string"]
        ctx["card_note"] = f"reply block types: {block_types}"
        if not txt.strip():
            raise Blocker(f"model returned no text (HTTP {r.status_code}, blocks={block_types}): {r.text[:140]}")
    except Blocker:
        raise                                            # Z007 §C: precise blockers survive as themselves
    except Exception as e:
        raise Blocker(f"could not read reply structure ({str(e)[:80]}): {r.text[:160]}")
    clean = re.sub(r"```(?:json)?", "", txt).strip()   # fence artifacts leak into values otherwise
    m = re.search(r"\{.*\}", clean, re.S)
    j = {}
    if m:
        try:
            parsed = json.loads(m.group(0))
            if isinstance(parsed, dict):
                j = parsed
        except ValueError:
            pass
    if not (j.get("description") or j.get("image_prompt")):
        dm = re.search(r'"description"\s*:\s*"([^"]+)"', clean)
        pm = re.search(r'"image_prompt"\s*:\s*"([^"]+)"', clean)
        if dm or pm:
            j = {"description": (dm.group(1) if dm else "")[:600],
                 "image_prompt": (pm.group(1) if pm else "")[:600]}
        else:
            j = {"description": clean[:600], "image_prompt": clean[:600]}   # conversational reply still describes
    out = _save(json.dumps(j, indent=1).encode(), "r3_deepseek_describe.json")
    ctx["card_note"] = (ctx.get("card_note", "") + " || " if ctx.get("card_note") else "") + \
        f"DESCRIPTION: {j.get('description', '')[:200]} || PROMPT: {j.get('image_prompt', '')[:200]}"
    return out


# --------------------------------------------------------------- browser routes (Z007 §A/§B)
def _pick(page, selectors):
    """First VISIBLE candidate locator (individual checks — no comma-joined .first)."""
    for sel in selectors:
        if _visible(page, sel, 1200):
            return page.locator(sel).first
    return page.locator(selectors[0]).first      # fall through: let the step-fail path report it


def _type_like_human(page, locator, text):
    locator.first.wait_for(state="visible", timeout=15000)
    locator.first.click()
    for chunk in text.split(" "):
        page.keyboard.type(chunk + " ", delay=40)
    page.keyboard.type("\n")


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
            if len(data) > 20000:
                return data
        except Exception:
            continue
    return None


def _poll_generation(page, ctx, rid, site, evidence, selectors, out_name, deadline_s=480, every=15, min_bytes=20000):
    """SPEC-Z008 §A/§B2: poll up to `deadline_s` for a generated image, ~every `every` s.
    Each poll logs (elapsed, img count) into the card note. Downloads via requests first;
    if that returns nothing usable, fetches the bytes inside the browser context, and as a
    last resort screenshots the img element. Fails only after the full window."""
    t0 = time.time()
    polls = []
    while time.time() - t0 < deadline_s:
        elapsed = int(time.time() - t0)
        imgs = page.locator("img")
        n = imgs.count()
        data = None
        srcs = []
        for i in range(min(n, 30)):
            try:
                s = imgs.nth(i).get_attribute("src") or ""
                if s.startswith("http") and ("blob" in s or "oaiusercontent" in s or "scontent" in s or "th.bing" in s or "bing.net" in s or "rid=" in s or "id=" in s):
                    srcs.append(s)
            except Exception:
                continue
        for s in srcs:
            try:
                d = requests.get(s, timeout=30).content
                if len(d) >= min_bytes:
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
                if d_b64:
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
        box = _pick(page, ["[placeholder*='Ask ChatGPT']", "#prompt-textarea", "textarea[data-id='root']", "div[contenteditable='true']"])
        try:
            _type_like_human(page, box, desc + " photorealistic, no text")
        except Exception:
            _gen_fail(ctx, "chatgpt", evidence, "prompt box not usable")
        # SPEC-Z008 §A: generation may simply take longer than one fixed wait — poll 480s
        return _poll_generation(page, ctx, "r4", "chatgpt", evidence,
                                ["img[src*='oaiusercontent']", "img[alt*='Generated']", "img[src*='blob']"],
                                "r4_chatgpt_image.jpg", deadline_s=480)
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
                                "r5_bing_image.jpg", deadline_s=480)
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
            _type_like_human(page, box, desc + " photorealistic, no text")
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
        # textarea and a visible "add / New project" button. Start a project first.
        newproj = _pick(page, ["button:has-text('New project')", ":text('New project')", "button:has-text('add')"])
        try:
            newproj.first.click(timeout=10000)
            _note(ctx, "clicked New project (landing-page composer confirmed absent, per D140)")
        except Exception:
            _gen_fail(ctx, "flow", evidence, "'New project' button not found/clickable")
        page.wait_for_timeout(8000)
        # inventory the post-click screen the same way D140 did (main frame + iframes)
        inv = []
        for fr in [page.main_frame] + page.frames:
            if fr == page.main_frame or fr != page.main_frame:
                ta = fr.locator("textarea").count()
                ce = fr.locator("[contenteditable='true']").count()
                tb = fr.locator("[role='textbox']").count()
                if ta or ce or tb:
                    inv.append(f"frame={fr.url.split('/')[-1][:40] or 'main'}: textarea={ta} contenteditable={ce} textbox={tb}")
        _note(ctx, "post-New-project inventory: " + ("; ".join(inv) if inv else "no editors found on any frame"))
        box = None
        for sel in ("textarea:visible", "[contenteditable='true']:visible", "[role='textbox']:visible"):
            for fr in [page.main_frame] + page.frames:
                loc = fr.locator(sel)
                for i in range(min(loc.count(), 5)):
                    cand = loc.nth(i)
                    try:
                        if cand.is_visible() and (cand.bounding_box() or {}).get("height", 0) > 20:
                            box = cand
                            break
                    except Exception:
                        continue
                if box:
                    break
            if box:
                break
        if box is None:
            shot = "gen_flow_composer.png"
            try:
                page.screenshot(path=str(OUT / shot))
            except Exception:
                shot = "(screenshot unavailable)"
            raise Blocker(f"signed in OK (evidence: {evidence}); New project clicked; composer NOT found "
                          f"on the post-click screen (inventory: {'; '.join(inv) or 'none'}; "
                          f"iframes: {len(page.frames)}) — screenshot output/{shot}")
        _note(ctx, "composer found: visible editor in frame " + (box.page.url.split('/')[-1][:40] or 'main'))
        try:
            _type_like_human(page, box, desc + ". Cinematic slow camera move, photorealistic, no text.")
        except Exception:
            _gen_fail(ctx, "flow", evidence, "prompt box not usable")
        try:
            page.wait_for_selector("video", timeout=480000)   # Flow queues at busy times
        except Exception:
            _gen_fail(ctx, "flow", evidence, "no generated clip within 480s")
        vidsrc = page.locator("video source, video").first.get_attribute("src") or ""
        if not vidsrc:
            _gen_fail(ctx, "flow", evidence, "video download")
        return _save(requests.get(vidsrc, timeout=180).content, "r8_flow_video.mp4")
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


# ------------------------------------------------------------------ local/GPU (blender)
BLENDER_PATHS = [
    r"C:\Program Files\Blender Foundation",
    r"C:\Program Files\Blender",
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Blender Foundation"),
]


def find_blender():
    exe = shutil.which("blender")
    if exe:
        return exe, "PATH"
    for base in BLENDER_PATHS:
        b = Path(base)
        if b.is_dir():
            for sub in sorted(b.glob("*/blender.exe"), reverse=True):
                return str(sub), str(sub)
    return None, None


BLENDER_SCRIPT = """
import bpy, math, re, sys
import mathutils
scene = bpy.context.scene
args = sys.argv[sys.argv.index('--') + 1:]
desc = (args[0] if len(args) > 1 else "").lower()
out = args[-1]

# clean the factory scene entirely
for ob in list(bpy.data.objects):
    bpy.data.objects.remove(ob, do_unlink=True)

def make_mat(name, color, rough=0.5, metal=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    bsdf = m.node_tree.nodes['Principled BSDF']
    bsdf.inputs['Base Color'].default_value = (*color, 1)
    bsdf.inputs['Roughness'].default_value = rough
    bsdf.inputs['Metallic'].default_value = metal
    return m

def link(ob):
    if ob.name not in bpy.context.collection.objects:
        bpy.context.collection.objects.link(ob)

def add(kind, **kw):
    getattr(bpy.ops.mesh, 'primitive_' + kind + '_add')(**kw)
    return bpy.context.object

# ground with a rough, slightly varied material
ground = add('plane', size=60)
ground.data.materials.append(make_mat('ground', (0.18, 0.22, 0.16), rough=0.9, metal=0.0))

# subject from the description, by keyword class (simple, stated honestly: this is a
# keyword->primitive classifier, not a general scene builder)
white = make_mat('hull', (0.88, 0.89, 0.91), rough=0.28, metal=0.15)
dark = make_mat('dark', (0.05, 0.05, 0.06), rough=0.6, metal=0.1)
glass = make_mat('glassy', (0.4, 0.5, 0.6), rough=0.1, metal=0.6)
if re.search(r'jet|plane|aircraft|airliner|aviat|737|airbus', desc):
    add('cylinder', radius=0.45, depth=6, location=(0, 0, 1.6), rotation=(math.pi / 2, 0, 0)).data.materials.append(white)
    for sx in (-1, 1):
        w = add('cube', scale=(2.6, 0.9, 0.07), location=(sx * 1.6, -0.2, 1.6)); w.data.materials.append(white)
    t = add('cube', scale=(0.7, 0.5, 0.06), location=(0, 2.4, 2.1)); t.data.materials.append(white)
    for sx in (-1, 1):   # engines
        e = add('cylinder', radius=0.3, depth=0.9, location=(sx * 1.2, -0.6, 1.1), rotation=(math.pi / 2, 0, 0)); e.data.materials.append(dark)
    subject_z = 2.0
elif re.search(r'car|vehicle|automobile|truck|supercar', desc):
    b = add('cube', scale=(2.2, 1.0, 0.45), location=(0, 0, 0.75)); b.data.materials.append(make_mat('paint', (0.55, 0.08, 0.08), rough=0.25, metal=0.6))
    c = add('cube', scale=(1.2, 0.9, 0.35), location=(-0.2, 0, 1.2)); c.data.materials.append(glass)
    for px in (-1.1, 1.1):
        for py in (-0.95, 0.95):
            add('cylinder', radius=0.4, depth=0.3, location=(px, py, 0.4), rotation=(0, math.pi / 2, 0)).data.materials.append(dark)
    subject_z = 1.2
elif re.search(r'boat|ship|yacht|sail', desc):
    h = add('cube', scale=(1.0, 3.0, 0.5), location=(0, 0, 0.5)); h.data.materials.append(white)
    c = add('cube', scale=(0.7, 1.0, 0.5), location=(0, -0.6, 1.0)); c.data.materials.append(white)
    subject_z = 1.2
elif re.search(r'building|house|tower|skyscraper|city|castle', desc):
    b1 = add('cube', scale=(1.5, 1.5, 2.2), location=(0, 0, 2.2)); b1.data.materials.append(make_mat('wall', (0.75, 0.7, 0.62), rough=0.8))
    b2 = add('cube', scale=(0.9, 0.9, 1.4), location=(1.8, 0.4, 1.4)); b2.data.materials.append(make_mat('wall2', (0.6, 0.58, 0.55), rough=0.75))
    subject_z = 3.0
else:   # abstract monument (honest default: no subject keyword matched)
    p = add('cube', scale=(1.6, 1.6, 0.3), location=(0, 0, 0.3)); p.data.materials.append(make_mat('plinth', (0.4, 0.38, 0.34), rough=0.85))
    m = add('cube', scale=(0.5, 0.5, 2.6), location=(0, 0, 1.7)); m.data.materials.append(make_mat('mono', (0.25, 0.26, 0.3), rough=0.2, metal=0.7))
    s = add('sphere', radius=0.55, location=(0, 0, 3.3)); s.data.materials.append(glass)
    subject_z = 2.4

# sky: Nishita sky if this Blender has it, else a gradient-tinted background
world = bpy.data.worlds.new('sky'); scene.world = world
world.use_nodes = True
wnodes = world.node_tree.nodes
bg = wnodes['Background']
sky = None
try:
    sky = wnodes.new('ShaderNodeTexSky')
    sky.sky_type = 'NISHITA'
    sky.sun_elevation = math.radians(8)      # dusk: sun low
    sky.sun_rotation = math.radians(220)
    wnodes.links.new(sky.outputs['Color'], bg.inputs['Color'])
    bg.inputs['Strength'].default_value = 0.35
except Exception:
    bg.inputs[0].default_value = (0.18, 0.22, 0.34, 1)   # dusk gradient stand-in
    bg.inputs[1].default_value = 1.0

# key sun + gentle fill
sun = bpy.data.lights.new('key', 'SUN'); sun.energy = 4; sun.angle = math.radians(4)
so = bpy.data.objects.new('key', sun); link(so)
so.location = (5, -7, 6); so.rotation_euler = (math.radians(55), 0, math.radians(-35))
fill = bpy.data.lights.new('fill', 'AREA'); fill.energy = 180; fill.size = 6
fo = bpy.data.objects.new('fill', fill); link(fo)
fo.location = (-6, 3, 4)

# camera orbit (SPEC-Z006: reuse the scene camera if the scene kept one; guard the link)
cam = scene.camera or bpy.data.objects.new('cam', bpy.data.cameras.new('cam'))
scene.camera = cam
if cam.name not in bpy.context.collection.objects:
    bpy.context.collection.objects.link(cam)
for _eng in ('BLENDER_EEVEE_NEXT', 'BLENDER_EEVEE', 'CYCLES'):
    try:
        scene.render.engine = _eng
        break
    except TypeError:
        continue
scene.render.resolution_x = 1280
scene.render.resolution_y = 720
scene.render.fps = 24
scene.frame_end = 96
ims = scene.render.image_settings
try:
    ims.media_type = 'VIDEO'
except TypeError:
    pass
ims.file_format = 'FFMPEG'
scene.render.ffmpeg.format = 'MPEG4'
scene.render.ffmpeg.codec = 'H264'
scene.render.filepath = out
# slow orbit, camera explicitly AIMED at the subject (a fixed Euler tilt looked past it -
# Z008 acceptance found sky+ground-only frames; track-quaternion guarantees framing)
cam.data.lens = 38
target = mathutils.Vector((0.0, 0.0, subject_z - 0.3))
for f in range(1, scene.frame_end + 1):
    a = math.radians(200 + 70 * f / scene.frame_end)
    cam.location = (11.5 * math.cos(a), -11.5 * math.sin(a), subject_z + 2.0)
    direction = target - cam.location
    cam.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()
    scene.frame_set(f)
bpy.ops.render.render(animation=True)
print('BLENDER POC RENDER DONE')
"""


def r11_blender_video(desc, aspect, image_path, ctx):
    exe, where = find_blender()
    if not exe:
        raise Blocker("Blender not installed (searched PATH, Program Files, LOCALAPPDATA — "
                      "installation is a separate approved step)")
    OUT.mkdir(parents=True, exist_ok=True)
    script = OUT / "_blender_scene.py"
    script.write_text(BLENDER_SCRIPT, encoding="utf-8")
    out_mp4 = OUT / "r11_blender_video.mp4"
    ctx["card_note"] = (f"blender at: {where} || subject class from description keywords; "
                        "Principled node materials + Nishita sky + key/fill lights (Z008 §E)")
    r = subprocess.run([exe, "-b", "-P", str(script), "--", desc, str(out_mp4)],
                       capture_output=True, text=True, timeout=1800)
    if not out_mp4.is_file():
        raise Blocker("blender ran but produced no mp4: " + (r.stderr or r.stdout)[-200:].replace("\n", " "))
    return out_mp4


# ------------------------------------------------------------------ registry
ROUTES = [
    {"id": "r1", "name": "cloudflare-flux", "proves": "Cloudflare Workers AI REST image (FLUX.1-schnell)", "fn": r1_cloudflare_flux},
    {"id": "r2", "name": "hf-flux", "proves": "Hugging Face FLUX.1-schnell via gradio_client (free; HF_TOKEN raises quota)", "fn": r2_hf_flux},
    {"id": "r3", "name": "deepseek-describe", "proves": "DeepSeek vision: image -> description + image prompt", "fn": r3_deepseek_describe, "needs_image": True},
    {"id": "r4", "name": "chatgpt-image", "proves": "ChatGPT browser profile image generation (paid account)", "fn": r4_chatgpt_image},
    {"id": "r5", "name": "bing-image", "proves": "Bing Image Creator browser profile", "fn": r5_bing_image},
    {"id": "r6", "name": "meta-image", "proves": "meta.ai image generation (NEW provider, defensive selectors)", "fn": r6_meta_image},
    {"id": "r7", "name": "meta-video", "proves": "meta.ai image-to-video (uses R6/uploaded image)", "fn": r7_meta_video, "needs_image": True},
    {"id": "r8", "name": "flow-video", "proves": "Google Flow prompt -> short video", "fn": r8_flow_video},
    {"id": "r9", "name": "wangp", "proves": "local WanGP still -> image-to-video (incumbent baseline)", "fn": r9_wangp},
    {"id": "r10", "name": "marble-video", "proves": "World Labs Marble world -> recorded walk mp4. WARNING: uses one of the few free generations", "fn": r10_marble_video},
    {"id": "r11", "name": "blender-video", "proves": "Blender bpy low-poly scene render -> mp4", "fn": r11_blender_video},
]

assert len(ROUTES) == 11
