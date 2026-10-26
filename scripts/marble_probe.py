"""Look (read-only) at World Labs Marble in its own profile, so the Marble rung can be written against the real page.
Opens https://marble.worldlabs.ai/ in F:\\videos_test\\marble_profile, clicks nothing, saves: screenshot, page text, and
the buttons / inputs / links it sees. Optional 2nd arg: a URL path on marble.worldlabs.ai to look at instead.
Run: python scripts/marble_probe.py <out_dir> [url]"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from studio import config, imagegen  # noqa: E402


def main():
    out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
    uf = out / "url.txt"   # a page to look at instead of the home page (written before the run)
    url = sys.argv[2] if len(sys.argv) > 2 else (uf.read_text(encoding="utf-8").strip() if uf.exists() and uf.read_text(encoding="utf-8").strip() else "https://marble.worldlabs.ai/")
    cfg = dict(config.load(), imagegen_headless=False)
    from playwright.sync_api import sync_playwright
    res = {"url": url, "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    with sync_playwright() as pw:
        try:
            context, page = imagegen._launch(pw, cfg, "marble")
        except Exception as e:
            res["error"] = f"{type(e).__name__}: {str(e)[:400]}"
            (out / "probe.json").write_text(json.dumps(res, indent=1), encoding="utf-8"); print(res["error"]); return
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000); page.wait_for_timeout(9000)
            res["final_url"] = page.url; res["title"] = page.title()
            page.screenshot(path=str(out / "page.png"), full_page=False)
            page.screenshot(path=str(out / "page_full.png"), full_page=True)
            (out / "page.html").write_text(page.content(), encoding="utf-8")
            (out / "text.txt").write_text(page.inner_text("body")[:20000], encoding="utf-8")
            res["controls"] = page.evaluate("""() => [...document.querySelectorAll('button, a, input, textarea, [role=button], [contenteditable=true], select')]
                .filter(e => e.offsetParent !== null).slice(0, 200).map(e => ({tag: e.tagName.toLowerCase(), type: e.type || '',
                 text: (e.innerText || e.value || '').trim().slice(0, 80), aria: e.getAttribute('aria-label') || '',
                 ph: e.getAttribute('placeholder') || '', href: e.getAttribute('href') || '', id: e.id || '',
                 cls: (e.className && e.className.baseVal === undefined ? e.className : '').toString().slice(0, 80)}))""")
        except Exception as e:
            res["error"] = f"{type(e).__name__}: {str(e)[:400]}"
        finally:
            context.close()
    (out / "probe.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    print("done", res.get("final_url"), res.get("error", ""))


if __name__ == "__main__":
    main()
