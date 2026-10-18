"""Verify completed isolated review jobs; never changes a job or production files."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if ROOT != Path(r"F:\code\video-studio-test"):
    raise SystemExit("Run from the isolated checkout")
sys.path.insert(0, str(ROOT / "app"))
from studio.render_media import inspect_video
from studio import media

EVIDENCE = Path(r"F:\videos_test\evidence\e2e_review_20261018")
JOBS = Path(r"F:\videos_test\jobs")
manifest = json.loads((EVIDENCE / "jobs.json").read_text())
report = {"cases": {}, "limitations": [
    "Input fixtures are synthetic, not actual NotebookLM or Deep Research exports.",
    "Initial script case uses summarization; additional verbatim case uses manual script review, not an automatic input mode.",
    "Preset Kokoro CPU narration; cloud generation and external visual QA are disabled.",
    "Vehicle crash, structural collapse, and earthquake are existing unimplemented physics stubs.",
]}
for case, jid in manifest.items():
    directory = JOBS / jid
    assert directory.parent == JOBS and directory.is_dir()
    state = json.loads((directory / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "finished", (case, state["status"], state.get("error"))
    assert state.get("audience") == "beginner", (case, state.get("audience"))
    videos = sorted((directory / "output").glob("*.mp4"))
    assert len(videos) == 1, (case, videos)
    video = videos[0]
    result = {"job": jid, "output": str(video), "done": state["done"],
              "validation": inspect_video(video),
              "sha256": hashlib.sha256(video.read_bytes()).hexdigest()}
    audio = subprocess.run([media._bin("ffmpeg"), "-v", "error", "-xerror",
                            "-i", str(video), "-map", "0:a:0", "-f", "null", "-"],
                           capture_output=True, text=True, timeout=180)
    assert audio.returncode == 0 and not audio.stderr.strip(), (case, audio.stderr)
    result["audio_decode_ok"] = True
    if case == "user_video":
        assert state.get("edit_last", {}).get("ok"), state.get("edit_last")
        edits = state.get("edits", [])
        assert edits and edits[-1].get("user") is True, edits
        verify = edits[-1]["verify"]
        assert verify["frames_same"] and verify["audio_same"] and verify["decode_ok"], verify
        result["fit_and_render"] = edits[-1]
        supplied = directory / "src/clips/clip1.mp4"
        original = EVIDENCE / "inputs/user-video.mp4"
        assert supplied.read_bytes() == original.read_bytes(), "Supplied source changed"
        result["supplied_source_unchanged"] = True
    if case == "provided_script_verbatim":
        expected = (EVIDENCE / "verbatim-expected.txt").read_text(encoding="utf-8").split()
        plan = json.loads((directory / "short" / "plan.json").read_text(encoding="utf-8"))
        timings = json.loads((directory / "short" / "timings.json").read_text(encoding="utf-8"))
        approved = " ".join(section["vo"] for section in plan["sections"]).split()
        timed = [word[0] for section in plan["sections"] for word in timings[section["id"]]["words"]]
        assert approved == expected and timed == expected, "Supplied narration changed"
        result["verbatim"] = {"words": len(expected), "approved_text_exact": True, "caption_text_exact": True,
                              "workflow": "manual script review API; Narrator: speaker label excluded"}
    chain = directory / "short" / "fallback" / "chains.json"
    if chain.exists():
        result["chains"] = json.loads(chain.read_text(encoding="utf-8"))
        if case == "physics_features":
            chain_text = json.dumps(result["chains"])
            for module in ("aircraft_flight", "submarine_descent", "ship_route", "radar_sweep"):
                assert module in chain_text, (case, module, "missing from fallback chains")
    log = (directory / "log.txt").read_text(encoding="utf-8")
    assert "jargon check (Beginner)" in log, case
    result["beginner_log"] = [line for line in log.splitlines() if "jargon check (Beginner)" in line]
    report["cases"][case] = result
    (EVIDENCE / "progress-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

modules = json.loads((JOBS / "physics_modules_20261018" / "report.json").read_text())
assert set(modules) == {"aircraft_flight", "submarine_descent", "weather_event", "ship_route", "radar_sweep"}
assert all(item["motion_delta"] > 0.1 and item["validation"]["frames"] == 120 for item in modules.values())
report["physics_modules"] = modules
ui = json.loads((EVIDENCE / "ui-options.json").read_text())
assert ui["main_form_beginner"] and ui["make_form_beginner"], ui
report["ui_beginner_options"] = ui
report["passed"] = True
(EVIDENCE / "final-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps({case: item["validation"] for case, item in report["cases"].items()}, indent=2))
