"""Optional live YouTube bounded-extraction probe. No cookies, bypass, or upload."""
import json
import sys
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
assert ROOT == Path(r"F:\code\video-studio-test")
sys.path.insert(0, str(ROOT / "app"))
from studio import source_visuals, transcript
from studio.render_media import inspect_video

job = Path(r"F:\videos_test\jobs\youtube_source_probe")
(job / "src").mkdir(parents=True, exist_ok=True)
result = {}
try:
    info = json.loads(source_visuals._run_downloader([sys.executable, "-m", "yt_dlp", "--dump-single-json",
        "--skip-download", "--quiet", "--no-warnings", "--socket-timeout", "10", "--retries", "0",
        "--extractor-retries", "0", sys.argv[1]], timeout=45))
    url, language = transcript._pick_track(info)
    if not url:
        raise RuntimeError("No timestamped caption track available; no source timestamps guessed")
    captions = requests.get(url, timeout=15)
    captions.raise_for_status()
    cues = [{"start": e.get("tStartMs", 0) / 1000,
             "text": "".join(s.get("utf8", "") for s in e.get("segs", [])).strip()}
            for e in captions.json().get("events", []) if e.get("segs")]
    cue = next(c for c in cues if c["start"] >= 15 and c["text"])
    (job / "src/source_cues.json").write_text(json.dumps(cues), encoding="utf-8")
    meta = {"webpage_url": info["webpage_url"], "channel": info.get("channel", "")}
    request = {"kind": "clip", "start": cue["start"], "duration": 2.5,
               "purpose": "Transport test only; not a claim of editorial relevance"}
    source_visuals._extract(job, request, job / "clip.mp4", meta, print)
    result = {"status": "passed", "validation": inspect_video(job / "clip.mp4"), "cue": cue,
              "source": meta, "purpose": request["purpose"]}
except Exception as error:
    result = {"status": "unavailable", "reason": str(error)[:400]}
(job / "report.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
print(json.dumps(result, indent=2))
