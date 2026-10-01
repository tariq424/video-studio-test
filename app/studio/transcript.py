"""Get a YouTube video's metadata + transcript.
1) one English caption track, fetched directly with retries (avoids yt-dlp's multi-track requests that trigger HTTP 429)
2) fallback: download the audio only and transcribe locally with faster-whisper on the GPU."""
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

def _fetch_caption(url, log):
    for i, wait in enumerate([0, 20, 60, 150]):
        if wait: log(f"  captions rate-limited, retrying in {wait}s"); time.sleep(wait)
        r = requests.get(url, headers=UA, timeout=60)
        if r.status_code == 200 and r.text.strip().startswith("{"): return r.json()
        if r.status_code not in (429, 403, 503): break
    return None

def _whisper(url, outdir, log):
    import yt_dlp
    log("  falling back to local speech-to-text (downloading audio only)...")
    opts = {"format": "bestaudio[ext=m4a]/bestaudio", "outtmpl": str(outdir / "audio.%(ext)s"), "quiet": True, "no_warnings": True}
    with yt_dlp.YoutubeDL(opts) as y: y.extract_info(url, download=True)
    audio = sorted(glob.glob(str(outdir / "audio.*")))[0]
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise RuntimeError("Captions were blocked and local transcription isn't installed. Paste the transcript into the job, or run Reinstall in Pinokio.")
    def run(m):
        segs, _ = m.transcribe(audio, language="en", vad_filter=True)
        text = []; t0 = time.time()
        for s in segs:
            text.append(s.text.strip())
            if time.time() - t0 > 60: log(f"  transcribed to {int(s.end//60)} min..."); t0 = time.time()
        return _clean(" ".join(text))
    try:
        return run(WhisperModel("large-v3-turbo", device="cuda", compute_type="float16"))
    except Exception as e:
        log(f"  GPU transcription unavailable ({str(e)[:80]}); using CPU (slower)")
        return run(WhisperModel("small.en", device="cpu", compute_type="int8"))

def fetch(url, outdir, log):
    import yt_dlp
    outdir = Path(outdir); outdir.mkdir(parents=True, exist_ok=True)
    with yt_dlp.YoutubeDL({"skip_download": True, "quiet": True, "no_warnings": True}) as y:
        info = y.extract_info(url, download=False)
    meta = {k: info.get(k) for k in ["id", "title", "channel", "uploader", "upload_date", "duration", "webpage_url", "description"]}
    meta["chapters"] = [{"title": c.get("title"), "start": c.get("start_time")} for c in (info.get("chapters") or [])]
    (outdir / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    text = ""
    turl, lang = _pick_track(info)
    if turl:
        d = _fetch_caption(turl, log)
        if d: text = _from_json3(d); log(f"  captions: {lang}")
    if len(text.split()) < 200:
        text = _whisper(url, outdir, log)
    (outdir / "transcript.txt").write_text(text, encoding="utf-8")
    log(f"Transcript: {len(text.split())} words from '{meta['title']}' ({(meta['duration'] or 0)//60} min)")
    return meta, text
