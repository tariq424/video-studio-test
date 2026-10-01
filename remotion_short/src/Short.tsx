import React from 'react';
import {AbsoluteFill, Sequence, Audio, Img, OffthreadVideo, staticFile, useCurrentFrame, useVideoConfig,
  interpolate, spring, Easing} from 'remotion';

export const FPS = 30;
type Word = {w: string; s: number; e: number};
export type Scene = {id: string; vo: string; tpl: string; data: any; bg: {type: string; src: string}; dur: number; words: Word[]};
export type ShortProps = {scenes: Scene[]};
const PAD = 0.35;
export const sceneFrames = (s: Scene) => Math.ceil((s.dur + PAD + (s.tpl === 'cta' ? 1.8 : 0)) * FPS);

const FONT = '"Segoe UI", "Arial Black", Arial, sans-serif';
const GOLD = '#FFC83D';
const ACC = '#FF4D4D';
const shadow = '0 6px 24px rgba(0,0,0,.65), 0 2px 4px rgba(0,0,0,.8)';

// ---------- background ----------
const Background: React.FC<{bg: Scene['bg']; frames: number; k: number}> = ({bg, frames, k}) => {
  const f = useCurrentFrame();
  const t = f / Math.max(1, frames);
  const zoom = 1.06 + 0.12 * t;
  const dx = (k % 2 === 0 ? 1 : -1) * 30 * t;
  const style: React.CSSProperties = {width: '100%', height: '100%', objectFit: 'cover', transform: `scale(${zoom}) translateX(${dx}px)`};
  return (
    <AbsoluteFill>
      {bg.type === 'motion'
        ? <OffthreadVideo src={staticFile(bg.src)} muted style={{...style, transformOrigin: (bg as any).cropTop ? '50% 100%' : '50% 50%',
            transform: `scale(${((bg as any).cropTop ? 1.38 : 1.02) + 0.05 * t})`}}
            playbackRate={Math.min(1, 5 / Math.max(1, frames / FPS))} />
        : <Img src={staticFile(bg.src)} style={style} />}
      <AbsoluteFill style={{background: 'linear-gradient(180deg, rgba(0,0,0,.55) 0%, rgba(0,0,0,.15) 30%, rgba(0,0,0,.25) 55%, rgba(0,0,0,.85) 100%)'}} />
    </AbsoluteFill>
  );
};

// ---------- helpers ----------
const useIn = (delay = 0, damping = 14) => {
  const f = useCurrentFrame(); const {fps} = useVideoConfig();
  return spring({frame: f - delay, fps, config: {damping, mass: 0.7}});
};
const Pop: React.FC<{delay?: number; children: React.ReactNode; y?: number; style?: React.CSSProperties}> = ({delay = 0, children, y = 40, style}) => {
  const p = useIn(delay);
  return <div style={{opacity: p, transform: `translateY(${(1 - p) * y}px) scale(${0.9 + 0.1 * p})`, ...style}}>{children}</div>;
};
const Panel: React.FC<{children: React.ReactNode}> = ({children}) => (
  <AbsoluteFill style={{top: 250, height: 900, padding: '0 70px', justifyContent: 'center', alignItems: 'center', fontFamily: FONT, color: 'white', textAlign: 'center'}}>
    {children}
  </AbsoluteFill>
);

// ---------- templates ----------
const Hook: React.FC<{d: any}> = ({d}) => {
  const lines: string[] = String(d.title).split('\n');
  return (
    <Panel>
      <Pop><div style={{display: 'inline-block', background: ACC, padding: '10px 26px', borderRadius: 40, fontSize: 38, fontWeight: 800, letterSpacing: 4}}>{d.kicker}</div></Pop>
      <div style={{height: 40}} />
      {lines.map((l, i) => (
        <Pop key={i} delay={8 + i * 9}><div style={{fontSize: 108, fontWeight: 900, lineHeight: 1.08, textShadow: shadow, color: i === lines.length - 1 ? GOLD : 'white'}}>{l}</div></Pop>
      ))}
    </Panel>
  );
};

