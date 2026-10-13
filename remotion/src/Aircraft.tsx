// Side-view airliner in an airline's simplified livery (app/studio/liveries.py): colours + tail design only, no logos or lettering.
// Drawn in a 400 x 120 box, nose at x=396, y=60 (same frame as Illustration.tsx's Airliner). lv undefined -> the generic airliner.
import React from "react";

export type Livery = { key?: string; body: string; belly: string; stripe?: string; tail: string; tail2?: string; tail3?: string;
  tail_art?: "solid" | "split" | "band" | "arc" | "flag"; engine: string; wingtip?: string };

export const GENERIC: Livery = { body: "#f4f6f8", belly: "#c9d1db", stripe: "", tail: "#8b9bb0", tail2: "", tail_art: "solid", engine: "#aeb8c5", wingtip: "" };

const TAIL = "M44,47 L20,4 L46,4 L98,47 Z";   // fin outline (root 44..98 at y=47, tip 20..46 at y=4)

const TailArt: React.FC<{ lv: Livery; id: string }> = ({ lv, id }) => {
  const a = lv.tail_art || "solid", t2 = lv.tail2 || lv.tail;
  return (
    <g>
      <defs><clipPath id={id}><path d={TAIL} /></clipPath></defs>
      <path d={TAIL} fill={lv.tail} />
      <g clipPath={`url(#${id})`}>
        {a === "split" ? <path d="M0,0 L58,0 L36,50 L0,50 Z" fill={t2} /> : null}
        {a === "band" ? <rect x={0} y={18} width={110} height={14} fill={t2} /> : null}
        {a === "arc" ? <path d="M40,50 C40,26 52,10 72,0 L110,0 L110,50 Z" fill={t2} /> : null}
        {a === "flag" ? <g><rect x={0} y={0} width={110} height={16} fill={t2} /><rect x={0} y={16} width={110} height={16} fill={lv.tail3 || t2} /></g> : null}
      </g>
    </g>
  );
};

export const LiveryAirliner: React.FC<{ lv?: Livery | null; gear?: boolean; night?: boolean; f: number; id?: string }> = ({ lv, gear, night, f, id = "lvt" }) => {
  const L = lv || GENERIC; const dark = "#5b6676"; const blink = Math.floor(f / 18) % 2 === 0;
  const wing = L.wingtip || dark;
  return (
    <g>
      <TailArt lv={L} id={id} />
      <path d="M36,60 L6,76 L28,78 L78,64 Z" fill={L.tail} />
      <path d="M10,60 C10,49 30,44 62,44 L328,44 C356,44 380,51 396,60 C382,69 358,75 328,75 L62,75 C30,75 10,71 10,60 Z" fill={L.body} />
      <path d="M30,66 L330,66 C352,66 372,68 388,64 C372,71 354,75 328,75 L62,75 C42,75 30,72 30,66 Z" fill={L.belly} />
      {L.stripe ? <path d="M28,63 L360,63 C370,63 380,62 388,61 L388,64 C378,65 368,66 360,66 L28,66 Z" fill={L.stripe} /> : null}
      <path d="M360,50 L378,52 L386,58 L364,57 Z" fill="#2b3a52" />
      {Array.from({ length: 22 }, (_, i) => <rect key={i} x={86 + i * 11.5} y={52} width={5} height={6} rx={2} fill="#6f7f95" />)}
      <path d="M182,64 L128,110 L160,112 L246,66 Z" fill={dark} />
      <path d="M128,110 L122,98 L132,99 L140,111 Z" fill={wing} />
      <rect x={152} y={84} width={56} height={17} rx={8} fill={L.engine} />
      <rect x={202} y={86} width={8} height={13} rx={3} fill="#3b4656" />
      {gear ? <g fill={dark}><rect x={318} y={74} width={4} height={18} /><circle cx={320} cy={95} r={6} /><rect x={176} y={74} width={5} height={22} /><circle cx={178} cy={99} r={7} /></g> : null}
      <circle cx={226} cy={110} r={4} fill={blink || !night ? "#ff4b4b" : "#5b1b1b"} />
    </g>
  );
};
