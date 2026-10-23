"""Background music: a suspense cue under the hook, then a quiet bed under the rest, ducked whenever the narrator speaks.

Tracks come from your own folder (no downloads, no licences guessed): music_dir (default <jobs folder parent>\\music) with
    hook\\   short suspense / tension cues   (played under the hook: the Short's first beat, the explainer's first seconds)
    bed\\    calm background tracks, e.g. lo-fi (looped under the rest of the video)
Use tracks you are allowed to put on YouTube (YouTube Studio > Audio Library is free and safe). A random track is picked
per video. No tracks -> no music, the video is unchanged. Any failure leaves the video as it was (never fails the job).

Settings: music_on (true), music_dir, music_hook_db (-14: hook cue level), music_bed_db (-24: bed level under speech),
music_long (true: explainers get it too)."""
import json
import random
from pathlib import Path

from . import media

AUDIO = (".mp3", ".m4a", ".wav", ".ogg", ".aac", ".flac")


def folder(cfg):
    return Path(cfg.get("music_dir") or (Path(cfg.get("jobs_dir") or ".").parent / "music"))


def _pick(cfg, sub, rng):
    d = folder(cfg) / sub
    files = sorted(p for p in d.glob("*") if p.suffix.lower() in AUDIO) if d.is_dir() else []
    return rng.choice(files) if files else None


def mix(mp4, cfg, log, hook_secs=6.0, seed=None):
    """Lay music under the narration of mp4 (in place). -> True if music was added."""
    if not cfg.get("music_on", True): return False
    mp4 = Path(mp4); rng = random.Random(seed)
    hook, bed = _pick(cfg, "hook", rng), _pick(cfg, "bed", rng)
    if not hook and not bed:
        log(f"  music: no tracks in {folder(cfg)}\\hook or \\bed; no music added"); return False
    try:
        total = media.dur(mp4); h = max(0.0, min(float(hook_secs), total)) if hook else 0.0
        hdb, bdb = float(cfg.get("music_hook_db", -14)), float(cfg.get("music_bed_db", -24))
        ins, parts = ["-i", mp4], []
        if hook:
            ins += ["-i", hook]
            # the cue plays under the hook and fades out over its last second
            parts.append(f"[{len(ins) // 2 - 1}:a]atrim=0:{h + 1:.2f},asetpts=PTS-STARTPTS,volume={hdb}dB,afade=t=out:st={max(0, h - 0.5):.2f}:d=1.5[mh]")
        if bed and total - h > 2:
            ins += ["-stream_loop", "-1", "-i", bed]
            k = len([x for x in ins if x == "-i"]) - 1
            parts.append(f"[{k}:a]atrim=0:{total - h + 1:.2f},asetpts=PTS-STARTPTS,volume={bdb}dB,afade=t=in:st=0:d=1.5,"
                         f"afade=t=out:st={max(0, total - h - 2):.2f}:d=2,adelay={int(h * 1000)}|{int(h * 1000)}[mb]")
        tracks = [t for t, ok in (("[mh]", hook), ("[mb]", bed and total - h > 2)) if ok]
        music = "".join(tracks) + (f"amix=inputs={len(tracks)}:normalize=0:duration=longest" if len(tracks) > 1 else "anull") + ",aformat=channel_layouts=stereo[m];"
        # duck the music under the voice (sidechain), then put the two together; the voice level is untouched
        flt = ";".join(parts) + ";" + music + \
              "[0:a]asplit=2[v][key];[m][key]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=400[md];" \
              "[v][md]amix=inputs=2:normalize=0:duration=first[a]"
        tmp = mp4.with_name("_music_" + mp4.name)
        media.ff(*ins, "-filter_complex", flt, "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                 "-movflags", "+faststart", "-t", f"{total:.3f}", tmp)
        if media.dur(tmp) < total - 0.5: raise RuntimeError("the result came out shorter")
        tmp.replace(mp4)
        (mp4.parent / (mp4.stem + "_music.json")).write_text(json.dumps({"hook": str(hook or ""), "bed": str(bed or ""), "hook_secs": h}, indent=1), encoding="utf-8")
        log(f"Music added: {'hook ' + hook.name + f' ({h:.1f}s)' if hook else ''}{' + ' if hook and bed else ''}{'bed ' + bed.name if bed else ''}")
        return True
    except Exception as e:
        log(f"  music skipped ({' '.join(str(e).split())[:250]}); the video is unchanged")
        return False


def hook_secs_short(job):
    """The Short's hook = its first beat (from the timeline)."""
    try:
        b0 = json.loads((Path(job) / "short" / "public" / "teaser.json").read_text(encoding="utf-8"))["beats"][0]
        return float(b0["start"]) + float(b0["dur"])
    except Exception:
        return 6.0
