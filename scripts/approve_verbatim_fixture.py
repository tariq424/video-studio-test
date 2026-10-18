"""Approve an exact supplied narration through the ordinary script-review API.

This tests the existing manual script-review workflow, not a new automatic
verbatim-input mode. Speaker label 'Narrator:' is metadata, not spoken text.
"""
import json
import re
import sys
import time
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
if ROOT != Path(r"F:\code\video-studio-test"):
    raise SystemExit("Only run in the isolated checkout")
job = sys.argv[1]
assert re.fullmatch(r"\d{8}_\d{6}", job)
base = f"http://127.0.0.1:42021/api/jobs/{job}"
for _ in range(60):
    state = requests.get(base, timeout=10).json()
    if state["status"] == "awaiting_review":
        break
    if state["status"] == "error":
        raise RuntimeError(state["error"])
    time.sleep(5)
else:
    raise TimeoutError("Script did not reach approval")
source = (ROOT / "tests/fixtures/e2e/provided-script.txt").read_text(encoding="utf-8")
words = source.removeprefix("Narrator:").split()
plan = requests.get(base + "/short_plan", timeout=10).json()
n = len(plan["sections"])
for index, section in enumerate(plan["sections"]):
    section["vo"] = " ".join(words[len(words)*index//n:len(words)*(index+1)//n])
response = requests.put(base + "/short_plan", json=plan, timeout=30)
response.raise_for_status()
saved = requests.get(base + "/short_plan", timeout=10).json()
assert " ".join(section["vo"] for section in saved["sections"]).split() == words
evidence = Path(r"F:\videos_test\evidence\e2e_review_20261018")
(evidence / "verbatim-expected.txt").write_text(" ".join(words), encoding="utf-8")
manifest = json.loads((evidence / "jobs.json").read_text())
manifest["provided_script_verbatim"] = job
(evidence / "jobs.json").write_text(json.dumps(manifest, indent=2))
requests.post(base + "/approve", timeout=30).raise_for_status()
print(f"Approved {len(words)} exact supplied words in {n} sections; no added CTA")
