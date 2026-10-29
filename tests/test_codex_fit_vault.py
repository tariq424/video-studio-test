import json
import os
import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from studio import config, imagegen


def _img(path, size=(16, 16)):
    Image.new("RGB", size, (120, 130, 140)).save(path, "JPEG", quality=90)


class FakeVault:
    def __init__(self):
        self.data = {}

    def get_password(self, service, name):
        return self.data.get(name, "")

    def set_password(self, service, name, value):
        self.data[name] = value

    def delete_password(self, service, name):
        self.data.pop(name, None)


def test_narration_fit_port_isolation(monkeypatch):
    monkeypatch.delenv("PORT", raising=False)
    assert imagegen.narration_fit_on() is False

    monkeypatch.setenv("PORT", "42021")
    assert imagegen.narration_fit_on() is False

    monkeypatch.setenv("PORT", "42022")
    assert imagegen.narration_fit_on() is True

    monkeypatch.setenv("PORT", "not-a-port")
    assert imagegen.narration_fit_on() is False


def test_stable_non_google_first():
    assert imagegen._stable_non_google_first(["gemini", "hf", "chatgpt"]) == ["hf", "chatgpt", "gemini"]
    assert imagegen._stable_non_google_first(["bing", "chatgpt", "gemini"]) == ["bing", "chatgpt", "gemini"]


def test_generate_many_rejects_fresh_mismatch_and_advances(monkeypatch, tmp_path):
    monkeypatch.setenv("PORT", "42022")
    sd = tmp_path / "ws"
    d = sd / "imagegen"
    d.mkdir(parents=True)
    cfg = {
        "imagegen_on": True,
        "imagegen_providers": ["hf", "chatgpt"],
        "imagegen_rotate": False,
        "imagegen_max_per_video": 8,
        "imagegen_per_beat": 1,
        "imagegen_timeout": 60,
        "imagegen_text_check": False,
        "imagegen_delay_secs": [0, 0],
        "imagegen_state": str(sd / "state.json"),
        "jobs_dir": str(tmp_path),
    }
    monkeypatch.setattr(imagegen, "_pause", lambda *a, **k: None)
    monkeypatch.setattr(imagegen, "_answered", lambda *a, **k: None)

    def fake_hf(cfg, sec, aspect, out, timeout, log, evidence, extras=()):
        _img(out)
        return "hf prompt"

    def fake_chatgpt(cfg, image, aspect, vo, out, timeout, log, evidence, extras):
        _img(out)
        return "chatgpt prompt"

    monkeypatch.setattr(imagegen, "_session_hf", fake_hf)
    monkeypatch.setattr(imagegen, "_session_chatgpt", fake_chatgpt)

    def fake_fit(cfg, image_path, sec, log):
        if "hf" in str(image_path):
            return "rejected", "does not match narration"
        return "accepted", "matches narration"

    monkeypatch.setattr(imagegen, "_fit_check_now", fake_fit)

    res = imagegen.generate_many(cfg, sd, {"id": "b1", "vo": "the moon"}, "b1", lambda *a, **k: None, count=1)

    assert len(res) == 1
    assert "chatgpt" in res[0][0].name
    assert len(list((d / "_rejected").glob("b1_hf*"))) == 1
    audit = json.loads((d / "fit_audit.json").read_text(encoding="utf-8"))
    assert audit["counts"] == {"checked": 2, "accepted": 1, "rejected_for_narration": 1, "unavailable": 0}


