import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.studio import imagegen, wangp

FIXTURE = (Path(__file__).parent / "fixtures" / "mock_imagegen.html").resolve().as_uri()
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"


def _have_playwright():
    try:
        import playwright.sync_api  # noqa: F401
        return Path(CHROME).is_file()
    except ImportError:
        return False


class GeminiAgainstAMockSite(unittest.TestCase):
    """The real Playwright automation (upload -> describe + prompt -> generate -> download) against a local Gemini stand-in."""

    def setUp(self):
        if not _have_playwright():
            self.skipTest("Playwright / Chromium not available")
        imagegen.reset()
        self.root = Path(tempfile.mkdtemp())
        self.sd = self.root / "jobs" / "J" / "short"; self.sd.mkdir(parents=True)
        prof = self.root / "flow_profile"; prof.mkdir(); (prof / "First Run").write_text("")
        self.cfg = {"jobs_dir": str(self.root / "jobs"), "gemini_url": FIXTURE, "flow_chrome": CHROME,
                    "imagegen_headless": True, "imagegen_timeout": 40, "imagegen_delay_secs": [0, 0],
                    "imagegen_providers": ["gemini"], "imagegen_per_beat": 2}
        from PIL import Image
        self.shot = self.root / "shot.png"; Image.new("RGB", (640, 360), "green").save(self.shot)

    def test_screenshot_described_then_generated_then_downloaded(self):
        logs = []
        img, site, prompt = imagegen.generate(self.cfg, self.sd, {"id": "b0", "vo": "x"}, "b0", logs.append, image=self.shot)
        self.assertEqual(site, "gemini")
        self.assertTrue(prompt.startswith("A photorealistic golden retriever"), prompt)
        from PIL import Image
        with Image.open(img) as im:
            self.assertGreaterEqual(min(im.size), 300)
        self.assertTrue(any("screenshot uploaded" in l for l in logs))
        self.assertEqual(imagegen.tag(), "GENERATED · GEMINI")

    def test_a_beat_needing_two_visuals_gets_a_second_angle_not_flow(self):
        logs = []
        res = imagegen.generate_many(self.cfg, self.sd, {"id": "b3", "vo": "x"}, "b3", logs.append, image=self.shot, count=3)
        self.assertEqual(len(res), 2)   # capped by imagegen_per_beat (2)
        self.assertTrue(all(Path(p).is_file() for p, _ in res))
        self.assertTrue(any("image 2: generate a second image" in l for l in logs))
        self.assertTrue(any("2 image(s) ready" in l for l in logs))

    def test_without_a_screenshot_the_narration_is_used(self):
        img, site, prompt = imagegen.generate(self.cfg, self.sd, {"id": "b1", "vo": "A laptop reads text from images."}, "b1", print)
        self.assertTrue(prompt.startswith("A wide cinematic shot of a quiet laptop"))
        self.assertTrue(Path(img).is_file())

    def test_refusal_falls_through_with_evidence(self):
        logs = []
        with patch.object(imagegen, "GENERATE", "Generate an image: REFUSE "):
            res = imagegen.generate(self.cfg, self.sd, {"id": "b2", "vo": "x"}, "b2", logs.append, image=self.shot)
        self.assertEqual(res, (None, None, None))
        self.assertTrue(any("declined" in l for l in logs))
        self.assertTrue((self.sd / "imagegen" / "b2_gemini_generate_fail.png").exists())


