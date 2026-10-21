// 3D "reconstruction" scenes for subjects stock footage can't show correctly (a specific airline's plane, a specific car,
// named people). Low-poly, built from code (no downloaded models), coloured with the subject's scheme, never with logos or
// faces, so nothing on screen can be the wrong brand or a wrong likeness. Rendered with three.js inside Remotion.
import React, { useLayoutEffect, useMemo } from "react";
import { useThree } from "@react-three/fiber";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig, Easing } from "remotion";
import { ThreeCanvas } from "@remotion/three";
import * as THREE from "three";
import { HEAD, BODY, C } from "./theme";

export type ReconScene = "aircraft_flight" | "aircraft_landing" | "aircraft_ground" | "cabin" | "cockpit_door" | "vehicle_road" | "people" | "object";
export type Recon = {
  kind: "recon";
  scene: ReconScene;
  name?: string;                 // e.g. "flydubai Boeing 737-800" (shown as the subject label)
  colors?: string[];             // [body, accent, tail/trim]
  labels?: { text: string; sub?: string; row?: number; seat?: number }[];   // cabin: row 1-30, seat 0-5; people: index
  caption?: string;              // short line under the RECONSTRUCTION tag
  people?: number;               // people scene: how many figures
  model?: "airliner" | "fighter"; // aircraft scenes: which 3D model
  motion?: "cruise" | "dive" | "climb" | "unstable";   // aircraft_flight attitude, chosen from the narration
  altitude?: [number, number];   // HUD altimeter counting from -> to (feet), e.g. [30000, 15000]
  squawk?: string[];             // HUD transponder codes shown in turn, e.g. ["7700", "7500"]
  door?: "closed" | "open";      // cockpit_door: open shows an injured crew member (mannequin) in the doorway
};

