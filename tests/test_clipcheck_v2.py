"""Clip check v2: reject only for a contradiction (owner, 2026-10-23)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from studio import footage as F  # noqa: E402

OK = {"same_scene": True, "looks_ok": True, "overlay_text": False, "platform": False, "mood_clash": False, "stand_in": False}


def v(j, mv, place="", neutral=False):
    return F.contra_verdict({}, {**OK, **j}, mv, place, neutral, log=lambda m: None)


def test_kind():
    assert F.kind_clash("car", "pickup truck", "an electric car")
    assert not F.kind_clash("car", "sedan", "an electric car")
    assert not F.kind_clash("truck", "pickup truck", "a pickup truck")
    assert F.kind_clash("cat", "dog", "a cat")
    assert F.kind_clash("pen", "ballpoint pen", "a fountain pen")
    assert not F.kind_clash("pen", "fountain pen", "a fountain pen")
    assert not F.kind_clash("buildings", "apartment buildings", "beachfront apartment buildings")
    assert not F.kind_clash("", "dog", "")


def test_verdicts():
    beach = {"main": "beachfront apartment buildings", "kind": "buildings", "place": "Cyprus"}
    assert v({"main_visible": "no", "kind_shown": "none", "place_seen": "none"}, beach) == (False, "doesn't show beachfront apartment buildings")
    assert v({"main_visible": "yes", "kind_shown": "apartment buildings", "place_seen": "none"}, beach)[0]
    assert v({"main_visible": "unclear", "kind_shown": "none", "place_seen": "none"}, {"main": "", "kind": "", "place": ""})[0]   # abstract line
    car = {"main": "an electric car", "kind": "car", "place": ""}
    assert not v({"main_visible": "yes", "kind_shown": "pickup truck", "place_seen": "none"}, car)[0]
    # neutral closing card: no recognisable place at all
    ok, why = v({"main_visible": "unclear", "kind_shown": "none", "place_seen": "London skyline"}, {}, neutral=True)
    assert not ok and "closing card" in why
    assert not v({"platform": True, "main_visible": "yes"}, beach)[0]
    assert not v({"mood_clash": True, "main_visible": "yes", "kind_shown": "apartment buildings"}, beach)[0]


def test_place_matching_words_needs_no_ai():
    assert F.place_ok({}, "Limassol, Cyprus seafront", "Cyprus")
    assert F.place_ok({}, "none", "Cyprus")
    assert F.place_ok({}, "Eiffel Tower", "")   # no story place: any real place is fine
