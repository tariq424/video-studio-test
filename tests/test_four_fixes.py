import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.studio import physics, source_visuals, writer


class SourceClipIsFullFrameVideo(unittest.TestCase):
    def setUp(self):
        self.job = Path(tempfile.mkdtemp())
        (self.job / "src").mkdir()
        cues = [{"start": 120.5, "text": "Google says its quantum chip"}, {"start": 123.0, "text": "cut error rates in a single step"},
                {"start": 126.2, "text": "a problem open for twenty years"}]
        (self.job / "src" / "source_cues.json").write_text(json.dumps(cues))
        (self.job / "src" / "meta.json").write_text(json.dumps({"channel": "Desire"}))

    def _fake_extract(self, job, req, dest, meta, log):
        Path(dest).write_bytes(b"x")

    def test_make_returns_a_video_item_not_a_pip_graphic(self):
        with patch.object(source_visuals, "_extract", side_effect=self._fake_extract), \
             patch.object(source_visuals, "inspect_video", return_value={"duration": 2.6, "fps": 30, "frames": 78}):
            item = source_visuals.make({}, self.job, self.job / "short", {"id": "b1", "vo": "Google quantum chip cut error rates single step twenty years"}, print)
        self.assertEqual(item["type"], "video")
        self.assertTrue(Path(item["path"]).exists())
        self.assertTrue(item["tag"].startswith("SOURCE"))
        self.assertEqual(item["secs"], 2.6)

    def test_long_gets_one_clip_per_section_as_footage(self):
        plan = {"sections": [{"id": "s0", "vo": "Google quantum chip cut error rates single step twenty years",
                              "visuals": [{"id": "s0_0", "type": "still", "prompt": "p"}, {"id": "s0_1", "type": "chart", "chart": {}, "prompt": "q"}]}]}
        with patch.object(source_visuals, "_extract", side_effect=self._fake_extract), \
             patch.object(source_visuals, "inspect_video", return_value={"duration": 2.6, "fps": 30, "frames": 78}):
            source_visuals.apply_long(self.job, plan, {}, print)
        v0, v1 = plan["sections"][0]["visuals"]
        self.assertEqual(v0["stock_src"], "source")
        self.assertTrue(v0["stock"].startswith("build/source_excerpts/"))
        self.assertNotIn("g", v0)
        self.assertNotIn("stock_src", v1)   # the same excerpt is not repeated in the next visual


class PhysicsGate(unittest.TestCase):
    def test_macbook_gets_no_physics(self):
        sec = {"id": "b0", "vo": "The new MacBook moves fast and tracks your work across apps", "subject": {"name": "MacBook Pro"}}
        self.assertTrue(physics.non_physical(sec))
        self.assertIsNone(physics.synthetic_motion(sec))
        logs = []
        self.assertIsNone(physics.provide({}, sec, None, logs.append))
        self.assertTrue(any("physics off" in l for l in logs))

    def test_real_movers_still_get_physics(self):
        sec = {"id": "b0", "vo": "The tanker crossed the Strait of Hormuz"}
        self.assertEqual(physics.non_physical(sec), "")
        self.assertIsNotNone(physics.synthetic_motion(sec))


class ExplainerPunchUp(unittest.TestCase):
    def test_every_section_gets_a_take_and_a_joke(self):
        long_vo = " ".join(f"Sentence number {i} explains a plain fact about the tool." for i in range(30))
        plan = {"sections": [{"id": "s0", "vo": "Windows has a text tool. It copies words from pictures. You paste them into ChatGPT."},
                             {"id": "s1", "vo": long_vo}]}
        fake = MagicMock(); fake.__enter__.return_value = fake; fake.name = "deepseek"; fake.trace.return_value = fake
        def answer(system, prompt, max_tokens=0, check=None):
            j = {"take": "Our take: this is less a hack than reading the label on the box"} if "OUR TAKE" in prompt \
                else {"joke": "Prompt engineering, now with the engineering part removed entirely"}
            if check: check(j)
            return j
        fake.chat_json.side_effect = answer
        logs = []
        with patch("app.studio.writer.LLM", return_value=fake):
            writer.punch_up_long({}, plan, logs.append)
        for s in plan["sections"]:
            self.assertIn("Our take:", s["vo"])
            self.assertTrue(s["vo"].endswith("removed entirely."))
        self.assertEqual(len(plan["sections"][1]["jokes"]), 2)   # a long section gets a second joke
        self.assertTrue(any("2 of 2 sections got our take, 3 jokes" in l for l in logs))

    def test_a_failing_model_never_blocks(self):
        plan = {"sections": [{"id": "s0", "vo": "One. Two."}]}
        fake = MagicMock(); fake.__enter__.return_value = fake; fake.name = "deepseek"; fake.trace.return_value = fake
        fake.chat_json.side_effect = RuntimeError("model down")
        with patch("app.studio.writer.LLM", return_value=fake):
            writer.punch_up_long({}, plan, print)
        self.assertEqual(plan["sections"][0]["vo"], "One. Two.")

    def test_section_prompt_no_longer_asks_for_jokes(self):
        self.assertIn("Do NOT write jokes", writer.SECTION)


class PresenterNeverCrashes(unittest.TestCase):
    def test_pipeline_wraps_presenter(self):
        src = (Path(__file__).parent.parent / "app" / "studio" / "pipeline.py").read_text(encoding="utf-8")
        i = src.index('elif st == "presenter":')
        block = src[i:i + 900]
        self.assertIn("try:", block)
        self.assertIn("On-screen presenter skipped", block)
        self.assertIn('j.save(presenter=False)', block)


if __name__ == "__main__":
    unittest.main()
