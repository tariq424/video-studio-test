// Flat vector illustrations and silhouettes: the ladder rung after the AI still and before the 3D reconstruction.
// Pure SVG, CPU only, renders in seconds. They are meant to read as a design choice (editorial flat illustration), so they stay
// simple: flat colour, no gradients on objects, gentle motion. No logos, no names, no livery.
import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { HEAD } from "./theme";
import { LiveryAirliner, Livery } from "./Aircraft";

export type Illustration = {
  kind: "illustration";
  scene: "sky" | "airport" | "city" | "radar" | "cockpit" | "sea";
  time?: "day" | "dusk" | "night" | "storm";
  attitude?: "level" | "dive" | "climb" | "bank" | "down" | "up" | "landing" | "ground";
  ground?: "desert" | "green" | "sea";
  alarm?: boolean;
  aircraft?: "airliner" | "fighter";   // which aircraft the sky / airport scene draws (illustrate.aircraft_for); default airliner
  count?: number;                       // fighters: 2 = a pair in formation (lead + wingman)
  livery?: Livery | null;               // airliner in an airline's simplified livery (liveries.py); none = the generic flat airliner
  seed?: number;
};
export type Silhouette = {
  kind: "silhouette";
  shape: "airliner" | "jet" | "person" | "people" | "building" | "car" | "ship";
  time?: "day" | "dusk" | "night" | "storm";
  attitude?: "level" | "dive" | "climb" | "bank" | "down" | "up" | "landing" | "ground";
  pose?: "still" | "moving";   // cars drive past, people walk; buildings have no pose
  text?: string;
  seed?: number;
};

const SKY: Record<string, [string, string, string]> = {
  day: ["#5aa6e8", "#9fd0f5", "#e8f4fb"],
  dusk: ["#1c2550", "#c4536b", "#f6a65a"],
  night: ["#03060f", "#0d1a33", "#1d3157"],
  storm: ["#1d232c", "#3a4452", "#6a7584"],
};
const GROUND: Record<string, string> = { desert: "#c99a5b", green: "#4f7a4a", sea: "#1f4f78" };
const rnd = (i: number) => { const x = Math.sin(i * 12.9898 + 78.233) * 43758.5453; return x - Math.floor(x); };
const ANGLE: Record<string, number> = { level: 0, dive: 24, down: 24, climb: -15, up: -15, bank: 0, landing: -4, ground: 0 };
// pose of a flying aircraft over the shot: pitch angle, vertical travel, and for a bank a squashed side view (wings tilted to camera)
const airPose = (att: string, p: number, t: number, W: number, H: number) => {
  const a = att === "down" ? "dive" : att === "up" ? "climb" : att;
  const dy = a === "dive" ? interpolate(p, [0, 1], [-H * 0.09, H * 0.11]) : a === "climb" ? interpolate(p, [0, 1], [H * 0.08, -H * 0.08])
    : a === "bank" ? -Math.sin(p * Math.PI) * H * 0.05 : Math.sin(t * 1.4) * 8;
  const ang = (ANGLE[a] ?? 0) + (a === "bank" ? interpolate(p, [0, 1], [0, 5]) : 0);
  return { ang, dy, sy: a === "bank" ? 0.72 : 1 };
};
// camera parallax: layers drift sideways at different speeds (near layers further), as on the AI-still parallax
const useCam = (seed: number, p: number, W: number) => {
  const e = p < 0.5 ? 2 * p * p : 1 - Math.pow(-2 * p + 2, 2) / 2;
  const span = W * 0.035 * (seed % 2 === 0 ? 1 : -1);
  return (d: number) => `translate(${interpolate(e, [0, 1], [span, -span]) * d},0)`;
};