def test_generate_many_resumed_cached_rejection_advances(monkeypatch, tmp_path):
    monkeypatch.setenv("PORT", "42022")
    sd = tmp_path / "ws"
    d = sd / "imagegen"
    d.mkdir(parents=True)
    cached = d / "b1_hf.jpg"
    _img(cached)
    (d / "gemini_usage.json").write_text(
        json.dumps({"b1": {"site": "hf", "files": ["b1_hf.jpg"], "prompt": "old prompt"}}),
        encoding="utf-8",
    )
    cfg = {
        "imagegen_on": True,
        "imagegen_providers": ["hf", "chatgpt"],
        "imagegen_rotate": False,
        "imagegen_max_per_video": 8,
        "imagegen_per_beat": 1,
        "imagegen_timeout": 60,
        "imagegen_text_check": False,
        "imagegen_delay_secs": [0, 0],
        "imagegen_state": str(sd / "state.json"),
        "jobs_dir": str(tmp_path),
    }
    monkeypatch.setattr(imagegen, "_pause", lambda *a, **k: None)
    monkeypatch.setattr(imagegen, "_answered", lambda *a, **k: None)
    monkeypatch.setattr(imagegen, "_session_hf", lambda *a, **k: pytest.fail("cached hf should not regenerate"))

    def fake_chatgpt(cfg, image, aspect, vo, out, timeout, log, evidence, extras):
        _img(out)
        return "chatgpt prompt"

    monkeypatch.setattr(imagegen, "_session_chatgpt", fake_chatgpt)
    monkeypatch.setattr(
        imagegen,
        "_fit_check_now",
        lambda cfg, img, sec, log: ("rejected", "narration mismatch") if "hf" in str(img) else ("accepted", "ok"),
    )

    res = imagegen.generate_many(cfg, sd, {"id": "b1", "vo": "the moon"}, "b1", lambda *a, **k: None, count=1)

    assert len(res) == 1
    assert "chatgpt" in res[0][0].name
    assert len(list((d / "_rejected").glob("b1_hf*"))) == 1
    audit = json.loads((d / "fit_audit.json").read_text(encoding="utf-8"))
    assert audit["counts"]["checked"] == 2
    assert audit["counts"]["rejected_for_narration"] == 1
    assert audit["counts"]["accepted"] == 1


def test_fit_verdict_unavailable_counts_fail_closed(monkeypatch, tmp_path):
    monkeypatch.setenv("PORT", "42022")
    d = tmp_path / "imagegen"
    d.mkdir()
    img = d / "b1.jpg"
    _img(img)
    cfg = {}

    def boom(cfg, image_path, sec, log):
        raise RuntimeError("ollama down")

    monkeypatch.setattr(imagegen, "_fit_check_now", boom)

    verdict, reason = imagegen._fit_verdict_for(cfg, d, {"vo": "narration"}, img, "prompt", lambda *a, **k: None, "hf")

    assert verdict == "unavailable"
    assert reason == "RuntimeError"
    audit = json.loads((d / "fit_audit.json").read_text(encoding="utf-8"))
    assert audit["counts"]["unavailable"] == 1
    assert audit["counts"]["rejected_for_narration"] == 0


def test_fit_verdict_cancelled_propagates(monkeypatch, tmp_path):
    monkeypatch.setenv("PORT", "42022")
    d = tmp_path / "imagegen"
    d.mkdir()
    img = d / "b1.jpg"
    _img(img)

    def cancel(cfg, image_path, sec, log):
        raise RuntimeError("cancelled")

    monkeypatch.setattr(imagegen, "_fit_check_now", cancel)

    with pytest.raises(RuntimeError, match="cancelled"):
        imagegen._fit_verdict_for({}, d, {"vo": "narration"}, img, "prompt", lambda *a, **k: None, "hf")


def test_hf_token_migration_verifies_before_rewrite(monkeypatch, tmp_path):
    cfgfile = tmp_path / "settings.json"
    cfgfile.write_text(json.dumps({"hf_token": "hf_plain_1234"}), encoding="utf-8")
    monkeypatch.setattr(config, "CFG", cfgfile)
    vault = FakeVault()
    monkeypatch.setattr(config, "_kr", lambda: vault)
    monkeypatch.delenv("VS_HF_TOKEN", raising=False)

    d = config.load()

    assert vault.data["hf_token"] == "hf_plain_1234"
    raw = json.loads(cfgfile.read_text(encoding="utf-8"))
    assert raw["hf_token"] == "vault"
    assert "hf_plain_1234" not in cfgfile.read_text(encoding="utf-8")
    assert d["hf_token"] == "hf_plain_1234"


