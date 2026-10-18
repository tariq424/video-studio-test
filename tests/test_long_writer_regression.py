import sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from studio import writer, config


class LongWriterRegression(unittest.TestCase):
    def test_long_writer_passes_collected_notes_to_jargon_review(self):
        class FakeLLM:
            name = "deterministic regression"
            tokens_in = tokens_out = 0

            def __init__(self, *a, **k):
                self.calls = 0

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

            def trace(self, *a):
                return self

            def chat_json(self, system, prompt, **kw):
                self.calls += 1
                if self.calls == 1:
                    return {
                        "title": "Test",
                        "sections": [
                            {
                                "title": f"Part {i}",
                                "points": ["A source fact"],
                                "words": 50,
                            }
                            for i in range(3)
                        ],
                    }
                return {
                    "vo": "ADS-B broadcasts aircraft position. " * 12,
                    "visuals": [
                        {"type": "still", "prompt": "Aircraft position diagram"}
                    ],
                }

        cfg = {**config.DEFAULTS, "audience": "beginner"}
        notes = "ADS-B is an aircraft radio broadcast used to share position."
        with (
            patch("studio.writer.LLM", FakeLLM),
            patch("studio.writer.make_notes", return_value=notes),
            patch("studio.writer.fit_length"),
            patch("studio.writer.fact_check", side_effect=lambda llm, p, *a: p),
            patch("studio.writer.jargon_check") as review,
            patch("studio.writer.editorial_review"),
        ):
            result = writer.write_plan(
                cfg, {"title": "ADS-B"}, "A source transcript", 3, lambda _: None
            )
        self.assertGreater(len(result["sections"]), 0)
        self.assertEqual(review.call_args.kwargs["source_notes"], notes)


if __name__ == "__main__":
    unittest.main()