const ease = (p: number) => (p < 0.5 ? 2 * p * p : 1 - Math.pow(-2 * p + 2, 2) / 2);
const col = (c: string | undefined, d: string) => (c && /^#[0-9a-f]{3,8}$/i.test(c) ? c : d);

// ---------------------------------------------------------------- shared pieces
const Std: React.FC<{ c: string; r?: number; m?: number; e?: string; ei?: number; side?: THREE.Side; op?: number }> = ({ c, r = 0.6, m = 0.05, e, ei = 0, side, op }) => (
  <meshStandardMaterial color={c} roughness={r} metalness={m} emissive={e || "#000"} emissiveIntensity={ei} side={side}
    transparent={op !== undefined} opacity={op ?? 1} />
);

// text label as a camera-facing sprite (drawn on a 2D canvas)
const Label: React.FC<{ text: string; sub?: string; pos: [number, number, number]; scale?: number; accent?: string }> = ({ text, sub, pos, scale = 1, accent = C.gold }) => {
  const tex = useMemo(() => {
    const cv = document.createElement("canvas"); cv.width = 1024; cv.height = sub ? 300 : 190;
    const g = cv.getContext("2d")!;
    g.fillStyle = "rgba(12,14,20,0.88)"; const r = 36;
    g.beginPath(); g.roundRect(8, 8, cv.width - 16, cv.height - 16, r); g.fill();
    g.fillStyle = accent; g.fillRect(8, 8, 18, cv.height - 16);
    const fit = (str: string, weight: number, size: number, fam: string) => {
      let z = size; g.font = `${weight} ${z}px ${fam}`;
      while (z > 30 && g.measureText(str).width > cv.width - 100) { z -= 4; g.font = `${weight} ${z}px ${fam}`; }
    };
    const T = text.toUpperCase().slice(0, 34), S = (sub || "").toUpperCase().slice(0, 44);
    g.fillStyle = "#fff"; g.textBaseline = "middle"; fit(T, 900, 92, "Montserrat, sans-serif");
    g.fillText(T, 60, sub ? 105 : cv.height / 2);
    if (sub) { g.fillStyle = "rgba(255,255,255,0.72)"; fit(S, 700, 60, "Inter, sans-serif"); g.fillText(S, 60, 215); }
    const t = new THREE.CanvasTexture(cv); t.anisotropy = 4; return t;
  }, [text, sub, accent]);
  const a = sub ? 300 / 1024 : 190 / 1024;
  return <sprite position={pos} scale={[2.4 * scale, 2.4 * scale * a, 1]}><spriteMaterial map={tex} depthTest={false} transparent /></sprite>;
};

// ---------------------------------------------------------------- airliner (narrow-body, ~37 m long; 1 unit = 1 m)
const Airliner: React.FC<{ colors?: string[]; gear?: boolean }> = ({ colors, gear = true }) => {
  const body = col(colors?.[0], "#f3f5f8"), accent = col(colors?.[1], "#2a5db0"), tail = col(colors?.[2], accent);
  const fus = useMemo(() => {
    // fuselage profile: radius along the length (x from tail -18 to nose +19), lathed around the x axis
    const pts: THREE.Vector2[] = [];
    const prof = (x: number) => {
      if (x > 14) { const u = (x - 14) / 5; return 2.0 * Math.sqrt(Math.max(0, 1 - u * u * 0.98)); }   // rounded nose
      if (x < -11) { const u = (-11 - x) / 7; return 2.0 * (1 - u * 0.82); }                           // tapered tail cone
      return 2.0;
    };
    for (let i = 0; i <= 80; i++) { const x = -18 + (37 * i) / 80; pts.push(new THREE.Vector2(Math.max(0.05, prof(x)), x)); }
    const g = new THREE.LatheGeometry(pts, 40); g.rotateZ(-Math.PI / 2); return g;
  }, []);
  const wing = useMemo(() => {
    const s = new THREE.Shape(); s.moveTo(0, 0); s.lineTo(-3.2, 16.5); s.lineTo(-5.0, 16.5); s.lineTo(-6.0, 0); s.closePath();
    const g = new THREE.ExtrudeGeometry(s, { depth: 0.35, bevelEnabled: false }); g.rotateX(Math.PI / 2); return g;
  }, []);
  const fin = useMemo(() => {
    const s = new THREE.Shape(); s.moveTo(0, 0); s.lineTo(-4.2, 7.2); s.lineTo(-6.2, 7.2); s.lineTo(-6.6, 0); s.closePath();
    return new THREE.ExtrudeGeometry(s, { depth: 0.3, bevelEnabled: false });
  }, []);
  const stab = useMemo(() => {
    const s = new THREE.Shape(); s.moveTo(0, 0); s.lineTo(-2.0, 6.2); s.lineTo(-3.2, 6.2); s.lineTo(-3.6, 0); s.closePath();
    const g = new THREE.ExtrudeGeometry(s, { depth: 0.2, bevelEnabled: false }); g.rotateX(Math.PI / 2); return g;
  }, []);
  const windows = useMemo(() => Array.from({ length: 26 }, (_, i) => -9 + i * 0.95), []);
  const Engine: React.FC<{ z: number }> = ({ z }) => (
    <group position={[3.2, -1.7, z]}>
      <mesh rotation={[0, 0, Math.PI / 2]}><cylinderGeometry args={[0.95, 0.85, 3.6, 28, 1, true]} /><Std c={accent} r={0.35} m={0.3} side={THREE.DoubleSide} /></mesh>
      <mesh position={[1.75, 0, 0]} rotation={[0, 0, Math.PI / 2]}><circleGeometry args={[0.9, 28]} /><Std c="#1b1f27" r={0.5} /></mesh>
      <mesh position={[1.6, 0, 0]} rotation={[0, 0, Math.PI / 2]}><coneGeometry args={[0.3, 0.6, 16]} /><Std c="#c9ced6" m={0.6} r={0.3} /></mesh>
      <mesh position={[-0.6, 0.8, 0]}><boxGeometry args={[2.4, 0.5, 0.25]} /><Std c={body} /></mesh>
    </group>
  );
  return (
    <group>
      <mesh geometry={fus}><Std c={body} r={0.35} m={0.15} /></mesh>
      {/* belly / cheatline in the accent colour */}
      <mesh position={[-1, -0.65, 0]} rotation={[0, 0, Math.PI / 2]} scale={[1, 1, 1]}><cylinderGeometry args={[1.62, 1.62, 26, 40, 1, true, Math.PI * 0.62, Math.PI * 0.76]} /><Std c={accent} r={0.4} side={THREE.DoubleSide} /></mesh>
      {/* cabin windows both sides */}
      {windows.map((x) => [1.98, -1.98].map((z) => (
        <mesh key={x + "_" + z} position={[x, 0.45, z]}><boxGeometry args={[0.32, 0.42, 0.06]} /><Std c="#202634" r={0.2} m={0.4} /></mesh>
      )))}
      {/* cockpit windows */}
      {[-0.55, 0.55].map((z) => <mesh key={z} position={[16.6, 0.75, z]} rotation={[0, z > 0 ? -0.5 : 0.5, 0.35]}><boxGeometry args={[0.9, 0.4, 0.5]} /><Std c="#151a24" r={0.1} m={0.6} /></mesh>)}
      {/* wings (right z>0, left mirrored) */}
      <group position={[3.8, -1.1, 0]} rotation={[0.08, 0, 0]}><mesh geometry={wing}><Std c="#c4cad3" r={0.45} m={0.25} /></mesh></group>
      <group position={[3.8, -1.1, 0]} rotation={[-0.08, 0, 0]} scale={[1, 1, -1]}><mesh geometry={wing}><Std c="#c4cad3" r={0.45} m={0.25} side={THREE.DoubleSide} /></mesh></group>
      {/* winglets in the tail colour */}
      {[16.4, -16.4].map((z) => <mesh key={z} position={[-0.3, 0.3, z]} rotation={[z > 0 ? -0.25 : 0.25, 0, 0]}><boxGeometry args={[1.6, 2.2, 0.15]} /><Std c={tail} /></mesh>)}
      <Engine z={5.6} /><Engine z={-5.6} />
      {/* vertical fin + stabilisers */}
      <group position={[-11.2, 1.3, -0.15]}><mesh geometry={fin}><Std c={tail} r={0.4} /></mesh></group>
      <group position={[-13.6, 0.4, 0]}><mesh geometry={stab}><Std c="#dfe3ea" /></mesh></group>
      <group position={[-13.6, 0.4, 0]} scale={[1, 1, -1]}><mesh geometry={stab}><Std c="#dfe3ea" side={THREE.DoubleSide} /></mesh></group>
      {gear ? <>
        {[[13.5, 0], [1.2, 2.6], [1.2, -2.6]].map(([x, z], i) => (
          <group key={i} position={[x, -2.6, z]}>
            <mesh position={[0, 0.6, 0]}><cylinderGeometry args={[0.12, 0.12, 1.4, 8]} /><Std c="#8a919c" m={0.5} /></mesh>
            <mesh rotation={[Math.PI / 2, 0, 0]} position={[0, -0.25, 0]}><cylinderGeometry args={[0.5, 0.5, 0.45, 18]} /><Std c="#16181d" r={0.9} /></mesh>
          </group>
        ))}
      </> : null}
    </group>
  );
};

// ---------------------------------------------------------------- fighter jet (single-seat, ~16 m; generic, no markings)
const Fighter: React.FC<{ colors?: string[] }> = ({ colors }) => {
  const body = col(colors?.[0], "#7d8590"), dark = col(colors?.[1], "#4a5058");
  const wing = useMemo(() => {   // delta wing, both sides in one shape (top view, x forward)
    const s = new THREE.Shape(); s.moveTo(2.5, 0.9); s.lineTo(-3.2, 5.4); s.lineTo(-4.6, 5.4); s.lineTo(-4.8, 0.9);
    s.lineTo(-4.8, -0.9); s.lineTo(-4.6, -5.4); s.lineTo(-3.2, -5.4); s.lineTo(2.5, -0.9); s.closePath();
    const g = new THREE.ExtrudeGeometry(s, { depth: 0.18, bevelEnabled: false }); g.rotateX(Math.PI / 2); return g;
  }, []);
  const fin = useMemo(() => {
    const s = new THREE.Shape(); s.moveTo(0, 0); s.lineTo(-1.6, 2.4); s.lineTo(-2.6, 2.4); s.lineTo(-2.8, 0); s.closePath();
    return new THREE.ExtrudeGeometry(s, { depth: 0.12, bevelEnabled: false });
  }, []);
  return (
    <group>
      {/* fuselage + nose cone + intake shoulders */}
      <mesh rotation={[0, 0, -Math.PI / 2]}><cylinderGeometry args={[0.85, 0.75, 11, 20]} /><Std c={body} r={0.6} m={0.3} /></mesh>
      <mesh position={[7.6, 0, 0]} rotation={[0, 0, -Math.PI / 2]}><coneGeometry args={[0.85, 4.2, 20]} /><Std c={body} r={0.6} m={0.3} /></mesh>
      {[0.95, -0.95].map((z) => <mesh key={z} position={[1.2, -0.1, z]}><boxGeometry args={[5.5, 1.1, 0.6]} /><Std c={body} r={0.6} m={0.3} /></mesh>)}
      {/* canopy */}
      <mesh position={[4.4, 0.75, 0]} scale={[2.2, 0.55, 0.6]}><sphereGeometry args={[1, 20, 14]} /><Std c="#2a3a4a" r={0.1} m={0.7} /></mesh>
      <group position={[0, -0.2, 0]}><mesh geometry={wing}><Std c={body} r={0.6} m={0.3} side={THREE.DoubleSide} /></mesh></group>
      {/* twin canted tails + tailplanes */}
      {[0.75, -0.75].map((z) => <group key={z} position={[-3.0, 0.5, z]} rotation={[z > 0 ? 0.35 : -0.35, 0, 0]}><mesh geometry={fin}><Std c={dark} r={0.6} m={0.3} /></mesh></group>)}
      {[1, -1].map((sgn) => <mesh key={sgn} position={[-5.0, 0, sgn * 2.0]}><boxGeometry args={[1.8, 0.12, 2.2]} /><Std c={body} /></mesh>)}
      {/* exhaust with afterburner glow */}
      <mesh position={[-5.6, 0, 0]} rotation={[0, 0, Math.PI / 2]}><cylinderGeometry args={[0.55, 0.6, 0.6, 18]} /><Std c="#2b2b2b" m={0.6} /></mesh>
      <mesh position={[-6.3, 0, 0]} rotation={[0, 0, Math.PI / 2]}><coneGeometry args={[0.45, 1.6, 16]} /><Std c="#ffb347" e="#ff8a00" ei={2} op={0.7} /></mesh>
    </group>
  );
};

// ---------------------------------------------------------------- environments
const Lights: React.FC<{ sky?: string; ground?: string; sun?: number }> = ({ sky = "#cfe3ff", ground = "#c9a77a", sun = 2.2 }) => (
  <>
    <hemisphereLight args={[sky, ground, 1.1]} />
    <directionalLight position={[30, 50, 20]} intensity={sun} />
    <directionalLight position={[-30, 10, -20]} intensity={0.35} color="#9fb8ff" />
  </>
);

const Desert: React.FC = () => {
  const dunes = useMemo(() => {
    const g = new THREE.PlaneGeometry(2400, 2400, 120, 120); g.rotateX(-Math.PI / 2);
    const p = g.attributes.position as THREE.BufferAttribute;
    for (let i = 0; i < p.count; i++) {
      const x = p.getX(i), z = p.getZ(i); const d = Math.hypot(x, z);
      const h = d < 160 ? 0 : (Math.sin(x * 0.012) * Math.cos(z * 0.009) * 14 + Math.sin(x * 0.031 + z * 0.02) * 5) * Math.min(1, (d - 160) / 300);
      p.setY(i, h - 2.7);
    }
    g.computeVertexNormals(); return g;
  }, []);
  return (
    <>
      <mesh geometry={dunes}><Std c="#d2b07e" r={1} /></mesh>
      {/* distant mesas */}
      {[[-500, -900, 90], [300, -1000, 60], [900, -700, 120], [-1000, -400, 70]].map(([x, z, h], i) => (
        <mesh key={i} position={[x, h / 2 - 3, z]}><cylinderGeometry args={[h * 1.6, h * 2.2, h, 7]} /><Std c="#b98a5c" r={1} /></mesh>
      ))}
    </>
  );
};

const Runway: React.FC = () => (
  <group position={[0, -2.68, 0]}>
    <mesh rotation={[-Math.PI / 2, 0, 0]}><planeGeometry args={[1400, 46]} /><Std c="#3a3d42" r={0.95} /></mesh>
    {Array.from({ length: 60 }, (_, i) => (
      <mesh key={i} rotation={[-Math.PI / 2, 0, 0]} position={[-700 + i * 24, 0.02, 0]}><planeGeometry args={[12, 0.9]} /><Std c="#f2f2f2" r={0.8} /></mesh>
    ))}
    {[-21, 21].map((z) => <mesh key={z} rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.02, z]}><planeGeometry args={[1400, 0.6]} /><Std c="#f2f2f2" /></mesh>)}
    {/* edge lights */}
    {Array.from({ length: 70 }, (_, i) => [-24, 24].map((z) => (
      <mesh key={i + "_" + z} position={[-700 + i * 20, 0.3, z]}><sphereGeometry args={[0.25, 8, 8]} /><Std c="#ffe6a0" e="#ffcf5a" ei={1.5} /></mesh>
    )))}
  </group>
);

