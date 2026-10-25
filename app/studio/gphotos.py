"""Missing-footage search in the owner's Google Photos (owner, 2026-10-25).

Template step for any video: when the narration mentions something we have no footage for, look 1) in our catalogued
folders, 2) in the media database (media_db), 3) in Google Photos with the pipeline's own signed-in Chrome profile
(F:/videos/gphotos_profile, signed in once by the owner): search the owner's way ("hamilton bermuda + mr. chicken"),
read each likely hit's details (date, time, place, file name), search again by place + date, download what fits.
Every item looked at gets a row in media_db with its Google Photos URL. The owner owns every item: no restrictions.

Pace: a few searches per video at a human speed; a sign-in or "verify it's you" page stops everything (never typed)."""
import json
import re
import time
from pathlib import Path

from . import media_db

PROFILE = "F:/videos/gphotos_profile"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")
BLOCK = re.compile(r"(verify it.s you|unusual traffic|captcha|couldn.t sign you in|choose an account)", re.I)


class Stop(RuntimeError):
    pass


def _launch(pw, cfg):
    prof = Path(cfg.get("gphotos_profile") or PROFILE)
    if not prof.exists() or not any(prof.iterdir()):
        raise Stop(f"no signed-in Google Photos profile at {prof}; run the gphotos-login hook once")
    headless = bool(cfg.get("gphotos_headless", True))
    kw = dict(user_data_dir=str(prof), headless=headless, accept_downloads=True, channel="chrome",
              viewport={"width": 1440, "height": 1000}, args=["--disable-blink-features=AutomationControlled"])
    if headless: kw["user_agent"] = UA
    ctx = pw.chromium.launch_persistent_context(**kw)
    return ctx, (ctx.pages[0] if ctx.pages else ctx.new_page())


def _guard(page):
    if "accounts.google.com" in page.url: raise Stop("Google asked for a sign-in; the owner signs in (gphotos-login), never typed here")
    try: body = page.inner_text("body", timeout=5000)
    except Exception: body = ""
    if BLOCK.search(body[:5000]): raise Stop("Google showed a check page (verify / unusual traffic); stopping")
    return body


def search(page, query, shot=None, scrolls=4):
    """-> [{"url", "label", "group"}] for one Google Photos search, in page order."""
    from urllib.parse import quote
    page.goto("https://photos.google.com/search/" + quote(query), wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000); _guard(page)
    seen, out = set(), []
    for _ in range(scrolls):
        items = page.evaluate("""() => {
            const res = [];
            for (const a of document.querySelectorAll('a[href*="/photo/"]')) {
                let g = '', el = a;
                for (let i = 0; i < 12 && el; i++) { el = el.parentElement;
                    const h = el && el.querySelector && el.querySelector('[role="heading"], h2, h3'); if (h && h.innerText) { g = h.innerText; break; } }
                res.push({url: a.href, label: a.getAttribute('aria-label') || '', group: g});
            }
            return res; }""")
        for it in items:
            u = it["url"].split("?")[0]
            if u not in seen: seen.add(u); out.append(dict(it, url=u))
        page.mouse.wheel(0, 2500); page.wait_for_timeout(1800)
    if shot:
        page.evaluate("window.scrollTo(0, 0)"); page.wait_for_timeout(1200); page.screenshot(path=str(shot), full_page=False)
    return out


COORD = re.compile(r"(-?\d{1,2}\.\d{4,})\s*,\s*(-?\d{1,3}\.\d{4,})")


