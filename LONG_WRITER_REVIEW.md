# Long-form script crash: isolated review

## Cause and repair

Production jobs `20261018_021142` and `20261018_003946` both failed in
`writer.write_plan()`. The Beginner patch passed an undefined local `notes` to
`jargon_check`; the collected notes in this function are named `notes_txt`.
This also affects Common long-form requests: Python evaluates the argument
before the jargon checker can return early.

Commit `e364ef9` changes that one argument and adds a regression test that calls
the long-form writer and checks that its collected notes reach jargon review.
The earlier Short-only checks did not exercise this path.

An isolated fresh install also exposed faster-whisper 1.2.1 / PyAV 19
incompatibility (`metadata_errors`). Commit `9a0d86d` constrains PyAV below 19;
PyAV 18.1.0 was installed and checked in the fork only.

## Isolation and evidence

- Code: `F:\code\video-studio-test`; server: `http://127.0.0.1:42021`.
- Jobs: `F:\videos_test\jobs`; evidence:
  `F:\videos_test\evidence\e2e_review_20261018`.
- Production code and port 42020 have not been changed or restarted during this review.
- Production jobs were inspected read-only. The older `20261017_140538`
  compositor failure is distinct; `20261017_165408` is finished. Job
  `20261016_171253` failed the existing 150-word input minimum (112 words).
- Narration uses an isolated Kokoro CPU environment and preset voice. DeepSeek
  generated and fact-checked the scripts. Cloud generation and external visual QA
  are disabled; visual ladder v2 and automatic physics are enabled.

Inputs under `tests/fixtures/e2e` are clearly labeled synthetic fixtures, not
real NotebookLM or Deep Research exports. These tests cover text/document intake,
not those external services. The first provided-script case exercised the existing
summarization workflow. After the user selected word-for-word preservation, a
separate case was added using the normal script-review API to approve all 214
supplied narration words, excluding the `Narrator:` speaker label and replacing
the generated closing line. This tests manual script review; it does not add an
automatic verbatim-input mode. Supplied footage is a
20-second calibration-pattern video generated with FFmpeg, not real user footage.

## Test cases

| Case | Test job |
| --- | --- |
| Provided script, 30-second smoke Short | `20261018_063030` |
| NotebookLM-format transcript, three-minute long form | `20261018_063004` |
| Deep Research-format Markdown, smoke Short | `20261018_063032` |
| Supplied video and fit-and-render | `20261018_063034` |
| Beginner and physical-motion beats | `20261018_063037` |
| Supplied script, word-for-word after script review | `20261018_125824` |

The focused physics script's source-supported radar beat was restored through
the script-review API after the model dropped it for length. The verbatim case
explicitly replaces the generated narration with the supplied script through
that same public API. Other generated scripts were not manually rewritten.
All jobs use Beginner and never-pause visuals.

`scripts/smoke_physics_modules.py` separately renders aircraft descent,
submarine pressure, missing-data weather motion, missing-data Hormuz ship route,
and radar sweep: four seconds / 120 frames each, full video decode, numerical
endpoint checks, and pixel-change checks within the animation region. Synthetic
graphics are labeled as illustrative. Vehicle crash, structural collapse, and
earthquake remain unimplemented stubs and are not claimed as passing features.

Initial voice-package setup failures and the PyAV failure remain in the test
job log; successful retries must not erase that history.

All six cases passed the final evidence collector: full video and audio decode,
Beginner logging, expected motion-module chains, and the additional assertions
below. All 26 offline tests and the F821 undefined-name scan also passed.

| Output | Seconds | Decoded frames |
| --- | ---: | ---: |
| NotebookLM-format long transcript | 219.97 | 6,599 |
| Initial summarized script | 33.07 | 992 |
| Research-format text | 39.07 | 1,172 |
| Supplied video after fit-and-render | 33.50 | 1,005 |
| Physics feature Short | 150.93 | 4,528 |
| Word-for-word supplied narration | 90.57 | 2,717 |

The verbatim case's approved narration and caption words both exactly match
all 214 supplied words; no generated closing narration remains. Its smoke-mode
30-second target was intentionally not enforced by cutting the supplied script.
Requested
lengths are targets: Beginner explanations and natural narration produced
overruns (the 180 s long-form request became 220 s; the 120 s feature Short
became 151 s), within the existing pipeline maximums. This review does not
claim exact-duration control or external visual-quality certification.

Each of the five separate physics clips passed all 120 frames and the motion
check; aircraft and submarine numerical endpoint assertions also passed. The
full feature job's fallback chains contain `aircraft_flight`,
`submarine_descent`, `ship_route`, and `radar_sweep`.

The supplied-video edit selected the newly supplied file, used mechanical
trimming at normal speed, and completed with identical frame count, unchanged
audio, and clean decoding. The smaller writer patch was also applied to a
throwaway copy of the preceding fork version and reproduced the corrected
source exactly after Windows line-ending normalization.

## Verification commands

Run only in the isolated checkout:

```powershell
cd F:\code\video-studio-test
app\env\Scripts\python.exe -m unittest discover -s tests -v
app\env\Scripts\python.exe -m ruff check --select F821 app tests scripts
app\env\Scripts\python.exe scripts\smoke_physics_modules.py
app\env\Scripts\python.exe scripts\collect_e2e_evidence.py
```

The collector fails unless all six jobs have finished, output video and audio
decode, Beginner checks ran, the four motion modules appear in the feature job's
fallback chains, the supplied-video edit preserves frames and audio, and the
verbatim script and caption words exactly match the supplied narration. Its
successful result is `final-report.json` in the evidence directory; a job merely
reaching script approval does not count as an end-to-end pass.

## Main recovery: held for review

The minimal production recovery patch is:
`F:\videos_test\evidence\e2e_review_20261018\fix-long-writer-notes.patch`.
It changes only `app/studio/writer.py`, preserving Beginner and Synthetic Motion.
The caption dependency patch is separate, named `caption-dependency.patch`.
Neither has been applied to production during this task.

After the fork results are reviewed and applying to main is authorized:

```powershell
git -C F:\code\video-studio apply --check F:\videos_test\evidence\e2e_review_20261018\fix-long-writer-notes.patch
git -C F:\code\video-studio apply F:\videos_test\evidence\e2e_review_20261018\fix-long-writer-notes.patch
```

Then restart the main instance through its normal launcher and Resume the failed
jobs. No production rollback, patch application, or restart is part of this review run.

## Subsequent fork work

The humor/original-commentary prompts and source screenshots/micro-clips are
documented in `EDITORIAL_SOURCE_REVIEW.md`, including current tests, generated
examples, live-download limitations and the unchanged TypeScript baseline errors.
