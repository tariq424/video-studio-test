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


def test_hold_previous():
    from studio import short as S
    beats = [{"id": "b0"}, {"id": "b1"}, {"id": "b2"}]
    out = {"b0": [{"type": "layers", "layers": ["a.png"], "rung": "imagegen"}],
           "b1": [{"type": "graphic", "g": {"kind": "headline"}, "rung": "headline"}],
           "b2": [{"type": "graphic", "g": {"kind": "headline"}, "rung": "headline"}]}
    tm = {"b0": {"dur": 4}, "b1": {"dur": 2.5}, "b2": {"dur": 6}}
    S.hold_previous(beats, out, {}, tm, {}, lambda m: None)
    assert out["b1"][0]["rung"] == "hold previous" and out["b1"][0]["layers"] == ["a.png"]
    assert out["b2"][0]["rung"] == "headline"   # too long to hold: the card stays


def test_main_seen_by_kind_even_if_model_says_no():
    beach = {"main": "beachfront property", "kind": "property", "place": "Cyprus"}
    assert v({"main_visible": "no", "kind_shown": "apartment building", "place_seen": "none"}, beach)[0]
    assert not v({"main_visible": "no", "kind_shown": "none", "place_seen": "none"}, beach)[0]
    assert F.place_ok({}, "suburban neighborhood", "China")   # not a nameable place
