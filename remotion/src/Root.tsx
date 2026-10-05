import React from "react";
import { Composition, registerRoot, staticFile } from "remotion";
import { Teaser } from "./Teaser";
import { FPS, W, H } from "./theme";
import { TeaserProps } from "./types";
import { ReconBackdrop, Recon } from "./Recon";

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
    id="Teaser"
    component={Teaser as React.FC<any>}
    fps={FPS}
    width={W}
    height={H}
    durationInFrames={FPS * 120}
    defaultProps={{ audio: "", total: 120, tag: "", beats: [] } as TeaserProps}
    calculateMetadata={async ({ props }) => {
      const p = (props as TeaserProps).beats.length ? (props as TeaserProps) : ((await (await fetch(staticFile("teaser.json"))).json()) as TeaserProps);
      return { durationInFrames: Math.ceil(p.total * FPS), props: p };
    }}
  />
  </>
);
registerRoot(Root);
