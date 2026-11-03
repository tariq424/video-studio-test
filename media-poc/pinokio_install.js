module.exports = {
  run: [
    { method: "shell.run", params: { venv: "venv", path: "F:/code/codex-render-work/zcode-z5-poc/media-poc", message: ["python -m pip install --upgrade pip", "pip install -r requirements.txt"] } },
    { method: "shell.run", params: { venv: "venv", path: "F:/code/codex-render-work/zcode-z5-poc/media-poc", message: ["python selfcheck.py"] } }
  ]
}