const Clouds: React.FC<{ t: number }> = ({ t }) => {
  const puffs = useMemo(() => {
    const out: [number, number, number, number][] = []; let s = 7;
    const rnd = () => ((s = (s * 9301 + 49297) % 233280) / 233280);
    for (let i = 0; i < 140; i++) out.push([rnd() * 1600 - 800, -40 - rnd() * 25, rnd() * 1600 - 800, 18 + rnd() * 30]);
    return out;
  }, []);
  return (
    <group position={[-t * 60, 0, 0]}>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -55, 0]}><planeGeometry args={[6000, 6000]} /><Std c="#e8eef6" r={1} /></mesh>
      {puffs.map(([x, y, z, r], i) => <mesh key={i} position={[x, y, z]} scale={[1.6, 0.55, 1.2]}><sphereGeometry args={[r, 14, 10]} /><Std c="#ffffff" r={1} /></mesh>)}
    </group>
  );
};

// a seated or standing mannequin (no face)
const Mannequin: React.FC<{ pos: [number, number, number]; seated?: boolean; hi?: string; rot?: number }> = ({ pos, seated = true, hi, rot = 0 }) => {
  const c = hi || "#e9e9ec";
  return (
    <group position={pos} rotation={[0, rot, 0]}>
      <mesh position={[0, seated ? 0.62 : 1.05, 0]}><capsuleGeometry args={[0.2, seated ? 0.42 : 0.62, 6, 14]} /><Std c={c} r={0.8} e={hi} ei={hi ? 0.25 : 0} /></mesh>
      <mesh position={[0, seated ? 1.12 : 1.7, 0]}><sphereGeometry args={[0.15, 18, 14]} /><Std c={c} r={0.8} e={hi} ei={hi ? 0.25 : 0} /></mesh>
      {!seated ? [-0.1, 0.1].map((x) => <mesh key={x} position={[x, 0.42, 0]}><capsuleGeometry args={[0.08, 0.6, 4, 8]} /><Std c={c} r={0.8} /></mesh>) : null}
    </group>
  );
};

