# Original commentary, mild wit, and source evidence

## Advisory review regression — 2026-10-18

The strict style gate stopped real job `20261018_213727` (AI news). Replaying
its saved model response now preserves all 11 checked sections, records a
warning and returns normally. Reproduce with:

```powershell
.\app\env\Scripts\python.exe scripts/replay_editorial_failure.py F:\videos_test\jobs\20261018_213727 --evidence F:\videos_test\evidence\editorial-failure-replay.json
```

Live DeepSeek job `20261018_215337` used the complete 5,621-word God's Eye
View transcript from production job `20261016_190435` (read-only), Beginner,
both outputs, three-minute explainer target, 165-second Short target, and
script approval required. Its six explainer sections and nine initial Short
beats both triggered advisory warnings instead of exceptions. The existing
Short length pass reduced the final plan to seven beats including attribution.
The job completed `script` and `short_script` and reached `awaiting_review`
with an empty error. Rendering was deliberately not started.

41 offline tests pass, including failed-annotation fallback, malformed model
responses, partial rewrite rollback, successful review, and cancellation.
Evidence: `F:\videos_test\evidence\editorial-live-regression.json` and
`editorial-failure-replay.json`. This regression used temporary fork port
42022 because automatic approval review rejected restarting the existing
42021 process; that process still requires a restart to load the fix.
Production code and port 42020 remain untouched.

## Original feature implementation

Implemented only in `F:\code\video-studio-test`. Production code, production
jobs, and port 42020 were not modified or restarted. The isolated server on
42021 was restarted and reports jobs under `F:\videos_test\jobs`.

## Writing behavior

The shared writer instructions now apply to Common, Beginner, Informed and
Expert, for both Shorts and explainer sections:

- Give selected facts original interpretation: significance, evidence limits,
  critical comparison or clearly marked inference. Reduce breadth to make room.
- Use a mild witty phrase or explanatory analogy in each content beat. Avoid
  slapstick, recycled source jokes, and jokes at victims' expense.
- Keep technical names and first-use explanations appropriate to the audience.
- Distinguish a source claim from verified evidence, and an illustration from
  observation. Checking a transcript is not independent verification of its claims.

A final editorial pass stores actual `analysis` and `humor` quotations in each
content section's `editorial` object. It checks the revised narration against
the source, reviews jargon, and source-checks any jargon additions again. If
definitions interrupt a quoted sentence, it refreshes the annotations without
rewriting the checked narration. The editorial pass now makes one bounded
attempt on a private copy. Unresolved style checks or model errors log an
advisory warning and preserve the previously source-checked narration instead
of stopping the pipeline. Cancellation still stops the job. Failed partial
rewrites are discarded; warnings are saved in `editorial_warnings`, without
inventing passing annotations. These annotations are an audit aid, not a
semantic or legal certificate.

The generated closing line keeps source attribution and adds the mild phrase
“Big picture, fewer rabbit holes.” No editorial pass runs after a user approves
or supplies verbatim narration. Credits and quotations are not joke material.

## Source visuals

`source_visuals.py` supplies a new visual-ladder rung for Shorts and long form.
An excerpt must be explicitly requested by a plan item, for example:

```json
{
  "source_visual": {
    "kind": "clip",
    "start": 42.5,
    "duration": 2.5,
    "purpose": "The animation illustrates a route but does not prove an observed journey"
  }
}
```

Use `kind: screenshot` for a still. For Shorts the request belongs on a content
section; for explainers it belongs on a visual. The writer receives a bounded
sample of real timestamped caption/ASR cues, not invented timestamps. Without
such cues it is told to omit requests. Remote requests must match an actual
stored cue, use a YouTube URL, and have a commentary purpose. A deliberately
supplied local `job\src\source_video.mp4` can also be extracted at a validated
timestamp. Supplied footage/edit decisions take precedence over source reuse.

