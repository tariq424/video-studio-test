import React from "react";
import { AbsoluteFill, Img, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { C, HEAD, BODY } from "./theme";
import { Graphic } from "./types";

const useT = () => { const f = useCurrentFrame(); const { fps } = useVideoConfig(); return { f, fps, t: f / fps }; };
const pop = (f: number, fps: number, delay = 0) => spring({ frame: f - delay * fps, fps, config: { damping: 14, stiffness: 170, mass: 0.7 } });

const Card: React.FC<{ children: React.ReactNode; style?: React.CSSProperties }> = ({ children, style }) => (
  <div style={{ background: C.card, border: `2px solid ${C.line}`, borderRadius: 34, padding: "40px 44px", backdropFilter: "blur(6px)", boxShadow: "0 30px 80px rgba(0,0,0,0.45)", ...style }}>{children}</div>
);

// graphics live in the upper-middle band (y ≈ 330–1080); captions sit below
const Band: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <AbsoluteFill style={{ top: 170, height: 760, bottom: "auto", alignItems: "center", justifyContent: "center", padding: "0 70px" }}>
    <div style={{ transform: "scale(0.72)", transformOrigin: "center top" }}>{children}</div>
  </AbsoluteFill>
);

const Hook: React.FC<{ lines: string[]; accent?: number }> = ({ lines, accent = -1 }) => {
  const { f, fps } = useT();
  return (
    <Band>
      <div style={{ textAlign: "center" }}>
        {lines.map((l, i) => {
          const s = pop(f, fps, 0.18 * i);
          return (
            <div key={i} style={{ fontFamily: HEAD, fontWeight: 900, fontSize: i === accent ? 118 : 92, lineHeight: 1.05, color: i === accent ? C.gold : C.text,
              transform: `translateY(${(1 - s) * 60}px) scale(${0.85 + 0.15 * s})`, opacity: s, textShadow: "0 8px 30px rgba(0,0,0,0.7)", letterSpacing: -1 }}>{l}</div>
          );
        })}
      </div>
    </Band>
  );
};

const Quote: React.FC<{ text: string; who: string }> = ({ text, who }) => {
  const { f, fps, t } = useT();
  const s = pop(f, fps);
  const words = text.split(" ");
  const shown = Math.floor(interpolate(t, [0.2, 0.2 + words.length * 0.09], [0, words.length], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }));
  return (
    <Band>
      <Card style={{ transform: `scale(${0.9 + 0.1 * s})`, opacity: s, width: 900 }}>
        <div style={{ fontFamily: HEAD, fontWeight: 900, fontSize: 150, color: C.gold, lineHeight: 0.6, height: 70 }}>“</div>
        <div style={{ fontFamily: HEAD, fontWeight: 800, fontSize: 60, lineHeight: 1.2, color: C.text }}>
          {words.map((w, i) => <span key={i} style={{ opacity: i < shown ? 1 : 0.12 }}>{w} </span>)}
        </div>
        <div style={{ marginTop: 26, display: "inline-block", fontFamily: BODY, fontWeight: 800, fontSize: 34, color: "#111", background: C.gold, borderRadius: 999, padding: "10px 24px",
          opacity: interpolate(t, [0.6, 0.9], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }) }}>— {who}</div>
      </Card>
    </Band>
  );
};