class ServiceRotation(unittest.TestCase):
    """One service per video, rotating; a failing service hands the beat (and the rest of the video) to the next."""

    def setUp(self):
        imagegen.reset()
        self.root = Path(tempfile.mkdtemp())
        self.cfg = {"jobs_dir": str(self.root / "jobs"), "imagegen_delay_secs": [0, 0], "imagegen_providers": ["gemini", "chatgpt", "bing"],
                    "imagegen_rotate": True}

    def fake(self, site, calls, fail=None):
        def run(cfg, *a, **k):
            calls.append(site)
            if fail: raise fail
            out = next(x for x in a if isinstance(x, Path) and x.suffix == ".jpg")
            from PIL import Image
            Image.new("RGB", (640, 360), "blue").save(out); return f"{site} prompt"
        return run

    def sd(self, name):
        d = self.root / "jobs" / name / "short"; d.mkdir(parents=True); return d

    def test_videos_rotate_between_services(self):
        calls = []
        with patch.object(imagegen, "_session", self.fake("gemini", calls)), \
                patch.object(imagegen, "_session_chatgpt", self.fake("chatgpt", calls)), \
                patch.object(imagegen, "_session_bing", self.fake("bing", calls)):
            for job in ("A", "B", "C", "D"):
                sd = self.sd(job)
                imagegen.generate(self.cfg, sd, {"id": "b0", "vo": "x"}, "b0", print)
                imagegen.generate(self.cfg, sd, {"id": "b1", "vo": "x"}, "b1", print)   # same video: same service
        self.assertEqual(calls, ["gemini", "gemini", "chatgpt", "chatgpt", "bing", "bing", "gemini", "gemini"])
        self.assertEqual(imagegen.tag(), "GENERATED · GEMINI")

    def test_a_limit_moves_the_video_to_the_next_service(self):
        calls = []
        with patch.object(imagegen, "_session", self.fake("gemini", calls, imagegen.Skip("Gemini usage limit", -1))), \
                patch.object(imagegen, "_session_chatgpt", self.fake("chatgpt", calls)), \
                patch.object(imagegen, "_session_bing", self.fake("bing", calls)):
            sd = self.sd("A")
            img, site, _ = imagegen.generate(self.cfg, sd, {"id": "b0", "vo": "x"}, "b0", print)
            self.assertEqual((site, Path(img).name), ("chatgpt", "b0_chatgpt.jpg"))
            imagegen.generate(self.cfg, sd, {"id": "b1", "vo": "x"}, "b1", print)
        self.assertEqual(calls, ["gemini", "chatgpt", "chatgpt"])   # Gemini cooled down: not asked again
        self.assertEqual((sd / "imagegen" / "provider.txt").read_text(), "chatgpt")
        self.assertIn("gemini", json.loads((self.root / "imagegen_state.json").read_text()))

    def test_hugging_face_first_then_the_rotation(self):
        calls = []
        with patch.object(imagegen, "_session_hf", self.fake("hf", calls, imagegen.Skip("Hugging Face quota", -1))), \
                patch.object(imagegen, "_session", self.fake("gemini", calls)), \
                patch.object(imagegen, "_session_chatgpt", self.fake("chatgpt", calls)):
            cfg = dict(self.cfg, imagegen_providers=["gemini", "chatgpt", "bing", "hf"], imagegen_first="hf", imagegen_rotate=True)
            imagegen.generate(cfg, self.sd("A"), {"id": "b0", "vo": "x"}, "b0", print)   # hf out of quota -> the video's rotation service
            imagegen.generate(cfg, self.sd("B"), {"id": "b0", "vo": "x"}, "b0", print)   # hf cooling down: straight to the next in turn
        self.assertEqual(calls, ["hf", "gemini", "chatgpt"])

    def test_fixed_priority_gemini_last(self):
        calls = []
        cfg = {"jobs_dir": str(self.root / "jobs"), "imagegen_delay_secs": [0, 0]}   # the defaults: hf -> chatgpt -> bing -> gemini
        from app.studio import config
        cfg = dict(config.DEFAULTS, **cfg)
        with patch.object(imagegen, "_session_hf", self.fake("hf", calls, RuntimeError("vision check: plane with four wings"))), \
                patch.object(imagegen, "_session_chatgpt", self.fake("chatgpt", calls, imagegen.Skip("ChatGPT limit", -1))), \
                patch.object(imagegen, "_session_bing", self.fake("bing", calls)), \
                patch.object(imagegen, "_session", self.fake("gemini", calls)):
            img, site, _ = imagegen.generate(cfg, self.sd("A"), {"id": "b0", "vo": "x"}, "b0", print)
            imagegen.generate(cfg, self.sd("B"), {"id": "b0", "vo": "x"}, "b0", print)   # next video: hf again, chatgpt cooling
        self.assertEqual(site, "bing")
        self.assertEqual(calls, ["hf", "chatgpt", "bing", "hf", "bing"])   # Gemini never touched while another works

    def test_one_image_per_beat_by_default(self):
        calls = []
        with patch.object(imagegen, "_session", self.fake("gemini", calls)):
            res = imagegen.generate_many(dict(self.cfg, imagegen_providers=["gemini"]), self.sd("A"), {"id": "b0", "vo": "x"}, "b0", print, count=3)
        self.assertEqual(len(res), 1)


