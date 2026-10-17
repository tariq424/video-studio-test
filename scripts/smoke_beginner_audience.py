"""Seed two script-only jobs from identical source excerpts; no production writes."""
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from studio import config

ROOT = Path(r'F:\videos_test')
SOURCE = Path(r'F:\videos\video_studio\jobs\20261016_190435\src\transcript.txt')


def main():
    assert Path(config.load()['jobs_dir']).resolve() == (ROOT / 'jobs').resolve()
    original = SOURCE.read_text(encoding='utf-8')
    start = re.search(r"You've got an entire weather panel", original, re.I)
    if not start: raise RuntimeError('Weather passage not found')
    excerpt = original[start.start():start.start() + 1200]
    evidence = ROOT / 'evidence/audience'
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / 'source-excerpt.txt').write_text(excerpt, encoding='utf-8')
    (evidence / 'source-sha256.txt').write_text(hashlib.sha256(SOURCE.read_bytes()).hexdigest(), encoding='utf-8')
    meta = json.loads((SOURCE.parent / 'meta.json').read_text(encoding='utf-8'))
    meta['description'] = ''  # compare only this passage, not the full episode's other topics
    meta['original_title'] = meta['title']
    meta['title'] = "GFS and ECMWF: weather forecasts in God's Eye View (source excerpt)"
    for audience in ['common', 'beginner']:
        job = ROOT / 'jobs' / f'audience_{audience}_final'
        if job.exists(): raise RuntimeError(f'Preserve existing test job: {job}')
        (job / 'src').mkdir(parents=True)
        (job / 'src/transcript.txt').write_text(excerpt, encoding='utf-8')
        (job / 'src/meta.json').write_text(json.dumps(meta), encoding='utf-8')
        state = dict(status='stopped', mode='short', smoke=True, short_secs=30, minutes=0.5,
            auto_approve=False, presenter=False, captions=True, audience=audience,
            provider='deepseek', done=['transcript'], auto_retries=3, title=f'Audience {audience} smoke')
        (job / 'state.json').write_text(json.dumps(state, indent=2), encoding='utf-8')
        print(f'Seeded {job}; resume via port 42021. Stops at script review, before TTS/render.')


if __name__ == '__main__': main()
