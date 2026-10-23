"""Bridge: a password-free door into Google apps for Playwright, with no hotkey.

It starts YOUR Chrome with the Google-signed-in bridge profile (default: the Flow/Gemini profile, F:\\videos_test\\flow_profile,
signed in once by hand) and a launcher page of Google apps. Chrome is started with a debugging port bound to 127.0.0.1 only,
so Playwright (this script, or any later step) can attach to that same window, open an app, look, download, and detach.

    app\\env\\Scripts\\python.exe scripts\\bridge.py start          open Chrome + the launcher page (window stays open)
    app\\env\\Scripts\\python.exe scripts\\bridge.py goto <app>     open an app in a new tab (notebooklm, photos, drive, gemini ...)
    app\\env\\Scripts\\python.exe scripts\\bridge.py tabs           list open tabs
    app\\env\\Scripts\\python.exe scripts\\bridge.py shot           screenshot of the front tab
    app\\env\\Scripts\\python.exe scripts\\bridge.py stop           close the bridge Chrome

Log and screenshots: F:\\videos_test\\smoke\\bridge\\. Owner's rule: Google tools are used sparingly and at human pace;
the bridge never runs while a pipeline step is using the same profile (it checks the profile lock first)."""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
PORT = 9333
OUT = Path(r"F:\videos_test\smoke\bridge") if os.name == "nt" else Path.home() / "videos" / "bridge"
PAGE = Path(__file__).resolve().with_name("bridge_apps.html")
APPS = {"notebooklm": "https://notebooklm.google.com/", "photos": "https://photos.google.com/", "drive": "https://drive.google.com/",
        "gemini": "https://gemini.google.com/app", "youtube": "https://www.youtube.com/", "studio": "https://studio.youtube.com/",
        "gmail": "https://mail.google.com/", "docs": "https://docs.google.com/document/", "sheets": "https://docs.google.com/spreadsheets/",
        "calendar": "https://calendar.google.com/", "keep": "https://keep.google.com/", "account": "https://myaccount.google.com/",
        "search": "https://www.google.com/", "maps": "https://maps.google.com/", "news": "https://news.google.com/",
        "translate": "https://translate.google.com/", "earth": "https://earth.google.com/web/", "flow": "https://labs.google/fx/tools/flow"}


def log(m):
    OUT.mkdir(parents=True, exist_ok=True)
    line = f"[{time.strftime('%H:%M:%S')}] {m}"; print(line, flush=True)
    with open(OUT / "bridge.log", "a", encoding="utf-8") as f: f.write(line + "\n")


def profile():
    from studio import config, imagegen
    cfg = config.load()
    p = Path(cfg.get("bridge_profile") or imagegen.profile_dir(cfg))
    return p, cfg


