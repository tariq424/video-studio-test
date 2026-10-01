import React from "react";
import { AbsoluteFill, Audio, Sequence, interpolate, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { Shot } from "./Background";
import { GraphicView } from "./Graphics";
import { Captions } from "./Captions";
import { C, BODY } from "./theme";
import { TeaserProps } from "./types";

const Progress: React.FC<{ total: number }> = ({ total }) => {
  const f = useCurrentFrame(); const { fps } = useVideoConfig();
  return <div style={{ position: "absolute", top: 0, left: 0, height: 10, width: `${(100 * f) / (total * fps)}%`, background: C.gold }} />;
};

const Exit: React.FC<{ dur: number; children: React.ReactNode }> = ({ dur, children }) => {
  const f = useCurrentFrame(); const { fps } = useVideoConfig(); const t = f / fps;
  const k = interpolate(t, [dur - 0.45, dur], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return <AbsoluteFill style={{ opacity: 1 - k, transform: `translateY(${-90 * k}px)` }}>{children}</AbsoluteFill>;
};

// top label; hidden on the end card, where it would overlap the card's badge
const Tag: React.FC<{ tag: string; hideFrom: number }> = ({ tag, hideFrom }) => {
  const f = useCurrentFrame(); const { fps } = useVideoConfig();
  if (!tag || f / fps >= hideFrom) return null;
  return (
    <div style={{ position: "absolute", top: 60, left: 0, right: 0, textAlign: "center" }}>
      <span style={{ fontFamily: BODY, fontWeight: 800, fontSize: 30, color: C.text, background: "rgba(0,0,0,0.45)", border: `1px solid ${C.line}`, borderRadius: 999, padding: "10px 24px", letterSpacing: 1 }}>{tag}</span>
    </div>
  );
};

export const Teaser: React.FC<TeaserProps> = ({ audio, total, tag, beats }) => {
  const { fps } = useVideoConfig();
  const fr = (s: number) => Math.max(1, Math.round(s * fps));
  return (
    <AbsoluteFill style={{ background: C.bg }}>
      {beats.map((b, bi) => (
        <Sequence key={b.id} from={fr(b.start)} durationInFrames={fr(b.dur)} name={b.id}>
          {b.bgs.map((bg, i) => {
            const end = i + 1 < b.bgs.length ? b.bgs[i + 1].from : b.dur;
            return (
              <Sequence key={i} from={fr(bg.from)} durationInFrames={fr(end - bg.from + 0.3)}>
                <Shot bg={bg} dur={end - bg.from} seed={bi * 3 + i} />
              </Sequence>
            );
          })}
          {b.graphics.map((g, i) => {
            const nextAt = i + 1 < b.graphics.length ? b.graphics[i + 1].at : b.dur;
            const d = g.g.kind === "cta" ? nextAt - g.at : Math.min(nextAt - g.at, 4.6);   // graphics leave so the scenery shows
            return (
              <Sequence key={"g" + i} from={fr(g.at)} durationInFrames={fr(d)}>
                <Exit dur={d}><GraphicView g={g.g} /></Exit>
              </Sequence>
            );
          })}
          {b.words.length > 0 && b.graphics[0]?.g.kind !== "cta" && <Captions words={b.words} />}
        </Sequence>
      ))}
      <Tag tag={tag} hideFrom={(beats.find((b) => b.graphics.some((g) => g.g.kind === "cta"))?.start ?? 1e9)} />
      <Progress total={total} />
      <Audio src={staticFile(audio)} />
    </AbsoluteFill>
  );
};
