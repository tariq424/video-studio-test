module.exports = {
  run: [
    { method: "shell.run", params: { venv: "env", path: "F:/code/explainer-studio/app", message: ["python -m pip install --upgrade pip", "pip install -r requirements.txt"] } },
    { method: "fs.write", params: { path: "installed.flag", text: "ok" } }
  ]
}