def test_hf_token_fail_closed_when_vault_unavailable(monkeypatch, tmp_path):
    cfgfile = tmp_path / "settings.json"
    cfgfile.write_text(json.dumps({"hf_token": "hf_plain_9999"}), encoding="utf-8")
    monkeypatch.setattr(config, "CFG", cfgfile)
    monkeypatch.setattr(config, "_kr", lambda: None)
    monkeypatch.delenv("VS_HF_TOKEN", raising=False)

    d = config.load()

    assert d["hf_token"] == ""
    raw = json.loads(cfgfile.read_text(encoding="utf-8"))
    assert raw["hf_token"] == "hf_plain_9999"  # migration refused: no rewritten plaintext backup


def test_hf_token_env_fallback(monkeypatch, tmp_path):
    cfgfile = tmp_path / "settings.json"
    cfgfile.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(config, "CFG", cfgfile)
    monkeypatch.setattr(config, "_kr", lambda: None)
    monkeypatch.setenv("VS_HF_TOKEN", "hf_env_1234")

    d = config.load()

    assert d["hf_token"] == "hf_env_1234"


def test_save_hf_token_to_vault_and_public_redacts(monkeypatch, tmp_path):
    cfgfile = tmp_path / "settings.json"
    cfgfile.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(config, "CFG", cfgfile)
    vault = FakeVault()
    monkeypatch.setattr(config, "_kr", lambda: vault)

    d = config.save({"hf_token": "hf_save_1234"})

    assert vault.data["hf_token"] == "hf_save_1234"
    assert json.loads(cfgfile.read_text(encoding="utf-8"))["hf_token"] == "vault"
    assert d["hf_token"] == "hf_save_1234"
    pub = config.public()
    assert pub["hf_token"] == "••••1234"
    assert "hf_save_1234" not in json.dumps(pub)


