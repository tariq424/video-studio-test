module.exports = async (kernel) => {
  // fixed address: http://127.0.0.1:42020 (server.py moves to the next free port and prints it if 42020 is taken)
  return {
    daemon: true,
    run: [
      { method: "shell.run", params: { venv: "env", path: "F:/code/video-studio/app", env: { PORT: "42020", PYTHONUNBUFFERED: "1" },
          message: ["python server.py"], on: [{ event: "/http:\\/\\/127\\.0\\.0\\.1:[0-9]+/", done: true }] } },
      { method: "local.set", params: { url: "{{input.event[0]}}" } }
    ]
  }
}
