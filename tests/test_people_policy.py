"""People policy (owner, 2026-11-07): nobody anonymised; named people drawn as courtroom sketches; no rebuilt screen layouts;
no mouthing; a speaker inset from the real source frame; longer real source clips."""
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from studio import people, imagegen, source_visuals, storyboard  # noqa: E402

ENTS = [{"name": "Daniella Weiss", "kind": "person"}, {"name": "Bassem Youssef", "kind": "person"}, {"name": "Gaza", "kind": "place"}]


def test_names_and_tail():
    vo = "Youssef asks Weiss about Egypt."
    assert people.names(vo, ENTS) == ["Daniella Weiss", "Bassem Youssef"]
    t = people.tail({"people": ["Daniella Weiss"]})
    assert "Daniella Weiss" in t and "courtroom sketch" in t and "Photorealistic" not in t
    assert people.tail({"people": []}).strip().startswith("Photorealistic")
    assert "recogni" not in t.lower()


def test_text_prompt_has_no_anonymising_and_sketches_named_people():
    sec = {"id": "b1", "vo": "Weiss says so.", "people": ["Daniella Weiss"],
           "described_prompt": "A woman at a desk. No real or recognizable people."}
    p = imagegen._text_prompt({}, sec, print)
    assert "recogni" not in p.lower() and "Daniella Weiss" in p and "courtroom sketch" in p


def test_layout_descriptions_are_detected():
    assert people.rebuilds_layout("Three-panel split-screen video call, each a chest-up shot")
    assert people.rebuilds_layout("a virtual panel discussion with four individuals in separate frames")
    assert not people.rebuilds_layout("An elderly woman in a headscarf stands on a dusty hill at dusk")


def test_describe_rules_do_not_anonymise():
    assert "anonym" not in imagegen.LOCAL_DESCRIBE.lower() or "do not anonymise" in imagegen.LOCAL_DESCRIBE.lower()
    assert "do not anonymise" in people.DESCRIBE_RULE.lower()
    assert "no lip movement" in people.ANIMATE
    src = (Path(__file__).resolve().parents[1] / "app" / "studio" / "routelib" / "routes.py").read_text(encoding="utf-8")
    assert "anonymous figure" not in src and src.count("no lip movement") >= 2


def test_storyboard_prompt_allows_named_people_as_sketch():
    assert "{people_rule}" in storyboard.PROMPTS
    assert "courtroom sketch" in storyboard._people_rule({"people": ["Daniella Weiss"]})


def test_inset_added_to_non_source_shots(tmp_path):
    sd = tmp_path / "short"; ex = sd / "source_excerpts"; ex.mkdir(parents=True)
    from PIL import Image
    Image.new("RGB", (64, 36), (10, 20, 30)).save(ex / "b1_snap.png")
    pub = tmp_path / "pub"
    bgs = [{"type": "video", "src": "media/fb/x.mp4", "tag": "SOURCE · Show"}, {"type": "graphic", "g": {"kind": "map"}},
           {"type": "image", "src": "media/fb/y.jpg", "tag": "GENERATED · CLOUDFLARE"}]
    used = []
    people.add_insets(sd, pub, {"id": "b1", "vo": "Weiss's promised land runs Nile to Euphrates."}, bgs, ENTS, used, log=lambda *_: None)
    assert "inset" not in bgs[0] and bgs[1]["inset"]["src"].startswith("media/fb/inset_b1") and "inset" in bgs[2]
    assert (pub / bgs[1]["inset"]["src"]).is_file() and used
    # no named person -> no inset
    b2 = [{"type": "graphic", "g": {"kind": "map"}}]
    people.add_insets(sd, pub, {"id": "b1", "vo": "The map of the region."}, b2, ENTS, log=lambda *_: None)
    assert "inset" not in b2[0]
    # switched off
    b3 = [{"type": "graphic", "g": {"kind": "map"}}]
    people.add_insets(sd, pub, {"id": "b1", "vo": "Weiss"}, b3, ENTS, log=lambda *_: None, cfg={"speaker_inset": False})
    assert "inset" not in b3[0]


def test_source_clip_length_and_budget_from_settings(tmp_path):
    assert source_visuals.clip_secs({}) == 8.0 and source_visuals.clip_secs({"source_clip_secs": 99}) == 20.0
    assert source_visuals.max_uses({}) == 6
    src = tmp_path / "src"; src.mkdir()
    (src / "source_cues.json").write_text(json.dumps([{"start": 30.0, "text": "promised land from the Nile to the Euphrates Egypt"}]))
    r = source_visuals.auto_request(tmp_path, {"vo": "Her promised land runs Nile to Euphrates, Egypt too."}, secs=8)
    assert r and r["duration"] == 8
