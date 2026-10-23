"""Story subject guard: a Tesla story never shows another make (or an unconfirmed one); interiors drive on the country's side."""
import json, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from studio import footage  # noqa: E402
from PIL import Image  # noqa: E402


def _clip(tmp, cid="c1"):
    for k in range(4): Image.new("RGB", (320, 180), (90, 90, 90)).save(tmp / f"{cid}_f{k}.jpg")
    sh = tmp / f"{cid}.jpg"; Image.new("RGB", (1300, 180)).save(sh); return {"id": cid, "desc": "car interior"}, sh


def test_drive_side():
    assert footage.drive_side("Chinese carmakers are winning at home") == "left"
    assert footage.drive_side("Sales in Japan and the UK fell") == "right"
    assert footage.drive_side("Sales in China and Japan") == "" and footage.drive_side("a new battery") == ""


def test_story_guard_and_make_check(monkeypatch):
    tmp = Path(tempfile.mkdtemp()); job = tmp / "job"; (job / "short" / "stock").mkdir(parents=True)
    (job / "entities.json").write_text(json.dumps([{"name": "Tesla Model Y", "brand": "Tesla", "kind": "vehicle"},
                                                  {"name": "Elon Musk", "brand": "", "kind": "person"}]))
    g = footage.story_guard(job / "short", "Tesla's sales in China")
    assert g == {"kinds": {"vehicle": ["Tesla"]}, "side": "left"}
    c, sh = _clip(tmp)
    answers = {}
    monkeypatch.setattr(footage, "_vision", lambda cfg, img, prompt: json.dumps(answers))
    cfg = {}
    answers.update(object=True, make="Honda", drive_side="left")
    ok, why = footage.make_check(cfg, c, sh, g, "Tesla's sales", print); assert not ok and "Honda" in why
    answers.update(make="unknown"); ok, why = footage.make_check(cfg, c, sh, g, "x", print); assert not ok and "can't be confirmed" in why
    answers.update(make="Tesla", drive_side="right"); ok, why = footage.make_check(cfg, c, sh, g, "x", print); assert not ok and "right-hand" in why
    answers.update(make="Tesla Model 3", drive_side="left"); assert footage.make_check(cfg, c, sh, g, "x", print) == (True, "")
    answers.update(object=False, make="none"); assert footage.make_check(cfg, c, sh, g, "x", print) == (True, "")   # a charger, a city: fine
    answers.update(object="car", make="BMW", drive_side="none"); ok, why = footage.make_check(cfg, c, sh, g, "x", print); assert not ok and "BMW" in why
    assert footage.make_check({"story_subject_guard": False}, c, sh, g, "x", print) == (True, "")