const Compare: React.FC<Extract<Graphic, { kind: "compare" }>> = ({ left, right, badge, note }) => {
  const { f, fps } = useT();
  const a = pop(f, fps, 0), b = pop(f, fps, 0.35), c = pop(f, fps, 0.7);
  const panel = (p: typeof left, s: number, from: number, col: string) => (
    <Card style={{ width: 430, minHeight: 470, textAlign: "center", transform: `translateX(${(1 - s) * from}px)`, opacity: s, borderColor: col, padding: "38px 26px" }}>
      <div style={{ fontSize: 120, lineHeight: 1.1 }}>{p.icon}</div>
      <div style={{ fontFamily: HEAD, fontWeight: 900, fontSize: 52, color: col, marginTop: 10, lineHeight: 1.1 }}>{p.head}</div>
      <div style={{ fontFamily: BODY, fontWeight: 600, fontSize: 34, color: C.mut, marginTop: 14, lineHeight: 1.3 }}>{p.body}</div>
    </Card>
  );
  return (
    <Band>
      <div style={{ display: "flex", gap: 40, alignItems: "center", position: "relative" }}>
        {panel(left, a, -300, C.red)}
        {panel(right, b, 300, C.teal)}
        <div style={{ position: "absolute", left: "50%", top: "50%", transform: `translate(-50%,-50%) scale(${c})`, width: 130, height: 130, borderRadius: 999, background: C.gold,
          color: "#111", fontFamily: HEAD, fontWeight: 900, fontSize: badge.length > 2 ? 44 : 70, display: "flex", alignItems: "center", justifyContent: "center", boxShadow: "0 10px 40px rgba(0,0,0,0.5)" }}>{badge}</div>
      </div>
      {note && <div style={{ position: "absolute", bottom: 10, fontFamily: BODY, fontWeight: 600, fontSize: 30, color: C.mut, opacity: c }}>{note}</div>}
    </Band>
  );
};

const Stat: React.FC<Extract<Graphic, { kind: "stat" }>> = ({ value, decimals = 0, prefix = "", suffix, label, sub }) => {
  const { f, fps, t } = useT();
  const s = pop(f, fps);
  const k = interpolate(t, [0.1, 1.3], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const eased = 1 - Math.pow(1 - k, 3);
  const n = (value * eased).toFixed(decimals);
  return (
    <Band>
      <div style={{ textAlign: "center", transform: `scale(${0.8 + 0.2 * s})`, opacity: s }}>
        <div style={{ fontFamily: HEAD, fontWeight: 900, fontSize: 270, lineHeight: 1, color: C.gold, textShadow: "0 12px 50px rgba(0,0,0,0.7)", letterSpacing: -6 }}>{prefix}{n}{suffix}</div>
        <div style={{ fontFamily: HEAD, fontWeight: 900, fontSize: 64, color: C.text, marginTop: 10, textShadow: "0 6px 24px rgba(0,0,0,0.8)" }}>{label}</div>
        {sub && <div style={{ fontFamily: BODY, fontWeight: 600, fontSize: 38, color: C.mut, marginTop: 18, opacity: interpolate(t, [1.0, 1.4], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }) }}>{sub}</div>}
      </div>
    </Band>
  );
};

const Icons: React.FC<Extract<Graphic, { kind: "icons" }>> = ({ title, items }) => {
  const { f, fps } = useT();
  return (
    <Band>
      <Card style={{ width: 900, opacity: pop(f, fps) }}>
        <div style={{ fontFamily: HEAD, fontWeight: 900, fontSize: 52, color: C.gold, marginBottom: 22 }}>{title}</div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 22 }}>
          {items.map((it, i) => { const s = pop(f, fps, 0.25 + 0.2 * i); return (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 18, transform: `scale(${0.6 + 0.4 * s})`, opacity: s }}>
              <div style={{ fontSize: 86 }}>{it.icon}</div>
              <div style={{ fontFamily: HEAD, fontWeight: 800, fontSize: 44, color: C.text }}>{it.label}</div>
            </div>); })}
        </div>
      </Card>
    </Band>
  );
};

