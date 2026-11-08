"""Owner, 2026-11-07 smoke-test findings, fixed for every video: own footage is the real source, place colour is really used,
no invented travel numbers, no single repair clip frozen across a long span."""
import json, subprocess, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from studio import media, physics, place, qc_repair, source_visuals, sources  # noqa: E402

PC = {"where": {"area": "Royal Naval Dockyard", "name": "Maritime Lane", "country": "Bermuda"}, "notes": [{"fact": "x"}],
      "sights": [{"name": "Ireland Island, Bermuda"}, {"name": "Places of interest in Bermuda"}, {"name": "Sandys Parish"}]}


def test_place_colour_terms_and_use():
    assert place.terms(PC) == ["Royal Naval Dockyard", "Maritime Lane", "Ireland Island", "Sandys"]
    assert place.colour_used(PC, [{"vo": "We're at the Royal Naval Dockyard."}, {"vo": "The boat tour was cancelled."}]) == 1
    assert place.colour_used(PC, [{"vo": "We're at the Royal Naval Dockyard."}, {"vo": "Ireland Island is next door."}]) == 2
    assert "ALL THREE are required" in place.COLOUR


def test_no_travel_chart_without_a_stated_number():
    assert physics.synthetic_profile({"vo": "She and her husband sailed the Caribbean on their own boat."}) is None
    r = physics.synthetic_profile({"vo": "Their ship sailed 300 km to Bermuda."})
    assert r and r["module"] == "synthetic_travel" and abs(r["series"][-1][1] - 300) < 40


def test_own_footage_cues_start_at_zero(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "source_cues.json").write_text(json.dumps([{"start": 3.0, "text": "glass bottom boat tour cancelled reefs wind"}]))
    sec = {"vo": "The glass bottom boat tour was cancelled because of wind on the reefs."}
    assert source_visuals.auto_request(tmp_path, sec) is None   # a YouTube source: the first 15 s are a bumper
    (tmp_path / "src" / "meta.json").write_text(json.dumps({"own_footage": True}))
    r = source_visuals.auto_request(tmp_path, sec, secs=8)
    assert r and r["start"] == 3.0 and r["duration"] == 8


def test_uploaded_video_kinds():
    assert sources.kind_of("IMG_0001.MOV") == "audio" and ".mov" in sources.VIDEO


def test_repair_joins_several_clips(tmp_path):
    clips = []
    for k, colour in enumerate(("red", "blue")):
        c = tmp_path / f"c{k}.mp4"
        media.ff("-f", "lavfi", "-i", f"color={colour}:s=320x240:d=4:r=30", "-c:v", "libx264", "-pix_fmt", "yuv420p", c, timeout=120)
        clips.append(c)
    out = qc_repair.join_clips(clips, 6.0, 360, 640, tmp_path / "j.mp4")
    assert abs(media.dur(out) - 6.0) < 0.3


def test_person_in_a_real_frame_is_sketched():
    from studio import people, imagegen
    assert people.shows_person("An older woman with short grey hair in a gift shop") and not people.shows_person("A white boat at a dock")
    p = imagegen._text_prompt({}, {"vo": "x", "people": [], "person_in_frame": True, "described_prompt": "An older woman in a shop."}, print)
    assert "courtroom sketch" in p and "Photorealistic" not in p
    p = imagegen._text_prompt({}, {"vo": "x", "people": [], "described_prompt": "A white boat at a dock."}, print)
    assert "Photorealistic" in p


def test_fill_beat_never_freezes_one_shot():
    from studio.short import _fill_beat
    src, lay, gfx = {"type": "video"}, {"type": "layers"}, {"type": "video"}
    r = _fill_beat([("fb", src, 8.0), ("fb", lay, 7.0), ("fb", gfx, 7.9)], 36.4)
    assert sum(cp for *_, cp in r) >= 36.1 and all(a[1] is not b[1] for a, b in zip(r, r[1:]))
    assert max(cp for *_, cp in r) <= 11.0


def test_map_needs_spread_out_places():
    from studio.short import map_useful
    near = {"points": [{"lat": 32.327, "lon": -64.834}, {"lat": 32.255, "lon": -64.818}]}
    far = {"points": [{"lat": 25.2, "lon": 55.3}, {"lat": 21.5, "lon": 39.2}]}
    assert not map_useful(near) and map_useful(far)