// cabin: 3+3 seats, rows along -z (row 1 nearest the cockpit at the far end)
const ROWS = 30, PITCH = 0.82;
const seatPos = (row: number, seat: number): [number, number, number] => {
  const x = [-1.55, -1.05, -0.55, 0.55, 1.05, 1.55][Math.max(0, Math.min(5, seat))];
  return [x, 0, -(row - 1) * PITCH];
};
const Cabin: React.FC<{ accent: string; labels?: Recon["labels"]; door?: boolean; open?: boolean; t: number }> = ({ accent, labels, door, open, t }) => {
  const hiSeats = new Set((labels || []).map((l) => `${l.row ?? 13}_${l.seat ?? 2}`));
  return (
    <group>
      {/* floor, aisle carpet, walls, ceiling */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0, -12]}><planeGeometry args={[4.2, 34]} /><Std c="#8d929b" r={1} /></mesh>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.01, -12]}><planeGeometry args={[0.6, 34]} /><Std c={accent} r={1} /></mesh>
      <mesh position={[0, 1.15, -12]} rotation={[Math.PI / 2, 0, 0]}><cylinderGeometry args={[2.15, 2.15, 34, 40, 1, true, Math.PI * 0.5, Math.PI]} /><Std c="#eef0f3" r={0.9} side={THREE.BackSide} e="#ffffff" ei={0.25} /></mesh>
      {/* overhead bins */}
      {[-1.45, 1.45].map((x) => <mesh key={x} position={[x, 2.25, -12]}><boxGeometry args={[1.0, 0.45, 34]} /><Std c="#f6f7f9" r={0.7} e="#ffffff" ei={0.35} /></mesh>)}
      {/* ceiling light strip */}
      <mesh position={[0, 2.95, -12]}><boxGeometry args={[0.5, 0.04, 34]} /><Std c="#fff" e="#fff6e0" ei={0.9} /></mesh>
      {/* windows */}
      {Array.from({ length: ROWS }, (_, i) => [-2.08, 2.08].map((x) => (
        <mesh key={i + "_" + x} position={[x, 1.25, -i * PITCH]} rotation={[0, x > 0 ? -Math.PI / 2 : Math.PI / 2, 0]}><planeGeometry args={[0.28, 0.38]} /><Std c="#9cc4ff" e="#bcd8ff" ei={0.6} /></mesh>
      )))}
      {/* seats + passengers */}
      {Array.from({ length: ROWS }, (_, r) => [0, 1, 2, 3, 4, 5].map((s) => {
        const [x, , z] = seatPos(r + 1, s); const hi = hiSeats.has(`${r + 1}_${s}`);
        const filled = ((r * 7 + s * 3) % 5) !== 0 || hi;
        return (
          <group key={r + "_" + s}>
            <mesh position={[x, 0.42, z]}><boxGeometry args={[0.46, 0.14, 0.48]} /><Std c="#4b5263" r={0.9} /></mesh>
            <mesh position={[x, 0.85, z + 0.24]}><boxGeometry args={[0.46, 0.85, 0.1]} /><Std c="#4b5263" r={0.9} /></mesh>
            <mesh position={[x, 1.2, z + 0.24]}><boxGeometry args={[0.4, 0.14, 0.12]} /><Std c="#d8dbe0" r={0.9} /></mesh>
            {filled ? <Mannequin pos={[x, 0.15, z + 0.05]} hi={hi ? C.gold : undefined} /> : null}
          </group>
        );
      }))}
      {/* front bulkhead + cockpit door */}
      <mesh position={[0, 1.4, -(ROWS + 1.5) * PITCH]}><boxGeometry args={[4.2, 2.9, 0.1]} /><Std c="#dfe2e7" /></mesh>
      {/* cockpit door: closed in the bulkhead, or swung open into the cabin with the flight deck lit behind it */}
      {door && open ? <>
        <mesh position={[-0.42, 1.05, -(ROWS + 1.5) * PITCH + 0.45]} rotation={[0, -1.2, 0]}><boxGeometry args={[0.85, 1.95, 0.05]} /><Std c="#c9ccd2" r={0.5} m={0.3} /></mesh>
        <mesh position={[0, 1.05, -(ROWS + 1.5) * PITCH + 0.03]}><planeGeometry args={[0.85, 1.95]} /><Std c="#ffd9a0" e="#ffcf80" ei={0.9} /></mesh>
      </> : <mesh position={[0, 1.05, -(ROWS + 1.5) * PITCH + 0.06]}><boxGeometry args={[0.85, 1.95, 0.05]} /><Std c={door ? "#c9ccd2" : "#d6d9de"} r={0.5} m={0.3} /></mesh>}
      {door ? <mesh position={[0, 2.2, -(ROWS + 1.5) * PITCH + 0.1]}><boxGeometry args={[0.5, 0.12, 0.02]} /><Std c="#ff3b3b" e="#ff2020" ei={1 + Math.sin(t * 6) * 0.8} /></mesh> : null}
      {door && open ? <group position={[0.9, 0.22, -(ROWS + 1.5) * PITCH + 0.75]} rotation={[0, 0, Math.PI / 2]}>
        {/* injured crew member lying in the open doorway (faceless mannequin, highlighted) */}
        <Mannequin pos={[0, 0, 0]} seated={false} hi="#e05252" />
      </group> : null}
      {(labels || []).map((l, i) => {
        const [x, , z] = seatPos(l.row ?? 13, l.seat ?? 2);
        return <Label key={i} text={l.text} sub={l.sub ?? `Row ${l.row ?? 13}`} pos={[x, 1.85, z]} scale={0.8} />;
      })}
    </group>
  );
};

