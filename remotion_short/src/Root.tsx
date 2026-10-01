// Reconstructed 2026-10-01: this file was accidentally overwritten by the teaser session.
import React from 'react';
import {Composition} from 'remotion';
import {Short, FPS, sceneFrames, ShortProps} from './Short';

export const RemotionRoot: React.FC = () => (
  <Composition
    id="Short"
    component={Short as React.FC<any>}
    fps={FPS}
    width={1080}
    height={1920}
    durationInFrames={FPS * 60}
    defaultProps={{scenes: []} as ShortProps}
    calculateMetadata={({props}) => ({
      durationInFrames: Math.max(1, (props as ShortProps).scenes.reduce((a, s) => a + sceneFrames(s), 0)),
    })}
  />
);
