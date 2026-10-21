"""Minimal client for WanGP's local MCP server (streamable HTTP), started ON DEMAND.

Memory policy (WanGP holds many GB of VRAM): nothing starts WanGP when a job starts. The first real generation request
(a presenter clip, an atmospheric still, the TTS fallback) launches WanGP's MCP server from its Pinokio install
(wangp_dir, default C:/pinokio/api/wan.git); as soon as that generation (or a held batch, e.g. all presenter clips) is
done, the process is stopped, which unloads every model and frees the VRAM. A WanGP that was already running (started in
Pinokio by you) is used but never stopped by the pipeline. Settings: wangp_on_demand (true), wangp_start_timeout (300 s).

The MCP port is picked by Pinokio at start-up and can change, so the URL is found automatically:
1) the "WanGP MCP URL" setting, if filled in; 2) the address WanGP's Pinokio launcher last printed
("Uvicorn running on ..."); 3) the usual ports 8000 and 42004."""
import json, os, re, socket, subprocess, sys, threading, time, requests
from pathlib import Path

_found = {"url": None, "t": 0.0}
_down = {"until": 0.0, "why": ""}   # after WanGP proves unreachable, skip it for DOWN_SECS instead of retrying every slot
DOWN_SECS = 600
UNREACHABLE = "WanGP not reachable"

def is_down(): return time.time() < _down["until"]

def mark_down(why=UNREACHABLE):
    _down.update(until=time.time() + DOWN_SECS, why=why)

def _from_pinokio_log(cfg):
    d = Path(cfg.get("wangp_dir") or "C:/pinokio/api/wan.git") / "logs" / "api" / "start.js"
    urls = []
    for name in ("latest", "events"):
        try: txt = (d / name).read_text(encoding="utf-8", errors="ignore")[-200000:]
        except Exception: continue
        for m in re.findall(r"Uvicorn running on (http://[0-9.]+:\d+)", txt): urls.append(m)
        for m in re.findall(r'"mcp_url":\s*"(http://[0-9.]+:\d+/mcp/?)"', txt): urls.append(m)
    out = []
    for u in reversed(urls):   # newest first
        u = u if u.rstrip("/").endswith("/mcp") else u.rstrip("/") + "/mcp"
        if u not in out: out.append(u)
    return out

def _probe(url):
    try:
        r = requests.post(url, headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
                          data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26",
                          "capabilities": {}, "clientInfo": {"name": "video-studio", "version": "1"}}}), timeout=4)
        return r.status_code < 400 and bool(r.headers.get("mcp-session-id") or "jsonrpc" in r.text)
    except Exception: return False

# ---- on-demand process (only the one this pipeline started; never a WanGP you started in Pinokio)
_proc = {"p": None, "url": None, "lock": threading.Lock()}


def wangp_dir(cfg):
    return Path(cfg.get("wangp_dir") or "C:/pinokio/api/wan.git")


def _python(cfg):
    env = wangp_dir(cfg) / "app" / "env"
    for c in (env / "Scripts" / "python.exe", env / "bin" / "python"):
        if c.is_file(): return c
    return None


def installed(cfg):
    return bool(cfg.get("wangp_on_demand", True)) and (wangp_dir(cfg) / "app" / "wgp.py").is_file() and _python(cfg) is not None


def owned():
    p = _proc["p"]
    return p is not None and p.poll() is None


