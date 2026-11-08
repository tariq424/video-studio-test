"""Nov 8 smoke test findings, as principles: a sketch stays a sketch when animated; the people in the story (including whoever
speaks in your footage) are always on the entity list, each with ONE look from a real frame; the fact-check accepts the place
notes we verified ourselves."""
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from studio import coherence, mediaroutes, people, writer  # noqa: E402


def test_keep_drawn_is_in_the_animate_prompts():
    src = (Path(__file__).parents[1] / "app" / "studio" / "routelib" / "routes.py").read_text(encoding="utf-8")
    assert "people.KEEP_DRAWN if drawn" in src
    assert "a drawing or sketch stays a drawing" in src
    assert "photograph" in people.KEEP_DRAWN


def test_animation_that_loses_the_sketch_falls_back_to_the_still(tmp_path, monkeypatch):
    vid, img = tmp_path / "b0_chain.mp4", tmp_path / "b0_chain.jpg"
    vid.write_bytes(b"x"); img.write_bytes(b"x")
    monkeypatch.setattr("studio.media.ok", lambda p: True)
    monkeypatch.setattr("studio.media.dur", lambda p: 5.0)
    monkeypatch.setattr("studio.media.ff", lambda *a, **k: Path(a[-1]).write_bytes(b"x"))
    seen = []
    def drawn(cfg, p):
        seen.append(Path(p).name); return Path(p).name == "b0_chain.jpg"   # still drawn, animation frame photo-real
    monkeypatch.setattr(people, "is_drawing", drawn)
    res = mediaroutes._keep_drawn({}, tmp_path, "b0_chain", vid, img, lambda *_: None, {"video": vid, "image": img})
    assert res["video"] is None and res["image"] == img
    assert (tmp_path / "b0_chain.drawn_lost").is_file()


def test_animation_that_keeps_the_sketch_is_used(tmp_path, monkeypatch):
    vid, img = tmp_path / "k.mp4", tmp_path / "k.jpg"
    vid.write_bytes(b"x"); img.write_bytes(b"x")
    monkeypatch.setattr("studio.media.ok", lambda p: True)
    monkeypatch.setattr("studio.media.dur", lambda p: 5.0)
    monkeypatch.setattr("studio.media.ff", lambda *a, **k: Path(a[-1]).write_bytes(b"x"))
    monkeypatch.setattr(people, "is_drawing", lambda cfg, p: True)
    res = mediaroutes._keep_drawn({}, tmp_path, "k", vid, img, lambda *_: None, {"video": vid, "image": img})
    assert res["video"] == vid


def test_photo_still_is_not_checked(tmp_path, monkeypatch):
    vid, img = tmp_path / "p.mp4", tmp_path / "p.jpg"
    vid.write_bytes(b"x"); img.write_bytes(b"x")
    monkeypatch.setattr("studio.media.ok", lambda p: True)
    calls = []
    monkeypatch.setattr(people, "is_drawing", lambda cfg, p: calls.append(p) or False)
    res = mediaroutes._keep_drawn({}, tmp_path, "p", vid, img, lambda *_: None, {"video": vid, "image": img})
    assert res["video"] == vid and len(calls) == 1


def test_people_never_crowded_out_by_places():
    assert "People never count toward the 6" in coherence.ENTITIES
    assert "speaks, is interviewed or introduces themselves" in coherence.ENTITIES


def test_entity_cap_keeps_people(tmp_path):
    places = [{"name": f"Place {i}", "kind": "building"} for i in range(7)]
    class L:
        def chat_json(self, *a, **k): return {"entities": places + [{"name": "Nia Dixon", "kind": "person", "role": "Visitor"}]}
    out = coherence.entities({}, tmp_path, "t", "text", lambda *_: None, lambda: False, llm=L())
    assert [e["name"] for e in out if e["kind"] == "person"] == ["Nia Dixon"]
    assert len([e for e in out if e["kind"] != "person"]) == 6


