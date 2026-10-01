"""Minimal client for WanGP's local MCP server (streamable HTTP)."""
import json, time, requests

class WanGP:
    def __init__(self, url):
        self.url = url; self.sid = None

    def _post(self, body, timeout=120):
        h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if self.sid: h["mcp-session-id"] = self.sid
        r = requests.post(self.url, headers=h, data=json.dumps(body), timeout=timeout)
        if r.headers.get("mcp-session-id"): self.sid = r.headers["mcp-session-id"]
        return r

    def init(self):
        self.sid = None
        r = self._post({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                        "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "explainer-studio", "version": "1"}}})
        r.raise_for_status()
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def alive(self):
        try: self.init(); return True
        except Exception: return False

    def call(self, name, args):
        for _ in range(5):
            try:
                if not self.sid: self.init()
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
            except (requests.RequestException, ValueError):
                self.sid = None; time.sleep(5)
        return {"error": "WanGP not reachable"}

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
        seed = int(src.get("seed", 1))
        for t in range(tries):
            s = dict(src); s["seed"] = seed + t * 1000
            r = self.run(s, stop=stop)
            if r["ok"]: return r
            log(f"  {tag}: attempt {t+1} failed ({r['err'][:160]})")
            if r["err"] == "cancelled": return r
            time.sleep(10)
        return r
