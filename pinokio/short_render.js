const D = "F:/videos/explainer_studio/shorts/moonshots_teaser"
module.exports = { run: [ { method: "shell.run", params: { path: "F:/code/explainer-studio/remotion_short", message: [
  `npx remotion render src/index.ts Short ${D}/output/raw.mp4 --props=${D}/assets.json --public-dir=${D} --codec=h264 --crf=18 --concurrency=6 --log=info`
] } } ] }
