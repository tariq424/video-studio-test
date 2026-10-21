import React from "react";
import { AbsoluteFill, Freeze, Img, Loop, Html5Video, OffthreadVideo, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { Bg } from "./types";
import { asset } from "./asset";
import { MapBackdrop, HeadlineBackdrop, LayersBackdrop } from "./Backdrops";
import { ReconBackdrop } from "./Recon";
import { IllustrationBackdrop, SilhouetteBackdrop } from "./Illustration";
import { SimBackdrop, SimMapBackdrop } from "./Sim";
import { MotionBackdrop } from "./Motion";
import { TemplateBackdrop } from "./Templates";

// Stills are wide (16:9) in a tall frame, so we SCROLL across them to reveal the whole scene.
// Videos play slightly slowed so a 5 s clip fills ~6 s.
export const Shot: React.FC<{ bg: Bg; dur: number; seed: number }> = (props) => {
  // Rung labels (GENERATED · GEMINI, GENERATED · FLOW, SOURCE · ..., ILLUSTRATIVE, SYNTHETIC...) stay in the timeline data and the job
  // log for debugging; they are never drawn on the video (owner's decision 2026-10-21; YouTube's altered-content flag discloses AI use).
  return (
    <AbsoluteFill>
      <ShotInner {...props} />
    </AbsoluteFill>
  );
};

// A clip that fails to load is reported on the console with a fixed marker; the Python render loop copies these lines
// into the job log, so a clip that doesn't play shows its real error instead of silently looking like a graphic.
export const mediaError = (src: string) => (e: any) => {
  const el = e?.currentTarget ?? e?.target; const me = el?.error;
  console.error(`[VS-MEDIA-ERROR] ${src}: ${me ? `MediaError code ${me.code} ${me.message || ""}` : (e?.message || String(e))}`);
};

// a video background, optionally fitted to its slot (beat editing): rate = playback speed (default 0.85), start = seconds
// into the source, freezeAt = hold the frame shown at that many seconds, loop = repeat every that many seconds
const Vid: React.FC<{ bg: any; style: React.CSSProperties }> = ({ bg, style }) => {
  const f = useCurrentFrame(); const { fps } = useVideoConfig();
  const VideoComponent = bg.decoder === "browser" ? Html5Video : OffthreadVideo;
  const v = <VideoComponent src={asset(bg.src)} muted playbackRate={bg.rate ?? 0.85} trimBefore={bg.start ? Math.round(bg.start * fps) : undefined} style={style}
    {...({ onError: mediaError(bg.src) } as any)} />;
  if (bg.loop) return <Loop durationInFrames={Math.max(1, Math.round(bg.loop * fps))} layout="none">{v}</Loop>;
  if (bg.freezeAt != null) { const n = Math.max(0, Math.round(bg.freezeAt * fps) - 1); if (f > n) return <Freeze frame={n}>{v}</Freeze>; }
  return v;
};

const ShotInner: React.FC<{ bg: Bg; dur: number; seed: number }> = ({ bg, dur, seed }) => {
  const f = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const tall = height > width;
  const t = f / fps;
  const p = Math.min(1, t / Math.max(dur, 0.1));
  const ease = p < 0.5 ? 2 * p * p : 1 - Math.pow(-2 * p + 2, 2) / 2;
  // first shot of a beat cuts in hard (a fade there dips to black between beats); later shots crossfade over the previous one
  const fadeIn = bg.from === 0 || (bg as any).user ? 1 : interpolate(t, [0, 0.35], [0, 1], { extrapolateRight: "clamp" });   // your files: hard cuts
  // your own file (fit-and-render): shown as it is - no push-in, pan or zoom unless you asked for motion (still === false)
  const hold = !!(bg as any).user && (bg as any).still !== false;
  const zz = (a: number, b: number) => (hold ? 1 : interpolate(p, [0, 1], [a, b]));
  const shade = "linear-gradient(180deg, rgba(5,8,14,0.45) 0%, rgba(5,8,14,0) 18%, rgba(5,8,14,0) 62%, rgba(5,8,14,0.7) 100%)";
  if (bg.type === "graphic") {
    const k = bg.g.kind;
    if (k === "source_excerpt") {
      const g = bg.g;
      const child = { type: "graphic", from: 0, g: g.graphic } as Bg;
      if (g.graphic?.kind === "source_excerpt") return null;
      // The excerpt is visible ONCE for at most three seconds, then only our graphic continues.
      if (t >= Math.min(3, g.seconds)) return <ShotInner bg={child} dur={dur} seed={seed} />;
      return <AbsoluteFill style={{ background: "#091421" }}>
        <div style={{ position: "absolute", right: 0, top: tall ? "26%" : "18%", width: "52%", height: tall ? "43%" : "64%", overflow: "hidden" }}>
          <div style={{ width, height, transform: `scale(${tall ? 0.43 : 0.52})`, transformOrigin: "top left" }}>
            <ShotInner bg={child} dur={dur} seed={seed} />
          </div>
        </div>
        <div style={{ position: "absolute", left: "3%", top: "30%", width: "44%", height: "35%", background: "black", border: "3px solid #ffc83d" }}>
          {g.media === "clip" ? <Html5Video src={asset(g.src)} muted style={{ width: "100%", height: "100%", objectFit: "contain" }} onError={mediaError(g.src) as any} />
            : <Img src={asset(g.src)} style={{ width: "100%", height: "100%", objectFit: "contain" }} />}
        </div>
      </AbsoluteFill>;
    }
    if (k === "motion") return <MotionBackdrop g={bg.g} dur={dur} />;
    if (k === "map") return <MapBackdrop g={bg.g} dur={dur} />;
    if (k === "recon") return <ReconBackdrop g={bg.g} dur={dur} />;
    if (k === "illustration") return <IllustrationBackdrop g={bg.g} dur={dur} />;
    if (k === "silhouette") return <SilhouetteBackdrop g={bg.g} dur={dur} />;
    if (k === "sim") return <SimBackdrop g={bg.g} dur={dur} />;
    if (k === "simmap") return <SimMapBackdrop g={bg.g} dur={dur} />;
    if (k === "tpl") return <TemplateBackdrop g={bg.g} dur={dur} />;
    return <HeadlineBackdrop g={bg.g as any} dur={dur} />;
  }
  if (bg.type === "layers") return <LayersBackdrop layers={bg.layers} dur={dur} seed={seed} />;
  if (bg.type === "video" && bg.fit === "frame") {
    // landscape clip shown whole, over a blurred enlarged copy of itself
    const z = zz(1.0, 1.03);
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
    const z = zz(1.0, 1.04);   // gentle: every % of zoom softens the picture
    return (
      <AbsoluteFill style={{ opacity: fadeIn, overflow: "hidden" }}>
        <Vid bg={bg} style={{ width: "100%", height: "100%", objectFit: "cover", transform: `scale(${z})` }} />
        <AbsoluteFill style={{ background: shade }} />
      </AbsoluteFill>
    );
  }
  if (bg.type === "image" && bg.fit === "still") {
    // a slide (chart / card) that must stay readable: cover, a slow 3% push-in, no scrolling
    const z = zz(1.0, 1.03);
    return (
      <AbsoluteFill style={{ opacity: fadeIn, overflow: "hidden", background: "#0b0f17" }}>
        <Img src={asset(bg.src)} style={{ width: "100%", height: "100%", objectFit: "cover", transform: `scale(${z})` }} />
      </AbsoluteFill>
    );
  }
  if (bg.type === "image" && bg.fit === "frame") {
    // a real photo shown whole (sharp), over a blurred enlarged copy of itself, with a slow push-in; credit line at the bottom
    const z = zz(1.0, 1.07);
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
