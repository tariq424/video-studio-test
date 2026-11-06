"""SPEC-Z005 Media Routes POC — standalone smoke-test GUI on 127.0.0.1:42054.

No Video Studio code. Single FastAPI app: serves the one-page GUI, per-route RUN,
RUN ALL (sequential; browser and GPU routes serialized by simply running one at a
time), output preview serving, per-profile OPEN LOGIN, and smoke-report.json.
"""
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

import routes
from routes import ROUTES, OUT, ROOT, Blocker

PORT = 42054
app = FastAPI(title="Media Routes POC")
_lock = threading.Lock()
_state = {r["id"]: {"status": "idle", "seconds": None, "output": None, "note": "", "error": ""} for r in ROUTES}
_upload = {"path": None}
_runs = 0
_last = {"desc": "", "aspect": "16:9"}   # (Z009 §E) cards show the LAST saved result, not "idle"
_rep = OUT / "smoke-report.json"
if _rep.is_file():
    try:
        for row in json.loads(_rep.read_text(encoding="utf-8")).get("routes", []):
            if row["id"] in _state:
                _state[row["id"]].update(status=row.get("result", "idle"), seconds=row.get("seconds"),
                                         output=row.get("output"), note=row.get("note", ""),
                                         error=row.get("error", ""))
    except Exception:
        pass
_last = {"desc": "", "aspect": "16:9"}


def _latest_image():
    if _upload["path"]:
        return _upload["path"]
    for pat in ("r1_*.jpg", "r2_*.jpg", "r6_meta*.jpg"):
        got = sorted(OUT.glob(pat))
        if got:
            return str(got[-1])
    return None


def _run_route(rid, desc, aspect):
    global _runs
    _last.update(desc=desc, aspect=aspect)
    with _lock:
        st = _state[rid]
        if st["status"] == "running":
            return
        st.update(status="running", seconds=None, output=None, note="", error="")
    route = next(r for r in ROUTES if r["id"] == rid)
    ctx = {}
    t0 = time.time()
    try:
        out = route["fn"](desc, aspect, _latest_image() if route.get("needs_image") else _upload["path"], ctx)
        with _lock:
            st.update(status="ok", seconds=round(time.time() - t0, 1),
                      output=str(out), note=ctx.get("card_note", ""), error="")
    except Blocker as b:
        with _lock:
            st.update(status="blocker", seconds=round(time.time() - t0, 1), note=str(b), output=None)
    except Exception as e:
        with _lock:
            st.update(status="failed", seconds=round(time.time() - t0, 1),
                      error=f"{type(e).__name__}: {str(e)[:220]}")
    _runs += 1


def _write_report():
    rep = {"generated": time.strftime("%Y-%m-%d %H:%M:%S"), "port": PORT,
           "description": _last["desc"][:200], "aspect": _last["aspect"], "routes": []}
    for r in ROUTES:
        st = _state[r["id"]]
        rep["routes"].append({"id": r["id"], "name": r["name"], "result": st["status"],
                              "seconds": st["seconds"], "output": st["output"],
                              "note": st["note"], "error": st["error"]})
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "smoke-report.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    return rep


def _desc_default():
    return ("A white passenger jet with exactly two wings descending through clouds toward a "
            "runway at dusk, photorealistic")


@app.get("/", response_class=HTMLResponse)
def home():
    return PAGE.replace("__DEFAULT_DESC__", _desc_default()).replace("__ROUTES_JSON__", json.dumps(
        [{"id": r["id"], "name": r["name"], "proves": r["proves"],
          "needs_image": r.get("needs_image", False)} for r in ROUTES]))


@app.get("/healthz")
def healthz():
    return {"ok": True, "port": PORT, "routes": len(ROUTES)}


@app.get("/api/state")
def state():
    return {"state": _state, "upload": _upload["path"]}


@app.post("/api/description")
def description(desc: str = Form(...), aspect: str = Form("16:9")):
    return {"saved": True}


@app.post("/api/run/{rid}")
def run(rid: str, desc: str = Form("__DEFAULT_DESC__"), aspect: str = Form("16:9")):
    if rid not in _state:
        return JSONResponse({"error": "unknown route"}, status_code=404)
    threading.Thread(target=_run_route, args=(rid, desc, aspect), daemon=True).start()
    return {"started": rid}