Remote downloads request only the selected 2–3 second range, without cookies
or authentication bypass. The whole download is bounded to 90 seconds, including
ffmpeg descendants. Missing media, invalid timestamps, corruption, provider
errors and timeouts log a reason and continue the normal visual ladder.

The renderer shows the excerpt once, muted, in an attributed panel beside our
commentary and custom graphic/simulation. After at most three seconds the
excerpt disappears and our graphic continues. It is never looped as filler.
Extraction metadata retains source URL, credit, timestamp and purpose.

Settings:

```json
{"source_visuals": true, "source_visual_max_uses": 2}
```

The maximum is two excerpt-bearing plan items per output; zero disables use.
This and the duration limit are editorial choices, not legal safe harbors.

## Verification

- **38 offline tests pass**, including the existing regression suite and new
  bounds, invalid-input, cache/budget, attribution, owned-footage precedence,
  quote-preservation, remote-range and timeout-cleanup tests.
- Python undefined-name scan and `git diff --check` pass.
- Real FFmpeg extraction from an owned calibration video produced a screenshot
  and a 2.5-second clip through the Short fallback rung. Long-form routing also
  selects the new composite. Source SHA-256 remains unchanged.
- Three actual Remotion samples (landscape screenshot, landscape clip, portrait
  clip) each fully decode to **120 frames / four seconds**. Frames inspected
  before and after the 2.5-second cutoff show source evidence disappearing while
  the radar animation continues. The portrait title overlap found in the first
  layout was fixed and the samples rerendered.
- Live DeepSeek Common and Beginner examples passed the actual editorial,
  fact-check and jargon-review functions. Their final quoted analysis/wit
  annotations occur verbatim in the saved narration.
- A live YouTube retrieval attempt timed out. **Successful remote extraction
  is not verified on this PC**. Range selection and timeout behavior are tested
  with a controlled downloader; actual extraction/rendering uses an owned file.
- Full TypeScript checking still fails on pre-existing React Three Fiber JSX
  typing errors in `remotion/src/Recon.tsx`. That file matches the committed
  baseline; no errors were reported in the newly changed components. Actual
  Remotion bundling/rendering succeeds. This is not reported as a passing full
  TypeScript build.

The prior six complete voice/render workflow jobs are historical evidence in
`LONG_WRITER_REVIEW.md`; they were not rerun as six new full jobs for this change.

### Actual Beginner example

> Its route is a sequence of latitude and longitude coordinates, a pair of
> numbers that pin down an exact spot on a map like a street address for the ocean.

The same beat explains why a fictional route could be mistaken for monitoring
a real ship. Another beat expands AIS, explains its radio broadcast in plain
language, and comments that without the illustrative label “a silent drawing
acquires a voice it never had.”

Evidence:

- `F:\videos_test\jobs\source_evidence_smoke\report.json` and its MP4/PNG samples.
- `F:\videos_test\evidence\editorial_source_features\verified-examples.json`.
- `F:\videos_test\jobs\youtube_source_probe\report.json`.
- `F:\videos_test\evidence\editorial_source_features\typescript.log`.

Reproduce from the fork:

```powershell
app\env\Scripts\python.exe -m unittest discover -s tests -v
app\env\Scripts\python.exe -m ruff check --select F821 app tests scripts
app\env\Scripts\python.exe scripts\smoke_source_visuals.py
app\env\Scripts\python.exe scripts\smoke_editorial_prompts.py
```

## Policy boundaries

YouTube's reused-content policy looks for meaningful original commentary or
modification; it is separate from copyright/fair use. There is no fixed amount
of borrowed material that automatically qualifies as fair use. Neither prompts,
overlays, credit nor a short duration guarantee monetization or legal compliance.

- [YouTube channel monetization policies](https://support.google.com/youtube/answer/1311392)
- [U.S. Copyright Office fair-use FAQ](https://www.copyright.gov/help/faq/faq-fairuse.html)

No production patch or restart is included in this handoff.
