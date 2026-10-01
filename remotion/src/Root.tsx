import React from "react";
import { Composition, registerRoot, staticFile } from "remotion";
import { Teaser } from "./Teaser";
import { FPS, W, H } from "./theme";
import { TeaserProps } from "./types";

const Root: React.FC = () => (
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
);
registerRoot(Root);
