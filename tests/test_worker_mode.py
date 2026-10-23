"""The Linux worker mode: token guard for other machines, outputs listing, secrets from the service environment."""
import json, os, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))


def test_token_guard_and_outputs(monkeypatch):
    import server
    tmp = Path(tempfile.mkdtemp())
    monkeypatch.setattr(server.studio, "jobs_dir", lambda: tmp)
    j = tmp / "J1"; (j / "output").mkdir(parents=True); (j / "output" / "A_short.mp4").write_bytes(b"x"); (j / "output" / "_dbg.jpg").write_bytes(b"x")
    (j / "short").mkdir(); (j / "short" / "plan.json").write_text("{}")
    c = server.app.test_client()
    lan = {"REMOTE_ADDR": "192.168.40.150"}
    monkeypatch.setenv("VS_TOKEN", "s3cret")
    assert c.get("/api/jobs/J1/outputs", environ_base=lan).status_code == 403
    r = c.get("/api/jobs/J1/outputs", environ_base=lan, headers={"X-VS-Token": "s3cret"})
    assert r.status_code == 200 and r.get_json()["files"] == ["output/A_short.mp4", "short/plan.json"]
    assert c.get("/api/jobs/J1/outputs").status_code == 200   # this machine itself: no token needed
    monkeypatch.delenv("VS_TOKEN")
    assert c.get("/api/jobs/J1/outputs", environ_base=lan).status_code == 200   # no worker mode: unchanged


def test_secrets_from_environment(monkeypatch):
    from studio import config
    monkeypatch.setattr(config, "_vault_get", lambda k: "")
    monkeypatch.setenv("VS_DEEPSEEK_API_KEY", "sk-test"); monkeypatch.setenv("VS_HF_TOKEN", "hf_x")
    monkeypatch.setattr(config, "_raw", lambda: {})
    d = config.load()
    assert d["deepseek_api_key"] == "sk-test" and d["hf_token"] == "hf_x"
