// Data / physics simulation for a beat (app/studio/physics.py): an animated profile (altitude, depth...) drawn over the beat's
// length, the subject riding the curve, a live readout and event marks. The time series is compressed into the shot.
import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { C, HEAD, BODY } from "./theme";

export type Sim = { kind: "sim"; module: string; title: string; unit: string; series: [number, number][]; icon?: string; label?: string;
  notes?: string; marks?: { t: number; text: string }[] };

export const SimBackdrop: React.FC<{ g: Sim; dur: number }> = ({ g, dur }) => {
  const f = useCurrentFrame(); const { fps, width: W, height: H } = useVideoConfig(); const t = f / fps; const tall = H > W;
  const s = g.series; const T = s[s.length - 1][0] || 1;
  const p = Math.min(1, Math.max(0, (t - 0.4) / Math.max(0.5, dur - 1.2)));   // series time shown so far (0..1)
  const tNow = p * T;
  const vs = s.map((x) => x[1]); const vmin = Math.min(...vs), vmax = Math.max(...vs); const span = vmax - vmin || 1;
  const box = tall ? { x: 160, y: 520, w: W - 250, h: 760 } : { x: 160, y: 200, w: W - 320, h: H - 420 };
  const X = (tt: number) => box.x + (tt / T) * box.w, Y = (v: number) => box.y + box.h - ((v - vmin) / span) * box.h;
  const shown = s.filter((x) => x[0] <= tNow);
  const cur = (() => { const i = s.findIndex((x) => x[0] > tNow); if (i <= 0) return s[i === 0 ? 0 : s.length - 1];
    const a = s[i - 1], b = s[i]; const k = (tNow - a[0]) / (b[0] - a[0] || 1); return [tNow, a[1] + (b[1] - a[1]) * k] as [number, number]; })();
  const path = shown.map((x, i) => `${i ? "L" : "M"}${X(x[0]).toFixed(1)},${Y(x[1]).toFixed(1)}`).join(" ") + ` L${X(cur[0]).toFixed(1)},${Y(cur[1]).toFixed(1)}`;
  const ang = (() => { const i = Math.max(1, s.findIndex((x) => x[0] > tNow)); const a = s[i - 1], b = s[Math.min(i, s.length - 1)];
    return (Math.atan2(-(Y(b[1]) - Y(a[1])), X(b[0]) - X(a[0])) * -180) / Math.PI; })();
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((k) => vmin + span * k);
  const fmt = (v: number) => `${Math.round(v).toLocaleString("en-US")} ${g.unit}`;
  return (
    <AbsoluteFill style={{ background: "linear-gradient(170deg, #0d1626 0%, #070a12 70%)" }}>
      <div style={{ position: "absolute", top: tall ? 330 : 60, left: 0, right: 0, textAlign: "center", fontFamily: HEAD, fontWeight: 900, fontSize: tall ? 56 : 46, color: C.text }}>{g.title}</div>
      {g.label ? <div style={{ position: "absolute", top: tall ? 410 : 122, left: 0, right: 0, textAlign: "center", fontFamily: BODY, fontWeight: 600, fontSize: tall ? 30 : 26, color: C.mut }}>{g.label}</div> : null}
      <svg width={W} height={H} style={{ position: "absolute", inset: 0 }}>
        {ticks.map((v, i) => <g key={i}><line x1={box.x} x2={box.x + box.w} y1={Y(v)} y2={Y(v)} stroke="rgba(255,255,255,0.1)" />
          <text x={box.x - 12} y={Y(v) + 8} fill="rgba(255,255,255,0.55)" fontSize={tall ? 24 : 20} textAnchor="end" fontFamily="Inter">{Math.round(v).toLocaleString("en-US")}</text></g>)}
        {(g.marks || []).map((m, i) => <g key={"m" + i} opacity={tNow >= m.t ? 1 : 0.25}><line x1={X(m.t)} x2={X(m.t)} y1={box.y} y2={box.y + box.h} stroke={C.gold} strokeDasharray="8 8" />
          <text x={X(m.t) + 10} y={box.y + 30 + i * 34} fill={C.gold} fontSize={tall ? 24 : 21} fontFamily="Inter" fontWeight={700}>{m.text}</text></g>)}
        <path d={path} fill="none" stroke={C.teal} strokeWidth={6} strokeLinejoin="round" />
        <g transform={`translate(${X(cur[0])},${Y(cur[1])}) rotate(${-ang})`}>
          {g.icon === "sub"
            ? <g fill="#f2c94c"><ellipse cx={0} cy={0} rx={46} ry={16} /><rect x={-8} y={-30} width={22} height={18} rx={4} /></g>
            : <g fill="#ffffff"><path d="M48,0 C40,-6 20,-7 -30,-6 L-44,-24 L-52,-24 L-44,-4 L-48,0 L-44,4 L-52,24 L-44,24 L-30,6 C20,7 40,6 48,0 Z" />
                <path d="M6,-4 L-22,-34 L-12,-34 L22,-4 Z M6,4 L-22,34 L-12,34 L22,4 Z" /></g>}
        </g>
      </svg>
      <div style={{ position: "absolute", right: tall ? 90 : 160, top: tall ? 1300 : H - 200, fontFamily: HEAD, fontWeight: 900, fontSize: tall ? 64 : 52, color: C.gold }}>{fmt(cur[1])}</div>
      {g.notes ? <div style={{ position: "absolute", left: tall ? 90 : 160, top: tall ? 1310 : H - 188, fontFamily: BODY, fontWeight: 600, fontSize: tall ? 26 : 22, color: C.mut, maxWidth: tall ? 520 : 900 }}>{g.notes}</div> : null}
    </AbsoluteFill>
  );
};
