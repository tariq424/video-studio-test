"""Job queue: one job renders at a time (single GPU). Each stage is resumable."""
import json, threading, time, traceback, re, shutil, datetime, queue
from pathlib import Path
from . import config, transcript, writer, render, assemble, media, sources, short
from .wangp import WanGP

STAGES = ["transcript", "script", "short_script", "review", "short_stock", "short_voice", "short_render",
          "charts", "voice", "captions", "broll", "presenter", "motion", "stills", "assemble"]
LONG = {"script", "charts", "voice", "captions", "broll", "presenter", "motion", "stills", "assemble"}
SHORT = {"short_script", "short_stock", "short_voice", "short_render"}
def stages_for(mode): return [s for s in STAGES if not ((mode == "short" and s in LONG) or (mode == "long" and s in SHORT))]

class Job:
    def __init__(self, path): self.dir = Path(path)
    @property
    def state(self):
        p = self.dir / "state.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    def save(self, **kw):
        s = self.state; s.update(kw); s["updated"] = time.time()
        (self.dir / "state.json").write_text(json.dumps(s, indent=1), encoding="utf-8")
    def log(self, msg):
        line = f"[{datetime.datetime.now():%H:%M:%S}] {msg}"
        with open(self.dir / "log.txt", "a", encoding="utf-8") as f: f.write(line + "\n")
    def plan(self):
        p = self.dir / "plan.json"; return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    def save_plan(self, plan): (self.dir / "plan.json").write_text(json.dumps(plan, indent=1), encoding="utf-8")
    def short_plan(self):
        p = self.dir / "short" / "plan.json"; return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    def save_short_plan(self, plan):
        (self.dir / "short").mkdir(exist_ok=True); (self.dir / "short" / "plan.json").write_text(json.dumps(plan, indent=1), encoding="utf-8")

