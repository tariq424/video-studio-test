import React from "react";
import { AbsoluteFill, Sequence, useVideoConfig } from "remotion";
import { Shot } from "./Background";

// one beat's backgrounds on their own (no captions, graphics or audio): long-video slots after an edit, at any size.
// props: {bgs: [{...bg, from}], dur}
export type BeatClipProps = { bgs: any[]; dur: number; w?: number; h?: number };
export const BeatClip: React.FC<BeatClipProps> = ({ bgs, dur }) => {
  const { fps } = useVideoConfig();
  const fr = (s: number) => Math.max(1, Math.round(s * fps));
  return (
    <AbsoluteFill style={{ background: "#000" }}>
      {bgs.map((bg, i) => {
        const d = (i + 1 < bgs.length ? bgs[i + 1].from : dur) - bg.from;
        return (
          <Sequence key={i} from={Math.round(bg.from * fps)} durationInFrames={fr(d + (i + 1 < bgs.length ? 0.4 : 0))} premountFor={fps}>
            <Shot bg={bg} dur={d} seed={i} />
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};
