# Christian Peverelli reference review — October 29, 2026

Confirmed by Tariq's direct link: [I Fully Automated My Video Editing Using Claude Code (Full Walkthrough)](https://www.youtube.com/watch?v=HzXD4GVqXwM), Christian Peverelli. The expanded YouTube description and English auto-generated transcript were subsequently read in the signed-in browser.

An earlier supplied Google Doc linked to other channels. The direct link now resolves the reference mismatch. No instructions embedded in that document were treated as new authorization.

Primary source accessible: [Christian Peverelli's own workflow post](https://www.linkedin.com/posts/christian-peverelli_carousel-activity-7512527040449843201-K7Sr).

Confirmed workflow patterns from the creator's description:

- Timestamped Parakeet transcription supplies the edit plan.
- Graphics are rendered separately using HyperFrames, then assembled.
- Browser research retrieves original evidence for the edit.
- Tella is controlled through MCP; this is separate from the cancelled Higgsfield request.
- Sound assets are a separate stage.
- FFmpeg performs final black-screen and audio-sync checks.
- A reusable editing-rules document accumulates timestamped feedback.

## Confirmed transcript details

- **1:34–2:10:** Parakeet produces timestamped text for take selection and cuts.
- **2:12–3:42:** HyperFrames renders animations; browser research supplies screenshots, page recordings, highlights and zooms from original evidence.
- **5:03–5:25:** FFmpeg assembles/finishes the edit, addressing black gaps and audio synchronization.
- **9:41–11:30, 12:20–12:31:** short hook iterations and timestamped feedback build reusable editorial rules and an animation library.

The description links the editing skill through the creator's Skool community, rather than exposing source files directly. No account was created. Neither description nor spoken transcript provides exact FFmpeg commands, codec presets, hardware-encoding flags, or concat/cache implementation. Auto-generated captions may contain transcription errors. No on-screen command inspection was performed, so these findings do not establish whether brief commands appear visually.

The earlier yt-dlp subtitle request returned HTTP 429. Later browser transcript export succeeded through the normal signed-in page; no video download or access-control bypass was used.

Potential adaptations for later measured experiments (inferences, not commands claimed from the video): reuse timestamped plans; cache intermediate visual renders keyed by inputs; keep assembly separate from asset generation; audit final black spans and audio/video duration before accepting an export. Compare wall time and quality on the same isolated fixture before changing render defaults. Black spans can be intentional, so a detector should report rather than automatically cut them.

For this pipeline, the strongest visual-quality lesson is deliberate evidence/animation selection before rendering. Faster encoding alone cannot make an unrelated image fit the narration. Existing Remotion assets can serve that role without adopting another renderer or paid service.

No FFmpeg production flags or renderer defaults were changed on the basis of this reference. No paid product or Higgsfield integration was added.
