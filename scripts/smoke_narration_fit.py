"""Offline selection + CPU encode smoke. No HF, Google, browser, GPU or real vision calls.

Mocked local vision verdicts exercise rejection/audit/fallback, then real FFmpeg
encodes only the accepted candidate. This does not measure vision-model accuracy.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from studio import imagegen
from PIL import Image
import imageio_ffmpeg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--work', required=True, type=Path)
    args = ap.parse_args()
    work = args.work.resolve()
    if work.exists(): raise SystemExit('Use a fresh smoke directory; existing evidence is preserved')
    work.mkdir(parents=True)
    lines = []
    def log(line):
        lines.append(line)
        print(line)
    def session(cfg, image, aspect, vo, out, *a):
        Image.new('RGB', (320, 180), 'red' if 'chatgpt' in out.name else 'green').save(out)
        return 'deterministic fixture'
    def bing(cfg, sec, aspect, out, *a):
        return session(cfg, None, aspect, sec['vo'], out)
    def vision(cfg, img, prompt):
        return json.dumps({'match': 'no' if 'chatgpt' in str(img) else 'yes', 'reason': 'fixture verdict'})
    cfg = {'imagegen_providers': ['chatgpt', 'bing'], 'imagegen_rotate': False,
           'jobs_dir': str(work / 'jobs'), 'vet_provider': 'local',
           'imagegen_state': str(work / 'provider_state.json')}
    imagegen.reset()
    with patch.dict(os.environ, PORT='42022'), \
            patch.object(imagegen, '_session_chatgpt', session), \
            patch.object(imagegen, '_session_bing', bing), \
            patch.object(imagegen, '_local_fit_vision', vision):
        selected = imagegen.generate_many(cfg, work, {'vo': 'a fixture narrative'}, 'b0', log)
    assert len(selected) == 1 and selected[0][0].name == 'b0_bing.jpg'
    audit = json.loads((work / 'imagegen' / imagegen.FIT_AUDIT).read_text())
    assert audit['counts']['rejected_for_narration'] == 1
    assert audit['counts']['accepted'] == 1
    output = work / 'fit_gate_smoke.mp4'
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-hide_banner', '-loglevel', 'error',
                    '-loop', '1', '-i', str(selected[0][0]), '-t', '2', '-r', '24',
                    '-c:v', 'libx264', '-threads', '1', '-pix_fmt', 'yuv420p', str(output)], check=True)
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-hide_banner', '-loglevel', 'error',
                    '-xerror', '-i', str(output), '-f', 'null', '-'], check=True)
    report = {'kind': 'offline fixture with mocked providers and local vision', 'port_gate': 42022,
              'counts': audit['counts'], 'selected': selected[0][0].name,
              'encoded_seconds': 2, 'strict_decode': 'passed', 'hf_calls': 0, 'network_calls': 0}
    (work / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    (work / 'log.txt').write_text('\n'.join(lines), encoding='utf-8')
    print('PASS: rejected candidate retained; accepted candidate encoded and decoded')


if __name__ == '__main__': main()