def test_migrate_secrets_entrypoint_counts(monkeypatch, tmp_path):
    cfgfile = tmp_path / "settings.json"
    cfgfile.write_text(
        json.dumps({"hf_token": "hf_plain_1234", "deepseek_api_key": "deep_plain"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "CFG", cfgfile)
    vault = FakeVault()
    monkeypatch.setattr(config, "_kr", lambda: vault)

    assert config.migrate_secrets() == 2
    raw = json.loads(cfgfile.read_text(encoding="utf-8"))
    assert raw["hf_token"] == "vault"
    assert raw["deepseek_api_key"] == "vault"


def test_unchanged_cache_not_counted_again_but_inputs_invalidate(monkeypatch, tmp_path):
    img = tmp_path / "image.jpg"
    img.write_bytes(b"first")
    calls = []
    monkeypatch.setattr(imagegen, "_fit_check_now", lambda *a: (calls.append(1) or "accepted", "ok"))
    sec = {"vo": "a rocket lifting off"}
    cfg = {"vet_model": "local-a"}
    def check(): return imagegen._fit_verdict_for(cfg, tmp_path, sec, img, "prompt", lambda *a: None)
    check(); check()
    assert len(calls) == 1
    stamp = img.stat()
    img.write_bytes(b"other")  # same size and mtime: content still invalidates the verdict
    os.utime(img, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    check()
    sec["vo"] = "a rocket on a launch pad"; check()
    cfg["vet_model"] = "local-b"; check()
    assert len(calls) == 4
    assert json.loads((tmp_path / imagegen.FIT_AUDIT).read_text())["counts"]["checked"] == 4


@pytest.mark.parametrize("port", [None, "42021", "42023", "bad", ""])
def test_production_and_other_ports_do_not_call_fit(monkeypatch, tmp_path, port):
    if port is None: monkeypatch.delenv("PORT", raising=False)
    else: monkeypatch.setenv("PORT", port)
    imagegen.reset()
    def session(cfg, sec, aspect, out, *a, **kw):
        _img(out); return "prompt"
    monkeypatch.setattr(imagegen, "_session_hf", session)
    monkeypatch.setattr(imagegen, "_fit_check_now", lambda *a: pytest.fail("fit ran outside test port"))
    result = imagegen.generate_many({"imagegen_providers": ["hf"]}, tmp_path, {"vo": "moon"}, "b0", lambda *a: None)
    assert result and not (tmp_path / "imagegen" / imagegen.FIT_AUDIT).exists()


@pytest.mark.parametrize("rotate", [False, True])
def test_google_is_last_even_with_rotation_preference(monkeypatch, tmp_path, rotate):
    monkeypatch.setenv("PORT", "42022")
    imagegen.reset()
    calls = []
    def hf(*a, **kw):
        calls.append("hf"); raise imagegen.Skip("unavailable")
    def google(cfg, image, aspect, vo, out, *a):
        calls.append("gemini"); _img(out); return "prompt"
    monkeypatch.setattr(imagegen, "_session_hf", hf)
    monkeypatch.setattr(imagegen, "_session", google)
    monkeypatch.setattr(imagegen, "_job_provider", lambda *a: "gemini")
    monkeypatch.setattr(imagegen, "_fit_check_now", lambda *a: ("accepted", "ok"))
    result = imagegen.generate_many({"imagegen_providers": ["gemini", "hf"], "imagegen_rotate": rotate,
                                    "imagegen_first": "gemini"}, tmp_path, {"vo": "moon"}, "b0", lambda *a: None)
    assert calls == ["hf", "gemini"] and result


def test_unavailable_fresh_image_fails_closed_and_retains_evidence(monkeypatch, tmp_path):
    monkeypatch.setenv("PORT", "42022")
    imagegen.reset()
    def session(cfg, sec, aspect, out, *a, **kw):
        _img(out); return "prompt"
    monkeypatch.setattr(imagegen, "_session_hf", session)
    monkeypatch.setattr(imagegen, "_local_fit_vision", lambda *a: "not json")
    assert not imagegen.generate_many({"imagegen_providers": ["hf"]}, tmp_path, {"vo": "moon"}, "b0", lambda *a: None)
    folder = tmp_path / "imagegen"
    assert list((folder / "_rejected").glob("*.jpg"))
    counts = json.loads((folder / imagegen.FIT_AUDIT).read_text())["counts"]
    assert counts["unavailable"] == 1 and counts["rejected_for_narration"] == 0


def test_fit_uses_local_provider_even_when_config_names_paid_model(monkeypatch, tmp_path):
    from studio import footage
    img = tmp_path / "image.jpg"; _img(img)
    seen = []
    def vision(cfg, *a):
        seen.append(cfg["vet_provider"]); return '{"match":"yes"}'
    monkeypatch.setattr(footage, "_vision", vision)
    assert imagegen._fit_check_now({"vet_provider": "claude"}, img, {"vo": "moon"}, print)[0] == "accepted"
    assert seen == ["local"]


def test_vault_write_failure_does_not_rewrite_or_reveal(monkeypatch, tmp_path):
    cfgfile = tmp_path / "settings.json"; cfgfile.write_text("{}")
    monkeypatch.setattr(config, "CFG", cfgfile)
    class FailingVault(FakeVault):
        def set_password(self, service, name, value): raise RuntimeError("backend echoed " + value)
    monkeypatch.setattr(config, "_kr", FailingVault)
    with pytest.raises(RuntimeError) as err: config.save({"hf_token": "fake-sensitive-value"})
    assert "fake-sensitive-value" not in str(err.value)
    assert cfgfile.read_text() == "{}"


def test_vault_readback_failure_retains_settings(monkeypatch, tmp_path):
    cfgfile = tmp_path / "settings.json"; cfgfile.write_text('{"hf_token":"fake-original"}')
    monkeypatch.setattr(config, "CFG", cfgfile)
    vault = FakeVault(); monkeypatch.setattr(config, "_kr", lambda: vault)
    monkeypatch.setattr(config, "_vault_get", lambda name: "")
    with pytest.raises(RuntimeError): config.migrate_secrets()
    assert cfgfile.read_text() == '{"hf_token":"fake-original"}'


def test_atomic_settings_failure_keeps_original(monkeypatch, tmp_path):
    cfgfile = tmp_path / "settings.json"; cfgfile.write_text('{"hf_token":"fake-original"}')
    monkeypatch.setattr(config, "CFG", cfgfile)
    vault = FakeVault(); monkeypatch.setattr(config, "_kr", lambda: vault)
    def fail(*a): raise PermissionError("busy")
    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(PermissionError): config.migrate_secrets()
    assert cfgfile.read_text() == '{"hf_token":"fake-original"}'
    assert not list(tmp_path.glob("*.tmp"))