// ---------------------------------------------------------------- vehicle (low-poly SUV / car)
const Vehicle: React.FC<{ colors?: string[]; t: number }> = ({ colors, t }) => {
  const body = col(colors?.[0], "#9aa3ad"), trim = col(colors?.[1], "#20242b");
  const shell = useMemo(() => {
    const s = new THREE.Shape();
    s.moveTo(-2.4, 0.35); s.lineTo(2.35, 0.35); s.lineTo(2.4, 0.95); s.lineTo(1.4, 1.1); s.lineTo(0.8, 1.75); s.lineTo(-1.9, 1.78); s.lineTo(-2.4, 1.2); s.closePath();
    const g = new THREE.ExtrudeGeometry(s, { depth: 1.85, bevelEnabled: true, bevelSize: 0.08, bevelThickness: 0.08, bevelSegments: 3 });
    g.translate(0, 0, -0.925); return g;
  }, []);
  return (
    <group>
      <mesh geometry={shell}><Std c={body} r={0.3} m={0.4} /></mesh>
      {/* glasshouse */}
      <mesh position={[-0.55, 1.45, 0]}><boxGeometry args={[2.3, 0.42, 2.03]} /><Std c="#1c2230" r={0.1} m={0.6} /></mesh>
      {[[1.55, 1.0], [-1.65, 1.0], [1.55, -1.0], [-1.65, -1.0]].map(([x, z], i) => (
        <group key={i} position={[x, 0.36, z]} rotation={[Math.PI / 2, t * 12, 0]}>
          <mesh><cylinderGeometry args={[0.4, 0.4, 0.3, 22]} /><Std c="#15171b" r={0.9} /></mesh>
          <mesh position={[0, 0.15, 0]}><cylinderGeometry args={[0.22, 0.22, 0.02, 12]} /><Std c="#b9bec6" m={0.7} r={0.3} /></mesh>
        </group>
      ))}
      {/* windscreen along the slope, rear window, grille */}
      <mesh position={[1.2, 1.51, 0]} rotation={[0, 0, 2.31]}><boxGeometry args={[0.9, 0.05, 1.72]} /><Std c="#1c2230" r={0.1} m={0.6} /></mesh>
      <mesh position={[-2.25, 1.52, 0]} rotation={[0, 0, -1.1]}><boxGeometry args={[0.55, 0.05, 1.6]} /><Std c="#1c2230" r={0.1} m={0.6} /></mesh>
      <mesh position={[2.5, 0.66, 0]}><boxGeometry args={[0.05, 0.3, 1.3]} /><Std c={trim} r={0.6} /></mesh>
      {[0.62, -0.62].map((z) => <mesh key={z} position={[2.5, 0.88, z]}><boxGeometry args={[0.04, 0.1, 0.35]} /><Std c="#fff" e="#fff8e0" ei={1.2} /></mesh>)}
    </group>
  );
};

