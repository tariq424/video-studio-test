// Visual ladder v2, rung 5: "Remotion graphics" - eight parameterised full-screen compositions for beats that stock, photos, cloud
// and WanGP didn't cover (app/studio/graphics.py picks one and fills `d`). Rendered to a 6-10 s MP4 per beat through the
// ShotPreview composition; the GRAPHICS label is drawn by Shot (Shorts) or burned in at render time (explainers).
// Works in both frames: portrait 1080x1920 (Shorts) and landscape 1920x1080 (explainers).
import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig, Easing } from "remotion";
import { C, HEAD, BODY } from "./theme";
import { MapBackdrop, MapPoint } from "./Backdrops";

export type TplKind = "stat" | "quote" | "timeline" | "compare" | "route" | "chart" | "list" | "abstract";
export type Tpl = { kind: "tpl"; t: TplKind; d: any };

const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;
const BG = "linear-gradient(165deg, #0f1a2e 0%, #070a12 62%, #17110a 100%)";

const useT = () => {
  const f = useCurrentFrame(); const { fps, width, height } = useVideoConfig();
  return { f, fps, t: f / fps, W: width, H: height, tall: height > width };
};
const appear = (t: number, at: number, len = 0.45) => interpolate(t, [at, at + len], [0, 1], { ...clamp, easing: Easing.out(Easing.cubic) });

// slow drifting diagonal lines: the shared texture of every template (a design system, not a slideshow)
const Texture: React.FC<{ dur: number }> = ({ dur }) => {
  const { t } = useT();
  const x = interpolate(t, [0, Math.max(dur, 1)], [0, -180]);
  return <AbsoluteFill style={{ backgroundImage: "repeating-linear-gradient(135deg, rgba(255,255,255,0.035) 0 2px, transparent 2px 52px)", backgroundPosition: `${x}px 0` }} />;
};

const Kicker: React.FC<{ text?: string; o: number }> = ({ text, o }) => text ? (
  <div style={{ fontFamily: BODY, fontWeight: 800, fontSize: 32, letterSpacing: 2, color: "#111", background: C.gold, borderRadius: 999,
    padding: "8px 26px", opacity: o, alignSelf: "center", marginBottom: 30 }}>{String(text).toUpperCase().slice(0, 28)}</div>) : null;

// the middle band of the frame: Shorts keep the top (tag, progress bar) and bottom (captions) clear
const Band: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { tall } = useT();
  return <AbsoluteFill style={{ top: tall ? 400 : 120, bottom: tall ? 520 : 170, height: "auto", padding: tall ? "0 70px" : "0 180px",
    display: "flex", flexDirection: "column", justifyContent: "center", alignItems: "stretch" }}>{children}</AbsoluteFill>;
};

const fmtNum = (v: number, dec: number) => v.toLocaleString("en-US", { minimumFractionDigits: dec, maximumFractionDigits: dec });

// 1. stat card: big number counting up, label, optional context line
const Stat: React.FC<{ d: any; dur: number }> = ({ d, dur }) => {
  const { t, tall } = useT();
  const value = Number(d.value) || 0, dec = Math.max(0, Math.min(3, Number(d.decimals) || 0));
  const k = d.count === false ? 1 : interpolate(t, [0.3, Math.min(2.4, dur * 0.4)], [0, 1], { ...clamp, easing: Easing.out(Easing.cubic) });
  return (
    <Band>
      <Kicker text={d.kicker} o={appear(t, 0.1)} />
      <div style={{ textAlign: "center", fontFamily: HEAD, fontWeight: 900, whiteSpace: "nowrap", lineHeight: 1, color: C.gold,
        fontSize: Math.min(tall ? 210 : 230, Math.floor((tall ? 1500 : 2600) / Math.max(4, `${d.prefix || ""}${fmtNum(value, dec)}${d.suffix || ""}`.length))),
        opacity: appear(t, 0.2), textShadow: "0 12px 50px rgba(255,200,61,0.25)" }}>
        {d.prefix || ""}{fmtNum(value * k, dec)}{d.suffix || ""}
      </div>
      <div style={{ textAlign: "center", fontFamily: HEAD, fontWeight: 900, fontSize: tall ? 62 : 58, color: C.text, marginTop: 30, opacity: appear(t, 0.8) }}>{d.label}</div>
      {d.sub ? <div style={{ textAlign: "center", fontFamily: BODY, fontWeight: 600, fontSize: tall ? 36 : 34, color: C.mut, marginTop: 18, opacity: appear(t, 1.2) }}>{d.sub}</div> : null}
    </Band>
  );
};