def start(cfg, log=print):
    """Launch WanGP's MCP server and wait until it answers. -> MCP URL. Raises RuntimeError."""
    with _proc["lock"]:
        if owned() and _probe(_proc["url"]): return _proc["url"]
        py = _python(cfg)
        if not installed(cfg): raise RuntimeError(f"WanGP is not running and no on-demand install was found at {wangp_dir(cfg)}")
        with socket.socket() as so:
            so.bind(("127.0.0.1", 0)); port = so.getsockname()[1]
        app = wangp_dir(cfg) / "app"; env = dict(os.environ)
        venv = app / "env"
        env["PATH"] = os.pathsep.join(str(x) for x in (venv / "Scripts", venv / "Library" / "bin", venv / "bin")) + os.pathsep + env.get("PATH", "")
        env["VIRTUAL_ENV"] = str(venv); env.pop("PYTHONHOME", None); env["PYTHONUNBUFFERED"] = "1"
        logf = Path(cfg.get("jobs_dir") or ".").parent / "wangp_on_demand.log"
        try: out = open(logf, "a", encoding="utf-8", errors="replace")
        except OSError: out = subprocess.DEVNULL
        log(f"  WanGP: starting on demand (MCP on port {port}; output in {logf})")
        flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        p = subprocess.Popen([str(py), "wgp.py", "--mcp", "--mcp-transport", "streamable-http", "--mcp-host", "127.0.0.1",
                              "--mcp-port", str(port)], cwd=str(app), env=env, stdout=out, stderr=subprocess.STDOUT,
                             creationflags=flags if os.name == "nt" else 0)
        url = f"http://127.0.0.1:{port}/mcp"
        _proc.update(p=p, url=url)
        t0, limit = time.time(), float(cfg.get("wangp_start_timeout", 300))
        while time.time() - t0 < limit:
            if p.poll() is not None:
                _proc.update(p=None, url=None)
                raise RuntimeError(f"WanGP exited while starting (code {p.returncode}); see {logf}")
            if _probe(url):
                log(f"  WanGP: ready after {time.time() - t0:.0f}s")
                _found.update(url=url, t=time.time()); _down.update(until=0.0, why="")
                return url
            time.sleep(3)
        _kill(p); _proc.update(p=None, url=None)
        raise RuntimeError(f"WanGP did not answer within {limit:.0f}s of starting; see {logf}")


def _kill(p):
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True, timeout=30)
        else:
            p.kill()
        p.wait(timeout=30)
    except Exception:
        pass


def release(log=print, why="generation finished"):
    """Stop the WanGP process this pipeline started: unloads every model and frees the VRAM. A WanGP you started yourself
    is left alone."""
    with _proc["lock"]:
        p = _proc["p"]
        if p is None: return False
        _kill(p); _proc.update(p=None, url=None); _found.update(url=None, t=0.0)
    log(f"  WanGP: stopped ({why}); models unloaded, VRAM freed")
    return True


def find_url(cfg, fresh=False):
    """Return a WanGP MCP URL that answers, or the best guess if none does."""
    if not fresh and _found["url"] and time.time() - _found["t"] < 30: return _found["url"]
    if not fresh and not _found["url"] and time.time() - _found.get("miss_t", 0) < 30 and _found.get("miss"):
        return _found["miss"]   # nothing answered a moment ago: don't probe every port again (status polls every few seconds)
    cands = [cfg["wangp_mcp"]] if cfg.get("wangp_mcp") else []
    cands += _from_pinokio_log(cfg) + ["http://127.0.0.1:8000/mcp", "http://127.0.0.1:42004/mcp/"]
    seen = []
    for u in cands:
        if u in seen: continue
        seen.append(u)
        if _probe(u): _found.update(url=u, t=time.time()); return u
    _found.update(url=None, t=0.0, miss=seen[0], miss_t=time.time())
    return seen[0]

