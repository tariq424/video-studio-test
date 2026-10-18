# Stock validation and render worker fix

The UI Resume of production job 20261017_165408 failed again, on generated graphic b0_0.mp4 rather than stock px34337855.mp4. Both files pass ffprobe and strict full-frame decoding. A corrupt-download check alone therefore does not explain or fix all observed failures.

Changes:
- footage.fetch validates new downloads and cached files using the existing ffprobe + strict full-frame decode helper. It removes partial/invalid files, retries once, then raises so the existing selection logic drops the clip and the visual ladder fills the gap.
- Percentage-based Short render concurrency is bounded to two workers. Explicit numeric overrides remain supported. The production setting was 75% and free RAM was about 1.2 GB when failures were observed; worker fan-out was a plausible pressure source. The complete failing timeline is tested at two workers instead of assuming validation makes a healthy clip safe.

Tests: 21 offline tests pass, including corrupt/truncated downloads, invalid cached media replacement, valid-cache reuse, and worker configuration. scripts/smoke_stock_validation.py copies the exact failed job's public timeline and media into F:\videos_test\jobs\stock_validation_smoke and renders all 178.6 seconds at full 1080x1920 resolution. It verifies source hashes remain unchanged and strictly decodes the completed video. No source narration or script is rewritten.

Patch: F:\videos_test\evidence\stock-validation.patch (only app/studio/footage.py and app/studio/short.py).

Manual rollback is possible using the two original files saved under F:\videos_test\evidence\stock-validation-backup before applying to main. Production lifecycle uses Pinokio pterm stop/run, preserving launcher configuration and other services.

Completed isolated result: 5,357 frames, 178.566667 seconds at 30fps; strict decode passed, original source hashes unchanged; 775.87 seconds for render/encoding.

## Follow-up after production verification

The first main rerender still failed on px7989667.mp4 at two workers. Thus the worker limit alone was not a complete fix. Source files were equivalent, but the passing fork used a local Chrome override whereas main used Remotion's default browser.

The follow-up explicitly selects installed Chrome (or remotion_browser_executable when configured). It also adds bounded runtime recovery for frame-extraction or frame-fetch errors: only the video identified in the error URL and actually present in the current timeline is replaced by a headline card; other assets, timing, captions, and original source files remain intact. Each failed video is removed from the current timeline so it cannot create an infinite retry loop. Unknown errors remain errors. Runtime replacements are logged and saved in short/public/teaser.json; a later full rebuild may attempt original assets again.

Validation: 24 offline tests pass. scripts/smoke_runtime_recovery.py injects a compositor error into the actual Short render loop, then invokes real Remotion with explicit Chrome. It passes on the second render attempt: 4 seconds, 120 frames, 30fps, strict full decoding; source retained, only the named clip replaced, second clip preserved. Evidence: F:\videos_test\jobs\runtime_recovery_smoke\report.json and workflow.log.

Follow-up patch: F:\videos_test\evidence\render-runtime-recovery.patch. Main originals for rollback are saved under F:\videos_test\evidence\runtime-recovery-backup. This patch supplements the earlier stock-validation patch.

## Preserve visuals using browser decoding

Production's native compositor rejected several additional files that pass full decoding. Runtime recovery now switches all video slots to Remotion Html5Video in installed Chrome on the first native failure, preserving the original footage. Only an asset that also fails browser decoding is replaced by a headline card. The per-job decision is saved in public/video_decoder.json and honored by preflight on later builds. Retry bounds account for both decoder fallback and asset fallback.

Validation: 25 offline tests pass. The real four-second recovery smoke injects one compositor failure, then renders both original videos using Chrome decoding: 120 frames pass strict decoding, sources retained, exactly two render attempts. This supersedes the card-first behavior described above. Main job's generated decoder policy is set to browser before resuming, restoring original visual selections from fallback.json during build; original media, script, and narration are retained.