class GeminiLadder(unittest.TestCase):
    def setUp(self):
        imagegen.reset()
        self.root = Path(tempfile.mkdtemp())
        self.sd = self.root / "jobs" / "J" / "short"; self.sd.mkdir(parents=True)
        self.cfg = {"jobs_dir": str(self.root / "jobs"), "imagegen_providers": ["gemini"]}

    def test_no_profile_skips_for_the_job(self):
        logs = []
        self.assertEqual(imagegen.generate(self.cfg, self.sd, {"id": "b0"}, "b0", logs.append), (None, None, None))
        self.assertTrue(any("no signed-in Google profile" in l for l in logs))
        logs.clear()
        imagegen.generate(self.cfg, self.sd, {"id": "b1"}, "b1", logs.append)
        self.assertTrue(any("gemini skipped (" in l for l in logs))

    def test_usage_limit_is_saved_across_jobs(self):
        with patch.object(imagegen, "_session", side_effect=imagegen.Skip("Gemini usage limit", -1)):
            imagegen.generate(self.cfg, self.sd, {"id": "b0"}, "b0", print)
        imagegen.reset()
        with patch.object(imagegen, "_session") as sess:
            imagegen.generate(self.cfg, self.sd, {"id": "b1"}, "b1", print)
        sess.assert_not_called()
        self.assertIn("gemini", json.loads((self.root / "imagegen_state.json").read_text()))

    def test_prompt_extraction(self):
        self.assertEqual(imagegen.extract_prompt("Desc...\n\n**PROMPT:** A red kite over green hills at dusk, wide shot, soft light, photorealistic."),
                         "A red kite over green hills at dusk, wide shot, soft light, photorealistic.")
        self.assertTrue(imagegen.extract_prompt("Here you go:\n```\nA misty pine forest at sunrise with light rays through tall trees\n```").startswith("A misty pine"))
        self.assertEqual(imagegen.extract_prompt("Sorry."), "")


class CutoutLayers(unittest.TestCase):
    def test_rembg_cutout_makes_background_and_subject(self):
        from PIL import Image, ImageDraw
        from app.studio import depth
        d = Path(tempfile.mkdtemp())
        im = Image.new("RGB", (800, 1000), (40, 90, 160)); ImageDraw.Draw(im).ellipse((250, 300, 550, 700), fill=(240, 200, 60))
        im.save(d / "g.jpg")
        def fake_remove(img, session=None):
            a = Image.new("L", img.size, 0); ImageDraw.Draw(a).ellipse((300, 500, 780, 1400), fill=255)
            out = img.convert("RGBA"); out.putalpha(a); return out
        fake = MagicMock(remove=fake_remove, new_session=lambda name: object())
        with patch.dict("sys.modules", {"rembg": fake}):
            depth._rembg["session"] = None
            lay = depth.cutout_layers(d / "g.jpg", d / "g_px", print)
        self.assertEqual([p.suffix for p in lay], [".jpg", ".png"])
        with Image.open(lay[1]) as fg:
            self.assertEqual(fg.mode, "RGBA"); self.assertEqual(fg.size, (1080, 1920))


