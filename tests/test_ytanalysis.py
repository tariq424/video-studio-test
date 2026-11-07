"""YouTube analysis: Gemini's summary/commentary cleaned, comment shares COUNTED (never estimated), refusals never used."""
import sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from studio import ytanalysis as y


class YT(unittest.TestCase):
    def test_clean_strips_gemini_ui(self):
        self.assertEqual(y._clean("Gemini said\n\nThe facts.\n\nTo explore this further:\nchip one"), "The facts.")

    def test_verdict_counts_shares(self):
        coms = [{"author": f"@u{i}", "text": f"comment {i}", "likes": 100 - i} for i in range(20)]
        labels = {str(i): ("Youssef won" if i < 15 else "Weiss won" if i < 18 else "neither") for i in range(20)}
        llm = MagicMock(); llm.__enter__.return_value.chat_json.return_value = {"sides": ["Youssef won", "Weiss won"], "labels": labels}
        with patch("studio.llm.LLM", return_value=llm):
            r = y.verdict({}, coms, "a debate", lambda _: None)
        self.assertEqual([(x["side"], x["n"], x["share"]) for x in r["sides"]], [("Youssef won", 15, 83), ("Weiss won", 3, 17)])
        self.assertEqual(r["top"][0]["author"], "@u0")
        self.assertEqual(len(r["top"]), 5)

    def test_refusal_is_not_saved(self):
        with tempfile.TemporaryDirectory() as src, patch.object(y, "fetch_comments", return_value=[]):
            fake_pw = MagicMock()
            with patch("playwright.sync_api.sync_playwright", return_value=fake_pw), \
                    patch("studio.imagegen._launch", return_value=(MagicMock(), MagicMock())), \
                    patch("studio.imagegen._check"), patch("studio.imagegen._responses", return_value=[]), \
                    patch("studio.imagegen._box"), patch("studio.imagegen._send"), \
                    patch("studio.imagegen._wait_answer", return_value="Gemini said I cannot directly access or stream external YouTube video links. " * 3):
                self.assertIsNone(y.analyze({}, "https://www.youtube.com/watch?v=x", src, lambda _: None))
            self.assertFalse((Path(src) / "gemini_analysis.md").exists())

    def test_only_youtube_links(self):
        self.assertTrue(y.is_youtube("https://youtu.be/abc"))
        self.assertFalse(y.is_youtube("https://example.com/video.mp4"))


if __name__ == "__main__":
    unittest.main()