// 2. quote card: words revealed in turn, attribution under a rule
const Quote: React.FC<{ d: any; dur: number }> = ({ d, dur }) => {
  const { t, tall } = useT();
  const words = String(d.text || "").split(/\s+/).filter(Boolean);
  const per = Math.min(0.22, Math.max(0.06, (dur * 0.45) / Math.max(words.length, 1)));
  return (
    <Band>
      <div style={{ fontFamily: HEAD, fontWeight: 900, fontSize: tall ? 220 : 200, color: C.gold, lineHeight: 0.6, opacity: appear(t, 0), height: tall ? 110 : 100 }}>“</div>
      <div style={{ fontFamily: HEAD, fontWeight: 800, fontSize: tall ? 64 : 60, lineHeight: 1.22, color: C.text }}>
        {words.map((w, i) => <span key={i} style={{ opacity: appear(t, 0.3 + i * per, 0.25) }}>{w} </span>)}
      </div>
      <div style={{ height: 4, background: C.gold, width: interpolate(t, [0.6, 1.4], [0, tall ? 220 : 300], clamp), marginTop: 40 }} />
      <div style={{ fontFamily: BODY, fontWeight: 800, fontSize: tall ? 38 : 36, color: C.mut, marginTop: 22, opacity: appear(t, 0.3 + words.length * per) }}>
        {d.who ? `— ${d.who}` : ""}{d.role ? <span style={{ fontWeight: 600 }}>{`, ${d.role}`}</span> : null}
      </div>
    </Band>
  );
};

// 3. timeline: a rule drawn across, markers popping in order (vertical in portrait)
const Timeline: React.FC<{ d: any; dur: number }> = ({ d, dur }) => {
  const { t, tall, fps, f } = useT();
  const steps: { when: string; label: string }[] = (d.steps || []).slice(0, 6);
  const n = Math.max(steps.length, 1);
  const span = Math.max(1.2, dur * 0.6);
  const draw = interpolate(t, [0.4, 0.4 + span], [0, 1], { ...clamp, easing: Easing.inOut(Easing.cubic) });
  return (
    <Band>
      {d.title ? <div style={{ fontFamily: HEAD, fontWeight: 900, fontSize: tall ? 58 : 54, color: C.text, textAlign: "center", marginBottom: tall ? 50 : 70, opacity: appear(t, 0.1) }}>{d.title}</div> : null}
      <div style={{ position: "relative", height: tall ? 860 : 330 }}>
        {tall
          ? <div style={{ position: "absolute", left: 120, top: 0, width: 6, height: `${draw * 100}%`, background: C.gold, borderRadius: 3 }} />
          : <div style={{ position: "absolute", top: 120, left: 0, height: 6, width: `${draw * 100}%`, background: C.gold, borderRadius: 3 }} />}
        {steps.map((s, i) => {
          const at = (i + 0.5) / n; const on = draw >= at;
          const pop = on ? spring({ frame: f - Math.round((0.4 + at * span) * fps), fps, config: { damping: 12 } }) : 0;
          const pos = `${at * 100}%`;
          return (
            <div key={i} style={tall
              ? { position: "absolute", top: pos, left: 0, right: 0, transform: "translateY(-50%)", display: "flex", alignItems: "center", opacity: on ? 1 : 0.15 }
              : { position: "absolute", left: pos, top: 0, width: `${88 / n}%`, transform: "translateX(-50%)", textAlign: "center", opacity: on ? 1 : 0.15 }}>
              {tall ? <>
                <div style={{ width: 246, display: "flex", justifyContent: "center" }}><div style={{ width: 44, height: 44, borderRadius: 22, background: C.gold, border: "8px solid #0b0f17", transform: `scale(${0.4 + 0.6 * pop})` }} /></div>
                <div><div style={{ fontFamily: HEAD, fontWeight: 900, fontSize: 46, color: C.gold }}>{s.when}</div>
                  <div style={{ fontFamily: BODY, fontWeight: 700, fontSize: 38, color: C.text, marginTop: 6 }}>{s.label}</div></div>
              </> : <>
                <div style={{ fontFamily: HEAD, fontWeight: 900, fontSize: 44, color: C.gold, height: 80 }}>{s.when}</div>
                <div style={{ width: 44, height: 44, borderRadius: 22, background: C.gold, border: "8px solid #0b0f17", margin: "18px auto 0", transform: `scale(${0.4 + 0.6 * pop})` }} />
                <div style={{ fontFamily: BODY, fontWeight: 700, fontSize: 34, color: C.text, marginTop: 30 }}>{s.label}</div>
              </>}
            </div>
          );
        })}
      </div>
    </Band>
  );
};

