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
                    "imagegen_headless": True, "imagegen_timeout": 40}
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


class GeminiLadder(unittest.TestCase):
    def setUp(self):
        imagegen.reset()
        self.root = Path(tempfile.mkdtemp())
        self.sd = self.root / "jobs" / "J" / "short"; self.sd.mkdir(parents=True)
        self.cfg = {"jobs_dir": str(self.root / "jobs")}

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