class WanGPOnDemand(unittest.TestCase):
    def setUp(self):
        wangp._down.update(until=0.0, why="")

    def test_alive_never_starts_wangp(self):
        with patch.object(wangp, "_probe", return_value=False), patch.object(wangp, "installed", return_value=True), \
             patch.object(wangp, "start") as st:
            self.assertTrue(wangp.WanGP({"wangp_mcp": "http://127.0.0.1:1/mcp"}).alive())
        st.assert_not_called()

    def test_generation_unloads_right_after(self):
        wg = wangp.WanGP({"wangp_mcp": "http://127.0.0.1:1/mcp"})
        with patch.object(wg, "_gen", return_value={"ok": True, "file": "f"}), patch.object(wangp, "release") as rel:
            wg.gen({"seed": 1}, print, "still b3")
        rel.assert_called_once()

    def test_a_held_batch_unloads_once_at_the_end(self):
        wg = wangp.WanGP({"wangp_mcp": "http://127.0.0.1:1/mcp"})
        with patch.object(wg, "_gen", return_value={"ok": True, "file": "f"}), patch.object(wangp, "release") as rel:
            with wg.hold():
                wg.gen({}, print, "presenter s0_open"); wg.gen({}, print, "presenter s3_close")
                rel.assert_not_called()
        rel.assert_called_once()

    def test_failed_start_marks_down(self):
        wg = wangp.WanGP({"wangp_mcp": "http://127.0.0.1:1/mcp"})
        with patch.object(wangp, "_probe", return_value=False), patch.object(wangp, "installed", return_value=True), \
             patch.object(wangp, "start", side_effect=RuntimeError("WanGP exited while starting")):
            r = wg.call("wangp_generate", {})
        self.assertIn(wangp.UNREACHABLE, r["error"])
        self.assertTrue(wangp.is_down())

    def test_release_kills_only_our_process(self):
        self.assertFalse(wangp.release(print))
        fake = MagicMock(); fake.poll.return_value = None
        wangp._proc.update(p=fake, url="u")
        with patch.object(wangp, "_kill") as k:
            self.assertTrue(wangp.release(print, "test"))
        k.assert_called_once_with(fake)


if __name__ == "__main__":
    unittest.main()


def test_pacing_waits_between_gemini_requests(monkeypatch):
    from app.studio import imagegen
    slept = []
    monkeypatch.setattr(imagegen.time, "sleep", lambda s: slept.append(s))
    imagegen._answered()
    imagegen._pause({"imagegen_delay_secs": [15, 30]}, lambda m: None, "next")
    assert slept and 14 <= slept[0] <= 30
    slept.clear()
    imagegen._last["gemini"] = 0
    imagegen._pause({"imagegen_delay_secs": [15, 30]}, lambda m: None, "next")
    assert not slept   # long idle already counts as the pause


def test_gemini_defaults_headless_and_paced():
    from app.studio import config
    assert config.DEFAULTS["imagegen_headless"] is True
    assert config.DEFAULTS["imagegen_delay_secs"] == [15, 30]


def test_hf_images_with_text_are_retried_then_handed_on(tmp_path, monkeypatch):
    import sys, types
    from PIL import Image
    src = tmp_path / "gen.png"; Image.new("RGB", (64, 64), "red").save(src)
    calls = []
    class FakeClient:
        def __init__(self, *a, **k): pass
        def predict(self, *a, **k): calls.append(1); return (str(src), 1)
    monkeypatch.setitem(sys.modules, "gradio_client", types.SimpleNamespace(Client=FakeClient))
    from app.studio import flow
    monkeypatch.setattr(flow, "visual_prompt", lambda cfg, sec, log: "a quiet street at dusk")
    cfg = {"imagegen_delay_secs": [0, 0]}
    answers = iter(["plane with four wings", ""])
    monkeypatch.setattr(imagegen, "_has_text", lambda cfg, img, log: next(answers))
    out = tmp_path / "o.jpg"
    imagegen._session_hf(cfg, {"vo": "x"}, "16:9", out, 30, print, None)
    assert out.is_file() and len(calls) == 2   # retried once, the second image is clean
    monkeypatch.setattr(imagegen, "_has_text", lambda cfg, img, log: "sign")
    import pytest
    with pytest.raises(RuntimeError): imagegen._session_hf(cfg, {"vo": "x"}, "16:9", tmp_path / "p.jpg", 30, print, None)
    assert not (tmp_path / "p.jpg").exists()
