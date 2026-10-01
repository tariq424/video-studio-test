import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { C, HEAD } from "./theme";
import { Word } from "./types";

// Karaoke captions: a page of up to ~7 words (never crossing a sentence end); the spoken word lights up.
export const paginate = (words: Word[], max = 6): Word[][] => {
  const pages: Word[][] = []; let cur: Word[] = [];
  words.forEach((w) => {
    cur.push(w);
    const end = /[.!?]["')\]]*$/.test(w[0]);
    const soft = /[,;:]$/.test(w[0]) && cur.length >= 4;
    if (end || soft || cur.length >= max) { pages.push(cur); cur = []; }
  });
  if (cur.length) pages.push(cur);
  return pages;
};

export const Captions: React.FC<{ words: Word[] }> = ({ words }) => {
  const f = useCurrentFrame(); const { fps } = useVideoConfig(); const t = f / fps;
  const pages = paginate(words);
  let page = pages.find((p, i) => t >= p[0][1] - 0.05 && (i === pages.length - 1 || t < pages[i + 1][0][1] - 0.05));
  if (!page) { if (t < (pages[0]?.[0][1] ?? 0)) return null; page = pages[pages.length - 1]; }
  return (
    <AbsoluteFill style={{ top: 1390, height: 190, bottom: "auto", alignItems: "center", justifyContent: "center", padding: "0 80px" }}>
      <div style={{ textAlign: "center", fontFamily: HEAD, fontWeight: 800, fontSize: 46, lineHeight: 1.25, letterSpacing: -0.5 }}>
        {page.map(([w, a, b], i) => {
          const next = page[i + 1]; const active = t >= a - 0.03 && t < (next ? Math.min(b + 0.08, next[1] - 0.03) : b + 0.08);
          const spoken = t >= b;
          return (
            <React.Fragment key={i}><span style={{
              color: active ? C.gold : spoken ? C.text : "rgba(255,255,255,0.55)",
              display: "inline",
              textShadow: "0 0 4px #000, 0 0 4px #000, 0 3px 14px rgba(0,0,0,0.95)",
            }}>{w}{i < page.length - 1 ? " " : ""}</span></React.Fragment>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
