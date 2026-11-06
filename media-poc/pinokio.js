module.exports = {
  version: "3.7",
  title: "Media Routes POC (42054)",
  description: "SPEC-Z005 standalone smoke test for every external media route. Code in media-poc/, outputs in media-poc/output (gitignored). http://127.0.0.1:42054",
  menu: async (kernel, info) => {
    let installed = info.exists("F:/code/codex-render-work/zcode-z5-poc/media-poc/venv/Scripts/python.exe")
    let running = { install: info.running("pinokio_install.js"), start: info.running("pinokio_start.js") }
    if (running.install) return [{ default: true, icon: "fa-solid fa-plug", text: "Installing", href: "pinokio_install.js" }]
    if (!installed) return [{ default: true, icon: "fa-solid fa-plug", text: "Install", href: "pinokio_install.js" }]
    if (running.start) {
      let local = info.local("pinokio_start.js")
      if (local && local.url) return [{ default: true, icon: "fa-solid fa-rocket", text: "Open Media Routes POC", href: local.url }, { icon: "fa-solid fa-terminal", text: "Terminal", href: "pinokio_start.js" }]
      return [{ default: true, icon: "fa-solid fa-terminal", text: "Starting", href: "pinokio_start.js" }]
    }
    return [{ default: true, icon: "fa-solid fa-power-off", text: "Start", href: "pinokio_start.js" }, { icon: "fa-solid fa-plug", text: "Reinstall", href: "pinokio_install.js" }]
  }
}