def test_one_look_per_person_reused_by_every_sketch(tmp_path, monkeypatch):
    (tmp_path / "entities.json").write_text(json.dumps([{"name": "Nia Dixon", "kind": "person"}]), encoding="utf-8")
    snap = tmp_path / "b0_snap.png"; snap.write_bytes(b"x")
    calls = []
    monkeypatch.setattr(people, "_vision_json", lambda cfg, img, ask: calls.append(1) or
                        {"person": "yes", "look": "The person appears to be an older woman with short gray hair, wearing a dark fleece jacket, and is indoors"})
    sec = {"vo": "Nia Dixon lives in Merrimack."}
    look = people.learn_look({}, tmp_path, sec, snap, None, lambda *_: None)
    assert look == "an older woman with short gray hair, wearing a dark fleece jacket"
    people.learn_look({}, tmp_path, {"vo": "Nia wanted quiet."}, snap, None, lambda *_: None)
    assert len(calls) == 1   # once per job
    saved = json.loads((tmp_path / "entities.json").read_text(encoding="utf-8"))
    assert saved[0]["look"] == look
    people._LOOKS.clear(); people._LOOKS_JOB[0] = None
    people.ents_for(tmp_path)   # a later step (another process) reads it back
    assert look in people.rule(["Nia Dixon"]) and "courtroom sketch" in people.rule(["Nia Dixon"])


def test_no_look_for_two_people_or_no_person(tmp_path, monkeypatch):
    (tmp_path / "entities.json").write_text(json.dumps([{"name": "Nia Dixon", "kind": "person"}, {"name": "Clinton Smith", "kind": "person"}]),
                                            encoding="utf-8")
    snap = tmp_path / "s.png"; snap.write_bytes(b"x")
    monkeypatch.setattr(people, "_vision_json", lambda *a: {"person": "no", "look": ""})
    assert people.learn_look({}, tmp_path, {"vo": "Nia Dixon and Clinton Smith met."}, snap, None, lambda *_: None) == ""
    assert people.learn_look({}, tmp_path, {"vo": "Nia Dixon spoke."}, snap, None, lambda *_: None) == ""


def test_fact_check_gets_the_verified_place_notes(tmp_path):
    (tmp_path / "place_colour.md").write_text("PLACE COLOUR: Royal Naval Dockyard, Bermuda", encoding="utf-8")
    assert "Royal Naval Dockyard" in writer.verified_notes(tmp_path)
    assert writer.verified_notes(tmp_path / "nope") == ""
    sent = []
    class L:
        def trace(self, *_): return self
        def chat_json(self, system, prompt, **k):
            sent.append(prompt); return {"vo": "We are at the Royal Naval Dockyard in Bermuda today with Nia.", "changes": []}
    plan = {"sections": [{"id": "b0", "title": "Beat 1", "vo": "We are at the Royal Naval Dockyard in Bermuda today with Nia.", "visuals": []}]}
    writer.fact_check(L(), plan, {"title": "t", "verified_notes": "PLACE COLOUR: Royal Naval Dockyard"}, "transcript words here", lambda *_: None, cfg={})
    assert "VERIFIED PLACE NOTES" in sent[0] and "Royal Naval Dockyard" in sent[0]


def test_render_workers_follow_free_memory(monkeypatch):
    from studio import short
    import psutil
    class VM:
        def __init__(self, gb): self.available = gb * 2**30
    assert short.render_concurrency({"short_concurrency": "3"}) == 3   # a number overrides
    for gb, n in ((12, 6), (6, 4), (3, 2)):
        monkeypatch.setattr(psutil, "virtual_memory", lambda gb=gb: VM(gb))
        assert short.render_concurrency({"short_concurrency": "auto"}) == n
        assert short.render_concurrency({"short_concurrency": "75%"}) == n   # old setting means auto


def test_headless_shell_first_installed_chrome_fallback(monkeypatch, tmp_path):
    from studio import short
    monkeypatch.setattr(short, "headless_shell", lambda log=print: tmp_path / "chrome-headless-shell.exe")
    assert "chrome-headless-shell" in short.render_browser_args({}, lambda *_: None)[0]
    monkeypatch.setattr(short, "headless_shell", lambda log=print: None)
    assert "chrome-headless-shell" not in "".join(short.render_browser_args({}, lambda *_: None))
    assert "chrome-headless-shell" not in "".join(short.render_browser_args({"remotion_headless_shell": False}, lambda *_: None))
    src = (Path(__file__).parents[1] / "app" / "studio" / "short.py").read_text(encoding="utf-8")
    assert "trying again with the installed Chrome" in src   # a failed shell render retries in Chrome before any clip becomes a card


def test_first_name_alone_counts_when_unique():
    ents = [{"name": "Nia Dixon", "kind": "person"}, {"name": "Clinton Smith", "kind": "person"}, {"name": "Clinton Jones", "kind": "person"}]
    assert people.names("Nia figured the tour was off.", ents) == ["Nia Dixon"]
    assert people.names("the nia of it", ents) == []          # lower-case word, not the name
    assert people.names("Clinton waved.", ents) == []         # two Clintons: ambiguous
    assert people.names("Smith waved.", ents) == ["Clinton Smith"]
