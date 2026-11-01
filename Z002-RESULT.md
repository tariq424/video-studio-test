# Z002 RESULT — fit gate: loosen wording-level rejections (S8 finding)

**Status: DONE — all 5 acceptance items green. Pushed to `codex/msg038-smoke` (test bed only).**

- Code commit: `4f6fe8a` (app/studio/imagegen.py + tests/test_fit_wording_variant.py)
- Result commit: this file
- Repo: video-studio-test, branch `codex/msg038-smoke`. Worktree checkout: `F:\code\codex-render-work\zcode-z002` (main checkout left untouched).
- Harness (rerunnable): `F:\code\codex-render-work\zcode-z002-harness\fit_check.py` — runs the REAL
  gate (Ollama qwen2.5vl:7b, PORT=42022) on the s8-frames specimens with narration loaded live from
  the nea_dixon iedit beats (short[19] Horseshoe locked / long[4] Arts Centre–Dockyard).
  Verdict JSONs: fit_before2.json / fit_after.json / fit_after2.json (stability re-run) in that dir.

## Change (matching/threshold logic only)
Stage-1 FIT_PROMPT now says wording-level variants of the same subject are matches. On a stage-1
match=no, `_fit_check_now` makes ONE independent subject check (FIT_SUBJECT_PROMPT: category-level
subject, ignore wording/naming/attributes/foreground clutter; "cannot tell" → no): same subject →
accepted with "wording-level only; subject check: …"; different subject → rejected with
"subject mismatch: …" (reason logged). match=yes verdicts make NO second call (locked beats that
pass behave exactly as before); malformed/unavailable stage-1 verdicts unchanged; provider ladder,
audit, caching, and fail-open behavior untouched. qc.py NOT touched.

## (5) Before/after verdicts (real gate, real specimens)

| Specimen (s8-frames) | Narration | Before | After (×2 runs, stable) |
|---|---|---|---|
| Horseshoe Bay locked beat — part56 (pink-sand cove) | short[19] | **accepted** ("curved, cove-shaped pink-sand beach…") | **accepted** — unchanged, stage-1 direct ✅ (3) |
| Arts Centre A — part04 (stone gallery, glass doors) | long[4] | rejected ("no specific i…") | **accepted** — "wording-level only; subject check: building with large glass doors" ✅ (1) |
| Arts Centre B — part17 (studio hallway) | long[4] | rejected ("hallway with green walls…") | **accepted** — "wording-level only; subject check: hallway with doors…" ✅ (1) |
| Mosque mismatch — mosque_frame.jpg (dashboard + arched bldg) | long[4] | rejected | **rejected** — "subject mismatch: car dashboard and a building with arched windows" ✅ (2) reason logged |

Observation rows (not gates): part58 generic lounger beach rejected→accepted (beach for a beach
beat); part47 dashboard-dominant view stays rejected. Note: the original S8 verdict artifacts were
not on disk (fit-smoke dirs hold the fixture harness only); before-verdicts above were captured on
pristine 003b7a4 code (git stash dance) against the same specimens — the before row pattern
reproduces the S8 finding exactly (locked accept + mosque reject + both Arts Centre reject).

## (4) Suite
`app\env` python, worktree: **151 passed, 4 skipped, 1 failed — only the known env failure**
`tests/test_setup_worker.py::test_bash_syntax` (WSL; it also cannot resolve the worktree path).
New unit tests (mocked, no vision calls): 7/7 in tests/test_fit_wording_variant.py; existing
tests/test_codex_fit_vault.py all green (old-schema stage-2 mocks stay rejected by design).

## Notes for Koda
- Specimen↔frame mapping was reconstructed (s8-frames contents identified via vision models,
  incl. the gate's own qwen2.5vl): part56=Horseshoe cove, part04/part17=the two Arts Centre
  pictures, mosque_frame=the mismatch specimen. part01≡part58 (identical bytes).
- The running 42022 server (PID 36820) serves the DIRTY MAIN worktree, which predates the fit
  gate entirely — the gate exists only on this branch. Verify from the branch/worktree, not that
  server. No production or live changes made; nothing merged.