@app.post("/api/upload")
def upload(file: UploadFile = File(None)):
    if file is None or not file.filename:
        return {"saved": None}
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / f"upload_{Path(file.filename).name}"
    p.write_bytes(file.file.read())
    _upload["path"] = str(p)
    return {"saved": str(p)}


@app.post("/api/run-all")
def run_all(desc: str = Form("__DEFAULT_DESC__"), aspect: str = Form("16:9")):
    def worker():
        for r in ROUTES:
            _run_route(r["id"], desc, aspect)
        _write_report()
    threading.Thread(target=worker, daemon=True).start()
    return {"started": "all"}


@app.get("/api/report")
def report():
    p = OUT / "smoke-report.json"
    return JSONResponse(json.loads(p.read_text(encoding="utf-8"))) if p.is_file() else {"none": True}


def _find_chrome():
    """Real chrome.exe (SPEC-Z009 §F: Playwright-driven browsers can't do real sign-ins —
    Google refuses them outright, ChatGPT serves the Cloudflare splash)."""
    cands = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    exe = shutil.which("chrome")
    if exe:
        return exe
    for c in cands:
        if Path(c).is_file():
            return c
    return None


@app.get("/api/login/{site}")
def login(site: str):
    if site not in routes.HOME_URLS:
        return JSONResponse({"error": "unknown site"}, status_code=404)
    chrome = _find_chrome()
    if not chrome:
        return JSONResponse({"error": "chrome.exe not found for OPEN LOGIN"}, status_code=500)
    routes._repair_prefs(site)          # same clean-exit repair _browser() does
    prof = str(routes.PROFILES / site)
    subprocess.Popen([chrome,
                      f"--user-data-dir={prof}",
                      "--hide-crash-restore-bubble",
                      "--window-position=60,60", "--window-size=1280,900",
                      "--lang=en-US",
                      routes.HOME_URLS[site]])
    return {"opened": site, "browser": "real chrome"}


@app.get("/output/{name}")
def output_file(name: str):
    p = (OUT / name).resolve()
    if not str(p).startswith(str(OUT.resolve())) or not p.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(p)


