"""Interview edit: cold-open hook located from an exact quote; filters build."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from studio import interview as I  # noqa: E402

SEGS = [{"i": 0, "text": "hello there", "words": [["hello", 0, 0.5], ["there", 0.5, 1]]},
        {"i": 1, "text": "They took her property, and they took her land. Wow.",
         "words": [["They", 10, 10.2], ["took", 10.2, 10.4], ["her", 10.4, 10.5], ["property,", 10.5, 11], ["and", 11, 11.1],
                   ["they", 11.1, 11.2], ["took", 11.2, 11.4], ["her", 11.4, 11.5], ["land.", 11.5, 12], ["Wow.", 12.2, 12.5]]}]


class FakeLLM:
    def __init__(self, *a, **k): pass
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def chat_json(self, system, user, max_tokens=0, check=None):
        j = {"seg": 1, "quote": "They took her property, and they took her land.", "text": "They took her land"}
        if check: check(j)
        return j


def test_hook(tmp_path, monkeypatch):
    import studio.llm
    monkeypatch.setattr(studio.llm, "LLM", FakeLLM)
    h = I.hook({}, SEGS, "ctx", "short", tmp_path, lambda m: None)
    assert h and abs(h["t0"] - 9.85) < 0.01 and abs(h["t1"] - 12.35) < 0.01 and h["text"] == "They took her land"
    assert (tmp_path / "hook_short.json").exists()


def test_filters():
    assert I._vf("short", 0.3, 1.12).startswith("hflip,crop=")
    assert "hflip" not in I._vf("documentary", None, 1.0, flip=False)


def test_fit_trims_long_bites_and_short():
    segs = [{"i": i, "start": i * 10.0, "end": i * 10.0 + 9.5, "text": "x", "words": []} for i in range(40)]
    j = {"short": {"items": [{"bite": [0, 0]}, {"bite": [2, 20]}, {"narr": "a b c"}, {"bite": [25, 30]}]},
         "documentary": {"chapters": [{"items": [{"bite": [5, 30]}]}]}}
    I.fit(j, segs, 90)
    assert all(segs[it["bite"][1]]["end"] - segs[it["bite"][0]]["start"] <= 40 for it in j["short"]["items"] if "bite" in it)
    assert I.total_secs(j["short"]["items"], segs) <= 100
    b = j["documentary"]["chapters"][0]["items"][0]["bite"]; assert segs[b[1]]["end"] - segs[b[0]]["start"] <= 60


def test_shots_holder_closeup_becomes_cutaway():
    from studio import shots
    an = {"secs": [{"t": t, "faces": ([[0.5, 0.4, 0.3, 0.3]] if t < 3 else [[0.3, 0.4, 0.1, 0.12]]), "tilt": 0} for t in range(6)]}
    sh = shots.plan_shots(an, 0, 6)
    assert [x[2] for x in sh] == ["self", "guest"] and sh[1][3][0] == 0.3
    assert "rotate=" in shots.vf_frame("documentary", None, 6.0) and "rotate=" not in shots.vf_frame("documentary", None, 1.0)


def test_shots_two_shot_selfie_and_edge_holder():
    from studio import shots
    # close selfie: two big faces -> the bigger one is the holder, the other the guest
    assert shots.kind_of({"faces": [[0.3, 0.5, 0.22, 0.3], [0.7, 0.4, 0.36, 0.5]]}) == "guest"
    # the holder half out of shot at the right edge, alone -> cutaway
    assert shots.kind_of({"faces": [[0.97, 0.5, 0.06, 0.7]]}) == "self"
    # a tiny face (a mirror) is nobody
    assert shots.kind_of({"faces": [[0.5, 0.5, 0.03, 0.05]]}) == "none"
    # car ceiling: flat top, the guest's head poking up at the bottom -> cutaway
    assert shots.kind_of({"faces": [[0.8, 0.85, 0.1, 0.2]], "top": 0.84}) == "empty"
    assert shots.kind_of({"faces": [], "top": 0.8}) == "empty"


def test_shots_crop_leaves_holder_out():
    from studio import shots
    vf = shots.vf_frame("documentary", [0.3, 0.5, 0.15, 0.2, [0.8, 0.45, 0.3, 0.5]], 0, False)
    import re
    z = float(re.search(r"ih/([0-9.]+)", vf).group(1)); x0 = float(re.search(r"iw\*([0-9.]+)", vf).group(1))
    cwf = 16 / 9 * 1080 / 1920 / z
    assert x0 + cwf <= 0.65 + 1e-3 and x0 <= 0.3 - 0.075


def test_short_ends_on_soundbite():
    from studio import interview
    its = interview.end_on_bite([{"bite": [0, 1]}, {"narr": "x"}, {"bite": [3, 4]}, {"narr": "closing"}, {"insert": "y"}])
    assert its[-1] == {"bite": [3, 4]} and len(its) == 3


def test_shots_head_at_bottom_edge_is_cut_away():
    from studio import shots
    assert shots.kind_of({"faces": [[0.5, 0.9, 0.12, 0.2]]}) == "empty"
    assert shots.kind_of({"faces": [[0.5, 0.45, 0.12, 0.2]]}) == "guest"


def _segs(n, sec=10.0):
    return [{"i": i, "start": i * sec, "end": i * sec + sec - 1.0, "text": f"Sentence {i}.", "words": []} for i in range(n)]


def test_augment_keeps_order_drops_and_pauses_for_facts():
    from studio import interview
    segs = _segs(12)
    tri = {"drop": [[3, 4, "small talk"]], "facts": [{"after": 6, "note": 0, "text": "A fact.", "visual": "harbour"}],
           "jokes": [{"after": 7, "text": "A joke."}], "chapters": [{"at": 0, "title": "Start"}, {"at": 9, "title": "Later"}],
           "pictures": [{"from": 0, "to": 11, "visual": "Bermuda road"}]}
    its = interview.augment_items(tri, segs)
    bites = [tuple(x["bite"]) for x in its if "bite" in x]
    kept = [i for a, b in bites for i in range(a, b + 1)]
    assert kept == [0, 1, 2, 5, 6, 7, 8, 9, 10, 11]   # in order, the dropped stretch gone
    k = next(i for i, x in enumerate(its) if "insert" in x)
    assert its[k - 1]["bite"][1] == 6 and its[k + 1]["bite"][0] == 7   # paused after 6, picks up at 7
    assert not any("narr" in its[i] and "insert" in its[i - 1] for i in range(1, len(its)))   # never two in a row
    assert next(x for x in its if "bite" in x and x["bite"][0] == 9)["chapter"] == "Later"
    assert all(x.get("visual") == "Bermuda road" for x in its if "bite" in x)


def test_cut_points_join_without_repeats():
    from studio import interview
    segs = _segs(5)
    _, a1 = interview._cut_points(segs, 0, 1)
    b0, _ = interview._cut_points(segs, 2, 3)
    assert a1 <= b0 and a1 > segs[1]["end"] and b0 < segs[2]["start"]


def test_missed_seconds_beside_holder_are_covered():
    from studio import shots
    secs = [{"t": 0, "faces": [[0.5, 0.5, 0.5, 1.0]], "tilt": 0}, {"t": 1, "faces": [], "tilt": 0}, {"t": 2, "faces": [], "tilt": 0},
            {"t": 3, "faces": [[0.5, 0.5, 0.5, 1.0]], "tilt": 0}] + [{"t": t, "faces": [], "tilt": 0} for t in range(4, 12)]
    sh = shots.plan_shots({"secs": secs}, 0, 12)
    assert sh[0][2] == "self" and sh[0][1] >= 5 and sh[-1][2] == "none"


def test_trip_footage_place_subject_scenery(tmp_path):
    import json
    from studio import interview
    cat = tmp_path / "catalog"; cat.mkdir()
    def rec(name, place, tags, desc, secs=20, **kw):
        f = tmp_path / f"{name}.MOV"; f.write_bytes(b"x")
        (cat / f"{name}.json").write_text(json.dumps(dict(original=str(f), seconds=secs, place=place, area="", address=place, tags=tags,
                                                        description=desc, **({"people": "none", "face_closeup": False, "quality": "good"} | kw))))
    rec("stg", "Town of St. George", ["church", "street"], "An old stone church on a narrow street.")
    rec("beach", "Horseshoe Bay Beach Road", ["beach", "ocean", "sky"], "A pink sand beach with turquoise water.")
    rec("selfie", "Hamilton", ["man", "street"], "A man's face close to the camera.", face_closeup=True)
    rec("plane", "Apron VII", ["airplane", "cabin"], "Inside an airplane cabin.")
    tf = interview.TripFootage(cat, root=None)
    tf._faceless = lambda f, r, d: True   # (fake files: the pixel face check is exercised live)
    assert len(tf.recs) == 2   # face close-up and airplane clips are never used
    assert tf.pick("St. George's church", "they built it in St. George's", 6, "place")[2]["original"].endswith("stg.MOV")
    assert tf.pick("Tucker's Town", "the land in Tucker's Town", 6, "place") is None   # not filmed there: no place match
    assert tf.pick("Tucker's Town", "the land in Tucker's Town", 6, "scenery") is None   # named place: no anonymous scenery as if it were it
    assert tf.pick("", "it's very nice here", 6, "scenery")[2]["original"].endswith("beach.MOV")


def test_augment_breaks_at_a_new_clip():
    from studio import interview
    segs = _segs(6)
    for x in segs[3:]: x["src"] = 1
    its = interview.augment_items({"chapters": [{"at": 0, "title": "A"}]}, segs)
    assert [tuple(x["bite"]) for x in its if "bite" in x] == [(0, 2), (3, 5)]
    t0, _ = interview._cut_points(segs, 3, 5)
    assert t0 == segs[3]["start"] - 0.15   # the new clip starts clean, not halfway into the other clip's pause