const Quote: React.FC<{d: any; frames: number}> = ({d, frames}) => {
  const f = useCurrentFrame();
  const words = String(d.text).split(' ');
  const per = Math.max(2, Math.floor((frames * 0.45) / words.length));
  return (
    <Panel>
      <Pop><div style={{fontSize: 220, lineHeight: 0.6, color: GOLD, fontFamily: 'Georgia, serif', textShadow: shadow}}>“</div></Pop>
      <div style={{fontSize: 70, fontWeight: 800, lineHeight: 1.22, textShadow: shadow, marginTop: 10}}>
        {words.map((w, i) => {
          const o = interpolate(f - 6 - i * per, [0, 8], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
          return <span key={i} style={{opacity: o, display: 'inline-block', transform: `translateY(${(1 - o) * 14}px)`, marginRight: 16}}>{w}</span>;
        })}
      </div>
      <Pop delay={10 + words.length * per}><div style={{marginTop: 40, fontSize: 42, fontWeight: 700, color: GOLD}}>— {d.who}</div></Pop>
    </Panel>
  );
};

const Stat: React.FC<{d: any}> = ({d}) => {
  const p = useIn(4, 9);
  return (
    <Panel>
      <div style={{fontSize: 250, fontWeight: 900, color: GOLD, transform: `scale(${0.4 + 0.6 * p})`, opacity: p, textShadow: shadow, lineHeight: 1}}>{d.big}</div>
      <Pop delay={14}><div style={{fontSize: 64, fontWeight: 800, textShadow: shadow, marginTop: 20}}>{d.label}</div></Pop>
      <Pop delay={40}><div style={{fontSize: 46, fontWeight: 600, opacity: 0.92, marginTop: 30, textShadow: shadow}}>{d.sub}</div></Pop>
    </Panel>
  );
};

const Counter: React.FC<{d: any; frames: number}> = ({d, frames}) => {
  const f = useCurrentFrame();
  const to = Number(d.to);
  const v = interpolate(f, [6, Math.min(frames * 0.55, 75)], [0, to], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.out(Easing.cubic)});
  const dec = String(d.to).includes('.') ? 1 : 0;
  const ring = interpolate(v, [0, 100], [0, 1]);
  const R = 300, C = 2 * Math.PI * R;
  return (
    <Panel>
      <div style={{position: 'relative', width: 700, height: 700}}>
        <svg width={700} height={700} style={{position: 'absolute', left: 0, top: 0}}>
          <circle cx={350} cy={350} r={R} stroke="rgba(255,255,255,.18)" strokeWidth={34} fill="none" />
          <circle cx={350} cy={350} r={R} stroke={GOLD} strokeWidth={34} fill="none" strokeLinecap="round"
            strokeDasharray={C} strokeDashoffset={C * (1 - ring)} transform="rotate(-90 350 350)" />
        </svg>
        <div style={{position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 170, fontWeight: 900, textShadow: shadow}}>
          {v.toFixed(dec)}{d.suffix}
        </div>
      </div>
      <Pop delay={20}><div style={{fontSize: 58, fontWeight: 800, marginTop: 30, textShadow: shadow}}>{d.label}</div></Pop>
      <Pop delay={40}><div style={{fontSize: 42, fontWeight: 600, marginTop: 16, opacity: 0.9, textShadow: shadow}}>{d.sub}</div></Pop>
    </Panel>
  );
};

