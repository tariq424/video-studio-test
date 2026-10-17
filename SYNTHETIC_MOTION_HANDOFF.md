# Synthetic Data Motion hand-off

Implemented only in F:\code\video-studio-test. Main checkout and port 42020 were left untouched. Original job inputs remain read-only.

Physical motion is checked before the graphics classifier can select an abstract card. The explainer and Short fallback ladders also return live animated graphic specifications, avoiding a silent headline-card downgrade. Existing supplied ship waypoints and successful NOAA/AIS data remain usable through their physics modules.

Missing ship/weather data now produces an illustrative motion schematic; radar has a new deterministic sweep module. Hormuz ship narration uses an illustrative three-waypoint path from the Persian Gulf through the strait into the Gulf of Oman. Other locations use a schematic rather than fabricated geographic precision. All synthetic graphics display a synthetic/not-live label. Coordinates, timing and radar targets are illustrative, not measured observations or forecasts. This does not add live radar API integration.

Files: app/studio/physics.py, graphics.py, render.py, short.py, review.py; remotion/src/Motion.tsx, Background.tsx, Backdrops.tsx. Tests: tests/test_synthetic_motion.py and scripts/smoke_synthetic_motion.py.

## Verification

Completed: 17 offline tests pass. Both real Remotion smoke clips pass strict decoding: 4 seconds, 120 frames, 1920x1080 at 30fps. Animation-region pixel mean changes: radar 2.0985, ship 0.4002. Both frames were visually inspected. Source SHA-256 remained unchanged. Main port 42020 remained PID 13564; port 42021 was not started for these standalone renderer checks.

Run offline checks:

```powershell
cd F:\code\video-studio-test
app\env\Scripts\python.exe -m unittest discover -s tests -p 'test_*.py'
$env:PORT='42021'
app\env\Scripts\python.exe -u scripts\smoke_synthetic_motion.py
```

Smoke fixtures use God’s Eye View source topics from job 20261016_190435, forcing radar and Hormuz ship motion. They are explicit paraphrased fixtures, not an AI regeneration of the complete source video. Both use the actual graphics classifier and Remotion renderer. Source excerpts and SHA-256 are saved alongside output. Pixel differences are measured within the animation region at 0.8 and 2.6 seconds; strict ffmpeg decoding validates the entire clip. No TTS, full-length pipeline rerun, production service restart, or upload is required.

Artifacts: F:\videos_test\jobs\synthetic-motion\radar.mp4, ship.mp4, radar.png, ship.png, report.json.

## Apply manually to main

A code-only patch is at F:\videos_test\evidence\synthetic-motion.patch. Review first, then:

```powershell
git -C F:\code\video-studio apply --check F:\videos_test\evidence\synthetic-motion.patch
git -C F:\code\video-studio apply F:\videos_test\evidence\synthetic-motion.patch
```

Those commands have not been run on main. If main has overlapping changes, resolve them manually instead of forcing the patch. Existing completed renders are not automatically regenerated.
