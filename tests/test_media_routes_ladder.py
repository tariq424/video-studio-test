"""Media routes wired into the visual ladder (2026-11-06): Cloudflare + Meta image services, Blender rung 3b, Meta video -> Flow."""
import sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from studio import config, imagegen, mediaroutes


def _fake_clip(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True); Path(path).write_bytes(b"x")


class Ladder(unittest.TestCase):
    def test_services_and_order(self):
        for s in ("cloudflare", "meta"):
            self.assertIn(s, imagegen.PROVIDERS)
        order = config.DEFAULTS["imagegen_providers"]
        self.assertEqual(order[0], "cloudflare")
        self.assertLess(order.index("meta"), order.index("gemini"))
        self.assertIn("cloudflare_api_token", config.SECRETS)

    def test_blender_partial_scene_is_not_used(self):
        with tempfile.TemporaryDirectory() as sd:
            def fake_run(cfg, route, desc, aspect, out, log, image=None, timeout=None):
                _fake_clip(out); return {"output": Path(out), "note": "PARTIAL - no photoreal model for: aircraft"}
            with patch.object(mediaroutes, "available", return_value=True), patch.object(mediaroutes, "run", side_effect=fake_run), \
                    patch("studio.flow.visual_prompt", return_value="a jet"), patch("studio.media.ok", side_effect=lambda p: Path(p).exists()):
                logs = []
                self.assertIsNone(mediaroutes.blender_rung({}, sd, {"id": "b0", "vo": "jet"}, "k", logs.append))
                self.assertTrue(any("partial scene" in l for l in logs))
                self.assertFalse((Path(sd) / "blender" / "k.mp4").exists())
                self.assertIsNone(mediaroutes.blender_rung({}, sd, {"id": "b0", "vo": "jet"}, "k", logs.append))   # not retried

    def test_meta_video_then_flow_with_cap(self):
        with tempfile.TemporaryDirectory() as sd:
            calls = []
            def fake_run(cfg, route, desc, aspect, out, log, image=None, timeout=None):
                calls.append(route)
                if route == "r7": return None                      # Meta video fails
                _fake_clip(out); return {"output": Path(out), "note": "approved (12 credits)"}
            cfg = {"flow_on": True, "meta_video_on": True, "flow_via_routes": True, "flow_max_per_video": 1}
            with patch.object(mediaroutes, "available", return_value=True), patch.object(mediaroutes, "run", side_effect=fake_run), \
                    patch("studio.flow.visual_prompt", return_value="a jet"), patch("studio.media.ok", side_effect=lambda p: Path(p).exists()):
                clip, tag, rung = mediaroutes.video_rung(cfg, sd, {"id": "b0"}, "a", lambda _: None)
                self.assertEqual((tag, rung), ("GENERATED · FLOW", "flow"))
                self.assertEqual(calls, ["r7", "r8"])
                clip2, _, _ = mediaroutes.video_rung(cfg, sd, {"id": "b1"}, "b", lambda _: None)   # cap: one paid clip per video
                self.assertIsNone(clip2)
                self.assertEqual(calls, ["r7", "r8", "r7"])

    def test_chain_never_for_a_known_person(self):
        with tempfile.TemporaryDirectory() as sd:
            snap = Path(sd) / "snap.jpg"; snap.write_bytes(b"x")
            calls = []
            with patch.object(mediaroutes, "available", return_value=True), \
                    patch.object(mediaroutes, "run", side_effect=lambda *a, **k: calls.append(a[1])):
                ents = [{"name": "Donald Trump", "kind": "person"}]
                self.assertIsNone(mediaroutes.chain_rung({}, sd, {"id": "b0", "vo": "Donald Trump spoke at the rally."}, "k",
                                                         lambda _: None, snap, ents=ents))
                self.assertIsNone(mediaroutes.chain_rung({}, sd, {"id": "b0", "vo": "He spoke.", "subject": {"kind": "person"}}, "k",
                                                         lambda _: None, snap))
                self.assertEqual(calls, [])

    def test_chain_describe_then_meta(self):
        with tempfile.TemporaryDirectory() as sd:
            snap = Path(sd) / "snap.jpg"; snap.write_bytes(b"x")
            calls = []
            def fake_run(cfg, route, desc, aspect, out, log, image=None, timeout=None):
                calls.append((route, image is not None))
                if route == "r12": Path(out).write_text("A rusty fishing trawler moored in a grey harbour at dawn, gulls overhead, wide shot", encoding="utf-8")
                else: _fake_clip(out)
                return {"output": Path(out), "note": ""}
            with patch.object(mediaroutes, "available", return_value=True), patch.object(mediaroutes, "run", side_effect=fake_run), \
                    patch("studio.media.ok", side_effect=lambda p: Path(p).exists()):
                r = mediaroutes.chain_rung({}, sd, {"id": "b0", "vo": "The trawler sat in the harbour."}, "k", lambda _: None, snap)
                self.assertEqual(calls, [("r12", True), ("r13", False)])
                self.assertTrue(r["video"].exists())
                self.assertIn("trawler", r["prompt"])

    def test_runs_inside_video_studio(self):
        """The routes are Video Studio's own (studio/routelib, this Python), never the media-poc setup folder."""
        with tempfile.TemporaryDirectory() as data:
            (Path(data) / "profiles").mkdir()
            seen = {}
            class FakeProc:
                pid, returncode = 4242, 2
                def __init__(self, cmd, **kw): seen.update(cmd=cmd, env=kw.get("env"), cwd=kw.get("cwd"))
                def communicate(self, timeout=None): return '{"status": "blocker", "note": "x"}', ""
            with patch("subprocess.Popen", FakeProc):
                mediaroutes.run({"media_routes_data": data}, "r6", "a jet", "16:9", Path(data) / "o.jpg", lambda _: None)
            self.assertEqual(seen["cmd"][0], sys.executable)
            self.assertEqual(seen["cmd"][1:3], ["-m", "studio.routelib.run_route"])
            self.assertEqual(seen["env"]["VS_MEDIA_DATA"], data)
            self.assertNotIn("media-poc", " ".join(seen["cmd"]) + str(seen["cwd"]))

    def test_timeout_kills_the_route_and_moves_on(self):
        """Never hang: a route past its limit is killed with its whole process tree (its Chrome too) and the ladder moves on."""
        import subprocess as sp
        with tempfile.TemporaryDirectory() as data:
            (Path(data) / "profiles").mkdir()
            killed, logs = [], []
            class SlowProc:
                pid, returncode = 4243, None
                def __init__(self, cmd, **kw): self.n = 0
                def communicate(self, timeout=None):
                    self.n += 1
                    if self.n == 1: raise sp.TimeoutExpired("route", timeout)
                    return "", ""
                def kill(self): killed.append("kill")
            real_run = sp.run
            def fake_run(cmd, **kw):
                if cmd and cmd[0] == "taskkill": killed.append(cmd); return sp.CompletedProcess(cmd, 0, "", "")
                return real_run(cmd, **kw)
            with patch("subprocess.Popen", SlowProc), patch("subprocess.run", side_effect=fake_run):
                r = mediaroutes.run({"media_routes_data": data}, "r13", "x", "16:9", Path(data) / "o.mp4", logs.append, timeout=1)
            self.assertIsNone(r)
            self.assertTrue(killed)
            if sys.platform == "win32": self.assertIn("/T", killed[0])
            self.assertTrue(any("stopped" in l and "next rung" in l for l in logs))

    def test_v2_after_wangp_never_raises(self):
        from studio import render
        with tempfile.TemporaryDirectory() as job, patch.object(render, "_v2_after_wangp", side_effect=ValueError("boom")):
            v, logs = {"id": "v1"}, []
            self.assertEqual(render.v2_after_wangp({}, Path(job), v, "The plane landed safely", logs.append), "headline")
            self.assertEqual(v["g"]["kind"], "headline")
            self.assertTrue(any("ladder failed" in l for l in logs))

    def test_chain_cap_per_video(self):
        with tempfile.TemporaryDirectory() as sd:
            snap = Path(sd) / "snap.jpg"; snap.write_bytes(b"x")
            for k in range(3): _fake_clip(Path(sd) / "chain" / f"old{k}.mp4")
            calls, logs = [], []
            with patch.object(mediaroutes, "available", return_value=True), \
                    patch.object(mediaroutes, "run", side_effect=lambda *a, **k: calls.append(a[1])), \
                    patch("studio.media.ok", side_effect=lambda p: Path(p).exists()):
                self.assertIsNone(mediaroutes.chain_rung({}, sd, {"id": "b9", "vo": "A trawler in a harbour."}, "new", logs.append, snap))
            self.assertEqual(calls, [])
            self.assertTrue(any("already made" in l for l in logs))

    def test_meta_fallback_description_naming_a_person_is_dropped(self):
        with tempfile.TemporaryDirectory() as sd, tempfile.TemporaryDirectory() as data:
            snap = Path(sd) / "snap.jpg"; snap.write_bytes(b"x")
            (Path(data) / "output").mkdir()
            (Path(data) / "output" / "r13_meta_chain.prompt.txt").write_text("Donald Trump at a podium in a navy suit, low angle", encoding="utf-8")
            def fake_run(cfg, route, desc, aspect, out, log, image=None, timeout=None):
                if route == "r12": return None   # Copilot blocked
                _fake_clip(out); return {"output": Path(out), "note": ""}
            ents = [{"name": "Donald Trump", "kind": "person"}]
            with patch.object(mediaroutes, "available", return_value=True), patch.object(mediaroutes, "run", side_effect=fake_run), \
                    patch("studio.media.ok", side_effect=lambda p: Path(p).exists()):
                r = mediaroutes.chain_rung({"media_routes_data": data}, sd, {"id": "b1", "vo": "A rally took place."}, "k",
                                           lambda _: None, snap, ents=ents)
            self.assertIsNone(r)
            self.assertFalse((Path(sd) / "chain" / "k.mp4").exists())

    def test_meta_video_cap_falls_to_flow(self):
        with tempfile.TemporaryDirectory() as sd:
            for k in range(3): _fake_clip(Path(sd) / "flow" / f"o{k}_meta.mp4")
            calls = []
            def fake_run(cfg, route, desc, aspect, out, log, image=None, timeout=None):
                calls.append(route); _fake_clip(out); return {"output": Path(out), "note": ""}
            with patch.object(mediaroutes, "available", return_value=True), patch.object(mediaroutes, "run", side_effect=fake_run), \
                    patch("studio.flow.visual_prompt", return_value="x"), patch("studio.media.ok", side_effect=lambda p: Path(p).exists()):
                clip, tag, rung = mediaroutes.video_rung({"flow_on": True, "flow_max_per_video": 1}, sd, {"id": "b"}, "new", lambda _: None)
            self.assertEqual(calls, ["r8"])
            self.assertEqual(rung, "flow")

    def test_flow_off_spends_nothing(self):
        with tempfile.TemporaryDirectory() as sd:
            calls = []
            with patch.object(mediaroutes, "available", return_value=True), \
                    patch.object(mediaroutes, "run", side_effect=lambda *a, **k: calls.append(a[1])), \
                    patch("studio.flow.visual_prompt", return_value="a jet"), patch("studio.media.ok", return_value=False):
                self.assertEqual(mediaroutes.video_rung({"flow_on": False}, sd, {"id": "b0"}, "a", lambda _: None), (None, None, None))
                self.assertNotIn("r8", calls)


if __name__ == "__main__":
    unittest.main()