// Side-view airliner facing right, drawn in a 400 x 120 box (nose at x=395, y=60). flat=true: coloured flat illustration.
const Airliner: React.FC<{ flat?: boolean; fill?: string; gear?: boolean; night?: boolean; f: number }> = ({ flat, fill = "#0b0f17", gear, night, f }) => {
  const body = flat ? "#f4f6f8" : fill, belly = flat ? "#c9d1db" : fill, tail = flat ? "#8b9bb0" : fill, eng = flat ? "#aeb8c5" : fill, dark = flat ? "#5b6676" : fill;
  const blink = Math.floor(f / 18) % 2 === 0;
  return (
    <g>
      <path d="M44,47 L20,4 L46,4 L98,47 Z" fill={tail} />
      <path d="M36,60 L6,76 L28,78 L78,64 Z" fill={dark} />
      <path d="M10,60 C10,49 30,44 62,44 L328,44 C356,44 380,51 396,60 C382,69 358,75 328,75 L62,75 C30,75 10,71 10,60 Z" fill={body} />
      {flat ? <path d="M30,66 L330,66 C352,66 372,68 388,64 C372,71 354,75 328,75 L62,75 C42,75 30,72 30,66 Z" fill={belly} /> : null}
      {flat ? <path d="M360,50 L378,52 L386,58 L364,57 Z" fill="#2b3a52" /> : null}
      {flat ? Array.from({ length: 22 }, (_, i) => <rect key={i} x={86 + i * 11.5} y={52} width={5} height={6} rx={2} fill="#7f8ea3" />) : null}
      <path d="M182,64 L128,110 L160,112 L246,66 Z" fill={dark} />
      <rect x={152} y={84} width={56} height={17} rx={8} fill={eng} />
      {flat ? <rect x={202} y={86} width={8} height={13} rx={3} fill="#3b4656" /> : null}
      {gear ? <g fill={dark}><rect x={318} y={74} width={4} height={18} /><circle cx={320} cy={95} r={6} /><rect x={176} y={74} width={5} height={22} /><circle cx={178} cy={99} r={7} /></g> : null}
      {flat ? <circle cx={226} cy={110} r={4} fill={blink || !night ? "#ff4b4b" : "#5b1b1b"} /> : null}
    </g>
  );
};

// Flat side-view fighter facing right (400 x 120 box, nose at x=398, y=60): single-engine stealth shape - chined nose, bubble canopy,
// side intake, twin canted tails, afterburner flame when burner=true. Generic (no markings, no national insignia, no serials).
const Fighter: React.FC<{ f: number; burner?: boolean; gear?: boolean; night?: boolean }> = ({ f, burner, gear, night }) => {
  const body = "#8a949f", top = "#a3adb8", dark = "#5c6570", deep = "#3c434c";
  const fl = burner ? 70 + Math.sin(f * 1.7) * 10 + Math.sin(f * 0.9) * 6 : 0;   // flame length flickers
  const blink = Math.floor(f / 18) % 2 === 0;
  return (
    <g transform="translate(0,60) scale(1,1.32) translate(0,-60)">
      {burner ? <g>
        <path d={`M28,52 L${28 - fl},60 L28,68 Z`} fill="#ff8a1f" opacity={0.85} />
        <path d={`M28,55 L${28 - fl * 0.62},60 L28,65 Z`} fill="#ffd34d" />
        <path d={`M28,57.5 L${28 - fl * 0.3},60 L28,62.5 Z`} fill="#fff6d6" />
      </g> : null}
      <path d="M78,50 L44,8 L70,8 L118,50 Z" fill={dark} />
      <path d="M96,51 L70,16 L90,16 L130,51 Z" fill={body} />
      <path d="M70,66 L26,84 L52,86 L112,68 Z" fill={dark} />
      <path d="M28,54 C34,50 48,48 72,48 L240,46 L300,45 C334,45 366,51 398,60 C366,68 334,72 300,72 L240,74 L72,72 C48,72 34,70 28,66 Z" fill={body} />
      <path d="M72,48 L240,46 L300,45 C334,45 366,51 398,60 L330,57 L240,56 L72,58 Z" fill={top} />
      <path d="M296,46 C306,30 334,30 352,48 C336,47 316,46 296,46 Z" fill={night ? "#1b2433" : "#2f3e52"} />
      <path d="M306,42 C314,35 328,35 338,43 C326,41 316,41 306,42 Z" fill="#c9d6e6" opacity={0.55} />
      <path d="M244,58 L290,58 L284,71 L244,71 Z" fill={deep} />
      <path d="M210,62 L136,96 L176,98 L262,64 Z" fill={dark} />
      <rect x={20} y={53} width={12} height={14} rx={3} fill={deep} />
      {gear ? <g fill={deep}><rect x={318} y={70} width={4} height={18} /><circle cx={320} cy={91} r={6} /><rect x={150} y={72} width={5} height={20} /><circle cx={152} cy={95} r={7} /></g> : null}
      <circle cx={150} cy={96} r={3.5} fill={blink || !night ? "#ff4b4b" : "#5b1b1b"} />
    </g>
  );
};