class Studio:
    def __init__(self):
        self.q = queue.Queue(); self.current = None; self.cancel = set()
        threading.Thread(target=self._worker, daemon=True).start()

    def jobs_dir(self): d = Path(config.load()["jobs_dir"]); d.mkdir(parents=True, exist_ok=True); return d
    def job(self, jid): return Job(self.jobs_dir() / jid)
    def list(self):
        out = []
        for d in sorted(self.jobs_dir().iterdir(), reverse=True):
            if d.is_dir() and (d / "state.json").exists(): s = Job(d).state; s["id"] = d.name; out.append(s)
        return out

    def create(self, url, minutes, presenter=False, auto_approve=False, transcript_text="", provider="", captions=True,
               mode="both", short_secs=165, upload=None, upload_name="", src_title="", src_credit=""):
        jid = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        j = self.job(jid); j.dir.mkdir(parents=True); (j.dir / "src").mkdir()
        up = ""
        if upload is not None:
            up = re.sub(r"[^A-Za-z0-9._ -]+", "_", upload_name or "upload")[:80]; upload.save(str(j.dir / "src" / up))
        elif transcript_text.strip():
            (j.dir / "src" / ("transcript_manual.txt" if url else "pasted.txt")).write_text(transcript_text, encoding="utf-8")
        j.save(url=url, minutes=float(minutes), presenter=bool(presenter), captions=bool(captions), auto_approve=bool(auto_approve), provider=provider or "",
               mode=mode if mode in ("long", "short", "both") else "both", short_secs=max(120.0, min(176.0, float(short_secs))),
               upload=up, src_title=src_title, src_credit=src_credit, status="queued", stage="transcript", done=[], title="", created=time.time())
        what = url or (f"file {up}" if up else "pasted text")
        j.log(f"Job created for {what} (output: {mode}; long {minutes} min, short {short_secs:.0f}s)"); self.q.put(jid); return jid

    def approve(self, jid):
        j = self.job(jid); s = j.state
        if s.get("status") == "awaiting_review":
            d = s.get("done", []); d.append("review"); j.save(done=d, status="queued"); j.log("Script approved"); self.q.put(jid)
    def resume(self, jid):
        j = self.job(jid); self.cancel.discard(jid); j.save(status="queued", error=""); j.log("Resumed"); self.q.put(jid)
    def stop(self, jid): self.cancel.add(jid); self.job(jid).log("Stop requested")

    def _worker(self):
        while True:
            jid = self.q.get()
            try: self._run(jid)
            except Exception as e:
                j = self.job(jid); j.log("ERROR: " + str(e)); j.log(traceback.format_exc()[-1500:])
                n = int(j.state.get("auto_retries", 0))
                rendering = j.state.get("stage") in ("charts", "voice", "captions", "presenter", "motion", "stills", "assemble", "broll", "short_stock", "short_voice", "short_render")
                if rendering and n < 3 and jid not in self.cancel:
                    j.save(status="queued", error="", auto_retries=n + 1)
                    j.log(f"Retrying automatically in 60s (attempt {n + 1} of 3); finished work is kept")
                    threading.Timer(60, lambda jid=jid: self.q.put(jid)).start()
                else:
                    j.save(status="error", error=str(e)[:500])
            finally: self.current = None

    def _run(self, jid):
        j = self.job(jid); s = j.state; cfg = config.load(); self.current = jid
        stop = lambda: jid in self.cancel
        wg = WanGP(cfg["wangp_mcp"]); log = j.log
        j.save(status="running", error="")
        mode = s.get("mode", "long")
        for st in stages_for(mode):
            if st in j.state.get("done", []): continue
            if stop(): j.save(status="stopped"); log("Stopped"); self.cancel.discard(jid); return
            j.save(stage=st); log(f"== {st} ==")
            if st == "transcript":
                man = j.dir / "src" / "transcript_manual.txt"
                if not s.get("url"):
                    up = j.dir / "src" / s["upload"] if s.get("upload") else None
                    meta, text = sources.load(j.dir / "src", up, s.get("src_title", ""), s.get("src_credit", ""), log)
                elif man.exists():
                    text = man.read_text(encoding="utf-8"); meta = {"title": "Pasted transcript", "webpage_url": s.get("url", "")}
                    try: meta, _ = transcript.fetch(s["url"], j.dir / "src", log) if s.get("url") else (meta, "")
                    except Exception as e: log(f"  (metadata fetch failed: {e})")
                    (j.dir / "src" / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
                    (j.dir / "src" / "transcript.txt").write_text(text, encoding="utf-8")
                else:
                    meta, text = transcript.fetch(s["url"], j.dir / "src", log)
                j.save(title=meta.get("title", ""))
            elif st == "script":
                if s.get("provider"): cfg["script_provider"] = s["provider"]
                prov = cfg.get("script_provider", "claude")
                if prov == "claude" and not cfg.get("anthropic_api_key"): raise RuntimeError("Add your Anthropic API key in Settings (or pick another Script AI).")
                if prov in ("zai", "deepseek") and not cfg.get(prov + "_api_key"): raise RuntimeError(f"Add your {prov} API key in Settings (or pick another Script AI).")
                meta = json.loads((j.dir / "src" / "meta.json").read_text(encoding="utf-8"))
                text = (j.dir / "src" / "transcript.txt").read_text(encoding="utf-8")
                plan = writer.write_plan(cfg, meta, text, s["minutes"], log, stop, j.dir / "src"); j.save_plan(plan)
            elif st == "short_script":
                if s.get("provider"): cfg["script_provider"] = s["provider"]
                meta = json.loads((j.dir / "src" / "meta.json").read_text(encoding="utf-8"))
                text = (j.dir / "src" / "transcript.txt").read_text(encoding="utf-8")
                lp = j.plan()
                sp = short.write_short(cfg, meta, text, s.get("short_secs", 165), mode, lp["title"] if lp else "", log, stop, j.dir / "src")
                j.save_short_plan(sp)
                if not lp: j.save(title=sp["title"])
            elif st in ("short_stock", "short_voice", "short_render"):
                sp = j.short_plan()
                if st == "short_stock":
                    if "short_voice" not in j.state.get("done", []) and wg.alive():
                        # footage (network + DeepSeek + a little GPU) and narration (GPU) run side by side
                        errs = []
                        def _stock():
                            try: short.do_stock(j.dir, sp, cfg, log, stop)
                            except Exception as e: errs.append(e)
                        th = threading.Thread(target=_stock, daemon=True); th.start()
                        log("Footage and narration run in parallel")
                        try: short.do_voice(j.dir, sp, cfg, wg, log, stop)
                        finally: th.join()   # never leave footage running into a retry
                        d = j.state.get("done", []); d.append("short_voice"); j.save(done=d)
                        if errs: raise errs[0]
                    else: short.do_stock(j.dir, sp, cfg, log, stop)
                elif st == "short_voice": _need_wangp(wg); short.do_voice(j.dir, sp, cfg, wg, log, stop)
                else:
                    meta = json.loads((j.dir / "src" / "meta.json").read_text(encoding="utf-8"))
                    out = short.do_render(j.dir, sp, cfg, meta, log, stop); j.save(short_output=str(out))
            elif st == "review":
                if not s.get("auto_approve"):
                    j.save(status="awaiting_review"); log("Script ready for review. Edit if you like, then press Approve."); return
            else:
                plan = j.plan()
                if st == "charts": render.do_charts(j.dir, plan, cfg, log)
                elif st == "voice": _need_wangp(wg); render.do_voice(j.dir, plan, cfg, wg, log, stop)
                elif st == "captions":
                    if s.get("captions", True):
                        from . import captions as C
                        for sec in plan["sections"]:
                            if stop(): raise RuntimeError("cancelled")
                            caps = C.build_section(cfg, j.dir, sec["id"], sec["vo"], log)
                            log(f"Captions {sec['id']}: {len(caps)} lines, {sum(1 for c in caps if c.get('emoji_png'))} icons")
                elif st == "presenter":
                    if s.get("presenter", False): _need_wangp(wg); render.do_presenter(j.dir, plan, cfg, wg, log, stop)
                elif st == "broll":
                    if cfg.get("long_broll", True):
                        from . import footage
                        footage.long_broll(j.dir, plan, cfg, log, stop); j.save_plan(plan)
                elif st == "motion":
                    if any(v["type"] == "motion" and not v.get("stock") for x in plan["sections"] for v in x["visuals"]): _need_wangp(wg)
                    render.do_motion(j.dir, plan, cfg, wg, log, stop); j.save_plan(plan)
                elif st == "stills":
                    if any(v["type"] == "still" and not v.get("stock") for x in plan["sections"] for v in x["visuals"]): _need_wangp(wg)
                    render.do_stills(j.dir, plan, cfg, wg, log, stop)
                elif st == "assemble":
                    meta = json.loads((j.dir / "src" / "meta.json").read_text(encoding="utf-8"))
                    parts = assemble.build(j.dir, plan, log, stop, use_presenter=s.get("presenter", False), use_captions=s.get("captions", True)); final = assemble.finalize(j.dir, plan, parts, meta, log)
                    j.save(output=str(final))
            if stop(): j.save(status="stopped"); log("Stopped"); self.cancel.discard(jid); return
            d = j.state.get("done", []); d.append(st); j.save(done=d)
        j.save(status="finished", stage="done"); log("Finished.")

def _need_wangp(wg):
    if not wg.alive(): raise RuntimeError("WanGP is not running. Start Wan2GP in Pinokio, then press Resume.")