def details(page, url, shot=None):
    """Open one item and read its info panel: date / time, place, file name, size, and the map pin when the page has it."""
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3500); _guard(page)
    page.keyboard.press("i"); page.wait_for_timeout(2500)   # the info panel
    body = page.inner_text("body", timeout=8000) or ""
    i = body.rfind("\nInfo\n")   # the info panel is the last block of the page text
    info = body[i + 6:] if i >= 0 else body[-3000:]
    html = page.content()
    lat = lon = None
    for m in re.finditer(r"maps[^\"']*?[?&](?:q|center|ll)=(-?\d+\.\d+)(?:,|%2C)(-?\d+\.\d+)", html):
        lat, lon = float(m[1]), float(m[2]); break
    if lat is None:
        for m in COORD.finditer(info):
            a, b = float(m[1]), float(m[2])
            if -90 <= a <= 90 and -180 <= b <= 180: lat, lon = a, b; break
    lines = [x.strip() for x in info.splitlines() if x.strip()]
    fname = next((x for x in lines if re.search(r"\.(heic|jpe?g|png|mov|mp4|webp)$", x, re.I)), "")
    date = next((x for x in lines if re.match(r"^[A-Z][a-z]{2} \d{1,2}, \d{4}$", x)), "")
    when = next((x for x in lines if re.search(r"\d{1,2}:\d{2}\s*(AM|PM)", x)), "")
    place = ""
    for i, x in enumerate(lines):   # the location sits after the camera / size lines; take the first line that looks like a place
        if re.search(r",", x) and not re.search(r"\d{1,2}:\d{2}|MP|×|ƒ/|mm|ISO|items|Backed|quality|Shared|\d{4}", x):
            place = x; break
    if shot: page.screenshot(path=str(shot), full_page=False)
    kind = "video" if re.search(r"\.(mov|mp4)$", fname, re.I) or re.search(r"\b\d+:\d{2}\b", " ".join(lines[:3])) and "video" in html[:200000].lower() else "photo"
    return {"url": url, "file_name": fname, "date": date, "time": when, "place": place, "lat": lat, "lon": lon,
            "kind": kind, "info": "\n".join(lines)[:2000]}


def download(page, url, out_dir):
    """The original file (Shift+D on the item page) -> local path."""
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3000); _guard(page)
    with page.expect_download(timeout=180000) as dl:
        page.keyboard.press("Shift+D")
    d = dl.value
    p = out_dir / d.suggested_filename
    if p.exists(): p = out_dir / f"{p.stem}_{int(time.time())}{p.suffix}"
    d.save_as(str(p))
    return p


def run(cfg, job, log=print):
    """job: {"search": [queries], "details": [urls], "download": [urls], "dir": folder, "topic": "...", "work": folder}
    Writes <work>/gphotos_result.json (+ screenshots) and records every item in media_db."""
    from playwright.sync_api import sync_playwright
    work = Path(job.get("work") or "."); work.mkdir(parents=True, exist_ok=True)
    res = {"search": {}, "details": [], "download": [], "stopped": ""}
    db = media_db.connect(cfg)
    with sync_playwright() as pw:
        ctx, page = _launch(pw, cfg)
        try:
            for k, q in enumerate(job.get("search") or []):
                hits = search(page, q, shot=work / f"search_{k}.png")
                res["search"][q] = hits
                log(f"  Google Photos: '{q}' -> {len(hits)} item(s)")
                for h in hits: media_db.upsert(db, {"url": h["url"], "found_by": q, "label": h.get("label", ""), "group_date": h.get("group", "")})
                time.sleep(4)
            if job.get("details_from"):   # every item of an earlier search (dedup), e.g. to look for a shop sign
                prev = json.loads((work / "gphotos_result.json").read_text(encoding="utf-8")) if (work / "gphotos_result.json").exists() else {}
                urls = []
                for h in (prev.get("search") or {}).get(job["details_from"], []) or res["search"].get(job["details_from"], []):
                    tail = h["url"].rsplit("/", 1)[-1]
                    if tail not in [x.rsplit("/", 1)[-1] for x in urls]: urls.append(h["url"])
                job["details"] = (job.get("details") or []) + urls
            for k, u in enumerate(job.get("details") or []):
                d = details(page, u, shot=work / f"item_{k}.png")
                res["details"].append(d); media_db.upsert(db, d)
                log(f"  item {k}: {d['file_name']} {d['date']} {d['time']} | {d['place']} | {d['lat']},{d['lon']}")
                time.sleep(2.5)
            for u in job.get("download") or []:
                p = download(page, u, job.get("dir") or "F:/videos/gphotos")
                res["download"].append({"url": u, "path": str(p)}); media_db.upsert(db, {"url": u, "local_path": str(p)})
                log(f"  downloaded {p.name}")
                time.sleep(3)
        except Stop as e:
            res["stopped"] = str(e); log(f"  Google Photos stopped: {e}")
        finally:
            try: ctx.close()
            except Exception: pass
    (work / "gphotos_result.json").write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
    return res
