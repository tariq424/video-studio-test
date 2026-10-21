// Data / physics simulation for a beat (app/studio/physics.py): an animated profile (altitude, depth...) drawn over the beat's
// length, the subject riding the curve, a live readout and event marks. The time series is compressed into the shot.
import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig, Easing } from "remotion";
import { C, HEAD, BODY } from "./theme";
import { geoMercator, geoPath } from "d3-geo";
import { feature } from "topojson-client";
import world from "world-atlas/countries-50m.json";
import { LiveryAirliner, Livery } from "./Aircraft";

// Altimeter (aircraft_flight): long needle = hundreds of feet (one turn per 1,000 ft), short = thousands (one turn per 10,000 ft),
// thin = ten-thousands; the drum below shows the exact altitude. Moves with the simulated altitude, frame by frame.
const Altimeter: React.FC<{ cx: number; cy: number; r: number; ft: number }> = ({ cx, cy, r, ft }) => {
  const a = (v: number, per: number) => ((((v % per) + per) % per) / per) * 360;
  const hand = (deg: number, len: number, w: number, col: string) =>
    <g transform={`rotate(${deg} ${cx} ${cy})`}><path d={`M${cx - w / 2},${cy + r * 0.12} L${cx},${cy - len} L${cx + w / 2},${cy + r * 0.12} Z`} fill={col} /></g>;
  return (
    <g>
      <circle cx={cx} cy={cy} r={r + 10} fill="#1b2233" stroke="#3a4560" strokeWidth={4} />
      <circle cx={cx} cy={cy} r={r} fill="#05070c" />
      {Array.from({ length: 50 }, (_, i) => { const big = i % 5 === 0, t = (i / 50) * 2 * Math.PI;
        return <line key={i} x1={cx + Math.sin(t) * r * (big ? 0.8 : 0.88)} y1={cy - Math.cos(t) * r * (big ? 0.8 : 0.88)} x2={cx + Math.sin(t) * r * 0.96} y2={cy - Math.cos(t) * r * 0.96}
          stroke="#e8edf5" strokeWidth={big ? 4 : 2} />; })}
      {Array.from({ length: 10 }, (_, i) => { const t = (i / 10) * 2 * Math.PI;
        return <text key={"n" + i} x={cx + Math.sin(t) * r * 0.64} y={cy - Math.cos(t) * r * 0.64 + r * 0.09} fill="#e8edf5" fontSize={r * 0.24} fontFamily="Inter" fontWeight={700} textAnchor="middle">{i}</text>; })}
      <text x={cx} y={cy - r * 0.28} fill="#8b949e" fontSize={r * 0.13} fontFamily="Inter" fontWeight={700} textAnchor="middle">ALT</text>
      <rect x={cx - r * 0.42} y={cy + r * 0.2} width={r * 0.84} height={r * 0.26} rx={6} fill="#11161f" stroke="#3a4560" />
      <text x={cx} y={cy + r * 0.4} fill="#ffc83d" fontSize={r * 0.2} fontFamily="Inter" fontWeight={800} textAnchor="middle">{Math.round(Math.max(0, ft)).toLocaleString("en-US")}</text>
      {hand(a(ft, 100000), r * 0.88, 3, "#9aa4b2")}
      {hand(a(ft, 10000), r * 0.5, 14, "#e8edf5")}
      {hand(a(ft, 1000), r * 0.86, 8, "#ffffff")}
      <circle cx={cx} cy={cy} r={r * 0.07} fill="#c9d1db" />
    </g>
  );
};

export type Sim = { kind: "sim"; module: string; title: string; unit: string; series: [number, number][]; icon?: string; label?: string;
  notes?: string; marks?: { t: number; text: string }[]; livery?: Livery | null };