// Fighter jet facing right (400 x 120 box).
const Jet: React.FC<{ fill: string }> = ({ fill }) => (
  <g fill={fill}>
    <path d="M396,60 L300,50 L230,46 L120,48 L60,40 L40,40 L50,56 L20,60 L50,64 L40,80 L60,80 L120,72 L230,74 L300,70 Z" />
    <path d="M250,52 L150,10 L130,10 L190,54 Z" /><path d="M250,68 L150,110 L130,110 L190,66 Z" />
    <path d="M300,52 C315,44 335,46 345,54 Z" opacity={0.6} />
  </g>
);

const Cloud: React.FC<{ x: number; y: number; s: number; c: string; o?: number }> = ({ x, y, s, c, o = 1 }) => (
  <g transform={`translate(${x},${y}) scale(${s})`} fill={c} opacity={o}>
    <rect x={-120} y={0} width={260} height={46} rx={23} /><circle cx={-50} cy={4} r={42} /><circle cx={20} cy={-8} r={58} /><circle cx={80} cy={10} r={36} />
  </g>
);

const Sky: React.FC<{ W: number; H: number; time: string; id: string }> = ({ W, H, time, id }) => {
  const [a, b, c] = SKY[time] || SKY.dusk;
  return (
    <>
      <defs><linearGradient id={id} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor={a} /><stop offset="0.62" stopColor={b} /><stop offset="1" stopColor={c} /></linearGradient></defs>
      <rect x={-W * 0.1} width={W * 1.2} height={H} fill={`url(#${id})`} />
      {time === "night" ? Array.from({ length: 70 }, (_, i) => <circle key={i} cx={rnd(i) * W} cy={rnd(i + 99) * H * 0.6} r={1 + rnd(i + 7) * 2} fill="#fff" opacity={0.25 + rnd(i + 3) * 0.6} />) : null}
    </>
  );
};

const Clouds: React.FC<{ W: number; H: number; f: number; time: string; seed: number; band?: [number, number] }> = ({ W, H, f, time, seed, band = [0.08, 0.6] }) => {
  const col = time === "night" ? "#22335a" : time === "storm" ? "#4b5563" : time === "dusk" ? "#f2b8a0" : "#ffffff";
  const back = time === "night" ? "#17264a" : time === "storm" ? "#2f3742" : time === "dusk" ? "#a8506a" : "#d6ecfa";
  return (
    <>
      {Array.from({ length: 5 }, (_, i) => {
        const sp = 0.35 + rnd(seed + i) * 0.4, x = ((rnd(seed + i * 3) * W * 1.4 - f * sp) % (W * 1.6) + W * 1.6) % (W * 1.6) - W * 0.3;
        return <Cloud key={"b" + i} x={x} y={H * (band[0] + rnd(seed + i * 5) * (band[1] - band[0]))} s={(W / 1080) * (0.9 + rnd(seed + i * 7) * 0.9)} c={back} o={0.9} />;
      })}
      {Array.from({ length: 4 }, (_, i) => {
        const sp = 1 + rnd(seed + 40 + i) * 0.8, x = ((rnd(seed + 50 + i * 3) * W * 1.4 - f * sp) % (W * 1.6) + W * 1.6) % (W * 1.6) - W * 0.3;
        return <Cloud key={"f" + i} x={x} y={H * (band[0] + 0.05 + rnd(seed + 60 + i * 5) * (band[1] - band[0]))} s={(W / 1080) * (1.2 + rnd(seed + 70 + i) * 1.1)} c={col} />;
      })}
    </>
  );
};

const Skyline: React.FC<{ W: number; base: number; f: number; fill: string; lit: string; seed: number; h: number; dome?: boolean }> = ({ W, base, f, fill, lit, seed, h, dome }) => {
  const out: React.ReactNode[] = []; let x = -20, i = 0;
  while (x < W + 20) {
    const w = 60 + rnd(seed + i) * 110, bh = h * (0.35 + rnd(seed + i * 3) * 0.65);
    out.push(<rect key={"b" + i} x={x} y={base - bh} width={w} height={bh + 2} fill={fill} />);
    for (let r = 0; r < Math.floor(bh / 34); r++) for (let c = 0; c < Math.floor(w / 26); c++) {
      const k = seed + i * 97 + r * 13 + c;
      if (rnd(k) > 0.62) out.push(<rect key={`w${i}-${r}-${c}`} x={x + 8 + c * 26} y={base - bh + 12 + r * 34} width={12} height={16} fill={lit}
        opacity={rnd(k + Math.floor(f / 45)) > 0.15 ? 0.9 : 0.25} />);
    }
    x += w + 6; i++;
  }
  if (dome) out.push(<g key="dome" fill={fill}><rect x={W * 0.38} y={base - h * 0.62} width={W * 0.24} height={h * 0.62} /><ellipse cx={W * 0.5} cy={base - h * 0.62} rx={W * 0.09} ry={h * 0.2} />
    {Array.from({ length: 6 }, (_, k) => <rect key={k} x={W * 0.395 + k * W * 0.038} y={base - h * 0.5} width={W * 0.014} height={h * 0.5} fill="rgba(255,255,255,0.12)" />)}</g>);
  return <>{out}</>;
};

