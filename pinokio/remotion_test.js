const P = "--props=F:/videos/explainer_studio/shorts/moonshots_teaser/props_test.json --public-dir=F:/videos/explainer_studio/shorts/moonshots_teaser --bundle-cache=true"
module.exports = { run: [ { method: "shell.run", params: { path: "F:/code/explainer-studio/remotion_short", message: [
  `npx remotion still src/index.ts Short F:/videos/explainer_studio/shorts/moonshots_teaser/test/f193.png --frame=193 ${P}`,
  `npx remotion still src/index.ts Short F:/videos/explainer_studio/shorts/moonshots_teaser/test/f1298.png --frame=1298 ${P}`,
  `npx remotion still src/index.ts Short F:/videos/explainer_studio/shorts/moonshots_teaser/test/f1970.png --frame=1970 ${P}`,
  `npx remotion still src/index.ts Short F:/videos/explainer_studio/shorts/moonshots_teaser/test/f2283.png --frame=2283 ${P}`,
  `npx remotion still src/index.ts Short F:/videos/explainer_studio/shorts/moonshots_teaser/test/f2829.png --frame=2829 ${P}`,
  `npx remotion still src/index.ts Short F:/videos/explainer_studio/shorts/moonshots_teaser/test/f509.png --frame=509 ${P}`
] } } ] }