PAGE = """<!doctype html><html><head><title>Media Routes POC :42054</title><style>
body{font-family:Segoe UI,system-ui,sans-serif;background:#10141c;color:#dfe5ee;margin:0;padding:18px}
h1{font-size:20px;margin:0 0 4px} .sub{color:#8b96a8;font-size:12px;margin-bottom:14px}
textarea{width:60%;min-height:52px;background:#1a2130;color:#dfe5ee;border:1px solid #2c3648;border-radius:8px;padding:8px;font:inherit}
select,button{background:#24304a;color:#dfe5ee;border:1px solid #35435f;border-radius:8px;padding:8px 12px;font:inherit;cursor:pointer}
.runall{background:#2f6feb;border-color:#2f6feb;font-weight:600;padding:10px 18px}
.cards{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:14px}
.card{background:#171e2b;border:1px solid #263145;border-radius:12px;padding:12px}
.card h3{margin:0 0 2px;font-size:14px}.proves{color:#8b96a8;font-size:11.5px;margin-bottom:8px}
.st{font-size:12px;padding:2px 8px;border-radius:6px;display:inline-block}
.idle{background:#24304a}.running{background:#8a6d1a}.ok{background:#1f6b3a}.blocker{background:#5a4a12}.failed{background:#6b1f1f}
.note{color:#aab6c8;font-size:11.5px;margin-top:6px;white-space:pre-wrap}
.preview img,.preview video{max-width:100%;max-height:220px;margin-top:8px;border-radius:8px}
.logins{margin-top:16px;background:#171e2b;border:1px solid #263145;border-radius:12px;padding:12px}
.loginbtn{margin:4px 6px 0 0;background:#173a2a;border-color:#1f6b3a}
#summary{margin-top:14px}.summary table{border-collapse:collapse;font-size:12px}
.summary td,.summary th{border:1px solid #263145;padding:4px 8px;text-align:left}
</style></head><body>
<h1>Media Routes POC <span style="color:#2f6feb">:42054</span></h1>
<div class="sub">Standalone smoke test — no Video Studio code, no QC gate. Tariq judges the outputs.
Blockers are precise reasons (no token / not signed in / not installed) and count as plumbing PASSes.</div>
<div><textarea id="desc">__DEFAULT_DESC__</textarea>
<select id="aspect"><option>16:9</option><option>9:16</option></select>
<button class="runall" onclick="runall()">RUN ALL</button>
<label style="margin-left:12px;font-size:12px;color:#8b96a8">image for describe/i2v routes:
<input type="file" id="imgfile" accept="image/*"></label>
<span id="upl" class="note"></span></div>
<div class="cards" id="cards"></div>
<div class="logins"><b>Sign-ins</b> — one visible browser per profile (media-poc/profiles/&lt;site&gt;), sign in once and close:
<button class="loginbtn" onclick="login('chatgpt')">OPEN LOGIN: ChatGPT</button>
<button class="loginbtn" onclick="login('bing')">OPEN LOGIN: Bing</button>
<button class="loginbtn" onclick="login('meta')">OPEN LOGIN: meta.ai</button>
<button class="loginbtn" onclick="login('flow')">OPEN LOGIN: Google Flow</button>
<button class="loginbtn" onclick="login('marble')">OPEN LOGIN: Marble</button></div>
<div class="summary" id="summary"></div>
<script>
const ROUTES = __ROUTES_JSON__;
const cards = document.getElementById('cards');
for (const r of ROUTES) {
  cards.insertAdjacentHTML('beforeend', `<div class="card" id="c_${r.id}">
   <h3>${r.name} <span class="st idle" id="s_${r.id}">idle</span></h3>
   <div class="proves">${r.proves}${r.needs_image ? ' · needs an image (upload or an image route first)' : ''}</div>
   <button onclick="run('${r.id}')">RUN</button>
   <div class="note" id="n_${r.id}"></div>
   <div class="preview" id="p_${r.id}"></div></div>`);
}
async function run(rid){ await fetch(`/api/run/${rid}`, {method:'POST',
  body:new URLSearchParams({desc:document.getElementById('desc').value, aspect:document.getElementById('aspect').value})}); }
async function runall(){ await fetch('/api/run-all', {method:'POST',
  body:new URLSearchParams({desc:document.getElementById('desc').value, aspect:document.getElementById('aspect').value})}); }
async function login(site){ await fetch(`/api/login/${site}`); }
document.getElementById('imgfile').addEventListener('change', async ev => {
  const f = new FormData(); if (ev.target.files[0]) f.append('file', ev.target.files[0]);
  const r = await (await fetch('/api/upload', {method:'POST', body:f})).json();
  document.getElementById('upl').textContent = r.saved ? ('uploaded: ' + r.saved) : ''; });
const PRE = ['jpg','jpeg','png','webp'];
async function refresh(){
  const d = await (await fetch('/api/state')).json();
  for (const r of ROUTES){
    const st = d.state[r.id];
    const s = document.getElementById('s_'+r.id);
    s.className = 'st ' + st.status;
    s.textContent = st.status + (st.seconds != null ? ' ' + st.seconds + 's' : '');
    document.getElementById('n_'+r.id).textContent = st.note || st.error || '';
    const p = document.getElementById('p_'+r.id);
    if (st.output){
      const u = '/output/' + st.output.split(/[\\\\/]/).pop();
      if (p.dataset.out !== st.output){
        p.dataset.out = st.output;
        const ext = u.split('.').pop().toLowerCase();
        p.innerHTML = PRE.includes(ext) ? `<img src="${u}">` : `<video controls src="${u}"></video>`;
      }
    } else { p.innerHTML = ''; p.dataset.out = ''; }
  }
  const rep = await (await fetch('/api/report')).json();
  if (rep.routes){
    document.getElementById('summary').innerHTML = '<h3>Smoke report</h3><table><tr><th>route</th><th>result</th><th>sec</th><th>output</th><th>note</th></tr>' +
      rep.routes.map(x => `<tr><td>${x.name}</td><td>${x.result}</td><td>${x.seconds ?? ''}</td><td>${(x.output||'').split(/[\\\\/]/).pop()}</td><td>${(x.note||x.error||'').slice(0,90)}</td></tr>`).join('') + '</table>';
  }
}
setInterval(refresh, 2000); refresh();
</script></body></html>"""


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="info")
