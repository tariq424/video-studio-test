"""House style from feedback: rules learned (via the script AI), merged/replaced, added to every script prompt, removable."""
import json, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from studio import style, writer  # noqa: E402


class FakeLLM:
    replies = []
    def __init__(self, *a): pass
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def chat_json(self, system, user, max_tokens=0, check=None):
        FakeLLM.last = user
        j = FakeLLM.replies.pop(0); assert check is None or check(j) is None; return j


def test_learn_merge_apply_remove(monkeypatch):
    cfg = {"jobs_dir": str(Path(tempfile.mkdtemp()) / "jobs"), "audience": "common"}
    assert style.text(cfg) == "" and writer.audience_line(cfg) == writer.AUDIENCE["common"]   # no rules: prompts unchanged
    monkeypatch.setattr("studio.llm.LLM", FakeLLM)
    FakeLLM.replies = [{"rules": [{"area": "humor", "rule": "One dry joke per beat, never puns.", "replaces": []}]}]
    r = style.learn(cfg, "the puns were awful", "Short 'Nvidia earnings'", "J1", lambda m: None)
    rid = r["added"][0]["id"]
    assert "the puns were awful" in FakeLLM.last and r["added"][0]["job"] == "J1"
    FakeLLM.replies = [{"rules": [{"area": "humor", "rule": "One dry joke per beat; puns only if truly clever.", "replaces": [rid]},
                                  {"area": "visuals", "rule": "No stock footage of people typing.", "replaces": ["nope"]}]}]
    r = style.learn(cfg, "ok a good pun is fine; and stop the typing hands", "Short 'X'", "J2", lambda m: None)
    assert r["replaced"] == [rid] and rid in FakeLLM.last
    rules = style.load(cfg); assert [x["area"] for x in rules] == ["humor", "visuals"]
    line = writer.audience_line(cfg)
    assert "HOUSE STYLE" in line and "puns only if truly clever" in line and "people typing" in line
    from studio import flow
    assert "people typing" in flow._style(cfg) and "puns" not in flow._style(cfg)   # visual prompts get visual rules only
    added = style.add(cfg, "Never open with a question.", "script")
    assert style.remove(cfg, added["id"]) and not style.remove(cfg, "zzz")
    style.replace_all(cfg, rules[:1]); assert len(style.load(cfg)) == 1


def test_endpoints(monkeypatch):
    import server
    from studio import config
    tmp = Path(tempfile.mkdtemp())
    monkeypatch.setattr(config, "load", lambda: {"jobs_dir": str(tmp / "jobs")})
    c = server.app.test_client()
    assert c.get("/api/style").get_json() == {"rules": []}
    r = c.post("/api/style", json={"rule": "Keep hooks under 8 words.", "area": "script"}).get_json()["rule"]
    assert c.get("/api/style").get_json()["rules"][0]["rule"] == "Keep hooks under 8 words."
    assert c.post("/api/style/learn", json={"note": ""}).status_code == 400
    assert c.delete(f"/api/style/{r['id']}").get_json()["ok"]
