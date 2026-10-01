import React from "react";
import { AbsoluteFill, Img, OffthreadVideo, interpolate, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { Bg } from "./types";

// Stills are wide (16:9) in a tall frame, so we SCROLL across them to reveal the whole scene.
// Videos play slightly slowed so a 5 s clip fills ~6 s.
export const Shot: React.FC<{ bg: Bg; dur: number; seed: number }> = ({ bg, dur, seed }) => {
  const f = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const t = f / fps;
  const p = Math.min(1, t / Math.max(dur, 0.1));
  const ease = p < 0.5 ? 2 * p * p : 1 - Math.pow(-2 * p + 2, 2) / 2;
  // first shot of a beat cuts in hard (a fade there dips to black between beats); later shots crossfade over the previous one
  const fadeIn = bg.from === 0 ? 1 : interpolate(t, [0, 0.35], [0, 1], { extrapolateRight: "clamp" });
  const shade = "linear-gradient(180deg, rgba(5,8,14,0.45) 0%, rgba(5,8,14,0) 18%, rgba(5,8,14,0) 62%, rgba(5,8,14,0.7) 100%)";
  if (bg.type === "video" && bg.fit === "frame") {
    // landscape clip shown whole, over a blurred enlarged copy of itself
    const z = interpolate(p, [0, 1], [1.0, 1.03]);
    return (
      <AbsoluteFill style={{ opacity: fadeIn, overflow: "hidden", background: "#000" }}>
        <OffthreadVideo src={staticFile(bg.src)} muted playbackRate={0.85}
          style={{ width: "100%", height: "100%", objectFit: "cover", filter: "blur(38px) brightness(0.55)", transform: "scale(1.15)" }} />
        <AbsoluteFill style={{ alignItems: "center", justifyContent: "center" }}>
          <div style={{ width: width, height: (width * 9) / 16, overflow: "hidden", boxShadow: "0 30px 80px rgba(0,0,0,0.6)", transform: `translateY(40px) scale(${z})` }}>
            <OffthreadVideo src={staticFile(bg.src)} muted playbackRate={0.85} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
          </div>
        </AbsoluteFill>
      </AbsoluteFill>
    );
  }
  if (bg.type === "video") {
    const z = interpolate(p, [0, 1], [1.0, 1.04]);   // gentle: every % of zoom softens the picture
    return (
      <AbsoluteFill style={{ opacity: fadeIn, overflow: "hidden" }}>
        <OffthreadVideo src={staticFile(bg.src)} muted playbackRate={0.85}
          style={{ width: "100%", height: "100%", objectFit: "cover", transform: `scale(${z})` }} />
        <AbsoluteFill style={{ background: shade }} />
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
      <Img src={staticFile(bg.src)} style={{ position: "absolute", top: 0, left: 0, height: "100%", width: imgW, maxWidth: "none",
        transform: `translateX(${x}px) scale(${z})`, transformOrigin: "center center" }} />
      <AbsoluteFill style={{ background: shade }} />
    </AbsoluteFill>
  );
};