// 4. comparison: two panels sliding in from opposite sides, a badge between them (stacked in portrait)
const Compare: React.FC<{ d: any; dur: number }> = ({ d }) => {
  const { t, tall } = useT();
  const side = (p: any, i: number) => {
    const k = appear(t, 0.2 + i * 0.35, 0.6);
    const off = (1 - k) * (i ? 1 : -1) * 260;
    const acc = i ? C.teal : C.gold;
    return (
      <div style={{ flex: 1, background: C.card, border: `2px solid ${C.line}`, borderTop: `8px solid ${acc}`, borderRadius: 28, padding: tall ? "40px 44px" : "50px 50px",
        transform: tall ? `translateY(${off * 0.5}px)` : `translateX(${off}px)`, opacity: k, textAlign: "center" }}>
        {p?.icon ? <div style={{ fontSize: tall ? 90 : 100 }}>{p.icon}</div> : null}
        <div style={{ fontFamily: HEAD, fontWeight: 900, fontSize: tall ? 60 : 62, color: acc, marginTop: 10 }}>{p?.head}</div>
        {p?.value ? <div style={{ fontFamily: HEAD, fontWeight: 900, fontSize: tall ? 90 : 96, color: C.text, marginTop: 8 }}>{p.value}</div> : null}
        <div style={{ fontFamily: BODY, fontWeight: 600, fontSize: tall ? 36 : 36, color: C.mut, marginTop: 14 }}>{p?.body}</div>
      </div>
    );
  };
  return (
    <Band>
      {d.title ? <div style={{ fontFamily: HEAD, fontWeight: 900, fontSize: tall ? 56 : 54, color: C.text, textAlign: "center", marginBottom: 40, opacity: appear(t, 0) }}>{d.title}</div> : null}
      <div style={{ display: "flex", flexDirection: tall ? "column" : "row", gap: tall ? 30 : 60, alignItems: "stretch", position: "relative" }}>
        {side(d.left, 0)}
        <div style={{ position: "absolute", left: "50%", top: "50%", transform: `translate(-50%,-50%) scale(${appear(t, 0.9, 0.3)})`, zIndex: 2,
          fontFamily: HEAD, fontWeight: 900, fontSize: 44, color: "#111", background: C.text, borderRadius: 999, padding: "16px 26px" }}>{(d.badge || "VS").toUpperCase()}</div>
        {side(d.right, 1)}
      </div>
      {d.note ? <div style={{ fontFamily: BODY, fontWeight: 600, fontSize: 28, color: C.mut, textAlign: "center", marginTop: 30, opacity: appear(t, 1.4) }}>{d.note}</div> : null}
    </Band>
  );
};

// 5. map with route: the existing route map (origin -> stops -> actual / planned)
const Route: React.FC<{ d: any; dur: number }> = ({ d, dur }) => {
  const pts: MapPoint[] = (d.points || []).filter((p: any) => isFinite(+p.lat) && isFinite(+p.lon)).map((p: any) => ({ ...p, lat: +p.lat, lon: +p.lon }));
  return <MapBackdrop g={{ kind: "map", title: d.title, points: pts }} dur={dur} />;
};