const Compare: React.FC<{d: any}> = ({d}) => {
  const f = useCurrentFrame();
  const l = useIn(4), r = useIn(22), vs = useIn(14, 8);
  const card = (side: any, p: number, from: number, col: string) => (
    <div style={{width: 400, padding: '50px 16px', borderRadius: 34, background: 'rgba(10,14,22,.78)', border: `5px solid ${col}`,
      transform: `translateX(${(1 - p) * from}px)`, opacity: p}}>
      <div style={{fontSize: 44, fontWeight: 800, color: col}}>{side.head}</div>
      <div style={{fontSize: 88, fontWeight: 900, marginTop: 24, whiteSpace: 'nowrap'}}>{side.value}</div>
    </div>
  );
  return (
    <Panel>
      <Pop><div style={{fontSize: 62, fontWeight: 900, textShadow: shadow, marginBottom: 50}}>{d.title}</div></Pop>
      <div style={{display: 'flex', gap: 110, alignItems: 'center'}}>
        {card(d.left, l, -500, '#FF6B6B')}
        {card(d.right, r, 500, '#3DDC97')}
      </div>
      <div style={{position: 'absolute', top: 470, fontSize: 60, fontWeight: 900, background: GOLD, color: '#111', borderRadius: 60, width: 120, height: 120,
        display: 'flex', alignItems: 'center', justifyContent: 'center', transform: `scale(${vs})`}}>VS</div>
    </Panel>
  );
};

