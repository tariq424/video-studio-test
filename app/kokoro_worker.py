"""Kokoro TTS worker. Runs in the Kokoro env (app/kenv), not Video Studio's env:  python kokoro_worker.py request.json

request.json = {"voice": "am_michael", "lang": "a", "speed": 1.0, "device": "" | "cuda" | "cpu",
                "items": [{"text": "...", "out": "path.wav"}, ...]}
Writes one 24 kHz mono WAV per item (Kokoro's native rate); the caller (studio/tts.py) converts to 48 kHz stereo.
The model loads once for the whole list. Exit code 0 = every item written."""
import json, sys


def main(path):
    import numpy as np
    import soundfile as sf
    from kokoro import KPipeline
    req = json.load(open(path, encoding="utf-8"))
    dev = req.get("device") or None
    if dev is None:
        try:
            import torch; dev = "cuda" if torch.cuda.is_available() else "cpu"
        except Exception: dev = "cpu"
    pipe = KPipeline(lang_code=req.get("lang", "a"), repo_id="hexgrad/Kokoro-82M", device=dev)
    voice, speed = req.get("voice", "am_michael"), float(req.get("speed", 1.0))
    for it in req["items"]:
        parts = []
        # one call per item; Kokoro splits long text itself (split_pattern on blank lines keeps sentences together)
        for _, _, audio in pipe(it["text"], voice=voice, speed=speed, split_pattern=r"\n\n+"):
            if audio is None: continue
            a = audio.detach().cpu().numpy() if hasattr(audio, "detach") else np.asarray(audio)
            parts.append(a.astype("float32"))
        if not parts: raise SystemExit(f"no audio for: {it['text'][:60]}")
        sf.write(it["out"], np.concatenate(parts), 24000)
        print(f"ok {it['out']}", flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
