import React from "react";
import { AbsoluteFill, Img, interpolate, staticFile, useCurrentFrame, useVideoConfig, Easing } from "remotion";
import { asset } from "./asset";
import { geoMercator, geoPath, geoInterpolate } from "d3-geo";
import { feature } from "topojson-client";
// Natural Earth 1:50m country outlines (public domain), bundled offline
import world from "world-atlas/countries-50m.json";
import { C, HEAD, BODY } from "./theme";

export type MapPoint = { name: string; lat: number; lon: number; role: "origin" | "planned" | "actual" | "stop" | "place" };
import type { Recon } from "./Recon";
import type { Illustration, Silhouette } from "./Illustration";
import type { Sim, SimMap } from "./Sim";
import type { Tpl } from "./Templates";
export type Backdrop =
  | { kind: "source_excerpt"; src: string; media: "clip" | "screenshot"; seconds: number; credit: string; purpose: string; timestamp: number; graphic: any }
  | { kind: "map"; title?: string; points: MapPoint[] }
  | { kind: "headline"; kicker?: string; text: string; sub?: string }
  | {kind: "motion"; module: string; title: string; label: string; angles: number[]; points: number[][]; targets: number[][]}
  | Recon | Illustration | Silhouette | Sim | SimMap | Tpl;

const countries = (feature as any)(world as any, (world as any).objects.countries);

// Full-screen animated route map: origin -> (stops) -> actual destination drawn in gold; the planned destination dashed.
export const MapBackdrop: React.FC<{ g: Extract<Backdrop, { kind: "map" }>; dur: number }> = ({ g, dur }) => {
  const f = useCurrentFrame(); const { fps, width, height } = useVideoConfig(); const t = f / fps;
  const pts = g.points;
  // fit the view around all points with generous padding (at least ~12 degrees across)
  const lats = pts.map((p) => p.lat), lons = pts.map((p) => p.lon);
  const cx = (Math.min(...lons) + Math.max(...lons)) / 2, cy = (Math.min(...lats) + Math.max(...lats)) / 2;
  // square-ish window (the map area is ~1:1) just big enough for all points plus a margin, at least 8 degrees across
  const half = Math.max(4, (Math.max(...lons) - Math.min(...lons)) * 0.75, (Math.max(...lats) - Math.min(...lats)) * 0.9);
  const box = { type: "MultiPoint", coordinates: [[cx - half, cy - half * 0.85], [cx + half, cy + half * 0.85]] } as any;
  const tall = height > width;   // Shorts (portrait) keep the top and the caption zone clear; landscape uses the full frame
  const top = tall ? 300 : 150, bottom = tall ? 1330 : height - 150;
  const zoom = interpolate(t, [0, dur], [1.0, 1.06]);
  const proj = geoMercator().fitExtent([[60, top], [width - 60, bottom]], box);
  const path = geoPath(proj);
  const P = (p: MapPoint) => proj([p.lon, p.lat]) as [number, number];
  const origin = pts.find((p) => p.role === "origin") || pts[0];
  const stops = pts.filter((p) => p.role === "stop");
  const actual = pts.find((p) => p.role === "actual");
  const planned = pts.find((p) => p.role === "planned");
  const legs: [MapPoint, MapPoint][] = [];
  const chain = [origin, ...stops, ...(actual ? [actual] : planned ? [planned] : [])];
  for (let i = 0; i + 1 < chain.length; i++) legs.push([chain[i], chain[i + 1]]);
  const arc = (a: MapPoint, b: MapPoint) => {
    const ip = geoInterpolate([a.lon, a.lat], [b.lon, b.lat]);
    return Array.from({ length: 41 }, (_, i) => proj(ip(i / 40)) as [number, number]);
  };
  const draw = interpolate(t, [0.6, Math.max(1.6, dur * 0.6)], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.inOut(Easing.cubic) });
  const fadeIn = 1;   // backdrops cut in hard (a fade dips to black between beats)
  // plane position along the full drawn route
  const all = legs.flatMap(([a, b]) => arc(a, b));
  const k = Math.min(all.length - 1, Math.max(0, Math.floor(draw * (all.length - 1))));
  const head = all[k] || P(origin), prev = all[Math.max(0, k - 1)] || head;
  const ang = (Math.atan2(head[1] - prev[1], head[0] - prev[0]) * 180) / Math.PI;
  const label = (p: MapPoint, i: number) => {
    const [x, y] = P(p);
    const show = interpolate(t, [0.3 + i * 0.25, 0.7 + i * 0.25], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
    const col = p.role === "actual" ? C.gold : p.role === "planned" ? "rgba(255,255,255,0.75)" : C.text;
    return (
      <g key={p.name + i} opacity={show}>
        <circle cx={x} cy={y} r={p.role === "actual" ? 16 : 12} fill={col} stroke="#0b0f17" strokeWidth={4} />
        {p.role === "actual" ? <circle cx={x} cy={y} r={16 + 18 * ((t * 1.2) % 1)} fill="none" stroke={C.gold} strokeWidth={3} opacity={1 - ((t * 1.2) % 1)} /> : null}
        <text x={x} y={y - 30} textAnchor="middle" fontFamily={HEAD} fontWeight={900} fontSize={40} fill={col}
          stroke="#0b0f17" strokeWidth={10} paintOrder="stroke">{p.name}</text>
        {p.role === "planned" && actual ? <text x={x} y={y - 78} textAnchor="middle" fontFamily={BODY} fontWeight={800} fontSize={26}
          fill="rgba(255,255,255,0.7)" stroke="#0b0f17" strokeWidth={8} paintOrder="stroke">PLANNED</text> : null}
      </g>
    );
  };
  return (
    <AbsoluteFill style={{ background: "radial-gradient(ellipse at 50% 45%, #13203a 0%, #070a12 75%)", opacity: fadeIn }}>
      <svg width={width} height={height} style={{ transform: `scale(${zoom})`, transformOrigin: "50% 45%" }}>
        <g>{(countries.features as any[]).map((c, i) => <path key={i} d={path(c) || ""} fill="#1a2740" stroke="#33476b" strokeWidth={1.5} />)}</g>
        {planned && actual ? <path d={"M" + arc(origin, planned).map((p) => p.join(",")).join("L")} fill="none" stroke="rgba(255,255,255,0.55)" strokeWidth={5} strokeDasharray="14 14" /> : null}
        {legs.map(([a, b], i) => {
          const pts2 = arc(a, b); const d = "M" + pts2.map((p) => p.join(",")).join("L");
          const share = 1 / legs.length; const local = Math.min(1, Math.max(0, (draw - i * share) / share));
          return <path key={i} d={d} fill="none" stroke={C.gold} strokeWidth={8} strokeLinecap="round" pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - local} />;
        })}
        {pts.map(label)}
        {draw > 0.02 && draw < 0.999 ? <text x={head[0]} y={head[1]} fontSize={58} textAnchor="middle" dominantBaseline="central"
          transform={`rotate(${ang + 45} ${head[0]} ${head[1]})`}>✈️</text> : null}
      </svg>
      {g.title ? <div style={{ position: "absolute", top: tall ? 1250 : height - 120, left: 0, right: 0, textAlign: "center" }}>
        <span style={{ fontFamily: HEAD, fontWeight: 900, fontSize: 40, color: "#111", background: C.gold, borderRadius: 999, padding: "10px 30px" }}>{g.title}</span>
      </div> : null}
    </AbsoluteFill>
  );
};

