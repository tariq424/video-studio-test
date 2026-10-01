module.exports = {
  run: [
    { method: "shell.run", params: { venv: "env", path: "F:/code/video-studio/app", message: ["python -m pip install --upgrade pip", "pip install -r requirements.txt"] } },
    { method: "shell.run", params: { path: "F:/code/video-studio/remotion", message: ["node -v", "npm install --no-audit --no-fund", "npx remotion browser ensure"] } },
    { method: "fs.write", params: { path: "installed.flag", text: "ok" } }
  ]
}