const Road: React.FC<{ t: number }> = ({ t }) => (
  <group>
    <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.01, 0]}><planeGeometry args={[3000, 3000]} /><Std c="#6f8a5a" r={1} /></mesh>
    <mesh rotation={[-Math.PI / 2, 0, 0]}><planeGeometry args={[3000, 9]} /><Std c="#3b3e44" r={0.95} /></mesh>
    <group position={[-((t * 22) % 12), 0, 0]}>
      {Array.from({ length: 200 }, (_, i) => <mesh key={i} rotation={[-Math.PI / 2, 0, 0]} position={[-1200 + i * 12, 0.01, 0]}><planeGeometry args={[5, 0.18]} /><Std c="#f4f4f4" /></mesh>)}
    </group>
    <group position={[-((t * 22) % 30), 0, 0]}>
      {Array.from({ length: 100 }, (_, i) => [-14, 14].map((z) => (
        <group key={i + "_" + z} position={[-1500 + i * 30, 0, z + (i % 3) * 3]}>
          <mesh position={[0, 1.2, 0]}><cylinderGeometry args={[0.15, 0.2, 2.4, 6]} /><Std c="#6b4f35" /></mesh>
          <mesh position={[0, 3.2, 0]}><coneGeometry args={[1.4, 3.4, 7]} /><Std c="#3f6b3a" r={1} /></mesh>
        </group>
      )))}
    </group>
  </group>
);

// ---------------------------------------------------------------- camera + scene graph
const Cam: React.FC<{ pos: [number, number, number]; look: [number, number, number]; fov?: number }> = ({ pos, look, fov = 45 }) => {
  const set = useThree((s) => s.set); const size = useThree((s) => s.size);
  const cam = useMemo(() => new THREE.PerspectiveCamera(fov, 1, 0.1, 6000), []);
  useLayoutEffect(() => { set({ camera: cam }); }, [cam, set]);
  cam.fov = fov; cam.aspect = size.width / Math.max(1, size.height);
  cam.position.set(...pos); cam.lookAt(...look); cam.updateProjectionMatrix();
  return null;
};