export const IllustrationBackdrop: React.FC<{ g: Illustration; dur: number }> = ({ g, dur }) => {
  const f = useCurrentFrame(); const { fps, width: W, height: H } = useVideoConfig(); const t = f / fps;
  const p = Math.min(1, t / Math.max(dur, 0.1)); const seed = g.seed ?? 3; const time = g.time || "dusk";
  const zoom = interpolate(p, [0, 1], [1.09, 1.15]); const tall = H > W; const u = Math.min(W, H) / 1080; const cam = useCam(seed, p, W);
  const ground = GROUND[g.ground || "desert"]; const id = `sky${seed}`;
  let scene: React.ReactNode = null;
  const fighter = g.aircraft === "fighter"; const burner = fighter && (g.attitude === "climb" || g.attitude === "up");
  if (g.scene === "sky") {
    const { ang, dy, sy } = airPose(g.attitude || "level", p, t, W, H);
    const pair = fighter && (g.count ?? 1) > 1;
    const k = (tall ? 1.85 : 2.3) * u * (pair ? 0.82 : 1), dx = interpolate(p, [0, 1], [-W * 0.05, W * 0.05]);
    scene = (<>
      <g transform={cam(0.15)}><Sky W={W} H={H} time={time} id={id} />
      {time === "dusk" || time === "day" ? <circle cx={W * 0.72} cy={H * 0.74} r={W * 0.16} fill={time === "dusk" ? "#ffd27a" : "#fff6cf"} opacity={0.9} /> : null}</g>
      <g transform={cam(0.45)}><Clouds W={W} H={H} f={fighter ? f * 2.6 : f} time={time} seed={seed} band={[0.06, 0.55]} /></g>
      <g transform={cam(0.8)}><path d={`M0,${H * 0.84} C${W * 0.25},${H * 0.8} ${W * 0.55},${H * 0.86} ${W},${H * 0.81} L${W},${H} L0,${H} Z`} fill={ground} opacity={0.95} />
      <path d={`M0,${H * 0.9} C${W * 0.3},${H * 0.86} ${W * 0.7},${H * 0.93} ${W},${H * 0.88} L${W},${H} L0,${H} Z`} fill="#000" opacity={0.18} /></g>
      <g transform={cam(1.2)}>
        {pair ? <g transform={`translate(${W / 2 - 200 * k + dx - 70 * k},${H * 0.42 + dy - (tall ? 0 : H * 0.06) + 135 * k}) scale(${k * 0.78}) rotate(${ang} 200 60)`}><Fighter f={f + 7} burner={burner} night={time === "night"} /></g> : null}
        <g transform={`translate(${W / 2 - 200 * k + dx},${H * 0.42 + dy - (pair && !tall ? H * 0.06 : 0)}) scale(${k}) rotate(${ang} 200 60) translate(0,${60 * (1 - sy)}) scale(1,${sy})`}>{fighter ? <Fighter f={f} burner={burner} night={time === "night"} /> : g.livery ? <LiveryAirliner lv={g.livery} night={time === "night"} f={f} id={`il${seed}`} /> : <Airliner flat night={time === "night"} f={f} />}</g></g>
      {time === "storm" && Math.floor(t * 2.3) % 7 === 3 ? <rect width={W} height={H} fill="#fff" opacity={0.18} /> : null}
    </>);
  } else if (g.scene === "airport") {
    const hz = H * (tall ? 0.6 : 0.55); const landing = g.attitude === "landing";
    const k = (tall ? 1.15 : 1.4) * u;
    const px = landing ? interpolate(p, [0, 1], [W * 0.02, W * 0.22]) : interpolate(p, [0, 1], [W * 0.05, W * 0.12]);
    const py = landing ? interpolate(p, [0, 1], [hz - H * 0.26, hz - H * 0.13]) : hz + H * 0.07;
    scene = (<>
      <g transform={cam(0.15)}><Sky W={W} H={hz + 2} time={time} id={id} /></g>
      <g transform={cam(0.4)}><Clouds W={W} H={hz} f={f} time={time} seed={seed} band={[0.1, 0.6]} /></g>
      <rect y={hz} width={W} height={H - hz} fill={ground} />
      <g transform={cam(0.6)}>
      <g fill={time === "night" ? "#1a2233" : "#5d6878"}>
        <rect x={W * 0.05} y={hz - H * 0.05} width={W * 0.5} height={H * 0.05} /><rect x={W * 0.08} y={hz - H * 0.065} width={W * 0.3} height={H * 0.016} />
        <rect x={W * 0.74} y={hz - H * 0.15} width={W * 0.03} height={H * 0.15} /><path d={`M${W * 0.71},${hz - H * 0.15} L${W * 0.8},${hz - H * 0.15} L${W * 0.79},${hz - H * 0.18} L${W * 0.72},${hz - H * 0.18} Z`} />
      </g>
      {Array.from({ length: 14 }, (_, i) => <rect key={i} x={W * 0.07 + i * W * 0.034} y={hz - H * 0.035} width={W * 0.018} height={H * 0.012} fill="#ffd27a" opacity={time === "night" || time === "dusk" ? 0.9 : 0.35} />)}</g>
      <path d={`M${W * 0.44},${hz} L${W * 0.56},${hz} L${W * 1.1},${H} L${-W * 0.1},${H} Z`} fill="#2e333b" />
      {Array.from({ length: 7 }, (_, i) => { const a = i / 7, b = (i + 0.45) / 7, y1 = hz + (H - hz) * a * a, y2 = hz + (H - hz) * b * b;
        return <path key={i} d={`M${W * 0.5 - 2 - a * 10},${y1} L${W * 0.5 + 2 + a * 10},${y1} L${W * 0.5 + 2 + b * 10},${y2} L${W * 0.5 - 2 - b * 10},${y2} Z`} fill="#f1f1ea" />; })}
      {Array.from({ length: 10 }, (_, i) => { const a = (i + 1) / 11, y = hz + (H - hz) * a * a, on = Math.floor(f / 10 + i) % 10 === 0;
        return <g key={i}><circle cx={W * 0.44 - a * W * 0.54} cy={y} r={3 + a * 6} fill={on ? "#fff" : "#ffcf6b"} /><circle cx={W * 0.56 + a * W * 0.54} cy={y} r={3 + a * 6} fill={on ? "#fff" : "#ffcf6b"} /></g>; })}
      <g transform={cam(1.2)}><g transform={`translate(${px},${py}) scale(${k}) rotate(${landing ? -4 : 0} 200 60)`}>{fighter ? <Fighter f={f} gear night={time === "night"} /> : g.livery ? <LiveryAirliner lv={g.livery} gear night={time === "night"} f={f} id={`ia${seed}`} /> : <Airliner flat gear night={time === "night"} f={f} />}</g></g>
    </>);
  } else if (g.scene === "city") {
    const base = H * (tall ? 0.78 : 0.82);
    scene = (<>
      <g transform={cam(0.1)}><Sky W={W} H={H} time={time} id={id} />
      {time === "night" ? <circle cx={W * 0.78} cy={H * 0.16} r={W * 0.06} fill="#f3f0d8" /> : null}</g>
      <g transform={cam(0.3)}><Clouds W={W} H={H} f={f} time={time} seed={seed} band={[0.05, 0.35]} /></g>
      <g transform={cam(0.6)}><Skyline W={W} base={base} f={f} fill={time === "night" ? "#18233b" : "#56607a"} lit="#ffd98a" seed={seed + 11} h={H * 0.34} /></g>
      <g transform={cam(1.1)}><Skyline W={W} base={base + 6} f={f} fill={time === "night" ? "#0a0f1c" : "#2e3446"} lit="#ffe9b8" seed={seed + 23} h={H * 0.24} dome /></g>
      <rect y={base} width={W} height={H - base} fill={time === "night" ? "#050811" : "#1d2230"} />
      {Array.from({ length: 18 }, (_, i) => <rect key={i} x={rnd(seed + i) * W} y={base + 20 + rnd(seed + i * 2) * (H - base - 40)} width={40 + rnd(i) * 120} height={3} fill="#ffd98a" opacity={0.25} />)}
    </>);
  } else if (g.scene === "radar") {
    const cx = W / 2, cy = H * 0.48, R = Math.min(W, H) * 0.42, sweep = (t * 70) % 360;
    const blips = Array.from({ length: 6 }, (_, i) => ({ a: rnd(seed + i) * 360, r: R * (0.25 + rnd(seed + i * 3) * 0.7) }));
    const tr = g.attitude === "down" || g.attitude === "dive";
    scene = (<>
      <rect width={W} height={H} fill="#03110c" />
      {Array.from({ length: 40 }, (_, i) => <line key={i} x1={0} y1={(i * H) / 40} x2={W} y2={(i * H) / 40} stroke="#0b2a1f" strokeWidth={1} />)}
      <circle cx={cx} cy={cy} r={R} fill="#062a1c" stroke="#1fd17a" strokeWidth={3} />
      {[0.25, 0.5, 0.75].map((k) => <circle key={k} cx={cx} cy={cy} r={R * k} fill="none" stroke="#1fd17a" strokeOpacity={0.35} strokeWidth={2} />)}
      <line x1={cx - R} y1={cy} x2={cx + R} y2={cy} stroke="#1fd17a" strokeOpacity={0.3} /><line x1={cx} y1={cy - R} x2={cx} y2={cy + R} stroke="#1fd17a" strokeOpacity={0.3} />
      <g transform={`rotate(${sweep} ${cx} ${cy})`}><path d={`M${cx},${cy} L${cx + R},${cy} A${R},${R} 0 0,0 ${cx + R * Math.cos(-0.5)},${cy + R * Math.sin(-0.5)} Z`} fill="#2bff9a" opacity={0.28} /><line x1={cx} y1={cy} x2={cx + R} y2={cy} stroke="#7dffc0" strokeWidth={3} /></g>
      {blips.map((b, i) => { const age = ((sweep - b.a) % 360 + 360) % 360; const o = Math.max(0.15, 1 - age / 300);
        return <circle key={i} cx={cx + b.r * Math.cos((b.a * Math.PI) / 180)} cy={cy + b.r * Math.sin((b.a * Math.PI) / 180)} r={7} fill="#9dffcf" opacity={o} />; })}
      {tr ? Array.from({ length: 6 }, (_, i) => <circle key={"t" + i} cx={cx + R * 0.3 + i * 14} cy={cy - R * 0.45 + i * i * 9 * Math.min(1, p * 1.5)} r={8 - i} fill="#ffcf3d" opacity={1 - i * 0.14} />) : null}
    </>);
  } else if (g.scene === "cockpit") {
    const dash = H * (tall ? 0.6 : 0.62);
    const bank = g.attitude === "down" || g.attitude === "dive" ? 10 + Math.sin(t * 2) * 4 : Math.sin(t * 0.8) * 2;
    scene = (<>
      <g transform={`rotate(${bank} ${W / 2} ${dash})`}><Sky W={W} H={dash + 40} time={time} id={id} /><Clouds W={W} H={dash} f={f * 2} time={time} seed={seed} band={[0.15, 0.7]} /></g>
      <path d={`M0,0 L${W},0 L${W},${dash} L${W * 0.86},${dash * 0.22} L${W * 0.54},${dash * 0.16} L${W * 0.5},${dash} L${W * 0.46},${dash * 0.16} L${W * 0.14},${dash * 0.22} L0,${dash} Z`} fill="#11151d" />
      <rect y={dash} width={W} height={H - dash} fill="#181d27" />
      <rect x={W * 0.06} y={dash + H * 0.03} width={W * 0.88} height={H * 0.13} rx={14} fill="#0b0e14" />
      {[0.1, 0.32, 0.54, 0.76].map((x, i) => (
        <g key={i}><rect x={W * x} y={dash + H * 0.045} width={W * 0.18} height={H * 0.1} rx={8} fill={i % 2 ? "#0e2236" : "#07131f"} stroke="#2a3a52" />
          {i % 2 === 0 ? <><rect x={W * x + 6} y={dash + H * 0.045 + 6} width={W * 0.18 - 12} height={H * 0.05 - 6} fill="#2f6fb5" /><rect x={W * x + 6} y={dash + H * 0.095} width={W * 0.18 - 12} height={H * 0.05 - 6} fill="#8a5a2b" /></>
            : Array.from({ length: 4 }, (_, j) => <rect key={j} x={W * x + 10} y={dash + H * 0.055 + j * H * 0.02} width={W * (0.06 + rnd(i * 9 + j) * 0.09)} height={6} fill="#3ee08f" opacity={0.8} />)}</g>))}
      {g.alarm ? <circle cx={W * 0.5} cy={dash + H * 0.02} r={14} fill={Math.floor(f / 8) % 2 ? "#ff3b3b" : "#5a1414"} /> : null}
      <g fill="#05070b"><rect x={W * 0.12} y={H * 0.74} width={W * 0.24} height={H * 0.3} rx={30} /><circle cx={W * 0.24} cy={H * 0.72} r={W * 0.08} />
        <rect x={W * 0.64} y={H * 0.74} width={W * 0.24} height={H * 0.3} rx={30} /><circle cx={W * 0.76} cy={H * 0.72} r={W * 0.08} /></g>
    </>);
  } else {   // sea
    const sea = H * 0.64;
    scene = (<>
      <g transform={cam(0.15)}><Sky W={W} H={sea + 2} time={time} id={id} /></g>
      <g transform={cam(0.4)}><Clouds W={W} H={sea} f={f} time={time} seed={seed} band={[0.08, 0.5]} /></g>
      <rect y={sea} width={W} height={H - sea} fill="#1f4f78" />
      <g transform={`translate(${interpolate(p, [0, 1], [W * 0.18, W * 0.3])},${sea - 70 * u + Math.sin(t * 1.2) * 4}) scale(${1.4 * u})`}>
        <path d="M0,50 L400,50 L360,92 L30,92 Z" fill="#2d3442" /><rect x={110} y={14} width={170} height={36} fill="#e9edf2" />
        <rect x={150} y={-12} width={70} height={26} fill="#e9edf2" /><rect x={236} y={-30} width={18} height={44} fill="#c0453b" />
        {Array.from({ length: 8 }, (_, i) => <rect key={i} x={120 + i * 19} y={24} width={9} height={9} fill="#5b6b80" />)}</g>
      {Array.from({ length: 14 }, (_, i) => { const y = sea + 20 + i * ((H - sea) / 14); const off = (f * (0.6 + i * 0.08)) % 120;
        return <path key={i} d={`M${-off},${y} q30,-10 60,0 t60,0 t60,0 t60,0 t60,0 t60,0 t60,0 t60,0 t60,0 t60,0 t60,0 t60,0 t60,0 t60,0 t60,0 t60,0 t60,0 t60,0 t60,0`} stroke="#9cc9ea" strokeOpacity={0.35} strokeWidth={3} fill="none" />; })}
    </>);
  }
  return (
    <AbsoluteFill style={{ overflow: "hidden", background: "#000" }}>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{ transform: `scale(${zoom})` }}>{scene}</svg>
    </AbsoluteFill>
  );
};