def chrome_exe():
    for c in (r"C:\Program Files\Google\Chrome\Application\chrome.exe", r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
              os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe")):
        if Path(c).exists(): return c
    raise SystemExit("Google Chrome not found")


def alive():
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/version", timeout=2) as r: return json.loads(r.read())
    except Exception:
        return None


def start():
    if alive(): log("bridge already running"); return
    prof, _ = profile()
    if not prof.exists() or not any(prof.iterdir()):
        raise SystemExit(f"no signed-in profile at {prof}: sign in once (scripts\\imagegen-login.ps1 -Site gemini)")
    if (prof / "lockfile").exists() or (prof / "SingletonLock").exists():
        try: (prof / "lockfile").unlink()   # a stale lock file goes away; a live one can't be removed while Chrome holds it
        except OSError: raise SystemExit("the profile is in use right now (a pipeline step or a sign-in window); try again later")
    args = [chrome_exe(), f"--user-data-dir={prof}", f"--remote-debugging-port={PORT}", "--remote-debugging-address=127.0.0.1",
            "--no-first-run", "--no-default-browser-check", "--new-window", PAGE.as_uri()]
    subprocess.Popen(args, close_fds=True, creationflags=0x00000008 | 0x00000200)   # detached: the window outlives this script
    for _ in range(30):
        if alive(): log(f"bridge started: Chrome with {prof} on 127.0.0.1:{PORT}, launcher page open"); return
        time.sleep(1)
    raise SystemExit("Chrome did not open its debugging port")


def _connect(pw):
    if not alive(): raise SystemExit("bridge is not running (bridge.py start)")
    b = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{PORT}")
    return b, b.contexts[0]


def goto(app):
    url = APPS.get(app.lower()) or (app if app.startswith("http") else None)
    if not url: raise SystemExit(f"unknown app {app}; one of: {', '.join(APPS)}")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b, ctx = _connect(pw)
        page = ctx.new_page(); page.goto(url, wait_until="domcontentloaded", timeout=60000); page.wait_for_timeout(3000)
        signed = "accounts.google.com" not in page.url
        log(f"opened {app}: {page.title()[:80]} ({page.url[:100]}){'' if signed else '  ** NOT SIGNED IN: sign in once in this window **'}")
        page.screenshot(path=str(OUT / f"{app}_{time.strftime('%H%M%S')}.png"))
        b.close()   # detaches only; the window and tab stay open


def tabs():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b, ctx = _connect(pw)
        for i, p in enumerate(ctx.pages): log(f"tab {i}: {p.title()[:70]}  {p.url[:100]}")
        b.close()


def shot():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b, ctx = _connect(pw)
        p = ctx.pages[-1]; f = OUT / f"shot_{time.strftime('%H%M%S')}.png"; p.screenshot(path=str(f)); log(f"screenshot {f} ({p.url[:80]})")
        b.close()


def stop():
    from playwright.sync_api import sync_playwright
    if not alive(): log("bridge not running"); return
    with sync_playwright() as pw:
        b = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{PORT}")
        try: b.new_browser_cdp_session().send("Browser.close")
        except Exception: pass
    log("bridge closed")


# ---------------------------------------------------------------- NotebookLM (read and download only; never creates or edits)
def _page(ctx, url_part, url):
    for p in ctx.pages:
        if url_part in p.url: p.bring_to_front(); return p
    p = ctx.new_page(); p.goto(url, wait_until="domcontentloaded", timeout=60000); return p


def dump(page, tag):
    """Screenshot + the clickable things on the page (for finding the right buttons)."""
    f = OUT / f"{tag}_{time.strftime('%H%M%S')}"
    page.screenshot(path=str(f) + ".png")
    items = page.evaluate("""() => [...document.querySelectorAll('button, a, [role=button], [role=menuitem], [role=tab]')]
        .filter(e => e.offsetParent !== null).map(e => ((e.getAttribute('aria-label') || '') + ' | ' + (e.innerText || '').trim().replace(/\s+/g, ' ')).slice(0, 120))
        .filter(t => t.replace(/[ |]/g, '').length)""")
    Path(str(f) + ".txt").write_text("\n".join(items), encoding="utf-8")
    log(f"{tag}: {page.title()[:60]} ({page.url[:90]}); {len(items)} clickable items -> {f.name}.txt/.png")


def nlm(action, name=""):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b, ctx = _connect(pw)
        page = _page(ctx, "notebook", "https://notebooklm.google.com/")
        page.set_default_timeout(20000)   # no step may wait longer than this (a hang at 11:58 waited forever)
        step = lambda m: log(f"  nlm {action}: {m}")
        page.wait_for_timeout(4000)
        if "accounts.google.com" in page.url: raise SystemExit("NotebookLM: not signed in")
        if action == "list":
            if "/notebook/" in page.url: page.goto("https://notebooklm.google.com/", wait_until="domcontentloaded"); page.wait_for_timeout(4000)
            dump(page, "nlm_list")
        elif action == "open":
            if "/notebook/" in page.url: page.goto("https://notebooklm.google.com/", wait_until="domcontentloaded"); page.wait_for_timeout(4000)
            page.get_by_text(name, exact=False).first.click(timeout=15000); page.wait_for_timeout(6000)
            dump(page, "nlm_open")
        elif action == "download":   # name = "<notebook title>|audio" or "|video"
            title, _, kind = name.partition("|"); kind = (kind or "audio").lower()
            if title and title.lower() not in page.title().lower():
                if "/notebook/" in page.url: page.goto("https://notebooklm.google.com/", wait_until="domcontentloaded"); page.wait_for_timeout(4000)
                page.get_by_text(title, exact=False).first.click(timeout=15000); page.wait_for_timeout(6000)
            dest = Path(r"F:\videos_test\smoke\nlm") if os.name == "nt" else OUT / "nlm"; dest.mkdir(parents=True, exist_ok=True)
            step("closing pop-ups")
            for _ in range(3):   # welcome / news pop-ups
                x = page.locator("button[aria-label='Close dialog'], button[aria-label='Dismiss banner']")
                if not x.count() or not x.first.is_visible(): break
                x.first.click(timeout=3000); page.wait_for_timeout(800)
            # a saved overview in the Studio panel is the row with a Play button; its own "More" menu has Download.
            # (The "Audio Overview" / "Video Overview" tiles CREATE new ones: never clicked.)
            step("looking for a saved overview (Play button)")
            plays = page.locator("button[aria-label='Play']")
            if not plays.count(): dump(page, "nlm_noitem"); raise SystemExit("no saved overview with a Play button in this notebook")
            row = plays.first.locator("xpath=ancestor::*[.//button[@aria-label='More']][1]")
            step("opening its menu")
            row.locator("button[aria-label='More']").first.click(timeout=10000); page.wait_for_timeout(1200)
            dump(page, "nlm_menu")
            step("clicking Download")
            with page.expect_download(timeout=180000) as dl:
                page.get_by_role("menuitem", name=re.compile("download", re.I)).first.click(timeout=10000)
            f = dest / (re.sub(r"[^\w-]+", "_", title or "notebook")[:60] + f"_{kind}_" + time.strftime("%Y%m%d_%H%M%S") + Path(dl.value.suggested_filename).suffix)
            dl.value.save_as(str(f)); log(f"downloaded {kind} overview -> {f} ({f.stat().st_size // 1024} KB)")
        b.close()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "start"
    try:
        if cmd == "goto": goto(sys.argv[2] if len(sys.argv) > 2 else "")
        elif cmd.startswith("nlm-"): nlm(cmd[4:], " ".join(sys.argv[2:]))
        elif cmd == "args":   # arguments from a file (spaces and quotes survive): F:\videos_test\smoke\bridge\args.txt
            a = (OUT / "args.txt").read_text(encoding="utf-8").strip().split(" ", 1); sys.argv = [sys.argv[0]] + a
            nlm(a[0][4:], a[1] if len(a) > 1 else "") if a[0].startswith("nlm-") else goto(a[1])
        elif cmd in ("start", "tabs", "shot", "stop"): {"start": start, "tabs": tabs, "shot": shot, "stop": stop}[cmd]()
        else: raise SystemExit(f"unknown command {cmd}: start | goto <app> | tabs | shot | stop")
    except SystemExit as e:
        log(f"bridge {cmd}: {e}"); raise
    except Exception as e:
        log(f"bridge {cmd} FAILED: {type(e).__name__}: {' '.join(str(e).split())[:300]}"); raise SystemExit(1)
