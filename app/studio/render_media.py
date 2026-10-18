"""Validate the exact public-dir videos sent to Remotion; never modify sources."""
import json
import math
import subprocess
from pathlib import Path
from . import media


def inspect_video(path):
    """Return fully decoded duration/fps or raise on unreadable/missing frames.

    Container duration alone is not proof a clip decodes to its advertised end.
    Decode every video frame strictly, with a bounded timeout and no output file.
    """
    path = Path(path)
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError('missing or empty video')
    probe = subprocess.run([media._bin('ffprobe'), '-v', 'error', '-select_streams', 'v:0',
        '-show_entries', 'stream=width,height,duration,avg_frame_rate,nb_frames',
        '-of', 'json', str(path)], capture_output=True, text=True, timeout=30)
    if probe.returncode or probe.stderr.strip():
        raise ValueError('ffprobe: ' + probe.stderr.strip()[:200])
    streams = json.loads(probe.stdout).get('streams', [])
    if not streams or not streams[0].get('width') or not streams[0].get('height'):
        raise ValueError('no usable video stream')
    stream = streams[0]
    num, den = stream.get('avg_frame_rate', '0/1').split('/')
    fps = float(num) / float(den)
    if not math.isfinite(fps) or fps <= 0:
        raise ValueError('invalid frame rate')
    decoded = subprocess.run([media._bin('ffmpeg'), '-nostdin', '-v', 'error',
        '-xerror', '-err_detect', 'explode', '-i', str(path), '-map', '0:v:0',
        '-an', '-sn', '-dn', '-fps_mode', 'passthrough', '-progress', 'pipe:1',
        '-f', 'null', '-'], capture_output=True, text=True, timeout=180)
    if decoded.returncode or decoded.stderr.strip():
        raise ValueError('decode: ' + decoded.stderr.strip()[:200])
    progress = dict(line.split('=', 1) for line in decoded.stdout.splitlines() if '=' in line)
    frames = int(progress.get('frame', '0').strip())
    duration = float(progress.get('out_time_us', '0')) / 1_000_000
    if frames < 1 or not math.isfinite(duration) or duration <= 0:
        raise ValueError('no decodable frames')
    declared_frames = stream.get('nb_frames', 'N/A')
    if declared_frames != 'N/A' and frames < int(declared_frames):
        raise ValueError(f'missing frames: decoded {frames}, declared {declared_frames}')
    advertised = float(stream.get('duration', duration))
    if advertised - duration > max(0.25, 2 / fps):
        raise ValueError(f'truncated duration: decoded {duration:.3f}s, declared {advertised:.3f}s')
    return {'duration': min(duration, advertised), 'fps': fps, 'frames': frames}


def sanitize_timeline(data, public_dir, log, stop=lambda: False):
    """Fallback bad assets and clamp source seeks, including edited backgrounds.

    Cache only within this pass: repeated assets decode once, repaired files are
    rechecked on the next render. All decisions apply to the staged public files.
    """
    root = Path(public_dir).resolve()
    checked = {}
    try:
        use_browser = json.loads((root / "video_decoder.json").read_text(encoding="utf-8")).get("decoder") == "browser"
    except (OSError, ValueError, AttributeError):
        use_browser = False
    for beat in data['beats']:
        for index, bg in enumerate(beat.get('bgs', [])):
            if stop():
                raise RuntimeError('cancelled')
            if bg.get('type') != 'video':
                continue
            if use_browser: bg['decoder'] = 'browser'
            try:
                path = (root / bg['src']).resolve()
                if not path.is_relative_to(root):
                    raise ValueError('video escapes public directory')
                if path not in checked:
                    try:
                        checked[path] = inspect_video(path)
                    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
                        checked[path] = str(error)
                info = checked[path]
                if isinstance(info, str):
                    raise ValueError(info)
                rate = float(bg.get('rate', 0.85))
                start = float(bg.get('start', 0))
                if not math.isfinite(rate) or rate <= 0 or not math.isfinite(start) or start < 0:
                    raise ValueError('invalid playback rate/start')
                # Keep at least two source frames away from EOF; Freeze's timeline
                # frame is multiplied by playbackRate before the source is sought.
                safe = (info['duration'] - start - 2 / info['fps']) / rate
                if safe < 1 / 30:
                    raise ValueError('source start is beyond the last safe frame')
                if bg.get('loop') is not None:
                    loop = float(bg['loop'])
                    if not math.isfinite(loop) or loop <= 0:
                        raise ValueError('invalid loop duration')
                    bg['loop'] = min(loop, safe)
                else:
                    freeze = float(bg.get('freezeAt', safe))
                    if not math.isfinite(freeze) or freeze < 0:
                        raise ValueError('invalid freeze time')
                    bg['freezeAt'] = min(freeze, safe)
                log(f"Media preflight: {bg['src']} OK ({info['frames']} decoded frames; safe hold {safe:.3f}s)")
            except (OSError, ValueError, KeyError, TypeError, ZeroDivisionError) as error:
                title = beat.get('title') or ' '.join(str(w[0]) for w in beat.get('words', [])[:12]) or beat['id'].replace('_', ' ')
                beat['bgs'][index] = {**{k: bg[k] for k in ('from', 'slot') if k in bg},
                    'type': 'graphic', 'g': {'kind': 'headline', 'text': title[:90],
                    'kicker': 'VIDEO STUDIO', 'sub': ''}}
                log(f"Media preflight: {bg.get('src', '?')} invalid ({error}) -> headline card")
    return data


def fallback_failed_video(timeline, public_dir, error, log):
    """Recover a runtime-only compositor failure without deleting a healthy source.

    Only URLs naming a video actually present in this timeline may be replaced.
    Native compositor failures switch videos to browser decoding first. A second
    failure for an already switched asset uses a card, bounding retries.
    """
    import re
    from urllib.parse import unquote
    if not any(x in error for x in ("Could not extract frame", "No frame found", "delayRender()")):
        return False
    match = re.search(r"/public/([^\s?&\"')]+?\.mp4)", unquote(error))
    if not match: return False
    src = match.group(1)
    root = Path(public_dir).resolve()
    if not (root / src).resolve().is_relative_to(root): return False
    path = Path(timeline)
    data = json.loads(path.read_text(encoding="utf-8"))
    targets = [bg for beat in data.get("beats", []) for bg in beat.get("bgs", [])
               if bg.get("type") == "video" and bg.get("src") == src]
    if not targets: return False
    if any(bg.get("decoder") != "browser" for bg in targets):
        videos = [bg for beat in data.get("beats", []) for bg in beat.get("bgs", []) if bg.get("type") == "video"]
        for bg in videos: bg["decoder"] = "browser"
        (root / "video_decoder.json").write_text(json.dumps({"decoder":"browser"}), encoding="utf-8")
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        log(f"Runtime media recovery: native compositor rejected {src}; switching {len(videos)} video slot(s) to Chrome decoding; original visuals retained")
        return True
    replaced = 0
    for beat in data.get("beats", []):
        for i, bg in enumerate(beat.get("bgs", [])):
            if bg.get("type") != "video" or bg.get("src") != src: continue
            text = beat.get("title") or " ".join(str(w[0]) for w in beat.get("words", [])[:12]) or beat.get("id", "Video")
            beat["bgs"][i] = {**{k:bg[k] for k in ("from", "slot") if k in bg},
                "type":"graphic", "g":{"kind":"headline", "text":text[:90], "kicker":"VIDEO STUDIO", "sub":""}}
            replaced += 1
    if not replaced: return False
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    log(f"Runtime media recovery: {src} failed in compositor; {replaced} slot(s) -> headline card; original file retained")
    return True