// 6. chart: bars growing or a line drawing itself, values from the narration
const Chart: React.FC<{ d: any; dur: number }> = ({ d, dur }) => {
  const { t, tall, W } = useT();
  const pts: { label: string; value: number }[] = (d.points || []).map((p: any) => ({ label: String(p.label ?? ""), value: Number(p.value) || 0 })).slice(0, 8);
  const n = Math.max(pts.length, 1); const vmax = Math.max(...pts.map((p) => p.value), 0) || 1; const vmin = Math.min(0, ...pts.map((p) => p.value));
  const box = tall ? { x: 90, y: 70, w: W - 180, h: 700 } : { x: 60, y: 60, w: W - 480, h: 520 };   // y: room for the top bar's value
  const Y = (v: number) => box.y + box.h - ((v - vmin) / (vmax - vmin || 1)) * box.h;
  const grow = interpolate(t, [0.5, Math.max(1.6, dur * 0.55)], [0, 1], { ...clamp, easing: Easing.out(Easing.cubic) });
  const unit = d.unit ? ` ${d.unit}` : "";
  const fmt = (v: number) => `${d.prefix || ""}${fmtNum(v, Number(d.decimals) || 0)}${d.suffix || ""}${unit}`;
  const line = d.style === "line";
  const X = (i: number) => box.x + (i + 0.5) * (box.w / n);
  const path = pts.map((p, i) => `${i ? "L" : "M"}${X(i)},${Y(p.value)}`).join(" ");
  return (
    <Band>
      {d.title ? <div style={{ fontFamily: HEAD, fontWeight: 900, fontSize: tall ? 56 : 52, color: C.text, textAlign: "center", marginBottom: 40, opacity: appear(t, 0) }}>{d.title}</div> : null}
      <svg width={box.w + box.x * 2} height={box.h + 90} style={{ alignSelf: "center", overflow: "visible" }}>
        <line x1={box.x} x2={box.x + box.w} y1={Y(0)} y2={Y(0)} stroke={C.line} strokeWidth={3} />
        {line ? <>
          <path d={path} fill="none" stroke={C.teal} strokeWidth={8} strokeLinejoin="round" strokeLinecap="round" pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - grow} />
          {pts.map((p, i) => (grow * n >= i + 0.5) ? <g key={i}><circle cx={X(i)} cy={Y(p.value)} r={12} fill={C.gold} />
            <text x={X(i)} y={Y(p.value) - 26} textAnchor="middle" fill={C.text} fontFamily={HEAD} fontWeight={900} fontSize={tall ? 32 : 30}>{fmt(p.value)}</text></g> : null)}
        </> : pts.map((p, i) => {
          const bw = (box.w / n) * 0.62; const k = Math.min(1, Math.max(0, grow * 1.3 - i * (0.3 / n)));
          const top = Y(vmin + (p.value - vmin) * k);
          return <g key={i}><rect x={X(i) - bw / 2} y={Math.min(top, Y(0))} width={bw} height={Math.abs(Y(0) - top)} rx={10} fill={p.value === vmax ? C.gold : C.teal} />
            <text x={X(i)} y={top - 22} textAnchor="middle" fill={C.text} fontFamily={HEAD} fontWeight={900} fontSize={tall ? 34 : 32} opacity={k}>{fmt(p.value * k)}</text></g>;
        })}
        {pts.map((p, i) => <text key={"l" + i} x={X(i)} y={box.y + box.h + 56} textAnchor="middle" fill={C.mut} fontFamily={BODY} fontWeight={700} fontSize={tall ? 30 : 28}>{p.label.slice(0, 14)}</text>)}
      </svg>
      {d.source ? <div style={{ fontFamily: BODY, fontWeight: 600, fontSize: 26, color: C.mut, textAlign: "center", marginTop: 20 }}>{d.source}</div> : null}
    </Band>
  );
};

