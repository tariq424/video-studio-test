module.exports = async (kernel) => {
  // fixed address: http://127.0.0.1:42054 (never moves: the spec names the port)
  return {
    daemon: true,
    run: [
      { method: "shell.run", params: { venv: "venv", path: "F:/code/codex-render-work/zcode-z5-poc/media-poc", env: { PYTHONUNBUFFERED: "1" },
          message: ["python server.py"], on: [{ event: "/running on http:\\/\\/127\\.0\\.0\\.1:42054/", done: true }] } },
      { method: "local.set", params: { url: "http://127.0.0.1:42054" } }
    ]
  }
}
