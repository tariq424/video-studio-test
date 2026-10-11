import React from "react";
import { Composition, registerRoot, staticFile } from "remotion";
import { Teaser } from "./Teaser";
import { FPS, W, H } from "./theme";
import { TeaserProps } from "./types";
import { ReconBackdrop, Recon } from "./Recon";
import { Shot } from "./Background";
import { BeatClip, BeatClipProps } from "./BeatClip";

// one background shot on its own (visual-review thumbnails and 2-second previews): props {bg, secs}; --public-dir = the job's short folder
type ShotProps = { bg: any; secs: number; w?: number; h?: number };
const ShotClip: React.FC<ShotProps> = ({ bg, secs }) => <Shot bg={{ ...bg, from: 0 }} dur={secs} seed={1} />;

// standalone reconstruction clip (long videos render these as B-roll): props {g, secs, w, h}
type ReconProps = { g: Recon; secs: number; w?: number; h?: number };
const ReconClip: React.FC<ReconProps> = ({ g, secs }) => <ReconBackdrop g={g} dur={secs} />;

const Root: React.FC = () => (
  <>
  <Composition
    id="Recon"
    component={ReconClip as React.FC<any>}
    fps={FPS}
    width={1920}
    height={1080}
    durationInFrames={FPS * 6}
    defaultProps={{ g: { kind: "recon", scene: "aircraft_flight", name: "Example 737", colors: ["#ffffff", "#1d4e9e", "#f26b21"] }, secs: 6 } as ReconProps}
    calculateMetadata={async ({ props }) => {
      const p = props as ReconProps;
      return { durationInFrames: Math.ceil(p.secs * FPS), width: p.w || 1920, height: p.h || 1080 };
    }}
  />
  <Composition
    id="ShotPreview"
    component={ShotClip as React.FC<any>}
    fps={FPS}
    width={W}
    height={H}
    durationInFrames={FPS * 7}
    defaultProps={{ bg: { type: "graphic", g: { kind: "headline", kicker: "", text: "Preview", sub: "" } }, secs: 7 } as ShotProps}
    calculateMetadata={async ({ props }) => ({ durationInFrames: Math.max(1, Math.ceil((props as ShotProps).secs * FPS)),
      width: (props as ShotProps).w || W, height: (props as ShotProps).h || H })}
  />
  <Composition
    id="BeatClip"
    component={BeatClip as React.FC<any>}
    fps={FPS}
    width={1920}
    height={1080}
    durationInFrames={FPS * 7}
    defaultProps={{ bgs: [], dur: 7 } as BeatClipProps}
    calculateMetadata={async ({ props }) => {
      const p = props as BeatClipProps;
      return { durationInFrames: Math.max(1, Math.round(p.dur * FPS)), width: p.w || 1920, height: p.h || 1080 };
    }}
  />
  <Composition
    id="Teaser"
    component={Teaser as React.FC<any>}
    fps={FPS}
    width={W}
    height={H}
    durationInFrames={FPS * 120}
    defaultProps={{ audio: "", total: 120, tag: "", beats: [] } as TeaserProps}
    calculateMetadata={async ({ props }) => {
      const p = (props as TeaserProps).beats.length ? (props as TeaserProps) : ((await (await fetch(staticFile("teaser.json"))).json()) as TeaserProps);
      return { durationInFrames: Math.ceil(p.total * FPS), props: p, width: p.w || W, height: p.h || H };
    }}
  />
  </>
);
registerRoot(Root);