const Timeline: React.FC<{d: any; frames: number}> = ({d, frames}) => {
  const f = useCurrentFrame();
  const items: string[][] = d.items;
  const grow = interpolate(f, [8, frames * 0.6], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  return (
    <Panel>
      <Pop><div style={{fontSize: 70, fontWeight: 900, textShadow: shadow, marginBottom: 60}}>{d.title}</div></Pop>
      <div style={{position: 'relative', width: 820, textAlign: 'left'}}>
        <div style={{position: 'absolute', left: 38, top: 20, width: 10, height: 480 * grow, background: GOLD, borderRadius: 5}} />
        {items.map((it, i) => (
          <Pop key={i} delay={14 + i * 40} y={20}>
            <div style={{display: 'flex', alignItems: 'center', gap: 40, marginBottom: 150}}>
              <div style={{width: 86, height: 86, borderRadius: 50, background: i === 0 ? ACC : GOLD, flexShrink: 0, boxShadow: shadow}} />
              <div>
                <div style={{fontSize: 56, fontWeight: 900, color: i === 0 ? ACC : GOLD}}>{it[0]}</div>
                <div style={{fontSize: 50, fontWeight: 700, textShadow: shadow}}>{it[1]}</div>
              </div>
            </div>
          </Pop>
        ))}
      </div>
    </Panel>
  );
};

const List: React.FC<{d: any; frames: number}> = ({d, frames}) => {
  const items: string[][] = d.items;
  const step = Math.floor((frames * 0.6) / items.length);
  return (
    <Panel>
      <Pop><div style={{fontSize: 70, fontWeight: 900, textShadow: shadow, marginBottom: 50}}>{d.title}</div></Pop>
      {items.map((it, i) => (
        <Pop key={i} delay={10 + i * step} y={30}>
          <div style={{display: 'flex', alignItems: 'center', gap: 30, background: 'rgba(10,14,22,.72)', borderRadius: 28, padding: '26px 34px',
            marginBottom: 28, width: 900, textAlign: 'left', borderLeft: `10px solid ${GOLD}`}}>
            <div style={{fontSize: 84}}>{it[0]}</div>
            <div style={{fontSize: 46, fontWeight: 800}}>{it[1]}</div>
          </div>
        </Pop>
      ))}
    </Panel>
  );
};

const Cta: React.FC<{d: any}> = ({d}) => {
  const f = useCurrentFrame();
  const bounce = Math.abs(Math.sin(f / 7)) * 30;
  return (
    <Panel>
      <Pop><div style={{fontSize: 44, fontWeight: 800, letterSpacing: 3, color: GOLD}}>WATCH THE</div></Pop>
      <Pop delay={6}><div style={{fontSize: 104, fontWeight: 900, lineHeight: 1.08, textShadow: shadow}}>{d.title}</div></Pop>
      <Pop delay={16}><div style={{marginTop: 50, display: 'inline-block', background: ACC, borderRadius: 50, padding: '22px 44px', fontSize: 50, fontWeight: 800}}>{d.sub}</div></Pop>
      <div style={{fontSize: 130, marginTop: 30, transform: `translateY(${bounce}px)`}}>👇</div>
    </Panel>
  );
};

// ---------- captions: whole sentence (clause), active word highlighted ----------
const splitCaps = (words: Word[]) => {
  const out: Word[][] = []; let cur: Word[] = [];
  words.forEach((w, i) => {
    cur.push(w);
    const end = /[.!?]["')]*$/.test(w.w) || (cur.length >= 12 && /[,;:]$/.test(w.w)) || cur.length >= 26;
    if (end) { out.push(cur); cur = []; }
  });
  if (cur.length) out.push(cur);
  return out;
};
const Captions: React.FC<{words: Word[]}> = ({words}) => {
  const f = useCurrentFrame(); const t = f / FPS;
  const groups = splitCaps(words);
  let g = groups.find((gr, i) => t >= gr[0].s - 0.05 && (i === groups.length - 1 || t < groups[i + 1][0].s - 0.05));
  if (!g && groups.length && t < groups[0][0].s) g = undefined;
  if (!g) return null;
  const start = g[0].s;
  const o = interpolate(t, [start - 0.05, start + 0.12], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  return (
    <AbsoluteFill style={{top: 1330, height: 470, padding: '0 60px', justifyContent: 'center', alignItems: 'center'}}>
      <div style={{opacity: o, fontFamily: FONT, fontSize: 56, fontWeight: 800, lineHeight: 1.3, textAlign: 'center', color: 'white',
        textShadow: '0 0 10px rgba(0,0,0,.9), 0 4px 10px rgba(0,0,0,.9)', WebkitTextStroke: '2px rgba(0,0,0,.6)'}}>
        {g.map((w, i) => {
          const active = t >= w.s && t < w.e + 0.08;
          return <span key={i} style={{color: active ? GOLD : 'white', marginRight: 14, display: 'inline-block',
            transform: active ? 'scale(1.06)' : 'none'}}>{w.w}</span>;
        })}
      </div>
    </AbsoluteFill>
  );
};

const ProgressBar: React.FC = () => {
  const f = useCurrentFrame(); const {durationInFrames} = useVideoConfig();
  return <div style={{position: 'absolute', top: 0, left: 0, height: 10, width: `${(f / durationInFrames) * 100}%`, background: GOLD}} />;
};

const SceneView: React.FC<{s: Scene; k: number; frames: number}> = ({s, k, frames}) => {
  const f = useCurrentFrame();
  const fadeIn = interpolate(f, [0, 8], [0, 1], {extrapolateRight: 'clamp'});
  const T: Record<string, React.FC<any>> = {hook: Hook, quote: Quote, stat: Stat, counter: Counter, compare: Compare, timeline: Timeline, list: List, cta: Cta};
  const C = T[s.tpl] || Quote;
  return (
    <AbsoluteFill style={{opacity: fadeIn, backgroundColor: 'black'}}>
      <Background bg={s.bg} frames={frames} k={k} />
      <C d={s.data} frames={frames} />
      <Captions words={s.words} />
      <Audio src={staticFile(`voice/${s.id}.wav`)} />
    </AbsoluteFill>
  );
};

export const Short: React.FC<ShortProps> = ({scenes}) => {
  let from = 0;
  return (
    <AbsoluteFill style={{backgroundColor: 'black'}}>
      {scenes.map((s, k) => {
        const n = sceneFrames(s); const el = (
          <Sequence key={s.id} from={from} durationInFrames={n}><SceneView s={s} k={k} frames={n} /></Sequence>);
        from += n; return el;
      })}
      <ProgressBar />
    </AbsoluteFill>
  );
};
