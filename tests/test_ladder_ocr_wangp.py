import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.studio import ocr, source_visuals, vidgen, wangp


PROMPT_SCREEN = """1.jpg  Open with
shift
Cmd
PROMPT
Ultra-realistic 8K cinematic portrait of a man, use face reference exactly, with facial features
identical to the uploaded image. He wears a dark, tailored three-piece suit and looks directly into
the camera with a powerful, thoughtful expression.
high-end editorial finish.
285%"""


class OcrPrompt(unittest.TestCase):
    def test_prompt_paragraph_is_extracted_without_ui_noise(self):
        p = ocr.prompt_from(PROMPT_SCREEN)
        self.assertTrue(p.startswith("Ultra-realistic 8K cinematic portrait"))
        self.assertTrue(p.endswith("editorial finish."))
        self.assertNotIn("Open with", p)

    def test_short_labels_are_not_a_prompt(self):
        self.assertEqual(ocr.prompt_from("Text extractor (+Shift +T)"), "")

    def test_respace_rapidocr_output(self):
        try:
            import wordninja  # noqa: F401
        except ImportError:
            self.skipTest("wordninja not installed")
        self.assertIn("He wears a dark, tailored", ocr._respace("image.Hewearsadark,tailored"))

    def test_real_image_round_trip(self):
        from PIL import Image, ImageDraw
        d = Path(tempfile.mkdtemp())
        im = Image.new("RGB", (1400, 300), "white"); dr = ImageDraw.Draw(im)
        try:
            from PIL import ImageFont
            font = ImageFont.load_default(size=30)
        except Exception:
            font = None
        dr.text((20, 40), "A golden retriever running across a misty meadow at sunrise,", fill="black", font=font)
        dr.text((20, 90), "cinematic lighting, shallow depth of field, slow motion camera.", fill="black", font=font)
        im.save(d / "p.png")
        text, engine = ocr.read(d / "p.png", {}, print)
        if engine == "none":
            self.skipTest("no OCR engine in this environment")
        self.assertIn("retriever", ocr.prompt_from(text, min_words=8).lower())


class SnapshotFromClip(unittest.TestCase):
    def test_frame_of_the_source_clip_is_read(self):
        d = Path(tempfile.mkdtemp())
        clip = d / "c.mp4"
        from app.studio import media
        media.ff("-f", "lavfi", "-i", "color=c=gray:s=320x240:d=2.5", "-r", 30, "-pix_fmt", "yuv420p", clip, timeout=60)
        with patch.object(ocr, "read", return_value=(PROMPT_SCREEN, "tesseract")):
            snap = source_visuals.snapshot({}, d, d / "short", {"id": "b0"}, print, source_item={"type": "video", "path": str(clip), "secs": 2.5})
        self.assertTrue(Path(snap["path"]).is_file())
        self.assertTrue(snap["prompt"].startswith("Ultra-realistic"))
        self.assertEqual(snap["from"], "frame of the source clip")

    def test_no_cue_no_snapshot(self):
        d = Path(tempfile.mkdtemp()); (d / "src").mkdir()
        self.assertIsNone(source_visuals.snapshot({}, d, d / "short", {"id": "b0", "vo": "nothing matches"}, print))


