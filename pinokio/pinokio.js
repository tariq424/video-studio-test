module.exports = {
  version: "3.7",
  title: "Explainer Studio",
  description: "Paste a YouTube link, get a narrated 1080p explainer video (uses Wan2GP). Code in F:\\code\\explainer-studio, outputs in F:\\videos\\explainer_studio",
  icon: "icon.jpg",
  menu: async (kernel, info) => {
    let installed = info.exists("F:/code/explainer-studio/app/env") || info.exists("installed.flag")
    let running = { install: info.running("install.js"), start: info.running("start.js") }
    if (running.install) return [{ default: true, icon: "fa-solid fa-plug", text: "Installing", href: "install.js" }]
    if (!installed) return [{ default: true, icon: "fa-solid fa-plug", text: "Install", href: "install.js" }]
    if (running.start) {
      let local = info.local("start.js")
      if (local && local.url) return [{ default: true, icon: "fa-solid fa-rocket", text: "Open Explainer Studio", href: local.url }, { icon: "fa-solid fa-terminal", text: "Terminal", href: "start.js" }]
      return [{ default: true, icon: "fa-solid fa-terminal", text: "Starting", href: "start.js" }]
    }
    return [{ default: true, icon: "fa-solid fa-power-off", text: "Start", href: "start.js" }, { icon: "fa-solid fa-plug", text: "Reinstall", href: "install.js" }]
  }
}
