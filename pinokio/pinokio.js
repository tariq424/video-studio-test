module.exports = {
  version: "3.7",
  title: "Video Studio",
  description: "YouTube link, NotebookLM audio or notes in; long explainer and/or a 2-3 min YouTube Short out. Code in F:\\code\\video-studio, outputs in F:\\videos\\video_studio",
  icon: "icon.jpg",
  menu: async (kernel, info) => {
    let installed = info.exists("F:/code/video-studio/app/env") && info.exists("F:/code/video-studio/remotion/node_modules")
    let running = { install: info.running("install.js"), start: info.running("start.js") }
    if (running.install) return [{ default: true, icon: "fa-solid fa-plug", text: "Installing", href: "install.js" }]
    if (!installed) return [{ default: true, icon: "fa-solid fa-plug", text: "Install", href: "install.js" }]
    let extra = info.exists("F:/code/video-studio/app/kenv/Scripts/python.exe") && !info.running("install_kokoro.js") ? [] :
      [{ icon: "fa-solid fa-microphone", text: info.running("install_kokoro.js") ? "Installing Kokoro" : "Install Kokoro narration (optional)", href: "install_kokoro.js" }]
    if (running.start) {
      let local = info.local("start.js")
      if (local && local.url) return [{ default: true, icon: "fa-solid fa-rocket", text: "Open Video Studio", href: local.url }, { icon: "fa-solid fa-terminal", text: "Terminal", href: "start.js" }, ...extra]
      return [{ default: true, icon: "fa-solid fa-terminal", text: "Starting", href: "start.js" }]
    }
    return [{ default: true, icon: "fa-solid fa-power-off", text: "Start", href: "start.js" }, { icon: "fa-solid fa-plug", text: "Reinstall", href: "install.js" }, ...extra]
  }
}
