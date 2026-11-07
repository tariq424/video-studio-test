"""Nov 7: with vision vetting off, a "vibrant brazilian flag over rio favela" stock clip played over a line about Israeli
sovereignty. The stock site's own title is now checked against the story, even when vision vetting is off."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from studio import footage  # noqa: E402


class FakeLLM:
    def __init__(self, *a, **k): pass
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def chat_json(self, system, prompt, max_tokens=0):
        title = prompt.split('Clip title: "')[1].split('"')[0]
        return {"contradicts": "flag" in title and "israel" not in title, "why": "another country's flag"}


def test_offstory_title_rejected_with_vetting_off(monkeypatch, tmp_path):
    from PIL import Image, ImageDraw
    monkeypatch.setattr(footage, "LLM", FakeLLM)
    footage._TITLE_CACHE.clear()
    img = Image.new("RGB", (64, 64), "gray"); d = ImageDraw.Draw(img)
    for x in range(0, 64, 4): d.line([(x, 0), (x, 63)], fill="white" if x % 8 else "black")
    sheet = tmp_path / "s.jpg"; img.save(sheet)
    cfg = {"vet_provider": "off"}
    vo = "Those who don't accept Israeli sovereignty should go to other countries."
    bad = {"id": "px1", "desc": "vibrant brazilian flag over rio favela", "query": "flags on hill"}
    ok, why, _ = footage.verify(cfg, bad, sheet, print, narration=vo, place="Israel")
    assert not ok and "title" in why
    good = {"id": "px2", "desc": "hillside settlement with trailers", "query": "outpost on hill"}
    ok, why, _ = footage.verify(cfg, good, sheet, print, narration=vo, place="Israel")
    assert ok, why


def test_title_check_can_be_turned_off():
    assert footage.title_contradicts({"clip_title_check": False}, "brazilian flag", "Israel line") == ""


class FakePlaceLLM(FakeLLM):
    def chat_json(self, system, prompt, max_tokens=0):
        seen = prompt.split('shows: "')[1].split('"')[0].lower()
        return {"outside": any(k in seen for k in ("japan", "us flag", "india"))}


def test_place_check_rejects_other_country_maps_but_keeps_every_side(monkeypatch):
    """Nov 7: maps of Japan / the US / India with pins passed vetting for Gaza lines."""
    monkeypatch.setattr(footage, "LLM", FakePlaceLLM)
    footage._PLACE_CACHE.clear()
    story = "Daniella Weiss wants settlers in Gaza; Bassem Youssef asks what happens to Egypt."
    assert not footage.place_ok({}, "map of Japan", "Israel", story=story, narration="the whole biblical promise")
    assert not footage.place_ok({}, "US flag", "Israel", story=story, narration="a new settlement")
    assert footage.place_ok({}, "Egyptian flag", "Israel", story=story, narration="110 million Egyptians")
    assert footage.place_ok({}, "Gaza City", "Israel", story=story, narration="settlers in Gaza")   # named in the line: no AI call
