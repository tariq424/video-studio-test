"""One-shot Bermuda harvest for the media DB (standalone v2, owner 2026-10-26).

Drop this file into F:\\code\\video-studio-test\\scripts\\ and run from the repo root:

    python scripts\\bermuda_index_v2.py

Order of work (v2: the DB is consulted FIRST, before the browser opens):
  1. Read media_db and snapshot what it already holds: every known Photos
     URL, and which of those already have full details.
  2. Search Google Photos for "bermuda" in the signed-in profile
     (F:/videos/gphotos_profile), scrolling until results stop growing.
  3. Sort the hits against the DB snapshot:
       - already complete in the DB  -> ignored entirely, never touched;
       - known but missing details   -> queued for the details pass only;
       - brand new                   -> recorded, then queued for details.
  4. The details pass opens only the queued items and merges each info
     panel (file name, date, time, place, GPS pin, photo/video).
  5. Prints the DB's Bermuda totals, how many were ignored as already
     complete, and how many rows carry a non-Bermuda place (likely
     search false positives).

Safe to re-run any time; a second pass costs one search scroll and then
only processes what is genuinely missing. Downloads nothing, never
touches the encrypted backup or its key, and stops by itself if Google
shows a sign-in or "verify it's you" page.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from studio import config, gphotos, media_db  # noqa: E402

QUERY = "bermuda"
MAX_SCROLLS = 80


def harvest(page, query):
    """Collect every /photo/ link for one search. Same link collection as
    gphotos.search(), but keeps scrolling until the page stops producing
    new items (the built-in helper stops after 4 scrolls, which can miss
    the tail of a big result set)."""
    from urllib.parse import quote
    page.goto("https://photos.google.com/search/" + quote(query),
              wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)
    gphotos._guard(page)
    seen, out, idle = set(), [], 0
    for _ in range(MAX_SCROLLS):
        items = page.evaluate("""() => {
            const res = [];
            for (const a of document.querySelectorAll('a[href*="/photo/"]')) {
                let g = '', el = a;
                for (let i = 0; i < 12 && el; i++) { el = el.parentElement;
                    const h = el && el.querySelector && el.querySelector('[role="heading"], h2, h3'); if (h && h.innerText) { g = h.innerText; break; } }
                res.push({url: a.href, label: a.getAttribute('aria-label') || '', group: g}); }
            return res; }""")
        new = 0
        for it in items:
            u = it["url"].split("?")[0]
            if u not in seen:
                seen.add(u)
                out.append(dict(it, url=u))
                new += 1
        print(f"  scroll: {len(out)} item(s) so far", flush=True)
        if new == 0:
            idle += 1
            if idle >= 2:
                break
        else:
            idle = 0
        page.mouse.wheel(0, 2500)
        page.wait_for_timeout(1800)
    return out


def main():
    cfg = config.load()
    db = media_db.connect(cfg)

    # 1) DB FIRST: snapshot what is already known before opening the browser.
    known = {}
    for url, fname, date in db.execute("SELECT url, file_name, date FROM items"):
        known[url] = bool(fname) and bool(date)
    complete = {u for u, has in known.items() if has}
    print(f"DB first: {len(known)} item(s) already known, "
          f"{len(complete)} of them complete", flush=True)

    work = Path("F:/bermuda/_work/gphotos")
    work.mkdir(parents=True, exist_ok=True)
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        ctx, page = gphotos._launch(pw, cfg)
        try:
            hits = harvest(page, QUERY)
            # 2) Sort the hits against the DB snapshot.
            ignored, incomplete, fresh = 0, [], []
            for h in hits:
                u = media_db.canon(h["url"])
                if u in complete:
                    ignored += 1                      # in the DB, done: ignore
                elif u in known:
                    incomplete.append(h["url"])       # row exists, details missing
                else:
                    fresh.append(h)
                    media_db.upsert(db, {"url": h["url"], "found_by": QUERY,
                                         "label": h.get("label", ""),
                                         "group_date": h.get("group", "")})
            print(f"search '{QUERY}': {len(hits)} hit(s) -> {ignored} already complete "
                  f"(ignored), {len(incomplete)} known but incomplete, "
                  f"{len(fresh)} new", flush=True)
            time.sleep(4)
            # 3) Details only for what the DB is missing.
            todo = incomplete + [h["url"] for h in fresh]
            print(f"details: {len(todo)} to open", flush=True)
            for k, u in enumerate(todo):
                d = gphotos.details(page, u, shot=work / f"item_{k}.png")
                media_db.upsert(db, d)
                print(f"  {k + 1}/{len(todo)}: {d['file_name']} {d['date']} "
                      f"{d['time']} | {d['place']} | {d['lat']},{d['lon']}", flush=True)
                time.sleep(2.5)
        except gphotos.Stop as e:
            print(f"stopped: {e}", flush=True)
        finally:
            try:
                ctx.close()
            except Exception:
                pass
    n = db.execute("SELECT COUNT(*) FROM items WHERE found_by LIKE '%bermuda%'").fetchone()[0]
    odd = db.execute("SELECT COUNT(*) FROM items WHERE found_by LIKE '%bermuda%' "
                     "AND place != '' AND lower(place) NOT LIKE '%bermuda%'").fetchone()[0]
    print(f"done. DB rows found by 'bermuda': {n}; "
          f"with a non-Bermuda place (likely false positives): {odd}", flush=True)


if __name__ == "__main__":
    main()