class WanGP:
    def __init__(self, url_or_cfg):
        """Pass the settings dict (preferred: the URL is found automatically) or a fixed URL."""
        self.cfg = url_or_cfg if isinstance(url_or_cfg, dict) else None
        self.url = None if self.cfg else url_or_cfg; self.sid = None

    def _post(self, body, timeout=120):
        h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if self.sid: h["mcp-session-id"] = self.sid
        r = requests.post(self.url, headers=h, data=json.dumps(body), timeout=(5, timeout))   # connect fast, read long
        if r.headers.get("mcp-session-id"): self.sid = r.headers["mcp-session-id"]
        return r

    def init(self):
        self.sid = None
        if self.cfg:
            self.url = find_url(self.cfg, fresh=self.url is not None)
            if not _probe(self.url) and installed(self.cfg):   # nothing running: start it now, for this generation
                self.url = start(self.cfg, getattr(self, "log", print))
        r = self._post({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                        "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "explainer-studio", "version": "1"}}})
        r.raise_for_status()
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def running(self):
        """Is a WanGP MCP server answering right now? (probe results are cached for 30 s)"""
        if not self.cfg: return _probe(self.url)
        u = find_url(self.cfg)
        return bool(_found["url"]) and u == _found["url"]

    def alive(self):
        """Can a generation use WanGP? True when one is running OR it can be started on demand. Never starts it."""
        if is_down(): return False
        try:
            if self.running(): return True
        except Exception: pass
        if self.cfg and installed(self.cfg): return True
        mark_down(); return False

    def hold(self):
        """with wg.hold(): ... keeps an on-demand WanGP loaded across several generations (all presenter clips, all
        narration chunks), then stops it."""
        wg = self
        class _Hold:
            def __enter__(self_): wg._held = getattr(wg, "_held", 0) + 1; return wg
            def __exit__(self_, *a):
                wg._held -= 1
                if not wg._held: release(getattr(wg, "log", print), "batch finished")
        return _Hold()

    def call(self, name, args):
        if is_down(): return {"error": f"{UNREACHABLE} (skipped: it failed less than {DOWN_SECS // 60} min ago)"}
        conn_fail = 0
        for _ in range(5):
            try:
                if not self.sid:
                    try: self.init()
                    except RuntimeError as e:   # on-demand start failed: don't try again for DOWN_SECS
                        mark_down(str(e)); return {"error": f"{UNREACHABLE}: {str(e)[:200]}"}
                r = self._post({"jsonrpc": "2.0", "id": int(time.time() * 1000), "method": "tools/call",
                                "params": {"name": name, "arguments": args}})
                if r.status_code >= 400:
                    self.sid = None; time.sleep(3); continue
                data = [l[6:] for l in r.text.splitlines() if l.startswith("data: ")]
                j = json.loads(data[-1] if data else r.text)
                res = j.get("result") or {}
                if "structuredContent" in res: return res["structuredContent"]
                if res.get("isError"): return {"error": (res.get("content") or [{}])[0].get("text", "error")}
                if "error" in j: return {"error": str(j["error"])}
                return res
            except (requests.ConnectionError, requests.ConnectTimeout):
                self.sid = None; conn_fail += 1
                if conn_fail >= 2: break   # nothing is listening: don't burn minutes retrying
                time.sleep(3)
            except (requests.RequestException, ValueError):
                self.sid = None; time.sleep(5)
        mark_down()
        return {"error": UNREACHABLE}

    def run(self, src, stop=lambda: False, stall_min=15, wait_start_min=45):
        """Start a generation, wait for it. Returns dict(ok, file, err)."""
        t0 = time.time()
        while True:
            if stop(): return {"ok": False, "err": "cancelled"}
            r = self.call("wangp_generate", {"source": src, "wait": False})
            if r.get("job_id"): break
            if "in progress" in str(r) and time.time() - t0 < wait_start_min * 60:
                time.sleep(15); continue
            return {"ok": False, "err": str(r)[:400]}
        jid = r["job_id"]; last = None; lc = time.time(); errs = 0
        while True:
            time.sleep(3)
            if stop():
                self.call("wangp_cancel_job", {"job_id": jid}); return {"ok": False, "err": "cancelled"}
            j = self.call("wangp_get_job", {"job_id": jid, "event_limit": 1})
            if "done" not in j:
                errs += 1
                if errs > 60: return {"ok": False, "err": "lost contact with WanGP"}
                continue
            errs = 0
            ev = json.dumps(j.get("events"))[:300]
            if ev != last: last, lc = ev, time.time()
            if j.get("done"):
                res = j.get("result") or {}
                files = res.get("generated_files") or []
                return {"ok": bool(res.get("success")) and bool(files), "file": files[0] if files else None,
                        "err": json.dumps(res.get("errors"))[:400]}
            if time.time() - lc > stall_min * 60:
                self.call("wangp_cancel_job", {"job_id": jid}); return {"ok": False, "err": "stalled"}

    def gen(self, src, log, tag, tries=3, stop=lambda: False):
        self.log = log
        try:
            return self._gen(src, log, tag, tries, stop)
        finally:   # memory policy: unload right after the generation unless a batch holds WanGP
            if not getattr(self, "_held", 0): release(log, f"{tag} done")

    def _gen(self, src, log, tag, tries=3, stop=lambda: False):
        seed = int(src.get("seed", 1))
        for t in range(tries):
            s = dict(src); s["seed"] = seed + t * 1000
            try: r = self.run(s, stop=stop)
            except Exception as e: r = {"ok": False, "err": f"error: {str(e)[:200]}"}
            if r["ok"]: return r
            log(f"  {tag}: attempt {t+1} failed ({r['err'][:160]})")
            if r["err"] == "cancelled": return r
            if UNREACHABLE in r["err"]: return r   # no point in more attempts: the ladder moves on to the next rung
            time.sleep(10)
        return r
