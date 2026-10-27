"""Public web search for QC-repair research, load-balanced over several routes (exchange doc MSG 008, Tariq 2026-10-26):
DuckDuckGo, Bing and Copilot (the signed-in Microsoft 365 Chrome profile, F:\\videos_test\\m365_profile) take turns
(round-robin, the starting route advances every call); a route that blocks or fails is rested and the next one is tried
instead of hammering it. Google only as the last resort: at most once an hour, and rested 6 h after it shows a block page
(Tariq's Google account is protected by going there sparingly). No route needs a password; Copilot uses the profile
Tariq signed in himself. State: <jobs_dir parent>/search_routes.json.
  search(cfg, query, log) -> (snippets, route)"""
import json, re, time
from pathlib import Path

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
      "Accept-Language": "en-US,en;q=0.9"}
ROTATION = ("wikipedia", "duckduckgo", "bing", "copilot")
REST = {"wikipedia": 600, "duckduckgo": 1800, "bing": 1800, "copilot": 3600, "google": 6 * 3600}
GOOGLE_MIN_GAP = 3600


def _log(log, m): (log or print)(m)


def _state_path(cfg):
    return Path(cfg.get("jobs_dir") or ".").parent / "search_routes.json"


def _load(cfg):
    try: return json.loads(_state_path(cfg).read_text(encoding="utf-8"))
    except Exception: return {}


def _save(cfg, st):
    try: _state_path(cfg).write_text(json.dumps(st, indent=1), encoding="utf-8")
    except OSError: pass


def _clean(parts, n=8):
    out = [" ".join(re.sub(r"<[^>]+>|&\w+;|&#\d+;", " ", s).split()) for s in parts]
    return [s for s in out if len(s.split()) > 4][:n]


STOP = set("the and for with from that this into over what when where which while about their there have has had were was are been "
           "used using tools plan plans planned".split())


def relevant(snips, q, need=2):
    """Keep snippets that share at least `need` content words with the query (block pages and ad filler share none)."""
    qw = {w for w in re.findall(r"[a-z]{4,}", q.lower()) if w not in STOP}
    return [s for s in snips if len(qw & set(re.findall(r"[a-z]{4,}", s.lower()))) >= min(need, len(qw))]


def _browser(cfg, headless=None):
    from .imagegen import profile_dir
    prof = profile_dir(cfg, "m365")
    if not prof.exists() or not any(prof.iterdir()): raise RuntimeError(f"no signed-in m365 profile at {prof}")
    return dict(user_data_dir=str(prof), headless=bool(cfg.get("imagegen_headless", True)) if headless is None else headless,
                channel="chrome", viewport={"width": 1280, "height": 900}, args=["--disable-blink-features=AutomationControlled"])


def _evidence(cfg, page, name):
    try:
        from . import config
        d = config.ROOT.parent / "patches" / "search_fail"; d.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(d / f"{name}.png")); (d / f"{name}.html").write_text(page.content(), encoding="utf-8")
    except Exception: pass


