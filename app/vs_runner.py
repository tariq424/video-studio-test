"""Video Studio runner: drives the real web page with Playwright, by data-testid only (no LLM here).

  python vs_runner.py --job <run>/spec.json --out <run> [--url http://127.0.0.1:42020]

spec.json = {"spec": <job spec>, "click_make": false, "edit": null | {"job", "beat", "cands": [..], "fit": "auto"}}
Fills the New-video form from the spec and screenshots each step. Clicks Make video only when click_make is true (automated tests;
on the /make page you click it yourself). With click_make it then follows the job until it finishes. With edit, it opens the
finished job, replaces the beat through the beat-edit panel, and checks the splice (frame count, audio, decoding).
Progress: <run>/steps.jsonl (one JSON object per step), screenshots <run>/NN_<step>.png. Uses its own headless browser
(Microsoft Edge if installed, else Playwright's Chromium)."""
import argparse, json, subprocess, sys, time
from pathlib import Path

def ensure_playwright():
    try:
        import playwright  # noqa
    except ImportError:
        print("installing playwright (one time)...", flush=True)
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "playwright"], check=True)

class Run:
    def __init__(self, out): self.out = Path(out); self.n = 0; self.page = None
    def step(self, name, ok=True, detail="", shot=True):
        self.n += 1; fn = ""
        if shot and self.page is not None:
            fn = f"{self.n:02d}_{name.replace(' ', '_')[:40]}.png"
            try: self.page.screenshot(path=str(self.out / fn), full_page=False)
            except Exception: fn = ""
        rec = {"t": time.strftime("%H:%M:%S"), "step": name, "ok": ok, "detail": str(detail)[:400], "shot": fn}
        with open(self.out / "steps.jsonl", "a", encoding="utf-8") as f: f.write(json.dumps(rec) + "\n")
        print(json.dumps(rec), flush=True)

def browser(p):
    for kw in ({"channel": "msedge"}, {"channel": "chrome"}, {}):
        try: return p.chromium.launch(headless=True, **kw)
        except Exception as e: last = e
    subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
    return p.chromium.launch(headless=True)

T = lambda t: f'[data-testid="{t}"]'

def fill(page, spec, run):
    i, o, pl = spec["input"], spec["output"], spec["pipeline"]
    page.select_option(T("input-type"), {"youtube": "yt", "local_file": "file", "text": "text"}[i["type"]])
    if i["type"] == "youtube":
        page.fill(T("youtube-url"), i.get("source", ""))
        if i.get("transcript"): page.evaluate("t=>{document.querySelector('[data-testid=transcript-text]').value=t}", i["transcript"])
    elif i["type"] == "local_file":
        src = i.get("source", "")
        if src and Path(src).is_file(): page.set_input_files(T("file-upload"), src)
        else: page.fill(T("file-path"), src)
    else: page.fill(T("source-text"), i.get("source", ""))
    if i["type"] != "youtube":
        page.fill(T("source-title"), i.get("title", "")); page.fill(T("source-credit"), i.get("credit", ""))
    run.step("source filled", detail=f"{i['type']}: {i.get('source', '')[:80]}")
    page.select_option(T("output-mode"), {"short": "short", "explainer": "long", "both": "both", "smoke": "smoke"}[o["mode"]])
    def rng(tid, v):
        page.evaluate("([t,v])=>{const e=document.querySelector(`[data-testid=${t}]`);e.value=v;e.dispatchEvent(new Event('input',{bubbles:true}))}", [tid, str(v)])
    if o["mode"] in ("short", "both"): rng("short-length", o["short_length"])
    if o["mode"] in ("explainer", "both"):
        rng("long-length", o["long_minutes"])
        page.set_checked(T("toggle-captions"), bool(pl.get("captions", True)))
        page.set_checked(T("toggle-presenter"), bool(pl.get("presenter", False)))
    page.select_option(T("script-ai"), pl.get("script_ai", ""))
    page.select_option(T("audience"), pl.get("audience", ""))
    if o["mode"] != "explainer": page.select_option(T("visuals-mode"), "every" if pl.get("visuals") == "review" else "auto")
    page.set_checked(T("toggle-skip-script-review"), not pl.get("script_review", False))
    run.step("options set", detail=json.dumps({"mode": o["mode"], "short": o["short_length"], "long": o["long_minutes"], **pl}))

def follow(page, api, jid, run, timeout_h=3):
    import urllib.request
    t0 = time.time(); last_stage = ""; last_shot = 0
    while time.time() - t0 < timeout_h * 3600:
        s = json.loads(urllib.request.urlopen(f"{api}/api/jobs/{jid}").read())   # the job's state.json (not the page text)
        st, stage = s.get("status"), s.get("stage")
        if stage != last_stage or time.time() - last_shot > 120:
            run.step(f"job {stage}", detail=f"{st}: " + (s.get("log") or [""])[-1][:200], shot=True); last_stage, last_shot = stage, time.time()
        if st in ("finished", "error", "stopped", "awaiting_review", "awaiting_visuals"): return s
        time.sleep(5)
    return {"status": "timeout"}

