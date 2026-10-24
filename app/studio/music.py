"""Background music: a suspense cue under the hook, then a quiet bed under the rest, ducked whenever the narrator speaks.

Tracks come from your own folder (no downloads, no licences guessed): music_dir (default <jobs folder parent>\\music) with
    hook\\   short suspense / tension cues   (played under the hook: the Short's first beat, the explainer's first seconds)
    bed\\    calm background tracks, e.g. lo-fi (looped under the rest of the video)
Use tracks you are allowed to put on YouTube (YouTube Studio > Audio Library is free and safe). A random track is picked
per video. No tracks -> no music, the video is unchanged. Any failure leaves the video as it was (never fails the job).

Settings: music_on (true), music_dir, music_hook_db (-4), music_bed_db (-6): the level in the narrator's pauses (breathers); under speech it dips ~10 dB more,
music_long (true: explainers get it too)."""
import json
import random
import time
from pathlib import Path

from . import media

# every track is first brought to the narration's loudness (-14 LUFS), so the dB settings below mean "this much under the voice"
# (2026-10-23: raw -14/-24 dB plus a hard 8:1 dip left the music 20-30 dB under the voice: inaudible)
NORM = "loudnorm=I=-14:TP=-2:LRA=11"
AUDIO = (".mp3", ".m4a", ".wav", ".ogg", ".aac", ".flac")


def folder(cfg):
    return Path(cfg.get("music_dir") or (Path(cfg.get("jobs_dir") or ".").parent / "music"))


MOODS = {   # mood -> how we describe a new track of that mood to Gemini (kind: hook = 15-20 s cue, bed = loopable background)
    "tense":       ("hook", "a tense cinematic build-up, low pulsing strings and a ticking pulse, 15-20 seconds, ending on a hit"),
    "dramatic":    ("hook", "a dramatic orchestral opener, big drums and brass swell, 15-20 seconds"),
    "playful":     ("hook", "a playful, cheeky pizzicato and woodblock sting, bright and quick, 15-20 seconds"),
    "classical":   ("bed", "light classical chamber music, string quartet and piano, gentle and elegant, steady tempo, loopable"),
    "light-dance": ("bed", "light, bouncy dance groove, soft four-on-the-floor beat, warm synths, unobtrusive, loopable"),
    "cheerful":    ("bed", "cheerful, sunny acoustic pop instrumental, ukulele, claps and glockenspiel, loopable"),
    "calm":        ("bed", "calm lo-fi hip hop instrumental, mellow keys and soft vinyl texture, relaxed, loopable"),
    "inspiring":   ("bed", "inspiring, hopeful cinematic underscore, piano and soft strings, slowly rising, loopable"),
    "upbeat":      ("bed", "upbeat modern news-style background, light percussion and plucked synths, energetic but quiet, loopable"),
    "somber":      ("bed", "somber, reflective ambient underscore, soft piano and pads, slow, loopable"),
}
PICK = """Pick background music for this news video. Hook = the opening cue; bed = quiet music under the rest.
Hook moods: tense, dramatic, playful. Bed moods: classical, light-dance, cheerful, calm, inspiring, upbeat, somber.
Match the story's tone (a light tech story -> cheerful or light-dance; serious harm or loss -> somber; never cheerful
music under bad news). VIDEO: {text}
Reply with JSON only: {{"hook": "...", "bed": "..."}}"""


def library(cfg):
    """[{file, kind, mood, desc, source}] from library.json, plus any file you dropped in hook/ or bed/ (mood 'any')."""
    root = folder(cfg); idx = root / "library.json"
    try: lib = json.loads(idx.read_text(encoding="utf-8"))
    except (OSError, ValueError): lib = []
    known = {x["file"] for x in lib}
    for kind in ("hook", "bed"):
        d = root / kind
        for f in (sorted(d.glob("*")) if d.is_dir() else []):
            rel = f"{kind}/{f.name}"
            if f.suffix.lower() in AUDIO and rel not in known: lib.append({"file": rel, "kind": kind, "mood": "any", "desc": "", "source": "yours"})
    return [x for x in lib if (root / x["file"]).exists()]


def add_to_library(cfg, f, kind, mood, desc, source="gemini"):
    root = folder(cfg); idx = root / "library.json"
    try: lib = json.loads(idx.read_text(encoding="utf-8"))
    except (OSError, ValueError): lib = []
    rel = Path(f).resolve().relative_to(root.resolve()).as_posix()
    lib = [x for x in lib if x["file"] != rel] + [{"file": rel, "kind": kind, "mood": mood, "desc": desc, "source": source, "at": time.time()}]
    idx.write_text(json.dumps(lib, indent=1), encoding="utf-8")