def _ddg(cfg, q):
    import requests
    r = requests.get("https://html.duckduckgo.com/html/", params={"q": q}, headers=UA, timeout=20)
    if r.status_code != 200: raise RuntimeError(f"HTTP {r.status_code}")
    return relevant(_clean(re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', r.text, re.S)), q)


def _bing(cfg, q):
    import requests
    r = requests.get("https://www.bing.com/search", params={"q": q, "setlang": "en"}, headers=UA, timeout=20)
    if r.status_code != 200: raise RuntimeError(f"HTTP {r.status_code}")
    if "captcha" in r.text.lower()[:20000] and "b_algo" not in r.text: raise RuntimeError("block page")
    items = re.findall(r'<li class="b_algo".*?</li>', r.text, re.S)
    got = relevant(_clean([" ".join(re.findall(r"<p[^>]*>(.*?)</p>", it, re.S)) or it for it in items]), q)
    if got: return got
    from playwright.sync_api import sync_playwright   # plain request got filler: the signed-in Microsoft profile
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(**_browser(cfg)); page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto("https://www.bing.com/search?setlang=en&q=" + __import__("urllib.parse").parse.quote(q), wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)
            snips = page.eval_on_selector_all("li.b_algo", "els => els.map(e => e.innerText)")
            got = relevant(_clean(snips), q)
            if not got: _evidence(cfg, page, "bing")
            return got
        finally:
            ctx.close()


def _google(cfg, q):
    import requests
    r = requests.get("https://www.google.com/search", params={"q": q, "hl": "en", "num": 8}, headers=UA, timeout=20)
    if r.status_code != 200 or "unusual traffic" in r.text or "/sorry/" in r.url: raise RuntimeError("block page")
    return relevant(_clean(re.findall(r'<div[^>]*class="[^"]*(?:VwiC3b|BNeawe s3v9rd)[^"]*"[^>]*>(.*?)</div>', r.text, re.S)), q)


ACCEPT = r"^(continue|got it|ok|okay|next|let's go|get started|try it|try the new copilot|accept|agree|i agree|done|start chatting)$"
DECLINE = r"^(not now|no thanks|no, thanks|maybe later|skip|decline|dismiss|close|cancel)$"


def _clear_prompts(page, log=None, rounds=4):
    """Tariq (2026-10-26): accept Copilot's "updated experience" notices; decline any upgrade / subscription offer."""
    for _ in range(rounds):
        clicked = False
        for b in page.locator("button, [role=button], a[role=button]").all()[:80]:
            try:
                if not b.is_visible(): continue
                t = " ".join((b.inner_text() or b.get_attribute("aria-label") or "").split()).lower()
            except Exception: continue
            if not t: continue
            if re.search(r"upgrade|subscribe|buy|premium|pro\b|free trial", t): continue   # never accept an upgrade
            ctx = ""
            try: ctx = page.inner_text("body")[:4000].lower()
            except Exception: pass
            upsell = bool(re.search(r"upgrade|subscribe|copilot pro|free trial|premium", ctx))
            if (upsell and re.match(DECLINE, t)) or (not upsell and re.match(ACCEPT, t)):
                try: b.click(timeout=2000); clicked = True; _log(log, f"    copilot: clicked '{t}'"); page.wait_for_timeout(1500); break
                except Exception: pass
        if not clicked: return


def _human_check(cfg, page):
    """A "verify you are human" check is never clicked or solved (bot-detection is not bypassed): stop and rest the route."""
    try: body = page.inner_text("body")
    except Exception: return
    if re.search(r"verify you are human|verification required|are you a robot|captcha", body, re.I):
        _evidence(cfg, page, "copilot_verify")
        raise RuntimeError("human verification required")


def _wikipedia(cfg, q):
    """Wikipedia's public API (no key, no bot check): the lead text of the best-matching articles."""
    import requests
    h = {"User-Agent": "VideoStudio/1.0 (personal documentary research tool)"}
    r = requests.get("https://en.wikipedia.org/w/api.php", params={"action": "query", "list": "search", "srsearch": q, "srlimit": 4,
                     "format": "json"}, headers=h, timeout=20)
    if r.status_code != 200: raise RuntimeError(f"HTTP {r.status_code}")
    titles = [x["title"] for x in r.json().get("query", {}).get("search", [])]
    if not titles: return []
    r = requests.get("https://en.wikipedia.org/w/api.php", params={"action": "query", "prop": "extracts", "exintro": 1, "explaintext": 1,
                     "exsentences": 4, "titles": "|".join(titles), "format": "json"}, headers=h, timeout=20)
    pages = (r.json().get("query", {}).get("pages", {}) or {}).values()
    return relevant([" ".join((p.get("title", "") + ": " + p.get("extract", "")).split()) for p in pages if p.get("extract")], q)[:4]


def _copilot(cfg, q, timeout=90):
    """Ask Copilot in the signed-in Microsoft 365 profile for a short factual description; its answer is the snippet."""
    from playwright.sync_api import sync_playwright
    ask = ("In 3-4 plain sentences, describe what the following looks like in real life (places, equipment, setting), "
           "for a documentary photographer: " + q)
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(**_browser(cfg, headless=False))
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto("https://copilot.microsoft.com/", wait_until="domcontentloaded", timeout=60000); page.wait_for_timeout(5000)
            _clear_prompts(page)
            _human_check(cfg, page)
            box = None
            for sel in ["#m365-chat-editor-target-element", "[aria-label='Message Copilot']", "textarea#userInput", "textarea", "[contenteditable=true]"]:
                loc = page.locator(sel)
                if loc.count(): box = loc.first; break
            if box is None: _evidence(cfg, page, "copilot"); raise RuntimeError("Copilot's message box was not found (screenshot in search_fail)")
            before = page.inner_text("body")
            box.click(); page.keyboard.insert_text(ask); page.wait_for_timeout(500); page.keyboard.press("Enter")
            t0, last, stable = time.time(), "", 0
            while time.time() - t0 < timeout:
                page.wait_for_timeout(2500)
                body = page.inner_text("body")
                if body == last: stable += 1
                else: stable, last = 0, body
                if stable >= 2 and len(body) > len(before) + 80: break
                if stable == 1: _clear_prompts(page, rounds=1); _human_check(cfg, page)
            k = last.rfind(ask[:60])   # the answer is the text after our own question (the sidebar comes before it)
            new = last[k + len(ask):] if k >= 0 else ""
            parts = [p.strip() for p in re.split(r"\n+", new) if len(p.split()) > 6 and not re.search(r"Press Tab|Message Copilot|Copilot may make mistakes", p)]
            _evidence(cfg, page, "copilot_last")
            if re.search(r"reached your daily limit", last, re.I):   # free plan quota: wait for the reset, never upgrade
                m = re.search(r"check back at ([0-9: ]+[AP]M)", last, re.I)
                raise RuntimeError("Copilot daily limit reached" + (f" (resets {m.group(1)})" if m else ""))
            if not parts: raise RuntimeError("Copilot gave no readable answer")
            return parts[:6]
        finally:
            ctx.close()


ROUTES = {"wikipedia": _wikipedia, "duckduckgo": _ddg, "bing": _bing, "copilot": _copilot, "google": _google}


def search(cfg, query, log=None):
    """-> (snippets, route). Never raises; ([], "") when every route is resting or failed."""
    st = _load(cfg); now = time.time()
    rr = int(st.get("next", 0)) % len(ROTATION)
    order = list(ROTATION[rr:] + ROTATION[:rr])
    st["next"] = (rr + 1) % len(ROTATION)
    g = st.get("google", {})
    if now - float(g.get("last", 0)) >= GOOGLE_MIN_GAP: order.append("google")   # last resort, rarely
    result, used = [], ""
    for name in order:
        rest = st.get(name, {}).get("rest_until", 0)
        if now < rest:
            _log(log, f"    search {name}: resting until {time.strftime('%H:%M', time.localtime(rest))}"); continue
        rec = st.setdefault(name, {})
        if name == "google": rec["last"] = now
        try:
            snippets = ROUTES[name](cfg, query)
            if snippets:
                rec.update(ok=rec.get("ok", 0) + 1, last_ok=now); result, used = snippets, name; break
            rec["empty"] = rec.get("empty", 0) + 1
            _log(log, f"    search {name}: no results; next route")
        except Exception as e:
            rest = 24 * 3600 if "human verification" in str(e) else 6 * 3600 if "daily limit" in str(e) else REST[name]
            rec.update(fail=rec.get("fail", 0) + 1, rest_until=now + rest, why=str(e)[:160])
            _log(log, f"    search {name}: {str(e)[:100]}; rested {rest // 60} min; next route")
    _save(cfg, st)
    _log(log, f"    search: {len(result)} snippet(s)" + (f" via {used}" if used else " (every route failed or resting)"))
    return result, used