const SceneGraph: React.FC<{ r: Recon; t: number; p: number; tall: boolean }> = ({ r, t, p, tall }) => {
  const accent = col(r.colors?.[1], "#2a5db0");
  const e = ease(p);
  switch (r.scene) {
    case "aircraft_flight": {
      const fighter = r.model === "fighter", dive = r.motion === "dive", climb = r.motion === "climb", wobble = r.motion === "unstable";
      const a = -0.9 + e * 0.9;
      const d = (tall ? 62 : 48) * (fighter ? 0.55 : 1);
      // dive: the nose drops to ~25 degrees and the aircraft sinks while the camera follows it down
      // pitch (+ = nose up), height change and bank for each attitude; "unstable" = erratic pitching and rolling
      const pitch = dive ? -interpolate(e, [0, 0.35, 1], [0, 0.42, 0.45]) : climb ? interpolate(e, [0, 0.4, 1], [0, 0.2, 0.22])
                  : wobble ? -(0.09 * (1 + Math.sin(t * 2.3)) + 0.03 * (1 + Math.sin(t * 5.1))) : 0;   // unstable: level to ~14 deg nose-down, never up
      const sink = dive ? -interpolate(p, [0, 1], [0, 60]) : climb ? interpolate(p, [0, 1], [0, 25]) : wobble ? -interpolate(p, [0, 1], [0, 18]) - 0.6 * (1 + Math.sin(t * 1.7)) : 0;   // unstable: sinks, never rises
      const bank = dive ? 0.12 * Math.sin(t * 0.7) : wobble ? 0.35 * Math.sin(t * 1.9) + 0.15 * Math.sin(t * 4.3) : 0.04 * Math.sin(t * 0.6);
      return (<>
        <color attach="background" args={[dive ? "#6f9fd6" : "#7fb2ec"]} /><fog attach="fog" args={["#cfe2f7", 200, 1600]} />
        <Lights sky="#d6e8ff" ground="#ffffff" />
        {dive || climb || wobble ? <Cam pos={[6, sink + 3, tall ? 62 : 48]} look={[0, sink + (climb ? 3 : -3), 0]} fov={tall ? 55 : 40} />   /* side view: the attitude is visible */
              : <Cam pos={[Math.cos(a) * d, 9 + e * 3, Math.sin(a) * d + 6]} look={[2, 0, 0]} fov={tall ? 55 : 40} />}
        <group rotation={[0.03 * Math.sin(t * 0.8), 0, climb ? pitch + bank * 0.2 : Math.min(0, pitch + bank * 0.2)]} position={[0, Math.sin(t * 0.9) * 0.4 + sink, 0]}>{/* nose-up only when climbing */}
          <group rotation={[bank, 0, 0]}>{fighter ? <Fighter colors={r.colors} /> : <Airliner colors={r.colors} gear={false} />}</group>
        </group>
        {fighter ? <group position={[-14, 2 + sink, -12]} rotation={[0.05 * Math.sin(t), 0, 0]}><Fighter colors={r.colors} /></group> : null}
        <group position={[0, dive ? -interpolate(p, [0, 1], [0, 40]) : 0, 0]}><Clouds t={t * (fighter ? 2.5 : 1)} /></group>
        {r.name ? <Label text={r.name} sub={r.labels?.[0]?.text} pos={[0, 9, 0]} scale={tall ? 5.5 : 4.2} /> : null}
      </>);
    }
    case "aircraft_landing": {
      const x = interpolate(p, [0, 1], [-260, 40]); const y = interpolate(p, [0, 0.75, 1], [26, 0.05, 0], { extrapolateRight: "clamp", easing: Easing.out(Easing.quad) });
      const pitch = interpolate(p, [0, 0.7, 0.85, 1], [0.03, 0.08, 0.06, 0], { extrapolateRight: "clamp" });
      return (<>
        <color attach="background" args={["#e9c99a"]} /><fog attach="fog" args={["#efd6ae", 300, 2000]} />
        <Lights sky="#ffe8c4" ground="#c9a06a" sun={2.6} />
        <Cam pos={[x + (tall ? 38 : 55), tall ? 10 : 14, tall ? 44 : 55]} look={[x, y, 0]} fov={tall ? 56 : 38} />
        <group position={[x, y, 0]} rotation={[0, 0, pitch]}>{r.model === "fighter" ? <Fighter colors={r.colors} /> : <Airliner colors={r.colors} />}</group>
        <Runway /><Desert />
        {r.name ? <Label text={r.name} sub={r.labels?.[0]?.text} pos={[x, y + 10, 0]} scale={tall ? 5.5 : 4.2} /> : null}
      </>);
    }
    case "aircraft_ground": {
      const a = 0.6 + e * 0.8;
      return (<>
        <color attach="background" args={["#e7cfa6"]} /><fog attach="fog" args={["#efd9b5", 250, 1800]} />
        <Lights sky="#fff0d6" ground="#c9a06a" sun={2.6} />
        <Cam pos={[Math.cos(a) * 52, 4 + e * 4, Math.sin(a) * 52]} look={[0, 0, 0]} fov={tall ? 55 : 40} />
        <Airliner colors={r.colors} />
        <Runway /><Desert />
        {/* apron vehicles: a police / security car and stairs */}
        <group position={[8, -2.68, 12]} rotation={[0, 0.9, 0]} scale={0.9}><Vehicle colors={["#ffffff", "#1c3f8f"]} t={0} /></group>
        <mesh position={[11, -1.6, 2.6]} rotation={[0, 0, -0.5]}><boxGeometry args={[4.4, 0.25, 1.2]} /><Std c="#cfd3d9" m={0.4} /></mesh>
        {r.name ? <Label text={r.name} sub={r.labels?.[0]?.text} pos={[0, 11, 0]} scale={tall ? 5.5 : 4.2} /> : null}
      </>);
    }
    case "cabin":
    case "cockpit_door": {
      const door = r.scene === "cockpit_door";
      const target = r.labels?.[0]?.row ?? 13;
      const z0 = door ? -16 : 3, z1 = door ? -(ROWS - (r.door === "open" ? 6 : 3)) * PITCH : -(target - 1) * PITCH + 4.2;
      const z = interpolate(e, [0, 1], [z0, z1]);
      return (<>
        <color attach="background" args={["#d9dde3"]} /><fog attach="fog" args={["#d9dde3", 6, 30]} />
        <hemisphereLight args={["#ffffff", "#b6bcc6", 1.4]} /><directionalLight position={[0, 5, 2]} intensity={0.8} />
        <Cam pos={[0.35, 2.15, z]} look={[0, 1.1, z - 10]} fov={tall ? 70 : 58} />
        <Cabin accent={accent} labels={r.labels} door={door} open={r.door === "open"} t={t} />
        {door ? <Label text="Cockpit" sub={r.door === "open" ? "Crew member injured" : "Door locked"} pos={[0, 2.55, -(ROWS + 1.5) * PITCH + 0.2]} scale={0.6} accent={C.red} /> : null}
      </>);
    }
    case "vehicle_road": {
      const a = -0.5 + e * 1.1;
      return (<>
        <color attach="background" args={["#a9cdf0"]} /><fog attach="fog" args={["#cfe2f2", 60, 600]} />
        <Lights sky="#e0efff" ground="#7c8f62" />
        <Cam pos={[Math.cos(a) * 9, 2.2, Math.sin(a) * 9 + 1]} look={[0, 0.9, 0]} fov={tall ? 60 : 42} />
        <Vehicle colors={r.colors} t={t} /><Road t={t} />
        {r.name ? <Label text={r.name} sub={r.labels?.[0]?.text} pos={[0, 3.2, 0]} scale={tall ? 1.4 : 1.1} /> : null}
      </>);
    }
    case "people": {
      const n = Math.max(1, Math.min(7, r.people ?? Math.max(1, r.labels?.length || 3)));
      const a = -0.3 + e * 0.6;
      return (<>
        <color attach="background" args={["#2a2f3a"]} /><fog attach="fog" args={["#2a2f3a", 8, 30]} />
        <hemisphereLight args={["#ffffff", "#40465a", 1.2]} /><spotLight position={[0, 8, 4]} angle={0.7} penumbra={0.6} intensity={60} />
        <Cam pos={[Math.sin(a) * 6.5, 1.8, Math.cos(a) * 6.5]} look={[0, 1.1, 0]} fov={tall ? 55 : 40} />
        <mesh rotation={[-Math.PI / 2, 0, 0]}><circleGeometry args={[6, 48]} /><Std c="#3a404d" r={0.9} /></mesh>
        {Array.from({ length: n }, (_, i) => {
          const x = (i - (n - 1) / 2) * 1.1; const l = r.labels?.[i];
          return (<group key={i}>
            <Mannequin pos={[x, 0, (i % 2) * -0.4]} seated={false} hi={l ? (i === 0 ? C.gold : "#9fd3ff") : undefined} />
            {l ? <Label text={l.text} sub={l.sub} pos={[x, 2.35 + (i % 2) * 0.35, 0]} scale={0.55} accent={i === 0 ? C.gold : "#9fd3ff"} /> : null}
          </group>);
        })}
      </>);
    }
    default: {
      return (<>
        <color attach="background" args={["#20242d"]} />
        <hemisphereLight args={["#ffffff", "#40465a", 1.3]} /><directionalLight position={[3, 6, 4]} intensity={1.5} />
        <Cam pos={[Math.sin(t * 0.3) * 6, 2.5, Math.cos(t * 0.3) * 6]} look={[0, 1, 0]} fov={45} />
        <mesh position={[0, 0.5, 0]}><cylinderGeometry args={[1.4, 1.6, 1, 32]} /><Std c="#3a404d" /></mesh>
        <mesh position={[0, 1.6, 0]} rotation={[t * 0.4, t * 0.6, 0]}><icosahedronGeometry args={[0.8, 0]} /><Std c={accent} m={0.3} r={0.4} /></mesh>
        {r.name ? <Label text={r.name} pos={[0, 3, 0]} scale={1} /> : null}
      </>);
    }
  }
};

