"""Read-only audit of the saved failed job; evidence is written outside it."""
import json
import subprocess
from pathlib import Path

source = Path(r'F:\videos\video_studio\jobs\20261016_190435')
rows = []
for relative in ['short/public', 'build/public']:
    public = source / relative
    data = json.loads((public / 'teaser.json').read_text(encoding='utf-8'))
    for beat in data['beats']:
        bgs = beat['bgs']
        for i, bg in enumerate(bgs):
            if bg.get('type') != 'video': continue
            path = public / bg['src']
            probe = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                '-of', 'csv=p=0', str(path)], capture_output=True, text=True, timeout=30)
            try: duration = float(probe.stdout.strip())
            except ValueError: continue
            # Teaser.tsx keeps every shot playing 0.4s under the next shot.
            slot = (bgs[i + 1]['from'] if i + 1 < len(bgs) else beat['dur']) - bg['from'] + 0.4
            rate = bg.get('rate', 0.85)
            sought = (min(slot, bg['freezeAt']) if 'freezeAt' in bg else slot) * rate + bg.get('start', 0)
            if not bg.get('loop') and sought >= duration:
                rows.append({'timeline': relative, 'beat': beat['id'], 'src': bg['src'],
                    'source_duration': duration, 'requested_through': sought,
                    'freezeAt': bg.get('freezeAt')})
out = Path(r'F:\videos_test\evidence/timing-audit.json')
out.write_text(json.dumps(rows, indent=2), encoding='utf-8')
print(f'{len(rows)} slots can request past EOF, including the 0.4s crossfade:')
for row in rows[:8]: print(row)