// 7. list / stacked cards: items arriving in sequence
const List: React.FC<{ d: any; dur: number }> = ({ d, dur }) => {
  const { t, tall } = useT();
  const items: { icon?: string; text: string }[] = (d.items || []).map((x: any) => typeof x === "string" ? { text: x } : x).slice(0, 5);
  const gap = Math.min(0.9, Math.max(0.35, (dur * 0.55) / Math.max(items.length, 1)));
  return (
    <Band>
      {d.title ? <div style={{ fontFamily: HEAD, fontWeight: 900, fontSize: tall ? 58 : 54, color: C.text, textAlign: "center", marginBottom: 40, opacity: appear(t, 0) }}>{d.title}</div> : null}
      {items.map((it, i) => {
        const k = appear(t, 0.35 + i * gap, 0.5);
        return (
          <div key={i} style={{ display: "flex", alignItems: "center", gap: 28, background: C.card, border: `2px solid ${C.line}`, borderLeft: `10px solid ${i % 2 ? C.teal : C.gold}`,
            borderRadius: 22, padding: tall ? "26px 34px" : "24px 40px", marginBottom: 22, opacity: k, transform: `translateX(${(1 - k) * 120}px)` }}>
            <div style={{ fontFamily: HEAD, fontWeight: 900, fontSize: tall ? 54 : 48, color: i % 2 ? C.teal : C.gold, minWidth: 70, textAlign: "center" }}>{it.icon || i + 1}</div>
            <div style={{ fontFamily: BODY, fontWeight: 700, fontSize: tall ? 42 : 40, color: C.text, lineHeight: 1.2 }}>{it.text}</div>
          </div>
        );
      })}
    </Band>
  );
};

// 8. abstract motion: a slow gradient field with drifting particles behind one line of text
const Abstract: React.FC<{ d: any; dur: number }> = ({ d, dur }) => {
  const { t, W, H, tall } = useT();
  const N = 46; const seed = (i: number) => { const x = Math.sin(i * 12.9898 + 78.233) * 43758.5453; return x - Math.floor(x); };
  const hue = interpolate(t, [0, Math.max(dur, 1)], [0, 40]);
  return (
    <AbsoluteFill style={{ background: `radial-gradient(ellipse at ${30 + 40 * Math.sin(t * 0.25)}% ${40 + 20 * Math.cos(t * 0.2)}%, hsl(${215 + hue},55%,22%) 0%, #070a12 70%)` }}>
      <svg width={W} height={H} style={{ position: "absolute", inset: 0 }}>
        {Array.from({ length: N }, (_, i) => {
          const x = (seed(i) * W + t * (12 + seed(i + 7) * 30)) % W; const y = (seed(i + 3) * H - t * (8 + seed(i + 11) * 22) + H) % H;
          const r = 2 + seed(i + 5) * 7;
          return <circle key={i} cx={x} cy={y} r={r} fill={i % 5 ? "rgba(255,255,255,0.18)" : "rgba(255,200,61,0.45)"} />;
        })}
      </svg>
      <Band>
        <Kicker text={d.kicker} o={appear(t, 0.2)} />
        <div style={{ fontFamily: HEAD, fontWeight: 900, fontSize: tall ? 74 : 72, lineHeight: 1.14, color: C.text, textAlign: "center", opacity: appear(t, 0.4, 0.8),
          transform: `translateY(${(1 - appear(t, 0.4, 0.8)) * 30}px)` }}>{d.text}</div>
        {d.sub ? <div style={{ fontFamily: BODY, fontWeight: 600, fontSize: tall ? 38 : 36, color: C.mut, textAlign: "center", marginTop: 24, opacity: appear(t, 1.1) }}>{d.sub}</div> : null}
      </Band>
    </AbsoluteFill>
  );
};

export const TemplateBackdrop: React.FC<{ g: Tpl; dur: number }> = ({ g, dur }) => {
  const d = g.d || {};
  if (g.t === "route") return <Route d={d} dur={dur} />;
  if (g.t === "abstract") return <Abstract d={d} dur={dur} />;
  const body = g.t === "stat" ? <Stat d={d} dur={dur} /> : g.t === "quote" ? <Quote d={d} dur={dur} /> : g.t === "timeline" ? <Timeline d={d} dur={dur} />
    : g.t === "compare" ? <Compare d={d} dur={dur} /> : g.t === "chart" ? <Chart d={d} dur={dur} /> : <List d={d} dur={dur} />;
  return <AbsoluteFill style={{ background: BG }}><Texture dur={dur} />{body}</AbsoluteFill>;
};
