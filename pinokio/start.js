module.exports = async (kernel) => {
  let port = await kernel.port()
  return {
    daemon: true,
    run: [
      { method: "shell.run", params: { venv: "env", path: "F:/code/video-studio/app", env: { PORT: port, PYTHONUNBUFFERED: "1" },
          message: ["python server.py"], on: [{ event: "/http:\\/\\/127\\.0\\.0\\.1:[0-9]+/", done: true }] } },
      { method: "local.set", params: { url: "{{input.event[0]}}" } }
    ]
  }
}
