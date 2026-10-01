export type Word = [string, number, number]; // text, start(s), end(s) relative to beat start

export type Graphic =
  | { kind: "hook"; lines: string[]; accent?: number }
  | { kind: "quote"; text: string; who: string }
  | { kind: "compare"; left: { icon: string; head: string; body: string }; right: { icon: string; head: string; body: string }; badge: string; note?: string }
  | { kind: "stat"; value: number; decimals?: number; prefix?: string; suffix: string; label: string; sub?: string }
  | { kind: "icons"; title: string; items: { icon: string; label: string }[] }
  | { kind: "timeline"; title: string; steps: { when: string; label: string }[] }
  | { kind: "cta"; thumb?: string; title: string; line: string; badge?: string; play?: boolean; arrow?: boolean };

export type Bg = { src: string; type: "image" | "video"; from: number; fit?: "cover" | "frame" }; // from = seconds into beat

export type Beat = {
  id: string;
  start: number; // seconds in the timeline
  dur: number;
  words: Word[];
  bgs: Bg[];
  graphics: { at: number; g: Graphic }[]; // at = seconds into beat
};

export type TeaserProps = {
  audio: string;
  total: number;
  tag: string;
  beats: Beat[];
};
