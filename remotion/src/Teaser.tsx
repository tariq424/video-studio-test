import React from "react";
import { AbsoluteFill, Audio, Sequence, interpolate, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { Shot } from "./Background";
import { GraphicView } from "./Graphics";
import { Captions } from "./Captions";
import { C, BODY } from "./theme";
import { TeaserProps } from "./types";
import { asset } from "./asset";

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

// emoji above the caption (a small pop-in), for the caption it belongs to
const Icon: React.FC<{ e: string; dur: number }> = ({ e, dur }) => {
  const f = useCurrentFrame(); const { fps, width, height } = useVideoConfig(); const t = f / fps; const tall = height > width;
  const k = interpolate(t, [0, 0.18], [0.6, 1], { extrapolateRight: "clamp" }); const o = interpolate(t, [0, 0.12, dur - 0.15, dur], [0, 1, 1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return <div style={{ position: "absolute", left: 0, right: 0, top: tall ? 1240 : height - 330, textAlign: "center", fontSize: tall ? 110 : 96, opacity: o,
    transform: `scale(${k})`, fontFamily: "'Segoe UI Emoji','Apple Color Emoji','Noto Color Emoji',sans-serif", filter: "drop-shadow(0 6px 14px rgba(0,0,0,0.6))" }}>{e}</div>;
};

export const Teaser: React.FC<TeaserProps> = ({ audio, total, tag, beats, progress }) => {
  const { fps } = useVideoConfig();
  const fr = (s: number) => Math.max(1, Math.round(s * fps));
  const shots = beats.flatMap((b, bi) => b.bgs.map((bg, i) => ({ bg, start: b.start + bg.from, seed: bi * 3 + i,
    dur: (i + 1 < b.bgs.length ? b.bgs[i + 1].from : b.dur) - bg.from })));
  return (
    <AbsoluteFill style={{ background: C.bg }}>
      {/* footage: one continuous layer; each shot keeps playing 0.4 s under the next one, so a shot that isn't painted on its
          first frame never shows the dark page background (that was a 1-frame flash at every beat change) */}
      {shots.map((x, k) => (
        <Sequence key={"bg" + k} from={fr(x.start)} durationInFrames={fr(x.dur + 0.4)} premountFor={fps}>
          <Shot bg={x.bg} dur={x.dur} seed={x.seed} />
        </Sequence>
      ))}
      {beats.map((b, bi) => (
        <Sequence key={b.id} from={fr(b.start)} durationInFrames={fr(b.dur)} name={b.id}>
          {b.graphics.map((g, i) => {
            const nextAt = i + 1 < b.graphics.length ? b.graphics[i + 1].at : b.dur;
            const d = g.g.kind === "cta" ? nextAt - g.at : Math.min(nextAt - g.at, 4.6);   // graphics leave so the scenery shows
            return (
              <Sequence key={"g" + i} from={fr(g.at)} durationInFrames={fr(d)}>
                <Exit dur={d}><GraphicView g={g.g} /></Exit>
              </Sequence>
            );
          })}
          {(b.icons || []).map((ic, i) => (
            <Sequence key={"i" + i} from={fr(ic.at)} durationInFrames={fr(ic.dur)}><Icon e={ic.e} dur={ic.dur} /></Sequence>
          ))}
          {b.words.length > 0 && b.graphics[0]?.g.kind !== "cta" && <Captions words={b.words} />}
        </Sequence>
      ))}
      <Tag tag={tag} hideFrom={(beats.find((b) => b.graphics.some((g) => g.g.kind === "cta"))?.start ?? 1e9)} />
      {progress === false ? null : <Progress total={total} />}
      <Audio src={asset(audio)} />
    </AbsoluteFill>
  );
};