export const ReconBackdrop: React.FC<{ g: Recon; dur: number }> = ({ g, dur }) => {
  const f = useCurrentFrame(); const { fps, width, height } = useVideoConfig(); const t = f / fps;
  const p = Math.min(1, t / Math.max(dur, 0.1)); const tall = height > width;
  return (
    <AbsoluteFill style={{ background: "#0b0f17" }}>
      <ThreeCanvas width={width} height={height} gl={{ antialias: true, preserveDrawingBuffer: true }} linear={false}>
        <SceneGraph r={g} t={t} p={p} tall={tall} />
      </ThreeCanvas>
      {g.altitude || g.squawk?.length ? (() => {
        // cockpit-style readouts: altitude counting down, transponder codes in turn
        const alt = g.altitude ? Math.round(interpolate(p, [0.05, 0.9], g.altitude, { extrapolateLeft: "clamp", extrapolateRight: "clamp" }) / 100) * 100 : null;
        const codes = g.squawk || []; const ci = codes.length ? Math.min(codes.length - 1, Math.floor(p * codes.length)) : -1;
        const box: React.CSSProperties = { fontFamily: "'Courier New', monospace", fontWeight: 700, color: "#7CFF8A", background: "rgba(5,10,8,0.82)",
          border: "2px solid rgba(124,255,138,0.6)", borderRadius: 10, padding: tall ? "14px 22px" : "10px 18px", fontSize: tall ? 44 : 34, lineHeight: 1.15 };
        return <div style={{ position: "absolute", left: tall ? 40 : 48, top: tall ? 330 : 40, display: "flex", flexDirection: "column", gap: 14 }}>
          {alt !== null ? <div style={box}><div style={{ fontSize: tall ? 22 : 18, opacity: 0.75 }}>ALTITUDE</div>{alt.toLocaleString("en-US")} ft</div> : null}
          {ci >= 0 ? <div style={{ ...box, color: Math.floor(t * 2) % 2 ? "#ff5a5a" : "#ffd25a", borderColor: "rgba(255,90,90,0.7)" }}>
            <div style={{ fontSize: tall ? 22 : 18, opacity: 0.75, color: "#ffd25a" }}>SQUAWK</div>{codes[ci]}</div> : null}
        </div>;
      })() : null}
      {g.caption ? <div style={{ position: "absolute", left: 0, right: 0, top: tall ? 1240 : undefined, bottom: tall ? undefined : 70, textAlign: "center" }}>
        <span style={{ fontFamily: HEAD, fontWeight: 900, fontSize: tall ? 40 : 36, color: "#111", background: C.gold, borderRadius: 999, padding: "10px 30px" }}>{g.caption}</span>
      </div> : null}
    </AbsoluteFill>
  );
};
