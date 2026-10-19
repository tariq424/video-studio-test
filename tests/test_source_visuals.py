import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from studio import source_visuals, writer


class SourceVisualTests(unittest.TestCase):
    def test_annotation_quotes_tolerate_punctuation_but_not_missing_words(self):
        self.assertEqual(writer._editorial_span("A pretty map, not a witness.", "A pretty map; not a witness"),
                         "A pretty map, not a witness")
        self.assertEqual(writer._editorial_span("A pretty map with invented positions is not a witness.", "A pretty map is not a witness"), "")
    def request(self, **kwargs):
        return {"source_visual": {"kind": "clip", "start": 1, "duration": 20,
                                  "purpose": "This claim needs independent evidence", **kwargs}}

    def test_bounded_duration_and_invalid_inputs(self):
        self.assertEqual(source_visuals._request(self.request())["duration"], 3)
        for kwargs in ({"start": -1}, {"start": float("nan")}, {"duration": float("inf")},
                       {"duration": 0}, {"purpose": ""}, {"kind": "unknown"}):
            self.assertIsNone(source_visuals._request(self.request(**kwargs)))

    def test_missing_and_malformed_cues_do_not_break_writer(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertIn("never invent", source_visuals.prompt(folder))
            (Path(folder) / "source_cues.json").write_text("broken")
            self.assertIn("unreadable", source_visuals.prompt(folder))

    def test_budget_cache_and_attribution(self):
        with tempfile.TemporaryDirectory() as folder:
            job = Path(folder); (job / "src").mkdir()
            (job / "src/meta.json").write_text(json.dumps({"channel": "Test creator", "webpage_url": "test"}))
            def extract(job, req, dest, meta, log):
                Image.new("RGB", (40, 40), "red").save(dest)
            with patch.object(source_visuals, "_extract", side_effect=extract) as extraction, patch("studio.review.files_url", return_value="http://localhost/test.png"):
                sec = {**self.request(kind="screenshot"), "id": "b0", "vo": "A claim needs evidence"}
                first = source_visuals.make({}, job, job / "short", sec, lambda _: None)
                self.assertEqual(first["g"]["credit"], "Test creator")
                self.assertEqual(first["g"]["kind"], "source_excerpt")
                source_visuals.make({}, job, job / "short", sec, lambda _: None)
                self.assertEqual(extraction.call_count, 1)
                self.assertIsNotNone(source_visuals.make({}, job, job / "short", {**sec, "id": "b1"}, print))
                self.assertIsNone(source_visuals.make({}, job, job / "short", {**sec, "id": "b2"}, print))
                self.assertIsNone(source_visuals.make({"source_visual_max_uses": 0}, job, job / "short", sec, print))

    def test_extraction_failure_continues_ladder(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(source_visuals, "_extract", side_effect=RuntimeError("blocked")):
            messages = []
            self.assertIsNone(source_visuals.make({}, Path(folder), Path(folder), self.request(), messages.append))
            self.assertIn("continuing visual ladder", messages[-1])
            self.assertFalse((Path(folder) / "source_excerpts/usage.json").exists())

    def test_no_source_request_or_disabled_leaves_supplied_media_alone(self):
        with patch.object(source_visuals, "_extract") as extraction:
            self.assertIsNone(source_visuals.make({}, ".", ".", {}, print))
            self.assertIsNone(source_visuals.make({"source_visuals": False}, ".", ".", self.request(), print))
            extraction.assert_not_called()

    def test_all_audiences_get_editorial_rules_and_fact_checker_preserves_them(self):
        for audience in writer.AUDIENCE:
            self.assertIn("EVERY content beat", writer.SYSTEM)
            self.assertIn("substantial, original analysis and unique commentary", writer.SYSTEM)
            self.assertTrue(writer.audience_line({"audience": audience}))
        self.assertIn("preserve the mild wit", writer.FACTCHECK)
        self.assertIn("not independent verification", writer.SYSTEM)

    def test_owned_long_visual_is_not_replaced(self):
        plan = {"sections": [{"vo": "test", "visuals": [{"id": "s0_0", "stock_src": "yours"}]}]}
        with patch.object(source_visuals, "make") as make:
            source_visuals.apply_long(Path("."), plan, {}, print)
            make.assert_not_called()

    def test_editorial_audit_requires_visible_new_analysis_and_wit(self):
        from unittest.mock import MagicMock
        llm = MagicMock(); llm.trace.return_value = llm
        vo = "A map can look convincing. A pretty line is not a measurement. Geography has no lie detector."
        llm.chat_json.return_value = {"sections": [{"id": "s0", "vo": vo,
            "analysis": "A pretty line is not a measurement.", "humor": "Geography has no lie detector."}]}
        plan = {"sections": [{"id": "s0", "vo": "A map shows a synthetic route made from invented positions for an illustration."}]}
        with patch.object(writer, "fact_check", side_effect=lambda llm, p, *a: p):
            writer.editorial_review(llm, plan, {}, "The source uses invented positions.", {}, print)
        self.assertIn("editorial", plan["sections"][0])
        llm.chat_json.return_value["sections"][0]["humor"] = "This is not in the narration"
        before = plan["sections"][0]["vo"]
        writer.editorial_review(llm, plan, {}, "Source facts", {}, print)
        self.assertEqual(plan["sections"][0]["vo"], before)
        self.assertIn("Keeping the previously source-checked narration", plan["editorial_warnings"][0])

    def test_editorial_failure_rolls_back_partial_rewrites(self):
        plan = {"sections": [{"id": "s0", "vo": "Checked narration"}]}
        def fail(llm, candidate, *args):
            candidate["sections"][0]["vo"] = "Unchecked replacement"
            raise ValueError("Malformed model response")
        with patch.object(writer, "_editorial_review_candidate", side_effect=fail):
            self.assertIs(writer.editorial_review(None, plan, {}, "source", {}, lambda _: None), plan)
        self.assertEqual(plan["sections"][0]["vo"], "Checked narration")
        self.assertTrue(plan["editorial_warnings"])

    def test_editorial_cancellation_is_not_suppressed(self):
        with self.assertRaisesRegex(RuntimeError, "stopped"):
            writer.editorial_review(None, {}, {}, "", {}, print, stop=lambda: True)
        with patch.object(writer, "_editorial_review_candidate", side_effect=RuntimeError("stopped")):
            with self.assertRaisesRegex(RuntimeError, "stopped"):
                writer.editorial_review(None, {}, {}, "", {}, print)

    def test_editorial_malformed_model_output_is_advisory(self):
        from unittest.mock import MagicMock
        for response in (None, {"sections": []}, {"sections": "invalid"}):
            llm = MagicMock(); llm.trace.return_value = llm
            llm.chat_json.return_value = response
            plan = {"sections": [{"id": "s0", "vo": "Previously checked narration"}]}
            writer.editorial_review(llm, plan, {}, "Source", {}, lambda _: None)
            self.assertEqual(plan["sections"][0]["vo"], "Previously checked narration")
            self.assertTrue(plan["editorial_warnings"])

    def test_remote_timestamp_must_be_a_real_caption_cue(self):
        with tempfile.TemporaryDirectory() as folder:
            job = Path(folder); (job / "src").mkdir()
            (job / "src/source_cues.json").write_text('[{"start": 5, "text": "source cue"}]')
            with self.assertRaisesRegex(ValueError, "verified source cues"):
                source_visuals._extract(job, source_visuals._request(self.request(start=7)), job / "clip.mp4",
                                       {"webpage_url": "https://youtu.be/g3toZwkrQQE"}, print)

    def test_youtube_downloader_requests_only_verified_range_without_audio(self):
        with tempfile.TemporaryDirectory() as folder:
            job = Path(folder); (job / "src").mkdir()
            (job / "src/source_cues.json").write_text('[{"start": 5, "text": "source cue"}]')
            downloaded = job / "download.mp4"
            from unittest.mock import MagicMock
            downloaded.write_bytes(b"mock transport")
            process = MagicMock(returncode=0)
            process.communicate.return_value = (json.dumps(str(downloaded)), "")
            def ff(*args, **kwargs): Image.new("RGB", (40, 40), "blue").save(args[-1])
            with patch("studio.source_visuals.subprocess.Popen", return_value=process) as spawn, patch("studio.media.ff", side_effect=ff):
                source_visuals._extract(job, source_visuals._request(self.request(start=5, duration=2.5, kind="screenshot")),
                                       job / "image.png", {"webpage_url": "https://youtu.be/g3toZwkrQQE"}, print)
            command = spawn.call_args.args[0]
            self.assertEqual(command[command.index("--download-sections") + 1], "*5.0-7.5")
            self.assertEqual(command[command.index("--retries") + 1], "0")
            self.assertNotIn("--cookies", command)
            process.communicate.assert_called_once_with(timeout=90)
            self.assertFalse(downloaded.exists())

    def test_downloader_timeout_cleans_up_only_its_own_process_tree(self):
        import subprocess
        from unittest.mock import MagicMock
        process = MagicMock(pid=123456)
        process.communicate.side_effect = [subprocess.TimeoutExpired("fixture", 90), ("", "")]
        with patch("studio.source_visuals.subprocess.Popen", return_value=process), patch("studio.source_visuals.subprocess.run") as kill:
            with self.assertRaisesRegex(RuntimeError, "exceeded 90 seconds"):
                source_visuals._run_downloader(["fixture"])
            if sys.platform == "win32":
                self.assertEqual(kill.call_args.args[0], ["taskkill", "/PID", "123456", "/T", "/F"])