def moods_for(cfg, text, log):
    """The script AI picks a hook mood and a bed mood for the story (default: tense + calm)."""
    if not text: return "tense", "calm"
    try:
        from .llm import LLM
        def ok(j):
            if j.get("hook") not in MOODS or MOODS[j["hook"]][0] != "hook" or j.get("bed") not in MOODS or MOODS[j["bed"]][0] != "bed":
                raise ValueError("pick one hook mood and one bed mood from the lists")
        with LLM(dict(cfg), log, lambda: False) as llm:
            j = llm.chat_json("You pick music moods. Reply with JSON only.", PICK.format(text=text[:1500].replace('"', "'")), max_tokens=100, check=ok)
        return j["hook"], j["bed"]
    except Exception as e:
        log(f"  music: mood pick failed ({str(e)[:80]}); tense + calm"); return "tense", "calm"


def choose(cfg, kind, mood, rng, log):
    """A track of this kind and mood from the library; a new one from Gemini only if none fits and today's cap allows;
    else any track of this kind (yours included)."""
    lib = [x for x in library(cfg) if x["kind"] == kind]
    fit = [x for x in lib if x["mood"] == mood]
    if fit: return folder(cfg) / rng.choice(fit)["file"]
    from . import music_gen
    if music_gen.allowed(cfg):
        desc = MOODS[mood][1]
        out = folder(cfg) / kind / f"{mood}_{time.strftime('%Y%m%d_%H%M%S')}.mp3"
        try:
            music_gen.generate(cfg, desc, out, log, evidence_dir=folder(cfg))
            add_to_library(cfg, out, kind, mood, desc); log(f"  music: new {mood} {kind} track added to the library")
            return out
        except Exception as e:
            log(f"  music: couldn't make a new {mood} track ({' '.join(str(e).split())[:150]}); using another from the library")
    any_ = lib   # nothing fits and no new track: any track of this kind (yours included)
    return folder(cfg) / rng.choice(any_)["file"] if any_ else None


def mix(mp4, cfg, log, hook_secs=6.0, seed=None, text=""):
    """Lay music under the narration of mp4 (in place). -> True if music was added."""
    if not cfg.get("music_on", True): return False
    mp4 = Path(mp4); rng = random.Random(seed)
    hm, bm = moods_for(cfg, text, log)
    log(f"  music: moods hook={hm}, bed={bm}")
    hook, bed = choose(cfg, "hook", hm, rng, log), choose(cfg, "bed", bm, rng, log)
    if not hook and not bed:
        log(f"  music: no tracks in the library ({folder(cfg)}); no music added"); return False
    try:
        total = media.dur(mp4); h = max(0.0, min(float(hook_secs), total)) if hook else 0.0
        hdb, bdb = float(cfg.get("music_hook_db", -4)), float(cfg.get("music_bed_db", -6))
        ins, parts = ["-i", mp4], []
        if hook:
            ins += ["-i", hook]
            # the cue plays under the hook and fades out over its last second
            parts.append(f"[{len(ins) // 2 - 1}:a]atrim=0:{h + 1:.2f},asetpts=PTS-STARTPTS,{NORM},volume={hdb}dB,afade=t=out:st={max(0, h - 0.5):.2f}:d=1.5[mh]")
        if bed and total - h > 2:
            ins += ["-stream_loop", "-1", "-i", bed]
            k = len([x for x in ins if x == "-i"]) - 1
            parts.append(f"[{k}:a]atrim=0:{total - h + 1:.2f},asetpts=PTS-STARTPTS,{NORM},volume={bdb}dB,afade=t=in:st=0:d=1.5,"
                         f"afade=t=out:st={max(0, total - h - 2):.2f}:d=2,adelay={int(h * 1000)}|{int(h * 1000)}[mb]")
        tracks = [t for t, ok in (("[mh]", hook), ("[mb]", bed and total - h > 2)) if ok]
        music = "".join(tracks) + (f"amix=inputs={len(tracks)}:normalize=0:duration=longest" if len(tracks) > 1 else "anull") + ",aformat=channel_layouts=stereo[m];"
        # duck the music under the voice (sidechain), then put the two together; the voice level is untouched
        flt = ";".join(parts) + ";" + music + \
              f"[0:a]asplit=2[v][key];[m][key]sidechaincompress=threshold={float(cfg.get('music_duck_threshold', 0.05))}:ratio={float(cfg.get('music_duck_ratio', 6))}:attack=40:release=500[md];" \
              "[v][md]amix=inputs=2:normalize=0:duration=first[a]"
        tmp = mp4.with_name("_music_" + mp4.name)
        media.ff(*ins, "-filter_complex", flt, "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                 "-movflags", "+faststart", "-t", f"{total:.3f}", tmp)
        if media.dur(tmp) < total - 0.5: raise RuntimeError("the result came out shorter")
        tmp.replace(mp4)
        (mp4.parent / (mp4.stem + "_music.json")).write_text(json.dumps({"hook": str(hook or ""), "bed": str(bed or ""), "hook_secs": h,
                                                                         "moods": [hm, bm]}, indent=1), encoding="utf-8")
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