export const SilhouetteBackdrop: React.FC<{ g: Silhouette; dur: number }> = ({ g, dur }) => {
  const f = useCurrentFrame(); const { fps, width: W, height: H } = useVideoConfig(); const t = f / fps;
  const p = Math.min(1, t / Math.max(dur, 0.1)); const seed = g.seed ?? 5; const time = g.time || "dusk"; const u = Math.min(W, H) / 1080; const tall = H > W;
  const ink = "#0a0d14"; const id = `ssky${seed}`;
  const zoom = interpolate(p, [0, 1], [1.09, 1.14]); const hz = H * (tall ? 0.8 : 0.84); const cam = useCam(seed, p, W);
  const att = g.attitude || "level"; const pose = g.pose || "still";
  let shape: React.ReactNode;
  if (g.shape === "airliner" || g.shape === "jet") {
    const k = (tall ? 2.3 : 2.4) * u, dx = interpolate(p, [0, 1], [-W * 0.06, W * 0.06]);
    const { ang, dy, sy } = airPose(att, p, t, W, H);
    shape = <g transform={`translate(${W / 2 - 200 * k + dx},${H * 0.42 + dy}) scale(${k}) rotate(${ang} 200 60) translate(0,${60 * (1 - sy)}) scale(1,${sy})`}>{g.shape === "jet" ? <Jet fill={ink} /> : <Airliner fill={ink} gear={att === "landing" || att === "ground"} f={f} />}</g>;
  } else if (g.shape === "person" || g.shape === "people") {
    const n = g.shape === "people" ? 3 : 1;
    shape = <g fill={ink}>{Array.from({ length: n }, (_, i) => { const x = W / 2 + (i - (n - 1) / 2) * W * 0.22, s = (n === 1 ? 1.25 : 0.95 - Math.abs(i - 1) * 0.08) * u;
      const walk = pose === "moving"; const bob = walk ? Math.abs(Math.sin(t * 5 + i)) * -14 : Math.sin(t * 1.1 + i) * 2;
      const xx = x + (walk ? interpolate(p, [0, 1], [-W * 0.06, W * 0.06]) : 0);
      return <g key={i} transform={`translate(${xx},${hz + bob}) scale(${s}) skewX(${walk ? -6 : 0})`}><circle cx={0} cy={-470} r={58} /><path d="M-95,-400 C-95,-420 95,-420 95,-400 L118,-150 L70,-150 L62,-20 L14,-20 L8,-150 L-8,-150 L-14,-20 L-62,-20 L-70,-150 L-118,-150 Z" /></g>; })}</g>;
  } else if (g.shape === "building") {
    shape = <Skyline W={W} base={hz} f={0} fill={ink} lit="rgba(255,210,122,0.0)" seed={seed + 3} h={H * 0.38} dome />;
  } else if (g.shape === "car") {
    const moving = pose === "moving", k = 2.2 * u, x = moving ? interpolate(p, [0, 1], [-W * 0.1, W * 0.45]) : W * 0.12;
    shape = <g transform={`translate(${x},${hz - 120 * k + (moving ? Math.sin(t * 9) * 1.5 : 0)}) scale(${k})`} fill={ink}><path d="M10,90 L20,60 L90,52 L140,20 L250,18 L300,55 L370,62 L385,90 Z" /><circle cx={95} cy={92} r={28} /><circle cx={300} cy={92} r={28} />
      {moving ? [0, 1, 2].map((i) => <rect key={i} x={-90 - i * 30} y={40 + i * 18} width={60} height={5} rx={2} opacity={0.5} />) : null}</g>;
  } else {   // ship
    const k = 2.2 * u, x = interpolate(p, [0, 1], [W * 0.05, W * 0.15]);
    shape = <g transform={`translate(${x},${hz - 110 * k + Math.sin(t * 1.2) * 4}) scale(${k})`} fill={ink}><path d="M0,80 L400,80 L360,120 L30,120 Z" /><rect x={120} y={40} width={150} height={40} /><rect x={160} y={10} width={60} height={30} /><rect x={235} y={-10} width={16} height={50} /></g>;
  }
  const [a, b, c] = SKY[time] || SKY.dusk;
  return (
    <AbsoluteFill style={{ overflow: "hidden", background: "#000" }}>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{ transform: `scale(${zoom})` }}>
        <defs><linearGradient id={id} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor={a} /><stop offset="0.55" stopColor={b} /><stop offset="1" stopColor={c} /></linearGradient></defs>
        <rect x={-W * 0.1} width={W * 1.2} height={H} fill={`url(#${id})`} />
        <g transform={cam(0.3)}><circle cx={W * 0.5} cy={hz - H * 0.02} r={W * (tall ? 0.36 : 0.2)} fill={time === "night" ? "#e9e6cf" : "#ffd88a"} opacity={time === "night" ? 0.85 : 0.75} /></g>
        {time === "night" ? Array.from({ length: 60 }, (_, i) => <circle key={i} cx={rnd(i) * W} cy={rnd(i + 31) * hz * 0.7} r={1 + rnd(i + 5) * 1.6} fill="#fff" opacity={0.6} />) : null}
        {g.shape === "ship" ? <rect y={hz} width={W} height={H - hz} fill={ink} opacity={0.85} /> : <path d={`M0,${hz} C${W * 0.3},${hz - 18} ${W * 0.7},${hz + 14} ${W},${hz - 8} L${W},${H} L0,${H} Z`} fill={ink} />}
        <g transform={cam(1.2)}>{shape}</g>
      </svg>
      {g.text ? <div style={{ position: "absolute", top: tall ? 340 : 110, left: 60, right: 60, textAlign: "center", fontFamily: HEAD, fontWeight: 900,
        fontSize: tall ? 58 : 44, lineHeight: 1.15, color: "#fff", textShadow: "0 4px 24px rgba(0,0,0,0.45)", opacity: interpolate(t, [0.2, 0.8], [0, 1], { extrapolateRight: "clamp" }) }}>{g.text}</div> : null}
    </AbsoluteFill>
  );
};