// Full-screen headline card for beats with no fitting footage.
export const HeadlineBackdrop: React.FC<{ g: Extract<Backdrop, { kind: "headline" }>; dur: number }> = ({ g, dur }) => {
  const f = useCurrentFrame(); const { fps, width, height } = useVideoConfig(); const t = f / fps; const tall = height > width;
  const a = interpolate(t, [0.1, 0.6], [0, 1], { extrapolateRight: "clamp" });
  const drift = interpolate(t, [0, dur], [0, -160]);
  return (
    <AbsoluteFill style={{ background: "linear-gradient(160deg, #101a2e 0%, #070a12 60%, #1d1406 100%)" }}>
      <AbsoluteFill style={{ backgroundImage: "repeating-linear-gradient(135deg, rgba(255,255,255,0.04) 0 2px, transparent 2px 48px)", backgroundPosition: `${drift}px 0` }} />
      <AbsoluteFill style={{ top: tall ? 860 : 170, bottom: "auto", height: tall ? 480 : 560, alignItems: "center", justifyContent: "center", padding: tall ? "0 80px" : "0 200px", opacity: a, transform: `translateY(${(1 - a) * 30}px)` }}>
        {g.kicker ? <div style={{ fontFamily: BODY, fontWeight: 800, fontSize: 34, color: "#111", background: C.gold, borderRadius: 999, padding: "8px 26px", marginBottom: 28, letterSpacing: 1 }}>{g.kicker.toUpperCase()}</div> : null}
        <div style={{ fontFamily: HEAD, fontWeight: 900, fontSize: 70, lineHeight: 1.12, color: C.text, textAlign: "center" }}>{g.text}</div>
        {g.sub ? <div style={{ fontFamily: BODY, fontWeight: 600, fontSize: 38, color: C.mut, marginTop: 22, textAlign: "center" }}>{g.sub}</div> : null}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// AI still split into depth layers; nearer layers move further (2.5D parallax).
export const LayersBackdrop: React.FC<{ layers: string[]; dur: number; seed: number }> = ({ layers, dur, seed }) => {
  const f = useCurrentFrame(); const { fps } = useVideoConfig(); const t = f / fps;
  const p = Math.min(1, t / Math.max(dur, 0.1)); const e = p < 0.5 ? 2 * p * p : 1 - Math.pow(-2 * p + 2, 2) / 2;
  const dir = seed % 2 === 0 ? 1 : -1;
  return (
    <AbsoluteFill style={{ overflow: "hidden", background: "#000" }}>
      {layers.map((src, i) => {
        const depth = [0.25, 0.65, 1.0][i] ?? 1;
        const x = dir * interpolate(e, [0, 1], [-40, 40]) * depth;
        const y = interpolate(e, [0, 1], [10, -10]) * depth;
        const s = 1.08 + 0.05 * depth * e;
        return <Img key={i} src={asset(src)} style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover",
          transform: `translate(${x}px, ${y}px) scale(${s})` }} />;
      })}
    </AbsoluteFill>
  );
};
