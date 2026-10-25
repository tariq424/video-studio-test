"""Run a Google Photos missing-footage job (app/studio/gphotos.py) from a JSON file:
{"search": ["hamilton bermuda + mr. chicken"], "details": [urls], "download": [urls], "dir": "F:\\bermuda\\from_google_photos", "work": "F:\\bermuda\\_work\\gphotos"}
Also: {"setup_key": true} makes MEDIA_DB_KEY in the repo .env if missing (after checking .env is git-ignored);
{"backup": true} writes the encrypted media db backup."""
import json, os, subprocess, sys, base64
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from studio import config, gphotos, media_db  # noqa: E402

def setup_key():
    repo = Path(__file__).resolve().parents[1]; env = repo / ".env"
    ign = subprocess.run(["git", "check-ignore", "-q", str(env)], cwd=repo).returncode == 0
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", ".env"], cwd=repo, capture_output=True).returncode == 0
    if not ign or tracked: return f"STOP: .env ignored={ign} tracked={tracked}; key not written"
    txt = env.read_text(encoding="utf-8", errors="ignore") if env.exists() else ""
    if "MEDIA_DB_KEY=" in txt: return "MEDIA_DB_KEY already present"
    key = base64.urlsafe_b64encode(os.urandom(32)).decode()
    with open(env, "a", encoding="utf-8") as f: f.write(("" if txt.endswith("\n") or not txt else "\n") + f"MEDIA_DB_KEY={key}\n")
    return "MEDIA_DB_KEY written to .env (git-ignored, untracked)"

def main():
    try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass
    job = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    cfg = config.load(); cfg.update(job.get("cfg") or {})
    if job.get("setup_key"): print(setup_key(), flush=True)
    if job.get("search") or job.get("details") or job.get("download") or job.get("details_from"): gphotos.run(cfg, job, lambda m: print(m, flush=True))
    if job.get("rows"):   # rows written by hand (e.g. footage the owner identified)
        db = media_db.connect(cfg)
        for r in job["rows"]: media_db.upsert(db, r)
        print("rows:", len(job["rows"]), flush=True)
    if job.get("dedupe"): db = media_db.connect(cfg); media_db.dedupe(db); print("deduped:", db.execute("select count(*) from items").fetchone()[0], flush=True)
    if job.get("backup"): media_db.backup(cfg, lambda m: print(m, flush=True))
    print("done", flush=True)

if __name__ == "__main__": main()
