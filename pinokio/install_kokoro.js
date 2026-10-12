// Optional: the Kokoro narration engine (tts_engine = "kokoro"). Its own env (app/kenv) so Video Studio's env never gets PyTorch.
// Safe to run while Video Studio is running: it only creates app/kenv and downloads the Kokoro-82M model; nothing is switched on.
module.exports = {
  run: [
    { method: "shell.run", params: { venv: "kenv", path: "F:/code/video-studio/app", message: [
      "python -m pip install --upgrade pip",
      "pip install torch --index-url https://download.pytorch.org/whl/cu128",
      "pip install \"kokoro>=0.9.2\" soundfile",
      "python -c \"from kokoro import KPipeline; p=KPipeline(lang_code='a'); [None for _ in p('Kokoro is ready.', voice='am_michael')]; print('kokoro ok')\""
    ] } },
    { method: "fs.write", params: { path: "kokoro.flag", text: "ok" } }
  ]
}
