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
    return jsonify(wangp=WanGP(cfg).alive(), api_key=bool(cfg.get("anthropic_api_key")), zai_key=bool(cfg.get("zai_api_key")), deepseek_key=bool(cfg.get("deepseek_api_key")), provider=cfg.get("script_provider"), current=studio.current, stages=STAGES)

@app.get("/api/jobs")
def jobs(): return jsonify(studio.list())

@app.post("/api/jobs")
def create():
    from studio.sources import kind_of
    if request.mimetype in ("multipart/form-data", "application/x-www-form-urlencoded"):   # web form (optionally with a file)
        b = {k: v for k, v in request.form.items()}; f = request.files.get("file")
        b.setdefault("auto_approve", "true")   # script review is skipped unless the user ticks it off
        for k in ("presenter", "auto_approve", "captions"): b[k] = b.get(k) in ("true", "1", "on", True)
    else: b = request.get_json(silent=True) or {}; f = None
    if f is not None and f.filename and not kind_of(f.filename): return jsonify(error="Unsupported file type. Use audio (.mp3 .m4a .wav ...) or .txt .md .pdf .docx"), 400
    if not b.get("url") and not b.get("transcript") and not (f and f.filename): return jsonify(error="Give a YouTube link, a file, or paste some text."), 400
    jid = studio.create(b.get("url", "").strip(), b.get("minutes", 15), b.get("presenter", False), b.get("auto_approve", True), b.get("transcript", ""),
                        b.get("provider", ""), b.get("captions", True), b.get("mode", "both"), float(b.get("short_secs", 165) or 165),
                        f if (f and f.filename) else None, f.filename if f else "", b.get("src_title", ""), b.get("src_credit", ""),
                        b.get("visual_review", "auto"))
    return jsonify(id=jid)

@app.post("/api/smoke")
def smoke():
    """One-beat test job with a fixed script (exercises the visual ladder, the review pause, the render and the thumbnail)."""
    b = request.get_json(silent=True) or {}
    return jsonify(id=studio.create_smoke(b.get("visual_review", "every")))

# ---- visual review (Shorts)
def _rv_payload(jid):
    from studio import review
    rv = review.load(studio.job(jid).dir)
    if not rv: abort(404)
    return rv

@app.get("/api/jobs/<jid>/review")
def get_review(jid): return jsonify(_rv_payload(jid))

@app.post("/api/jobs/<jid>/review/<bid>")
def review_beat(jid, bid):
    from studio import review
    b = request.get_json(silent=True) or {}; a = b.get("action"); j = studio.job(jid); cfg = config.load()
    try:
        if a in ("auto", "skip", "choose", "undo", "revert"):
            review.decide(j.dir, bid, a, b.get("cands") if a != "revert" else b.get("i"), cfg, j.log)
            j.log(f"Visual review {bid}: {a}" + (f" {', '.join(b.get('cands') or [])}" if a == "choose" else ""))
        elif a == "supply": review.supply(j.dir, bid, b.get("src", ""), b.get("tag", ""), cfg, j.log); j.log(f"Visual review {bid}: your file added")
        elif a in ("expand", "refine"):
            err = review.start(studio, jid, bid, a, {"text": b.get("text", ""), "tag": b.get("tag", "")})
            if err: return jsonify(error=err), 409
        else: return jsonify(error="unknown action"), 400
    except Exception as e: return jsonify(error=str(e)[:300]), 400
    return jsonify(_rv_payload(jid))

@app.post("/api/jobs/<jid>/review_all/<action>")
def review_all(jid, action):
    from studio import review
    j = studio.job(jid)
    try:
        if action == "approve_all": review.approve_all(j.dir); j.log("Visual review: approved the auto picks for all remaining beats")
        elif action != "continue": return jsonify(error="unknown action"), 400
        studio.continue_visuals(jid)
    except Exception as e: return jsonify(error=str(e)[:300]), 400
    return jsonify(ok=True)

@app.post("/api/jobs/<jid>/preview/<cid>")
def review_preview(jid, cid):
    from studio import review
    j = studio.job(jid)
    try: return jsonify(review.preview(j.dir, cid, config.load(), j.log))
    except Exception as e: return jsonify(error=str(e)[:300]), 400

@app.get("/api/jobs/<jid>/thumbnail")
def get_thumb(jid):
    from studio import thumb916
    return jsonify(thumb916.options(studio.job(jid).dir))

@app.post("/api/jobs/<jid>/thumbnail")
def set_thumb(jid):
    from studio import thumb916
    j = studio.job(jid); b = request.get_json(silent=True) or {}
    try:
        if b.get("approve"):
            o = thumb916.options(j.dir); o["approved"] = True
            (j.dir / "short" / "thumb.json").write_text(json.dumps(o, indent=1), encoding="utf-8"); j.log("Thumbnail approved"); return jsonify(o)
        opts = {k: b.get(k) for k in ("beat", "size", "color", "text")}
        if b.get("src"):   # your own picture (a path on this PC or a URL)
            from studio import review
            src = b["src"].strip().strip('"')
            if src.lower().startswith("http"):
                import requests
                r = requests.get(src, timeout=60, headers={"User-Agent": "VideoStudio/1.0"})
                if r.status_code != 200 or "text/html" in r.headers.get("content-type", ""): raise RuntimeError("couldn't download that image")
                p = j.dir / "short" / "thumb_src.jpg"; p.write_bytes(r.content); src = str(p)
            opts["image"] = src
        elif "beat" in b and b.get("beat"): opts["image"] = ""
        thumb916.make(j.dir, j.short_plan(), config.load(), j.log, opts)
        return jsonify(thumb916.options(j.dir))
    except Exception as e: return jsonify(error=str(e)[:300]), 400

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

@app.post("/api/jobs/<jid>/transcript")
def paste_transcript(jid):
    t = ((request.get_json(silent=True) or {}).get("text") or "").strip()
    if len(t.split()) < 50: return jsonify(error="That transcript is too short (need at least 50 words)."), 400
    studio.set_transcript(jid, t); return jsonify(ok=True)

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
    # fixed address http://127.0.0.1:42020 (PORT overrides); if it's taken, the next free port is used and printed
    want = int(os.environ.get("PORT") or 42020)
    port = want if os.environ.get("WERKZEUG_RUN_MAIN") else free_port(want)   # the reloader's child must reuse the parent's port
    os.environ["PORT"] = str(port)
    if port != want: print(f"Port {want} is busy; using {port} instead", flush=True)
    print(f"Video Studio running on http://127.0.0.1:{port}", flush=True)
    # VS_RELOAD=1: restart automatically when a .py file changes (development only - it also stops a running render;
    # the job is then marked stopped and Resume continues it)
    reload = os.environ.get("VS_RELOAD") == "1"
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True, use_reloader=reload)