class GeneratorLadder(unittest.TestCase):
    def setUp(self):
        vidgen.reset()
        self.sd = Path(tempfile.mkdtemp()) / "job" / "short"; self.sd.mkdir(parents=True)
        self.cfg = {"vidgen_state": str(self.sd.parent / "state.json")}
        self.clip = self.sd / "x.mp4"; self.clip.write_bytes(b"x")

    def test_free_sites_first_flow_last_and_cooldown_saved(self):
        logs = []
        def site(cfg, s, sd, key, prompt, image, aspect, log):
            if s == "bing": raise vidgen.Skip("Bing's create page offers no video option", 7 * 86400)
            raise RuntimeError("no clip after 300s")
        with patch.object(vidgen, "run_site", side_effect=site) as rs, \
             patch("app.studio.flow.generate", return_value=self.clip) as fg, \
             patch("app.studio.flow.visual_prompt", return_value="a calm lake at dawn, slow dolly shot"):
            clip, s = vidgen.generate(self.cfg, self.sd, {"id": "b0", "vo": "x"}, "b0", logs.append)
        self.assertEqual(s, "flow")
        self.assertEqual([c.args[1] for c in rs.call_args_list], ["bing", "meta"])   # sora is off by default
        self.assertTrue(any("sora: off" in l for l in logs))
        self.assertTrue(any("last resort" in l for l in logs))
        st = json.loads(Path(self.cfg["vidgen_state"]).read_text())
        self.assertIn("bing", st)
        fg.assert_called_once()
        # next job: bing is still cooling down (saved), so it is not even opened
        vidgen.reset()
        with patch.object(vidgen, "run_site", side_effect=site) as rs2, patch("app.studio.flow.generate", return_value=None), \
             patch("app.studio.flow.visual_prompt", return_value="p p p p p p p p"):
            vidgen.generate(self.cfg, self.sd, {"id": "b1", "vo": "x"}, "b1", logs.append)
        self.assertEqual([c.args[1] for c in rs2.call_args_list], ["meta"])

    def test_a_free_clip_means_no_flow_credits(self):
        out = self.sd / "vidgen" / "b0_meta.mp4"; out.parent.mkdir(parents=True); out.write_bytes(b"x")
        with patch.object(vidgen, "run_site", side_effect=lambda cfg, s, *a: (_ for _ in ()).throw(vidgen.Skip("dead")) if s == "bing" else out), \
             patch("app.studio.flow.generate") as fg, patch.object(vidgen.media, "dur", return_value=5.0):
            clip, s = vidgen.generate(self.cfg, self.sd, {"id": "b0", "vo": "x"}, "b0", print, prompt="the OCR prompt text here")
        self.assertEqual(s, "meta")
        fg.assert_not_called()
        self.assertEqual(vidgen.tag(s), "GENERATED · META AI")

    def test_ocr_prompt_reaches_the_site_with_the_anchor(self):
        seen = {}
        def site(cfg, s, sd, key, prompt, image, aspect, log):
            seen[s] = (prompt, image); raise RuntimeError("x")
        with patch.object(vidgen, "run_site", side_effect=site), patch("app.studio.flow.generate", return_value=None) as fg:
            vidgen.generate(self.cfg, self.sd, {"id": "b0"}, "b0", print, prompt="OCR TEXT", image="snap.png")
        self.assertEqual(seen["meta"], ("OCR TEXT", "snap.png"))
        self.assertEqual(fg.call_args.kwargs["prompt"], "OCR TEXT")


class WanGPOnDemand(unittest.TestCase):
    def setUp(self):
        wangp._down.update(until=0.0, why="")

    def test_alive_never_starts_wangp(self):
        with patch.object(wangp, "_probe", return_value=False), patch.object(wangp, "installed", return_value=True), \
             patch.object(wangp, "start") as st:
            self.assertTrue(wangp.WanGP({"wangp_mcp": "http://127.0.0.1:1/mcp"}).alive())
        st.assert_not_called()

    def test_generation_starts_then_unloads(self):
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

    def test_failed_start_marks_down_instead_of_retrying(self):
        wg = wangp.WanGP({"wangp_mcp": "http://127.0.0.1:1/mcp"})
        with patch.object(wangp, "_probe", return_value=False), patch.object(wangp, "installed", return_value=True), \
             patch.object(wangp, "start", side_effect=RuntimeError("WanGP exited while starting")):
            r = wg.call("wangp_generate", {})
        self.assertIn(wangp.UNREACHABLE, r["error"])
        self.assertTrue(wangp.is_down())

    def test_release_kills_only_our_process(self):
        self.assertFalse(wangp.release(print))   # nothing started by us: a WanGP you started yourself is never stopped
        fake = MagicMock(); fake.poll.return_value = None
        wangp._proc.update(p=fake, url="u")
        with patch.object(wangp, "_kill") as k:
            self.assertTrue(wangp.release(print, "test"))
        k.assert_called_once_with(fake)


if __name__ == "__main__":
    unittest.main()