const Timeline: React.FC<Extract<Graphic, { kind: "timeline" }>> = ({ title, steps }) => {
  const { f, fps, t } = useT();
  const draw = interpolate(t, [0.2, 1.6], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <Band>
      <div style={{ width: 920, textAlign: "center", opacity: pop(f, fps) }}>
        <div style={{ fontFamily: HEAD, fontWeight: 900, fontSize: 60, color: C.text, marginBottom: 70, textShadow: "0 6px 24px rgba(0,0,0,0.8)" }}>{title}</div>
        <div style={{ position: "relative", height: 260 }}>
          <div style={{ position: "absolute", top: 40, left: 60, height: 10, borderRadius: 10, width: 800 * draw, background: `linear-gradient(90deg, ${C.teal}, ${C.gold}, ${C.red})` }} />
          {steps.map((s, i) => { const x = 60 + (800 * i) / (steps.length - 1); const on = draw * (steps.length - 1) >= i - 0.02; const sp = pop(f, fps, 0.3 + 0.5 * i);
            return (
              <div key={i} style={{ position: "absolute", left: x - 150, width: 300, top: 0, opacity: on ? 1 : 0.15 }}>
                <div style={{ margin: "0 auto", width: 90, height: 90, borderRadius: 99, background: [C.teal, C.gold, C.red][i % 3], transform: `scale(${sp})`, boxShadow: "0 0 40px rgba(255,200,61,0.5)" }} />
                <div style={{ fontFamily: HEAD, fontWeight: 900, fontSize: 44, color: C.text, marginTop: 22 }}>{s.when}</div>
                <div style={{ fontFamily: BODY, fontWeight: 600, fontSize: 32, color: C.mut, marginTop: 6 }}>{s.label}</div>
              </div>); })}
        </div>
      </div>
    </Band>
  );
};

const CTA: React.FC<Extract<Graphic, { kind: "cta" }>> = ({ thumb, title, line, badge, play = true, arrow = true }) => {
  const { f, fps, t } = useT();
  const s = pop(f, fps);
  const bob = Math.sin(t * 5) * 14;
  return (
    <Band>
      <div style={{ textAlign: "center", transform: `scale(${0.85 + 0.15 * s})`, opacity: s }}>
        {badge ? <div style={{ fontFamily: BODY, fontWeight: 800, fontSize: 36, color: "#111", background: C.gold, display: "inline-block", borderRadius: 999, padding: "10px 28px", marginBottom: 26 }}>{badge}</div> : null}
        <div style={{ position: "relative", width: 900, height: thumb || play ? 506 : 260, borderRadius: 28, overflow: "hidden", border: `4px solid ${C.gold}`, boxShadow: "0 30px 90px rgba(0,0,0,0.6)",
          background: `linear-gradient(135deg, #16213a 0%, #0b0f17 60%, #2a1d05 100%)` }}>
          {thumb ? <Img src={staticFile(thumb)} style={{ width: "100%", height: "100%", objectFit: "cover" }} /> : null}
          <AbsoluteFill style={{ background: "linear-gradient(180deg, rgba(0,0,0,0) 30%, rgba(0,0,0,0.85) 100%)" }} />
          {play ? <div style={{ position: "absolute", left: "50%", top: "42%", transform: "translate(-50%,-50%)", width: 150, height: 150, borderRadius: 99, background: C.red, display: "flex", alignItems: "center", justifyContent: "center" }}>
            <div style={{ width: 0, height: 0, borderTop: "34px solid transparent", borderBottom: "34px solid transparent", borderLeft: `56px solid white`, marginLeft: 12 }} />
          </div> : null}
          <div style={{ position: "absolute", bottom: 26, left: 30, right: 30, fontFamily: HEAD, fontWeight: 900, fontSize: 46, color: C.text, textAlign: "left", lineHeight: 1.1 }}>{title}</div>
        </div>
        <div style={{ fontFamily: HEAD, fontWeight: 900, fontSize: 56, color: C.text, marginTop: 34 }}>{line}</div>
        {arrow ? <div style={{ fontSize: 110, color: C.gold, transform: `translateY(${bob}px)`, marginTop: 6, fontFamily: HEAD, fontWeight: 900 }}>↓</div> : null}
      </div>
    </Band>
  );
};

export const GraphicView: React.FC<{ g: Graphic }> = ({ g }) => {
  switch (g.kind) {
    case "hook": return <Hook lines={g.lines} accent={g.accent} />;
    case "quote": return <Quote text={g.text} who={g.who} />;
    case "compare": return <Compare {...g} />;
    case "stat": return <Stat {...g} />;
    case "icons": return <Icons {...g} />;
    case "timeline": return <Timeline {...g} />;
    case "cta": return <CTA {...g} />;
  }
};
