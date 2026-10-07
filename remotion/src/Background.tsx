import React from "react";
import { AbsoluteFill, Freeze, Img, Loop, OffthreadVideo, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { Bg } from "./types";
import { asset } from "./asset";
import { MapBackdrop, HeadlineBackdrop, LayersBackdrop } from "./Backdrops";
import { ReconBackdrop } from "./Recon";

// Stills are wide (16:9) in a tall frame, so we SCROLL across them to reveal the whole scene.
// Videos play slightly slowed so a 5 s clip fills ~6 s.
// News-style honesty label on real-but-not-of-the-event visuals: "FILE" (a real photo of the subject taken another time),
// "ILLUSTRATIVE" (generic stock footage). Same place and style as the RECONSTRUCTION tag, on the left.
export const Shot: React.FC<{ bg: Bg; dur: number; seed: number }> = (props) => {
  const { height, width } = useVideoConfig(); const tall = height > width;
  const tag = (props.bg as any).tag as string | undefined;
  return (
    <AbsoluteFill>
      <ShotInner {...props} />
      {tag ? <div style={{ position: "absolute", top: tall ? 250 : 40, left: tall ? 40 : 48, fontFamily: "Inter, sans-serif", fontWeight: 800,
        fontSize: tall ? 28 : 24, letterSpacing: 3, color: "#111", background: "rgba(255,200,61,0.95)", borderRadius: 8, padding: "8px 16px" }}>{tag}</div> : null}
    </AbsoluteFill>
  );
};

// a video background, optionally fitted to its slot (beat editing): rate = playback speed (default 0.85), start = seconds
// into the source, freezeAt = hold the frame shown at that many seconds, loop = repeat every that many seconds
const Vid: React.FC<{ bg: any; style: React.CSSProperties }> = ({ bg, style }) => {
  const f = useCurrentFrame(); const { fps } = useVideoConfig();
  const v = <OffthreadVideo src={asset(bg.src)} muted playbackRate={bg.rate ?? 0.85} trimBefore={bg.start ? Math.round(bg.start * fps) : undefined} style={style} />;
  if (bg.loop) return <Loop durationInFrames={Math.max(1, Math.round(bg.loop * fps))} layout="none">{v}</Loop>;
  if (bg.freezeAt != null) { const n = Math.max(0, Math.round(bg.freezeAt * fps) - 1); if (f > n) return <Freeze frame={n}>{v}</Freeze>; }
  return v;
};

const ShotInner: React.FC<{ bg: Bg; dur: number; seed: number }> = ({ bg, dur, seed }) => {
  const f = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const t = f / fps;
  const p = Math.min(1, t / Math.max(dur, 0.1));
  const ease = p < 0.5 ? 2 * p * p : 1 - Math.pow(-2 * p + 2, 2) / 2;
  // first shot of a beat cuts in hard (a fade there dips to black between beats); later shots crossfade over the previous one
  const fadeIn = bg.from === 0 ? 1 : interpolate(t, [0, 0.35], [0, 1], { extrapolateRight: "clamp" });
  const shade = "linear-gradient(180deg, rgba(5,8,14,0.45) 0%, rgba(5,8,14,0) 18%, rgba(5,8,14,0) 62%, rgba(5,8,14,0.7) 100%)";
  if (bg.type === "graphic") return bg.g.kind === "map" ? <MapBackdrop g={bg.g} dur={dur} /> : bg.g.kind === "recon" ? <ReconBackdrop g={bg.g} dur={dur} /> : <HeadlineBackdrop g={bg.g as any} dur={dur} />;
  if (bg.type === "layers") return <LayersBackdrop layers={bg.layers} dur={dur} seed={seed} />;
  if (bg.type === "video" && bg.fit === "frame") {
    // landscape clip shown whole, over a blurred enlarged copy of itself
    const z = interpolate(p, [0, 1], [1.0, 1.03]);
    return (
      <AbsoluteFill style={{ opacity: fadeIn, overflow: "hidden", background: "#000" }}>
        <Vid bg={bg} style={{ width: "100%", height: "100%", objectFit: "cover", filter: "blur(38px) brightness(0.55)", transform: "scale(1.15)" }} />
        <AbsoluteFill style={{ alignItems: "center", justifyContent: "center" }}>
          <div style={{ width: width, height: (width * 9) / 16, overflow: "hidden", boxShadow: "0 30px 80px rgba(0,0,0,0.6)", transform: `translateY(40px) scale(${z})` }}>
            <Vid bg={bg} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
          </div>
        </AbsoluteFill>
      </AbsoluteFill>
    );
  }
  if (bg.type === "video") {
    const z = interpolate(p, [0, 1], [1.0, 1.04]);   // gentle: every % of zoom softens the picture
    return (
      <AbsoluteFill style={{ opacity: fadeIn, overflow: "hidden" }}>
        <Vid bg={bg} style={{ width: "100%", height: "100%", objectFit: "cover", transform: `scale(${z})` }} />
        <AbsoluteFill style={{ background: shade }} />
      </AbsoluteFill>
    );
  }
  if (bg.type === "image" && bg.fit === "frame") {
    // a real photo shown whole (sharp), over a blurred enlarged copy of itself, with a slow push-in; credit line at the bottom
    const z = interpolate(p, [0, 1], [1.0, 1.07]);
    return (
      <AbsoluteFill style={{ opacity: fadeIn, overflow: "hidden", background: "#000" }}>
        <Img src={asset(bg.src)} style={{ width: "100%", height: "100%", objectFit: "cover", filter: "blur(38px) brightness(0.5)", transform: "scale(1.15)" }} />
        <AbsoluteFill style={{ alignItems: "center", justifyContent: "center" }}>
          <Img src={asset(bg.src)} style={{ width: width, maxHeight: height * 0.62, objectFit: "contain", boxShadow: "0 30px 80px rgba(0,0,0,0.6)",
            transform: `translateY(20px) scale(${z})` }} />
        </AbsoluteFill>
        {bg.credit ? <div style={{ position: "absolute", left: 40, right: 40, top: height * 0.5 + width * 0.36 + 40, textAlign: "center",
          fontFamily: "Inter, sans-serif", fontWeight: 600, fontSize: 22, color: "rgba(255,255,255,0.7)" }}>{bg.credit}</div> : null}
      </AbsoluteFill>
    );
  }
  const imgW = (height * 1920) / 1088;          // rendered width of a 16:9 still at full frame height
  const range = (imgW - width) * 0.85;           // how far we can scroll
  const leftToRight = seed % 2 === 0;
  const x = leftToRight ? interpolate(ease, [0, 1], [-(imgW - width) / 2 - range / 2, -(imgW - width) / 2 + range / 2])
                        : interpolate(ease, [0, 1], [-(imgW - width) / 2 + range / 2, -(imgW - width) / 2 - range / 2]);
  const z = interpolate(p, [0, 1], [1.02, 1.08]);
  return (
    <AbsoluteFill style={{ opacity: fadeIn, overflow: "hidden" }}>
      <Img src={asset(bg.src)} style={{ position: "absolute", top: 0, left: 0, height: "100%", width: imgW, maxWidth: "none",
        transform: `translateX(${x}px) scale(${z})`, transformOrigin: "center center" }} />
      <AbsoluteFill style={{ background: shade }} />
    </AbsoluteFill>
  );
};
