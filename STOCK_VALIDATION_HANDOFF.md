# Stock validation and render worker fix

The UI Resume of production job 20261017_165408 failed again, on generated graphic b0_0.mp4 rather than stock px34337855.mp4. Both files pass ffprobe and strict full-frame decoding. A corrupt-download check alone therefore does not explain or fix all observed failures.

Changes:
- footage.fetch validates new downloads and cached files using the existing ffprobe + strict full-frame decode helper. It removes partial/invalid files, retries once, then raises so the existing selection logic drops the clip and the visual ladder fills the gap.
- Percentage-based Short render concurrency is bounded to two workers. Explicit numeric overrides remain supported. The production setting was 75% and free RAM was about 1.2 GB when failures were observed; worker fan-out was a plausible pressure source. The complete failing timeline is tested at two workers instead of assuming validation makes a healthy clip safe.

Tests: 21 offline tests pass, including corrupt/truncated downloads, invalid cached media replacement, valid-cache reuse, and worker configuration. scripts/smoke_stock_validation.py copies the exact failed job's public timeline and media into F:\videos_test\jobs\stock_validation_smoke and renders all 178.6 seconds at full 1080x1920 resolution. It verifies source hashes remain unchanged and strictly decodes the completed video. No source narration or script is rewritten.

Patch: F:\videos_test\evidence\stock-validation.patch (only app/studio/footage.py and app/studio/short.py).

Manual rollback is possible using the two original files saved under F:\videos_test\evidence\stock-validation-backup before applying to main. Production lifecycle uses Pinokio pterm stop/run, preserving launcher configuration and other services.

Completed isolated result: 5,357 frames, 178.566667 seconds at 30fps; strict decode passed, original source hashes unchanged; 775.87 seconds for render/encoding.
