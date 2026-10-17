# Beginner audience — isolated implementation

Completed October 17, 2026 in F:\code\video-studio-test only. Main checkout and
port 42020 were not changed. Main listener remained PID 13564 during these tests.

## Changes

- Common remains the default. Beginner appears immediately below Common on the
  job form and /make, before Informed and Expert.
- /make passes the selection into the embedded form, saved specifications and
  Playwright runner. Old saved specifications inherit the existing settings default.
- Backend job creation and resumed-job configuration accept Beginner.
- Beginner keeps technical names and explains their first use with function,
  plain language and/or a familiar analogy; expanding an acronym alone is not enough.
- Fact-checking preserves explanations and avoids unsupported performance claims.
  Beginner jargon review can restore named systems from source notes; edits that
  remove existing acronyms are rejected. Common's prompt/behavior is preserved.
- Beginner 30-second smoke scripts focus on one technical idea; jargon review checks
  the complete story stays within 70 words, rather than blindly expanding every
  secondary feature. The existing separate closing line adds a few seconds.

## Tests and actual model comparison

11 unit tests pass (including the six media-guard tests). Browser checks passed on
port 42021 for both dropdowns, Common default, Beginner selection/propagation and
legacy saved specifications. The UI parse response was stubbed for that browser
check to avoid an unrelated Ollama call; backend parsing is covered by unit tests.

The real DeepSeek v4 pro backend generated both scripts from the same weather
passage of job 20261016_190435. The test title identifies the GFS/ECMWF source
excerpt; the original full-episode description was omitted so unrelated topics
would not leak into this focused comparison. Both test jobs stop at script review,
before TTS or rendering. No exact audio duration is claimed: these are 30-second
story targets, with word counts and a separate closing line below.

Initial trials were too shallow, overlong, or used a passage too short for the
existing notes safeguard. Those artifacts are retained in F:\videos_test\jobs.
The final Beginner sample includes the revised fact-check/jargon-review passes;
their prompts are retained under audience_beginner_final/prompts. The source
transcript SHA256 is unchanged. Evidence: F:\videos_test\evidence\audience.

### Common

Bilawal Sidhu shows a wind map with the two big forecast models, GFS and ECMWF. He prefers the second one, ECMWF, the European model. You can layer on rain radar, satellite clouds, and lightning density. You can switch between wind speed, pressure, and temperature.

Hurricane Rachel has a cyclone advisory. The wind matches what you see in real-time satellite imagery. You can scrub back through history on the fly.

Closing: That was a short summary of an excerpt from Bilawal Sidhu on weather forecast models. Follow for more.

Story: 69 words; with closing: 87 words.

### Beginner

Bilawal Sidhu compares two forecast models, computer programs that use weather measurements to predict what happens next. One is GFS, the US government's Global Forecast System; the other is ECMWF, Europe's weather model from the European Centre for Medium-Range Weather Forecasts. Sidhu prefers ECMWF.

ECMWF is one of the two big forecast models. Its wind predictions match real-time satellite imagery, pictures of Earth taken from space.

Closing: That was a short summary of Bilawal Sidhu. Follow for more.

Story: 66 words; with closing: 77 words.

## Manual application (not executed against main)

The code-only patch includes app/server.py, app/static/index.html,
app/static/make.html, app/studio/config.py, app/studio/make.py,
app/studio/pipeline.py, app/studio/short.py, app/studio/writer.py and app/vs_runner.py.
It excludes the earlier media fix, test settings, dependencies and test fixtures.
No new production dependencies are required.

Preserve any uncommitted production changes, then manually run:

```powershell
git -C F:\code\video-studio apply --check F:\videos_test\evidence\audience\beginner-audience.patch
git -C F:\code\video-studio apply F:\videos_test\evidence\audience\beginner-audience.patch
```

If the check reports conflicts, reconcile the listed files; do not force/reset the
main checkout. Restart production only at a safe point and refresh its browser.
Do not copy the fork's settings.json or test launch configuration into production.

Reproduction helpers: scripts/smoke_beginner_audience.py seeds fresh script-only
jobs (refuses overwrite); scripts/test_beginner_ui.py checks the UI with Playwright.
The isolated server is shut down after verification; port 42021 is released.
