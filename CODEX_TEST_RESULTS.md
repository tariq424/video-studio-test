# Test-only narration fit and HF credential loader — October 29, 2026

Branch: `codex/test-fit-vault-20261029`, based on private `feature/gpu-interlock` at `cf88d5a`. DeepSeek request and response are retained on the same named test branch in `tariq424/ai-exchange`. The main mailman was not altered or restarted. Higgsfield was excluded entirely.

## Changes

- New generated-image narration-fit rejection runs only with process `PORT=42022`, forcing the local vision provider for that check. Existing stock vetting, physical checks and QC are unchanged.
- Fresh and resumed image candidates are checked before selection. Rejected/unavailable candidates advance to another provider and are retained under `imagegen/_rejected`.
- `imagegen/fit_audit.json` records checked, accepted, narration rejection and unavailable counts with reasons. Logs show cumulative counts. Content/narration/model changes invalidate cached verdicts; unchanged accepted candidates are not recounted.
- Gemini remains configured, with Google generation placed after non-Google providers even when rotation prefers it. Existing own/stock assets precede generated images. Google Photos code remains intact; its existing browser workflow was not replaced with an invented API integration.
- Added HF token masking, verified Vault writes, atomic settings migration and Linux environment fallback. No real token is in this branch or the mailbox.

## Verification

Isolated test environment on F:, with dedicated jobs, GPU lock and reservation paths. No production environment packages were changed.

`PORT=42021 python -m pytest -q tests -k 'not test_bash_syntax'`: **144 passed, 4 skipped, 1 deselected**, plus four subtests. The new tests explicitly switch to 42022 and mock providers/vision. Older rotation fixtures were updated for Google-last ordering and isolated from the new model check.

The deselected Linux shell syntax test invokes Windows' WSL `bash` with a Windows path and fails before reading the script. Explicit Git Bash `-n` on `scripts/linux/setup-worker.sh` passes. Four browser fixture skips reflect the unavailable Linux browser path.

`python scripts/smoke_narration_fit.py --work <fresh directory>`: **PASS**. Mocked providers and local-vision verdicts, no HF/network/GPU calls; one candidate rejected, one accepted, rejected evidence retained. Accepted image encoded into a two-second MP4 with CPU FFmpeg and strict decode passed. This does not establish real model accuracy or a complete Video Studio render.

A broader intermediate test run exposed legacy fixtures which reached the actual local vision model when PORT was globally set to 42022. Those fixtures are now explicitly mocked; further testing stayed offline. The live job remained running.

## Runtime state

Isolated server is running at `127.0.0.1:42022` from `F:/code/codex-render-test`, with jobs under `F:/code/codex-render-work/jobs`. Read-only status confirms idle, local vet provider, and masked HF settings. Runtime settings exclude HF image generation and talking-head use, disable paid Flow, and keep stock before automatic source substitution.

Tariq approved applying only the credential-loader fix to live. The loader was updated on disk at `F:/code/video-studio-test/app/studio/config.py`, preserving the existing defaults and unrelated edits; a source-only backup is retained outside Git. The stopped legacy test copy received that loader too. No server restart occurred. The current live render on 42021 was in assemble and was left running.

The existing HF token was copied to Windows Credential Manager and verified without displaying it. **Live plaintext settings are not yet migrated**: the already-running server still has the old loader in memory. Migrating before it safely loads the new code would break authenticated HF calls. No plaintext settings backup was made. Token rotation is deferred at Tariq's instruction to test without HF; no token was revoked or refreshed.

## Remaining checks

- Real local-vision narration-fit quality and an actual test-server render, in an idle GPU window. Do not start competing GPU work while the old live process renders.
- Safely activate the approved credential loader, then migrate both existing plaintext settings entries and verify redaction on the live server. Any restart must account for unrelated pending changes in that working tree; do not deploy those implicitly.
- HF token rotation when Tariq resumes HF work/authentication.
- Christian reference is now confirmed by Tariq's direct link. Expanded description and English browser transcript were reviewed; see `RENDER_REFERENCE_REVIEW.md`. No exact FFmpeg optimization commands or measured speedup were verified.

No visual change was deployed to live. No publishing, deletion, Google generation or paid service was exercised.
