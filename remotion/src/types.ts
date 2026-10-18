export type Word = [string, number, number]; // text, start(s), end(s) relative to beat start

export type Graphic =
  | { kind: "hook"; lines: string[]; accent?: number }
  | { kind: "quote"; text: string; who: string }
  | { kind: "compare"; left: { icon: string; head: string; body: string }; right: { icon: string; head: string; body: string }; badge: string; note?: string }
  | { kind: "stat"; value: number; decimals?: number; prefix?: string; suffix: string; label: string; sub?: string }
  | { kind: "icons"; title: string; items: { icon: string; label: string }[] }
  | { kind: "timeline"; title: string; steps: { when: string; label: string }[] }
  | { kind: "cta"; thumb?: string; title: string; line: string; badge?: string; play?: boolean; arrow?: boolean };

import type { Backdrop } from "./Backdrops";
// from = seconds into beat. "layers": AI still split into depth layers (2.5D). "graphic": full-screen map/headline backdrop.
export type Bg =
  | { src: string; type: "image" | "video"; from: number; fit?: "cover" | "frame" | "still"; credit?: string; tag?: string; rate?: number; decoder?: "browser"; freezeAt?: number; start?: number; loop?: number; user?: boolean; still?: boolean }   // user = your own file (fit-and-render: no motion unless still is false)   // tag: "FILE" / "ILLUSTRATIVE"; still = a slide (chart) with a slow push-in
  | { type: "layers"; layers: string[]; from: number }
  | { type: "graphic"; g: Backdrop; from: number };

export type Beat = {
  id: string;
  start: number; // seconds in the timeline
  dur: number;
  words: Word[];
  bgs: Bg[];
  graphics: { at: number; g: Graphic }[]; // at = seconds into beat
  icons?: { at: number; dur: number; e: string }[]; // emoji shown above the caption, seconds into beat
};

export type TeaserProps = {
  audio: string;
  total: number;
  tag: string;
  beats: Beat[];
  w?: number; h?: number;   // explainer: 1920 x 1080 (default: the Short's 1080 x 1920)
  progress?: boolean;       // the top progress bar (Shorts); off for the explainer
};
