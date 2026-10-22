"""Proof of concept: one image from ChatGPT (Chrome profile) and one from Bing Image Creator (Edge profile).
Tries headless first (no window); if the site blocks headless, tries once with a window. Results, timings and
screenshots go to F:\\videos_test\\poc. Run on Windows with the fork's Python:
    app\\env\\Scripts\\python.exe scripts\\imagegen_poc.py [chatgpt|bing|both]"""
import base64
import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(r"F:\videos_test\poc")
PROMPT = ("A modern data center at dusk: long rows of glowing blue server racks, cooling towers visible through a "
          "window, cinematic lighting, wide 16:9 shot. No text, letters, logos or brand names. No people.")
UA = {"chrome": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
      "msedge": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36 Edg/141.0.0.0"}
SITES = {
    "chatgpt": dict(channel="chrome", profile=r"F:\videos_test\chatgpt_profile", url="https://chatgpt.com/"),
    "bing": dict(channel="msedge", profile=r"F:\videos_test\bing_profile", url="https://www.bing.com/images/create"),
}


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(OUT / "poc.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def save_url(page, src, dest):
    """Download an image the page shows, with the page's own cookies."""
    if src.startswith("data:"):
        dest.write_bytes(base64.b64decode(src.split(",", 1)[1]))
        return
    if src.startswith("blob:"):   # an in-page object URL: read it inside the page
        b64 = page.evaluate("""async (u) => { const b = await (await fetch(u)).blob(); return await new Promise(r => {
            const f = new FileReader(); f.onload = () => r(f.result.split(',')[1]); f.readAsDataURL(b); }); }""", src)
        dest.write_bytes(base64.b64decode(b64))
        return
    r = page.context.request.get(src, timeout=60000)
    if not r.ok:
        raise RuntimeError(f"download failed: HTTP {r.status}")
    dest.write_bytes(r.body())


def chatgpt(page, t0, timeout=240):
    box = page.locator("#prompt-textarea, div[contenteditable='true'][role='textbox'], div.ProseMirror[contenteditable='true'], "
                       "textarea[placeholder*='Ask'], [aria-label*='Ask ChatGPT']").first
    box.wait_for(state="visible", timeout=30000)
    before = page.evaluate("() => [...document.images].map(i => i.src)")
    box.click()
    page.keyboard.type("Create an image: " + PROMPT, delay=12)
    page.keyboard.press("Enter")
    log("  chatgpt: prompt sent, waiting for the image...")
    last, stable = None, 0
    while time.time() - t0 < timeout:
        time.sleep(3)
        imgs = page.evaluate("""() => [...document.images].filter(i => i.naturalWidth >= 512 &&
            ((i.alt || '').toLowerCase().includes('generated') || i.src.includes('oaiusercontent') || i.src.includes('/backend-api/estuary/')))
            .map(i => ({src: i.src, w: i.naturalWidth, h: i.naturalHeight}))""")
        imgs = [i for i in imgs if i["src"] not in before]
        busy = page.get_by_text("Creating image").count() + page.locator("[data-testid='stop-button']").count()
        if imgs and not busy:
            cur = imgs[-1]["src"]
            stable = stable + 1 if cur == last else 0
            last = cur
            if stable >= 2:   # same final image on three checks in a row: done (not the blurred preview)
                return imgs[-1]
    raise RuntimeError(f"no image after {timeout}s")


def bing(page, t0, timeout=240):
    box = page.get_by_placeholder("Describe the image", exact=False).first
    box.wait_for(state="visible", timeout=30000)
    box.click()
    page.keyboard.type(PROMPT, delay=12)
    gen = page.get_by_role("button", name="Generate").first
    gen.click()
    log("  bing: Generate clicked, waiting for the images...")
    while time.time() - t0 < timeout:
        time.sleep(3)
        imgs = page.evaluate("""() => [...document.images].filter(i => /\\/th\\/id\\/OIG|OIG\\d/.test(i.src) && i.naturalWidth >= 200)
            .map(i => ({src: i.src, w: i.naturalWidth, h: i.naturalHeight}))""")
        if imgs:
            time.sleep(4)   # let the whole set land
            imgs = page.evaluate("""() => [...document.images].filter(i => /\\/th\\/id\\/OIG|OIG\\d/.test(i.src) && i.naturalWidth >= 200)
                .map(i => ({src: i.src, w: i.naturalWidth, h: i.naturalHeight}))""")
            best = dict(imgs[0]); best["src"] = best["src"].split("?")[0]   # without ?w=..&h=.. : the full-size image
            best["count"] = len(imgs)
            return best
        txt = page.inner_text("body")[:4000].lower()
        for bad in ("content warning", "unsafe image", "can't create", "blocked", "try again later"):
            if bad in txt:
                raise RuntimeError(f"Bing says: {bad}")
    raise RuntimeError(f"no image after {timeout}s")


def run(site, headless):
    s = SITES[site]
    tag = "headless" if headless else "window"
    t0 = time.time()
    with sync_playwright() as pw:
        kw = dict(user_data_dir=s["profile"], channel=s["channel"], headless=headless, accept_downloads=True,
                  viewport={"width": 1440, "height": 900}, args=["--disable-blink-features=AutomationControlled"])
        if headless:
            kw["user_agent"] = UA[s["channel"]]
        ctx = pw.chromium.launch_persistent_context(**kw)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto(s["url"], wait_until="domcontentloaded", timeout=60000)
            time.sleep(4)
            img = (chatgpt if site == "chatgpt" else bing)(page, t0)
            dest = OUT / f"{site}_{tag}.png"
            save_url(page, img["src"], dest)
            secs = round(time.time() - t0)
            log(f"  {site} ({tag}): OK in {secs}s -> {dest} ({dest.stat().st_size // 1024} KB, {img.get('w')}x{img.get('h')})")
            return {"site": site, "mode": tag, "ok": True, "secs": secs, "file": str(dest), "w": img.get("w"), "h": img.get("h"),
                    "count": img.get("count", 1)}
        except Exception as e:
            shot = OUT / f"{site}_{tag}_fail.png"
            try: page.screenshot(path=str(shot), full_page=False)
            except Exception: pass
            log(f"  {site} ({tag}): FAILED after {round(time.time() - t0)}s: {e} (screenshot {shot})")
            return {"site": site, "mode": tag, "ok": False, "secs": round(time.time() - t0), "error": str(e)[:300], "shot": str(shot)}
        finally:
            ctx.close()


def hf():
    """Hugging Face FLUX.1-schnell Space through gradio_client (no browser)."""
    t0 = time.time()
    try:
        from gradio_client import Client
        tok = json.loads(Path(r"F:\code\video-studio-test\settings.json").read_text(encoding="utf-8-sig")).get("hf_token") or None
        if tok:
            from huggingface_hub import whoami
            log(f"  hf: token works for account '{whoami(token=tok).get('name')}'")
        else:
            log("  hf: no hf_token in settings.json (anonymous quota)")
        c = Client("black-forest-labs/FLUX.1-schnell", token=tok, verbose=False)
        api = c.view_api(return_format="dict", print_info=False)
        log(f"  hf: endpoints {list(api.get('named_endpoints', {}).keys())}")
        prompt = ("A red vintage pickup truck parked beside a New Hampshire covered bridge in autumn, golden leaves, "
                  "late afternoon light, photorealistic, wide 16:9. No text, no logos, no people.")
        res = c.predict(prompt, 0, True, 1344, 768, 4, api_name="/infer")
        src = res[0] if isinstance(res, (list, tuple)) else res
        src = src.get("path") if isinstance(src, dict) else src
        from PIL import Image
        dest = OUT / "hf_token_test.png"
        with Image.open(src) as im: im.save(dest); w, h = im.size
        log(f"  hf: OK in {round(time.time() - t0)}s -> {dest} ({w}x{h})")
        return {"site": "hf", "ok": True, "secs": round(time.time() - t0), "file": str(dest)}
    except Exception as e:
        log(f"  hf: FAILED after {round(time.time() - t0)}s: {str(e)[:400]}")
        return {"site": "hf", "ok": False, "error": str(e)[:400]}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    which = sys.argv[1] if len(sys.argv) > 1 else "both"
    results = []
    if which == "hf":
        results.append(hf()); (OUT / "results.json").write_text(json.dumps(results, indent=1), encoding="utf-8"); log("done"); return
    for site in (["chatgpt", "bing"] if which == "both" else [which]):
        log(f"{site}: headless try")
        r = run(site, True); results.append(r)
        if not r["ok"]:
            log(f"{site}: retry with a window")
            results.append(run(site, False))
    (OUT / "results.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    log("done")


if __name__ == "__main__":
    main()