export const SimBackdrop: React.FC<{ g: Sim; dur: number }> = ({ g, dur }) => {
  const f = useCurrentFrame(); const { fps, width: W, height: H } = useVideoConfig(); const t = f / fps; const tall = H > W;
  const s = g.series; const T = s[s.length - 1][0] || 1;
  const p = Math.min(1, Math.max(0, (t - 0.4) / Math.max(0.5, dur - 1.2)));   // series time shown so far (0..1)
  const tNow = p * T;
  const vs = s.map((x) => x[1]); const vmin = Math.min(...vs), vmax = Math.max(...vs); const span = vmax - vmin || 1;
  const air = g.module === "aircraft_flight";   // side-view airliner in the airline's livery + an altimeter (liveries.py)
  const box = air ? (tall ? { x: 150, y: 520, w: W - 230, h: 560 } : { x: 200, y: 250, w: W - 760, h: H - 520 })
    : tall ? { x: 160, y: 520, w: W - 250, h: 760 } : { x: 200, y: 250, w: W - 400, h: H - 520 };
  const X = (tt: number) => box.x + (tt / T) * box.w, Y = (v: number) => box.y + box.h - ((v - vmin) / span) * box.h;
  const shown = s.filter((x) => x[0] <= tNow);
  const cur = (() => { const i = s.findIndex((x) => x[0] > tNow); if (i <= 0) return s[i === 0 ? 0 : s.length - 1];
    const a = s[i - 1], b = s[i]; const k = (tNow - a[0]) / (b[0] - a[0] || 1); return [tNow, a[1] + (b[1] - a[1]) * k] as [number, number]; })();
  const path = shown.map((x, i) => `${i ? "L" : "M"}${X(x[0]).toFixed(1)},${Y(x[1]).toFixed(1)}`).join(" ") + ` L${X(cur[0]).toFixed(1)},${Y(cur[1]).toFixed(1)}`;
  const ang = (() => { const i = Math.max(1, s.findIndex((x) => x[0] > tNow)); const a = s[i - 1], b = s[Math.min(i, s.length - 1)];
    return (Math.atan2(-(Y(b[1]) - Y(a[1])), X(b[0]) - X(a[0])) * -180) / Math.PI; })();
  // aircraft pitch: follows the drawn curve (screen y grows downward, so a descent is a positive = clockwise = nose-down turn),
  // smoothed over a short window and capped at 28 deg so a steep-looking chart doesn't stand the jet on its nose
  const pitch = (() => { const dt = T * 0.03; const v = (tt: number) => { const i = s.findIndex((x) => x[0] > tt); if (i <= 0) return s[i === 0 ? 0 : s.length - 1][1];
      const a = s[i - 1], b = s[i]; return a[1] + (b[1] - a[1]) * ((tt - a[0]) / (b[0] - a[0] || 1)); };
    const t0 = Math.max(0, tNow - dt), t1 = Math.min(T, tNow + dt);
    const deg = (Math.atan2(Y(v(t1)) - Y(v(t0)), X(t1) - X(t0)) * 180) / Math.PI;
    return Math.max(-28, Math.min(28, deg)); })();
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((k) => vmin + span * k);
  const fmt = (v: number) => `${Math.round(v).toLocaleString("en-US")} ${g.unit}`;
  return (
    <AbsoluteFill style={{ background: "linear-gradient(170deg, #0d1626 0%, #070a12 70%)" }}>
      <div style={{ position: "absolute", top: tall ? 330 : 50, left: 0, right: 0, textAlign: "center", fontFamily: HEAD, fontWeight: 900, fontSize: tall ? 56 : 46, color: C.text }}>{g.title}</div>
      <svg width={W} height={H} style={{ position: "absolute", inset: 0 }}>
        {ticks.map((v, i) => <g key={i}><line x1={box.x} x2={box.x + box.w} y1={Y(v)} y2={Y(v)} stroke="rgba(255,255,255,0.1)" />
          <text x={box.x - 12} y={Y(v) + 8} fill="rgba(255,255,255,0.55)" fontSize={tall ? 24 : 20} textAnchor="end" fontFamily="Inter">{Math.round(v).toLocaleString("en-US")}</text></g>)}
        {(g.marks || []).map((m, i) => <g key={"m" + i} opacity={tNow >= m.t ? 1 : 0.25}><line x1={X(m.t)} x2={X(m.t)} y1={box.y} y2={box.y + box.h} stroke={C.gold} strokeDasharray="8 8" />
          <text x={X(m.t) + 10} y={box.y + 30 + i * 34} fill={C.gold} fontSize={tall ? 24 : 21} fontFamily="Inter" fontWeight={700}>{m.text}</text></g>)}
        <path d={path} fill="none" stroke={C.teal} strokeWidth={6} strokeLinejoin="round" />
        {air ? <g transform={`translate(${X(cur[0])},${Y(cur[1])}) rotate(${pitch}) scale(${tall ? 0.7 : 0.72}) translate(-200,-60)`}>
          <LiveryAirliner lv={g.livery} f={f} id={`sl${Math.round(T)}`} /></g> : null}
        {air ? <Altimeter cx={tall ? W - 220 : W - 290} cy={tall ? 1260 : H / 2 + 10} r={tall ? 118 : 175} ft={cur[1]} /> : null}
        <g transform={`translate(${X(cur[0])},${Y(cur[1])}) rotate(${-ang})`} opacity={air ? 0 : 1}>
          {g.icon === "sub"
            ? <g fill="#f2c94c"><ellipse cx={0} cy={0} rx={46} ry={16} /><rect x={-8} y={-30} width={22} height={18} rx={4} /></g>
            : <g fill="#ffffff"><path d="M48,0 C40,-6 20,-7 -30,-6 L-44,-24 L-52,-24 L-44,-4 L-48,0 L-44,4 L-52,24 L-44,24 L-30,6 C20,7 40,6 48,0 Z" />
                <path d="M6,-4 L-22,-34 L-12,-34 L22,-4 Z M6,4 L-22,34 L-12,34 L22,4 Z" /></g>}
        </g>
      </svg>
      <div style={{ position: "absolute", ...(air && tall ? { left: 90, top: 1150 } : { right: tall ? 90 : 200, top: tall ? 1300 : 52 }), fontFamily: HEAD, fontWeight: 900, fontSize: tall ? 64 : 52, color: C.gold }}>{fmt(cur[1])}</div>
      {g.notes ? <div style={{ position: "absolute", left: tall ? 90 : 200, top: tall ? (air ? 1240 : 1310) : 180, fontFamily: BODY, fontWeight: 600, fontSize: tall ? 26 : 22, color: C.mut, maxWidth: tall ? (air ? 560 : 520) : 900 }}>{g.notes}</div> : null}
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------- map simulations (weather_event, ship_route)
// A track on a map: the observed path drawn over the beat with the subject (storm / vessel) riding it, and for storms the
// forecast points with an uncertainty cone (circles of the forecast error radius, joined along the track).

export type SimPt = { lat: number; lon: number; label?: string; v?: string; r_km?: number };
export type SimMap = { kind: "simmap"; module: string; title: string; label?: string; notes?: string; icon?: "storm" | "ship";
  track: SimPt[]; forecast?: SimPt[]; places?: { name: string; lat: number; lon: number }[]; source?: string };

const countries2 = (feature as any)(world as any, (world as any).objects.countries);

export const SimMapBackdrop: React.FC<{ g: SimMap; dur: number }> = ({ g, dur }) => {
  const f = useCurrentFrame(); const { fps, width: W, height: H } = useVideoConfig(); const t = f / fps; const tall = H > W;
  const track = (g.track || []).filter((p) => isFinite(p.lat) && isFinite(p.lon));
  const fc = (g.forecast || []).filter((p) => isFinite(p.lat) && isFinite(p.lon));
  const all = [...track, ...fc, ...(g.places || [])];
  const lats = all.map((p) => p.lat), lons = all.map((p) => p.lon);
  const pad = Math.max(3, ...fc.map((p) => (p.r_km || 0) / 111));
  const box = { type: "MultiPoint", coordinates: [[Math.min(...lons) - pad, Math.min(...lats) - pad], [Math.max(...lons) + pad, Math.max(...lats) + pad]] } as any;
  const top = tall ? 480 : 150, bottom = tall ? 1300 : H - 120;
  const proj = geoMercator().fitExtent([[60, top], [W - 60, bottom]], box); const path = geoPath(proj);
  const P = (p: { lat: number; lon: number }) => proj([p.lon, p.lat]) as [number, number];
  const draw = interpolate(t, [0.5, Math.max(1.5, dur * (fc.length ? 0.5 : 0.75))], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.inOut(Easing.cubic) });
  const coneOn = interpolate(t, [dur * 0.5, dur * 0.75], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const tp = track.map(P);
  const k = draw * (tp.length - 1); const i0 = Math.floor(k); const fr = k - i0;
  const a = tp[Math.min(i0, tp.length - 1)] || [W / 2, H / 2], b = tp[Math.min(i0 + 1, tp.length - 1)] || a;
  const head: [number, number] = [a[0] + (b[0] - a[0]) * fr, a[1] + (b[1] - a[1]) * fr];
  const ang = (Math.atan2(b[1] - a[1], b[0] - a[0]) * 180) / Math.PI;
  const shown = tp.slice(0, i0 + 1).concat([head]);
  const rpx = (p: SimPt) => { const c = P(p); const n = P({ lat: p.lat + (p.r_km || 0) / 111, lon: p.lon }); return Math.abs(c[1] - n[1]); };
  // cone outline: offset each forecast point left/right of the track direction by its radius, then close the shape
  const fpts = fc.length ? [track[track.length - 1], ...fc].filter(Boolean) as SimPt[] : [];
  const cone = (() => {
    if (fpts.length < 2) return "";
    const L: [number, number][] = [], R: [number, number][] = [];
    fpts.forEach((p, i) => { const c = P(p); const q = P(fpts[Math.min(i + 1, fpts.length - 1)]); const o = P(fpts[Math.max(i - 1, 0)]);
      const dx = q[0] - o[0], dy = q[1] - o[1]; const len = Math.hypot(dx, dy) || 1; const r = i === 0 ? 4 : rpx(p);
      L.push([c[0] - (dy / len) * r, c[1] + (dx / len) * r]); R.push([c[0] + (dy / len) * r, c[1] - (dx / len) * r]); });
    return "M" + L.map((p) => p.join(",")).join("L") + "L" + R.reverse().map((p) => p.join(",")).join("L") + "Z";
  })();
  return (
    <AbsoluteFill style={{ background: "radial-gradient(ellipse at 50% 45%, #13203a 0%, #070a12 75%)" }}>
      <svg width={W} height={H} style={{ position: "absolute", inset: 0 }}>
        <g>{(countries2.features as any[]).map((c, i) => <path key={i} d={path(c) || ""} fill="#1a2740" stroke="#33476b" strokeWidth={1.5} />)}</g>
        {cone ? <g opacity={coneOn}>
          {fpts.slice(1).map((p, i) => <circle key={i} cx={P(p)[0]} cy={P(p)[1]} r={rpx(p)} fill="rgba(255,255,255,0.10)" />)}
          <path d={cone} fill="rgba(255,255,255,0.14)" stroke="rgba(255,255,255,0.7)" strokeWidth={3} strokeDasharray="10 8" />
          <path d={"M" + fpts.map((p) => P(p).join(",")).join("L")} fill="none" stroke="rgba(255,255,255,0.8)" strokeWidth={4} strokeDasharray="4 10" />
          {fc.map((p, i) => p.label ? <text key={"fl" + i} x={P(p)[0] + 16} y={P(p)[1] + 8} fill="rgba(255,255,255,0.85)" fontSize={tall ? 24 : 20} fontFamily="Inter" fontWeight={700}>{p.label}</text> : null)}
        </g> : null}
        <path d={"M" + shown.map((p) => p.join(",")).join("L")} fill="none" stroke={g.icon === "storm" ? C.red : C.gold} strokeWidth={7} strokeLinejoin="round" strokeLinecap="round" />
        {track.map((p, i) => (i <= k && p.label) ? <g key={"t" + i}><circle cx={tp[i][0]} cy={tp[i][1]} r={8} fill={C.text} />
          <text x={tp[i][0] + 14} y={tp[i][1] - 12} fill={C.text} fontSize={tall ? 26 : 22} fontFamily="Inter" fontWeight={800} stroke="#0b0f17" strokeWidth={6} paintOrder="stroke">{p.label}</text></g> : null)}
        {(g.places || []).map((p, i) => <g key={"p" + i}><circle cx={P(p)[0]} cy={P(p)[1]} r={9} fill={C.teal} stroke="#0b0f17" strokeWidth={3} />
          <text x={P(p)[0]} y={P(p)[1] - 20} textAnchor="middle" fill={C.teal} fontSize={tall ? 28 : 24} fontFamily={HEAD} fontWeight={900} stroke="#0b0f17" strokeWidth={7} paintOrder="stroke">{p.name}</text></g>)}
        <g transform={`translate(${head[0]},${head[1]})`}>
          {g.icon === "storm"
            ? <g transform={`rotate(${-t * 240})`} fill="none" stroke={C.red} strokeWidth={7} strokeLinecap="round">
                <circle r={9} fill={C.red} stroke="none" /><path d="M0,-30 A30,30 0 0,1 30,0" /><path d="M0,30 A30,30 0 0,1 -30,0" /></g>
            : <g transform={`rotate(${ang})`}><path d="M30,0 L-22,-14 L-14,0 L-22,14 Z" fill={C.gold} stroke="#0b0f17" strokeWidth={3} /></g>}
        </g>
      </svg>
      {/* title on a panel above the map (the map is drawn first so it never covers the text) */}
      <div style={{ position: "absolute", top: tall ? 320 : 24, left: 0, right: 0, textAlign: "center" }}>
        <div style={{ display: "inline-block", background: "rgba(7,10,18,0.82)", borderRadius: 18, padding: tall ? "14px 34px" : "10px 28px" }}>
          <div style={{ fontFamily: HEAD, fontWeight: 900, fontSize: tall ? 54 : 44, color: C.text }}>{g.title}</div>
        </div>
      </div>
      {track[Math.min(Math.round(k), track.length - 1)]?.v ? <div style={{ position: "absolute", right: tall ? 80 : 120, top: tall ? 1330 : H - 110, fontFamily: HEAD, fontWeight: 900,
        fontSize: tall ? 52 : 44, color: g.icon === "storm" ? C.red : C.gold }}>{track[Math.min(Math.round(k), track.length - 1)].v}</div> : null}
      {g.notes ? <div style={{ position: "absolute", left: tall ? 80 : 120, top: tall ? 1345 : H - 100, maxWidth: tall ? 560 : 1000, fontFamily: BODY, fontWeight: 600, fontSize: tall ? 24 : 21, color: C.mut }}>{g.notes}</div> : null}
    </AbsoluteFill>
  );
};