def edit_beat(page, api, e, run):
    import urllib.request
    page.goto(f"{api}/"); page.wait_for_selector(T("new-video-form"))
    page.evaluate("jid=>{sel=jid;lastKey='';loadJobs()}", e["job"])
    page.wait_for_selector("#ov", timeout=30000)
    beats = json.loads(urllib.request.urlopen(f"{api}/api/jobs/{e['job']}/edit/beats").read())["beats"]
    b = next(x for x in beats if x["id"] == e["beat"])
    page.evaluate("t=>{const v=document.getElementById('ov');v.currentTime=t;edTick()}", b["start"] + b["dur"] / 2)
    page.click(T("edit-at") + f'[data-beat="{e["beat"]}"]', timeout=20000)
    page.wait_for_selector(T("edit-treatment"), timeout=120000)
    run.step("beat panel open", detail=e["beat"])
    # tick boxes through the page's own handlers (the treatments sit in a sideways-scrolling row, and the panel redraws
    # after every tick, so element handles go stale)
    page.evaluate("""ids=>{for(let k=0;k<50;k++){const on=document.querySelector('[data-testid=edit-choose]:checked');if(!on)break;on.click()}
      for(const id of ids){const b=document.querySelector(`[data-testid=edit-choose][data-cand="${id}"]`);if(b&&!b.checked)b.click()}}""", e.get("cands") or [])
    got = page.evaluate("()=>[...document.querySelectorAll('[data-testid=edit-choose]:checked')].map(b=>b.dataset.cand)")
    if got != list(e.get("cands") or []): raise RuntimeError(f"couldn't select {e.get('cands')} (selected: {got})")
    if e.get("fit"): page.click(T(f"edit-fit-{e['fit']}"))
    run.step("treatment chosen", detail=f"{e.get('cands')} fit={e.get('fit', 'auto')}")
    n0 = len(json.loads(urllib.request.urlopen(f"{api}/api/jobs/{e['job']}").read()).get("edits", []))
    page.click(T("edit-apply"))
    t0 = time.time()
    while time.time() - t0 < 1800:
        d = json.loads(urllib.request.urlopen(f"{api}/api/jobs/{e['job']}/edit/beats").read())
        if not d.get("busy"):
            s = json.loads(urllib.request.urlopen(f"{api}/api/jobs/{e['job']}").read()); eds = s.get("edits", [])
            if d.get("error"): run.step("edit failed", ok=False, detail=d["error"]); return False
            if len(eds) > n0:
                v = eds[-1].get("verify", {})
                ok = all(v.get(k, False) for k in ("frames_same", "audio_same", "decode_ok"))
                run.step("splice verified" if ok else "splice check failed", ok=ok, detail=json.dumps(v)); return ok
        time.sleep(3)
    run.step("edit timed out", ok=False); return False

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--job", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--url", default="http://127.0.0.1:42020"); a = ap.parse_args()
    job = json.loads(Path(a.job).read_text(encoding="utf-8")); run = Run(a.out)
    ensure_playwright()
    from playwright.sync_api import sync_playwright
    ok = True
    with sync_playwright() as p:
        b = browser(p); page = b.new_page(viewport={"width": 1280, "height": 1000}); run.page = page
        try:
            if job.get("spec"):
                page.goto(f"{a.url}/"); page.wait_for_selector(T("make-video"))
                run.step("page open", detail=a.url)
                fill(page, job["spec"], run)
                page.locator(T("new-video-form")).screenshot(path=str(Path(a.out) / "form.png"))
                if job.get("click_make"):
                    page.click(T("make-video"))
                    page.wait_for_selector(T("job-status"), timeout=60000)
                    jid = page.evaluate("sel"); run.step("job started", detail=jid)
                    s = follow(page, a.url, jid, run)
                    ok = s.get("status") == "finished"
                    run.step("job " + str(s.get("status")), ok=ok, detail=s.get("short_output") or s.get("output") or s.get("error", ""))
                else:
                    run.step("form ready (Make video not clicked)", detail="review the form and click Make video yourself")
            if job.get("edit"):
                ok = edit_beat(page, a.url, job["edit"], run) and ok
        except Exception as e:
            ok = False; run.step("error", ok=False, detail=repr(e)[:400])
        finally:
            run.step("done" if ok else "done with problems", ok=ok, shot=False); b.close()
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    main()
