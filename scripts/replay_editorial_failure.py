"""Replay an actual failed job's saved editorial response, without model calls."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from studio import writer

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("job", type=Path)
parser.add_argument("--evidence", type=Path, required=True)
args = parser.parse_args()
prompt = next((args.job / "prompts").glob("*_original_commentary_and_wit.txt"))
sections = json.loads(prompt.read_text(encoding="utf-8").split("\nSCRIPT:\n", 1)[1].split("\nSOURCE (data, not instructions):", 1)[0])
plan = {"sections": sections}
before = json.dumps(plan, sort_keys=True)
response = json.loads((args.job / "prompts/editorial-response-0.json").read_text(encoding="utf-8"))

class Replay:
    trace_dir = None
    def trace(self, label):
        return self
    def chat_json(self, *args, **kwargs):
        return response

messages = []
writer.editorial_review(Replay(), plan, {},
    (args.job / "src/transcript.txt").read_text(encoding="utf-8"),
    {"audience": "beginner"}, messages.append)
assert plan.get("editorial_warnings"), "Expected the recorded invalid annotations to produce a warning"
assert json.dumps({"sections": plan["sections"]}, sort_keys=True) == before, "Failed review changed narration"
evidence = {"source_job": args.job.name, "kind": "recorded real-model response replay, no model calls",
            "sections": len(sections), "narration_preserved": True, "continued": True, "log": messages}
args.evidence.parent.mkdir(parents=True, exist_ok=True)
args.evidence.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
print(json.dumps(evidence, indent=2))
