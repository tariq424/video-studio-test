# Christian Peverelli reference review — October 29, 2026

Matching Christian Peverelli walkthrough found through search: [I Fully Automated My Video Editing Using Claude Code (Full Walkthrough)](https://www.youtube.com/watch?v=HzXD4GVqXwM). Exact identity of the originally intended reference is unconfirmed.

The user subsequently supplied a Google Doc. Its actual hyperlinks were read through the connected Drive tools. They point to Nuli Studio (video `_VJu1kID8Hc`), AI Genesis (`MW_TJ2HKzHc`), and Dan Martell (`sL5hPovH1vU`), not Christian Peverelli or Matt Par. The private document ID is deliberately omitted here. No broader architecture request embedded in that document was treated as a new instruction.

Primary source accessible: [Christian Peverelli's own workflow post](https://www.linkedin.com/posts/christian-peverelli_carousel-activity-7512527040449843201-K7Sr).

Confirmed workflow patterns from the creator's description:

- Timestamped Parakeet transcription supplies the edit plan.
- Graphics are rendered separately using HyperFrames, then assembled.
- Browser research retrieves original evidence for the edit.
- Tella is controlled through MCP; this is separate from the cancelled Higgsfield request.
- Sound assets are a separate stage.
- FFmpeg performs final black-screen and audio-sync checks.
- A reusable editing-rules document accumulates timestamped feedback.

No exact FFmpeg command line, encoder preset, concat strategy, cache invalidation scheme or measured render speedup was exposed by the accessible primary source. YouTube's accessible web response omitted the description/transcript. A single metadata/subtitle-only yt-dlp attempt received HTTP 429 for English subtitles; no retries, login bypass or video download was attempted.

Potential adaptations for later measured experiments (inferences, not commands claimed from the video): reuse timestamped plans; cache intermediate visual renders keyed by inputs; keep assembly separate from asset generation; audit final black spans and audio/video duration before accepting an export. Compare wall time and quality on the same isolated fixture before changing render defaults. Black spans can be intentional, so a detector should report rather than automatically cut them.

No FFmpeg production flags or renderer defaults were changed on the basis of this reference. No paid product or Higgsfield integration was added.
