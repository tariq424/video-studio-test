"""Job queue: one job renders at a time (single GPU). Each stage is resumable."""
import json, threading, time, traceback, re, shutil, datetime, queue
from pathlib import Path
from . import config, transcript, writer, render, assemble, media
from .wangp import WanGP

STAGES = ["transcript", "script", "review", "charts", "voice", "captions", "presenter", "motion", "stills", "assemble"]

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

    def create(self, url, minutes, presenter=False, auto_approve=False, transcript_text="", provider="", captions=True):
        jid = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        j = self.job(jid); j.dir.mkdir(parents=True); (j.dir / "src").mkdir()
        if transcript_text.strip(): (j.dir / "src" / "transcript_manual.txt").write_text(transcript_text, encoding="utf-8")
        j.save(url=url, minutes=float(minutes), presenter=bool(presenter), captions=bool(captions), auto_approve=bool(auto_approve), provider=provider or "", status="queued",
               stage="transcript", done=[], title="", created=time.time())
        j.log(f"Job created for {url} (target {minutes} min)"); self.q.put(jid); return jid

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
                rendering = j.state.get("stage") in ("charts", "voice", "captions", "presenter", "motion", "stills", "assemble")
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
        for st in STAGES:
            if st in j.state.get("done", []): continue
            if stop(): j.save(status="stopped"); log("Stopped"); self.cancel.discard(jid); return
            j.save(stage=st); log(f"== {st} ==")
            if st == "transcript":
                man = j.dir / "src" / "transcript_manual.txt"
                if man.exists():
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
                elif st == "motion": _need_wangp(wg); render.do_motion(j.dir, plan, cfg, wg, log, stop); j.save_plan(plan)
                elif st == "stills": _need_wangp(wg); render.do_stills(j.dir, plan, cfg, wg, log, stop)
                elif st == "assemble":
                    meta = json.loads((j.dir / "src" / "meta.json").read_text(encoding="utf-8"))
                    parts = assemble.build(j.dir, plan, log, stop, use_presenter=s.get("presenter", False), use_captions=s.get("captions", True)); final = assemble.finalize(j.dir, plan, parts, meta, log)
                    j.save(output=str(final))
            if stop(): j.save(status="stopped"); log("Stopped"); self.cancel.discard(jid); return
            d = j.state.get("done", []); d.append(st); j.save(done=d)
        j.save(status="finished", stage="done"); log("Finished.")

def _need_wangp(wg):
    if not wg.alive(): raise RuntimeError("WanGP is not running. Start Wan2GP in Pinokio, then press Resume.")
