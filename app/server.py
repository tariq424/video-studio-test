"""Video Studio: YouTube link, audio file (e.g. NotebookLM) or text in -> long explainer and/or a 2-3 min vertical Short out. Runs locally."""
import os, sys, json, socket
from pathlib import Path
from flask import Flask, jsonify, request, send_from_directory, abort
sys.path.insert(0, str(Path(__file__).resolve().parent))
from studio import config
from studio.pipeline import Studio, STAGES, stages_for
from studio.wangp import WanGP

app = Flask(__name__, static_folder="static"); studio = Studio()

@app.get("/")
def index(): return send_from_directory(app.static_folder, "index.html")

@app.get("/api/settings")
def get_settings(): return jsonify(config.public())
@app.post("/api/settings")
def set_settings():
    try: config.save(request.json or {})
    except Exception as e: return jsonify(error=str(e)), 500
    return jsonify(config.public())

@app.post("/api/test_vision")
def test_vision():
    from studio import qa
    cfg = config.load(); b = request.json or {}
    ok, issue = qa.check(cfg, b["image"], b.get("prompt", "a photo"))
    return jsonify(ok=ok, issue=issue, provider=cfg.get("qa_provider"))

@app.get("/api/test_footage")
def test_footage():
    """Search every footage source once (keys never returned) so setup problems show up before a job runs."""
    from studio import footage
    q = request.args.get("q", "rocket launch"); orient = request.args.get("orient", "portrait"); logs = []
    out = {}
    for name, fn in (("Pexels", lambda: footage.pexels(q, orient, logs.append, 2560)), ("Pixabay", lambda: footage.pixabay(q, orient, logs.append, 2560)),
                     ("NASA", lambda: footage.nasa(q, logs.append, limit=3))):
        try: r = fn(); out[name] = {"count": len(r), "examples": [{"id": c["id"], "desc": c["desc"][:80], "size": f"{c['w']}x{c['h']}", "dur": c["dur"]} for c in r[:3]]}
        except Exception as e: out[name] = {"error": str(e)[:200]}
    keys = footage._keys()
    out["keys"] = {k: bool(keys.get(k)) for k in ("PEXELS_API_KEY", "PIXABAY_API_KEY")}; out["log"] = logs[-10:]
    return jsonify(out)

@app.post("/api/test_key")
def test_key():
    from studio.llm import LLM
    prov = (request.json or {}).get("provider", "zai")
    cfg = config.load(); cfg["script_provider"] = prov
    if prov == "local": return jsonify(ok=False, msg="Local AI has no key; it needs Ollama running.")
    if not cfg.get({"claude": "anthropic_api_key"}.get(prov, prov + "_api_key")): return jsonify(ok=False, msg="No key saved for " + prov)
    try:
        llm = LLM(cfg, lambda m: None); llm._chat("", "Reply with the single word OK.", 20)
        return jsonify(ok=True, msg=f"{prov}: key works with model {llm.name}")
    except Exception as e: return jsonify(ok=False, msg=f"{prov}: {str(e)[:300]}")

@app.get("/api/status")
def status():
    cfg = config.load()
    return jsonify(wangp=WanGP(cfg["wangp_mcp"]).alive(), api_key=bool(cfg.get("anthropic_api_key")), zai_key=bool(cfg.get("zai_api_key")), deepseek_key=bool(cfg.get("deepseek_api_key")), provider=cfg.get("script_provider"), current=studio.current, stages=STAGES)

@app.get("/api/jobs")
def jobs(): return jsonify(studio.list())

@app.post("/api/jobs")
def create():
    from studio.sources import kind_of
    if request.mimetype in ("multipart/form-data", "application/x-www-form-urlencoded"):   # web form (optionally with a file)
        b = {k: v for k, v in request.form.items()}; f = request.files.get("file")
        for k in ("presenter", "auto_approve", "captions"): b[k] = b.get(k) in ("true", "1", "on")
    else: b = request.get_json(silent=True) or {}; f = None
    if f is not None and f.filename and not kind_of(f.filename): return jsonify(error="Unsupported file type. Use audio (.mp3 .m4a .wav ...) or .txt .md .pdf .docx"), 400
    if not b.get("url") and not b.get("transcript") and not (f and f.filename): return jsonify(error="Give a YouTube link, a file, or paste some text."), 400
    jid = studio.create(b.get("url", "").strip(), b.get("minutes", 15), b.get("presenter", False), b.get("auto_approve", False), b.get("transcript", ""),
                        b.get("provider", ""), b.get("captions", True), b.get("mode", "both"), float(b.get("short_secs", 165) or 165),
                        f if (f and f.filename) else None, f.filename if f else "", b.get("src_title", ""), b.get("src_credit", ""))
    return jsonify(id=jid)

@app.get("/api/jobs/<jid>")
def job(jid):
    j = studio.job(jid)
    if not j.dir.exists(): abort(404)
    s = j.state; s["id"] = jid
    lp = j.dir / "log.txt"; s["log"] = lp.read_text(encoding="utf-8").splitlines()[-60:] if lp.exists() else []
    s["stages"] = stages_for(s.get("mode", "long"))
    sp = j.short_plan()
    if sp: s["short_summary"] = {"title": sp["title"], "beats": len(sp["sections"]), "words": sum(len(x["vo"].split()) for x in sp["sections"])}
    pl = j.plan()
    if pl: s["plan_summary"] = {"title": pl["title"], "sections": [{"id": x["id"], "title": x["title"], "words": len(x["vo"].split()), "visuals": len(x["visuals"])} for x in pl["sections"]]}
    return jsonify(s)

@app.get("/api/jobs/<jid>/plan")
def get_plan(jid): return jsonify(studio.job(jid).plan() or {})
@app.put("/api/jobs/<jid>/plan")
def put_plan(jid):
    from studio.writer import normalize
    studio.job(jid).save_plan(normalize(request.json)); studio.job(jid).log("Script edited in the web page"); return jsonify(ok=True)

@app.get("/api/jobs/<jid>/short_plan")
def get_short_plan(jid): return jsonify(studio.job(jid).short_plan() or {})
@app.put("/api/jobs/<jid>/short_plan")
def put_short_plan(jid):
    p = studio.job(jid).short_plan(); new = request.json or {}
    if not p: abort(404)
    p["title"] = new.get("title", p["title"])
    for a, b in zip(p["sections"], new.get("sections", [])):
        if isinstance(b.get("vo"), str) and b["vo"].strip(): a["vo"] = " ".join(b["vo"].split())
    studio.job(jid).save_short_plan(p); studio.job(jid).log("Short script edited in the web page"); return jsonify(ok=True)

@app.post("/api/jobs/<jid>/<action>")
def act(jid, action):
    {"approve": studio.approve, "resume": studio.resume, "stop": studio.stop}[action](jid); return jsonify(ok=True)

@app.get("/files/<jid>/<path:p>")
def files(jid, p):
    d = studio.job(jid).dir.resolve(); f = (d / p).resolve()
    if d not in f.parents or not f.exists(): abort(404)
    return send_from_directory(f.parent, f.name)

def free_port(p):
    for q in range(p, p + 50):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", q)) != 0: return q
    return p

if __name__ == "__main__":
    port = int(os.environ.get("PORT") or free_port(7870))
    print(f"Video Studio running on http://127.0.0.1:{port}", flush=True)
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
