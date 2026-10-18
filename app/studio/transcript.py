"""Get a YouTube video's metadata + transcript.
1) one English caption track, fetched directly (avoids yt-dlp's multi-track requests that trigger HTTP 429)
2) fallback when the video has no captions: download the audio only and transcribe locally with faster-whisper.
If YouTube blocks or rate-limits us, stop at once with a clear error (no retries, no audio download)."""
import json, re, time, glob
from pathlib import Path
import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128 Safari/537.36"}

def _clean(t):
    t = re.sub(r"\[(Music|Applause|Laughter|__)\]", " ", t, flags=re.I)
    return re.sub(r"\s+", " ", t).strip()

def _from_json3(d):
    out, last = [], ""
    for ev in d.get("events", []):
        t = "".join(s.get("utf8", "") for s in ev.get("segs", []) or []).replace("\n", " ").strip()
        if t and t != last: out.append(t); last = t
    return _clean(" ".join(out))

def _pick_track(info):
    for src, prefs in ((info.get("subtitles") or {}, ["en", "en-US", "en-GB"]), (info.get("automatic_captions") or {}, ["en-orig", "en", "en-US"])):
        for lang in prefs:
            for f in src.get(lang, []) or []:
                if f.get("ext") == "json3": return f["url"], lang
    return None, None

BLOCKED = ("YouTube is blocking or rate-limiting requests from this PC ({why}). Stopped without retrying. "
           "Try again later, or paste the transcript into a new job.")

def _blocked(e):
    m = str(e).lower()
    return any(k in m for k in ("429", "too many requests", "sign in to confirm", "403", "forbidden", "rate"))

def _fetch_caption(url, log):
    r = requests.get(url, headers=UA, timeout=60)
    if r.status_code == 200 and r.text.strip().startswith("{"): return r.json()
    if r.status_code in (429, 403, 503): raise RuntimeError(BLOCKED.format(why=f"HTTP {r.status_code} on captions"))
    return None

def _whisper(url, outdir, log):
    import yt_dlp
    log("  falling back to local speech-to-text (downloading audio only)...")
    opts = {"format": "bestaudio[ext=m4a]/bestaudio", "outtmpl": str(outdir / "audio.%(ext)s"), "quiet": True, "no_warnings": True}
    try:
        with yt_dlp.YoutubeDL(opts) as y: y.extract_info(url, download=True)
    except Exception as e:
        if _blocked(e): raise RuntimeError(BLOCKED.format(why=str(e)[:120]))
        raise
    audio = sorted(glob.glob(str(outdir / "audio.*")))[0]
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise RuntimeError("Captions were blocked and local transcription isn't installed. Paste the transcript into the job, or run Reinstall in Pinokio.")
    def run(m):
        segs, _ = m.transcribe(audio, language="en", vad_filter=True)
        text = []; cues = []; t0 = time.time()
        for s in segs:
            text.append(s.text.strip())
            cues.append({"start": s.start, "text": s.text.strip()})
            if time.time() - t0 > 60: log(f"  transcribed to {int(s.end//60)} min..."); t0 = time.time()
        (outdir / "source_cues.json").write_text(json.dumps(cues, ensure_ascii=False), encoding="utf-8")
        return _clean(" ".join(text))
    try:
        return run(WhisperModel("large-v3-turbo", device="cuda", compute_type="float16"))
    except Exception as e:
        log(f"  GPU transcription unavailable ({str(e)[:80]}); using CPU (slower)")
        return run(WhisperModel("small.en", device="cpu", compute_type="int8"))

def video_id(url):
    m = re.search(r"(?:youtu\.be/|[?&]v=|/shorts/|/live/|/embed/)([A-Za-z0-9_-]{11})", url or "")
    return m.group(1) if m else ""

def meta_only(url, outdir):
    """Title/channel/description only (one light request, no captions)."""
    import yt_dlp
    try:
        with yt_dlp.YoutubeDL({"skip_download": True, "quiet": True, "no_warnings": True}) as y:
            info = y.extract_info(url, download=False)
    except Exception as e:
        if _blocked(e): raise RuntimeError(BLOCKED.format(why=str(e)[:120]))
        raise
    meta = {k: info.get(k) for k in ["id", "title", "channel", "uploader", "upload_date", "duration", "webpage_url", "description"]}
    meta["chapters"] = [{"title": c.get("title"), "start": c.get("start_time")} for c in (info.get("chapters") or [])]
    return meta

def fetch(url, outdir, log):
    import yt_dlp
    outdir = Path(outdir); outdir.mkdir(parents=True, exist_ok=True)
    try:
        with yt_dlp.YoutubeDL({"skip_download": True, "quiet": True, "no_warnings": True}) as y:
            info = y.extract_info(url, download=False)
    except Exception as e:
        if _blocked(e): raise RuntimeError(BLOCKED.format(why=str(e)[:120]))
        raise
    meta = {k: info.get(k) for k in ["id", "title", "channel", "uploader", "upload_date", "duration", "webpage_url", "description"]}
    meta["chapters"] = [{"title": c.get("title"), "start": c.get("start_time")} for c in (info.get("chapters") or [])]
    (outdir / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    text = ""
    turl, lang = _pick_track(info)
    if turl:
        d = _fetch_caption(turl, log)
        if d:
            cues = [{"start": e.get("tStartMs", 0) / 1000,
                     "text": "".join(s.get("utf8", "") for s in e.get("segs", [])).strip()}
                    for e in d.get("events", []) if e.get("segs")]
            (outdir / "source_cues.json").write_text(json.dumps(cues, ensure_ascii=False), encoding="utf-8")
        if d: text = _from_json3(d); log(f"  captions: {lang}")
    if len(text.split()) < 200:
        text = _whisper(url, outdir, log)
    (outdir / "transcript.txt").write_text(text, encoding="utf-8")
    log(f"Transcript: {len(text.split())} words from '{meta['title']}' ({(meta['duration'] or 0)//60} min)")
    return meta, text
