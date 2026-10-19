import unittest
from unittest.mock import MagicMock, patch

from app.studio import coherence, writer

ENTS = [{"name": "Kling 4", "brand": "Kuaishou", "kind": "product", "category_words": ["camera", "video"], "avoid": "", "colors": []},
        {"name": "Muse Wonder", "brand": "Meta", "kind": "product", "category_words": ["ai model"], "avoid": "", "colors": []},
        {"name": "Willow processor", "brand": "Google", "kind": "product", "category_words": ["chip"], "avoid": "", "colors": []},
        {"name": "Gemini 4 Argon", "brand": "Google", "kind": "product", "category_words": ["chatbot"], "avoid": "", "colors": []}]


class SubjectLockTests(unittest.TestCase):
    def test_generic_words_never_lock(self):
        self.assertIsNone(coherence.assign(ENTS, "hidden camera in office ceiling")[0])
        self.assertIsNone(coherence.assign(ENTS, "gleaming chip, frosty metallic surfaces")[0])

    def test_exact_name_locks_and_shared_brand_does_not(self):
        self.assertEqual(coherence.assign(ENTS, "Willow processor close-up")[0]["name"], "Willow processor")
        self.assertIsNone(coherence.assign(ENTS, "Google office lobby")[0])      # two Google subjects: ambiguous
        self.assertEqual(coherence.assign(ENTS, "Meta headquarters")[0]["name"], "Muse Wonder")


class ProtectionTests(unittest.TestCase):
    def plan(self):
        return {"sections": [{"id": "b0", "title": "Beat 1", "visuals": [],
                              "vo": "Willow cut errors forty times. Our take: lab progress, not a product. Like sorting produce at a grocery store.",
                              "protect": ["Our take: lab progress, not a product", "Like sorting produce at a grocery store"]}]}

    def test_fact_check_retries_when_it_drops_a_joke_then_accepts_accuracy(self):
        llm = MagicMock(); llm.trace.return_value = llm
        calls = []
        def chat_json(system, prompt, max_tokens=0, check=None):
            calls.append(prompt)
            j = {"vo": "Willow cut errors about forty times. It is lab progress, not a product, and quite neat to see.", "changes": []}
            check(j)
            return j
        llm.chat_json.side_effect = chat_json
        p = self.plan()
        logs = []
        writer.fact_check(llm, p, {}, "transcript words " * 50, logs.append)
        self.assertIn("PROTECTED WORDS", calls[0])
        self.assertTrue(any("had to reword" in l for l in logs))
        self.assertIn("about forty", p["sections"][0]["vo"])

    def test_punch_up_appends_a_joke_only_where_missing(self):
        p = {"sections": [{"id": "b0", "vo": "Willow cut errors forty times on magic states."},
                          {"id": "b1", "vo": "x y z. Our joke here is fine.", "joke": "Our joke here is fine"},
                          {"id": "b2", "vo": "Follow for more.", "cta": {"kind": "cta"}}]}
        fake = MagicMock(); fake.__enter__.return_value = fake; fake.name = "deepseek"; fake.trace.return_value = fake
        fake.chat_json.return_value = {"joke": "Finally, a computer that fails less often than my printer"}
        with patch("app.studio.llm.LLM", return_value=fake):
            writer.punch_up({}, p, print)
        self.assertTrue(p["sections"][0]["vo"].endswith("than my printer."))
        self.assertEqual(p["sections"][1]["vo"], "x y z. Our joke here is fine.")
        self.assertEqual(fake.chat_json.call_count, 1)


if __name__ == "__main__":
    unittest.main()


class SmokeTrimAndStockGateTests(unittest.TestCase):
    def test_trim_keeps_main_fact_and_opinion(self):
        from app.studio import short
        plan = {"sections": [{"id": "b0", "take": "Honestly, that is not spycraft.",
                              "vo": "An OpenAI employee hid a twenty-dollar recorder behind a TV. It was wrapped in toilet paper in a conference room. "
                                    "The FBI arrested him in October. Honestly, that is not spycraft."},
                             {"id": "b1", "vo": "That was AI Search, condensed.", "cta": {"kind": "cta"}}]}
        short.trim_smoke(plan, lambda m: None)
        self.assertEqual(plan["sections"][0]["vo"], "An OpenAI employee hid a twenty-dollar recorder behind a TV. Honestly, that is not spycraft.")
        self.assertEqual(plan["sections"][1]["vo"], "That was AI Search, condensed.")

    def test_stock_gate(self):
        from app.studio import footage
        q = ["hidden camera in office ceiling"]
        self.assertFalse(footage.on_subject({"desc": "animation of an unrolled tissue paper"}, q))
        self.assertTrue(footage.on_subject({"desc": "security cameras on an office ceiling"}, q))
        nar = "Google says its Willow quantum chip got more reliable."
        self.assertFalse(footage.on_subject({"desc": "futuristic circuit board with glowing neon"}, ["glowing quantum chip"], None, nar))
        self.assertTrue(footage.on_subject({"desc": "quantum computer chip close up"}, ["glowing quantum chip"], None, nar))
