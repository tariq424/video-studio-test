"""Seed an offline explainer job; submit it to the REAL isolated server with resume.

No source job writes, no AI, no external services. Run with app/env Python.
"""
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
from studio import config, media
from studio.render_media import inspect_video

SOURCE = Path(r'F:\videos\video_studio\jobs\20261016_190435')
TEST = Path(r'F:\videos_test')
JOB = TEST / 'jobs' / 'media_fallback_smoke'


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding='utf-8')


def main():
    from studio.pipeline import stages_for
    assert Path(config.load()['jobs_dir']).resolve() == (TEST / 'jobs').resolve()
    if JOB.exists():
        raise RuntimeError('Smoke job exists; keep evidence and choose a new job ID before rerunning.')
    original = SOURCE / 'short/public/media/fb/b2_1.mp4'
    snapshot = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in
                [SOURCE / 'log.txt', SOURCE / 'plan.json', original]}
    write(TEST / 'evidence/source-sha256-before.json', snapshot)
    report = inspect_video(original)
    write(TEST / 'evidence/source-clip-inspection.json', report)
    print('Source b2_1 strict decode:', report, flush=True)
    public = JOB / 'build/public/vid'
    public.mkdir(parents=True)
    (public / 'empty.mp4').write_bytes(b'')
    raw = original.read_bytes()
    (public / 'truncated.mp4').write_bytes(raw[:len(raw) // 2])
    shutil.copy2(original, public / 'original_b2_1.mp4')  # a copy, NOT a hard link
    sections = []
    for i, (name, duration, title) in enumerate([
        ('empty.mp4', 3, 'Empty video fallback'),
        ('truncated.mp4', 3, 'Truncated video fallback'),
        ('original_b2_1.mp4', 12, 'Safe hold beyond source end'),
    ]):
        sid = f's{i}'
        sections.append({'id': sid, 'title': title, 'vo': title,
            'visuals': [{'id': f'v{i}', 'type': 'motion', 'edit_slot': duration + 1.2,
                'edit_bgs': [{'type': 'video', 'src': f'vid/{name}', 'from': 0, 'rate': 1}]}]})
        voice = JOB / 'voice' / f'{sid}.wav'
        voice.parent.mkdir(exist_ok=True)
        media.ff('-f', 'lavfi', '-i', f'sine=frequency={220 + i * 110}:sample_rate=48000:duration={duration}', voice)
        write(JOB / f'captions/words_{sid}.json', [[title, 0, duration]])
        write(JOB / f'captions/icons_{sid}.json', [])
    write(JOB / 'plan.json', {'title': 'Media validation smoke', 'youtube_description': 'Offline regression fixture.', 'sections': sections})
    write(JOB / 'src/meta.json', {'title': 'Local smoke fixture', 'channel': 'Video Studio test', 'webpage_url': ''})
    # Resume only the real assemble stage; all upstream assets are deterministic.
    write(JOB / 'state.json', {'status': 'stopped', 'mode': 'long', 'minutes': 0.5,
        'presenter': False, 'captions': True, 'auto_approve': True, 'auto_retries': 3,
        'title': 'Media validation smoke', 'done': [s for s in stages_for('long') if s != 'assemble']})
    print('Seeded', JOB, flush=True)
    print('POST http://127.0.0.1:42021/api/jobs/media_fallback_smoke/resume', flush=True)


if __name__ == '__main__':
    main()
