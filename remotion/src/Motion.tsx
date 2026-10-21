import React from 'react';
import {AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';

// All positions/angles are deterministic inputs; no network or random calls at render time.
export const MotionBackdrop: React.FC<{g: any; dur: number}> = ({g, dur}) => {
  const frame = useCurrentFrame(); const {width: W, height: H, fps} = useVideoConfig();
  const p = Math.min(1, frame / fps / Math.max(dur, 0.1));
  const sample = (values: number[]) => interpolate(p, values.map((_, i) => i / (values.length - 1)), values);
  const radar = g.module === 'radar_sweep';
  const angle = sample(g.angles); const cx=W/2, cy=H/2, r=Math.min(W,H)*0.29;
  const x=sample(g.points.map((v:number[])=>v[0]))*W, y=sample(g.points.map((v:number[])=>v[1]))*H;
  return <AbsoluteFill style={{background:'#071524',color:'#fff',fontFamily:'Inter, sans-serif'}}>
    <div style={{position:'absolute',top:H*0.12,width:'100%',textAlign:'center',fontSize:44,fontWeight:800}}>{g.title}</div>
    <svg width={W} height={H}>
      {radar ? <g>
        {[0.33,0.66,1].map(k=><circle key={k} cx={cx} cy={cy} r={r*k} fill='none' stroke='#247869' strokeWidth={3}/>)}
        <line x1={cx-r} x2={cx+r} y1={cy} y2={cy} stroke='#247869'/>
        <line x1={cx} x2={cx} y1={cy-r} y2={cy+r} stroke='#247869'/>
        <g transform={`rotate(${angle} ${cx} ${cy})`}>
          <path d={`M${cx},${cy} L${cx+r},${cy} A${r},${r} 0 0 0 ${cx+r*0.866},${cy-r*0.5} Z`} fill='#36ed9a' opacity={0.2}/>
          <line x1={cx} y1={cy} x2={cx+r} y2={cy} stroke='#5affb2' strokeWidth={6}/>
        </g>
        {g.targets.map((v:number[],i:number)=><circle key={i} cx={cx+(v[0]-0.5)*r*1.5} cy={cy+(v[1]-0.5)*r*1.5} r={9} fill='#ffda65' opacity={0.4+0.6*Math.pow(Math.cos(frame/15+i),2)}/>)}
      </g> : <g>
        <path d={'M'+g.points.map((v:number[])=>`${v[0]*W},${v[1]*H}`).join(' L')} fill='none' stroke='#286677' strokeWidth={8}/>
        <path d={'M'+g.points.slice(0,Math.max(2,Math.floor(p*(g.points.length-1))+1)).map((v:number[])=>`${v[0]*W},${v[1]*H}`).join(' L')} fill='none' stroke='#4ce1cc' strokeWidth={7}/>
        <g transform={`translate(${x},${y})`}><path d='M30,0 L-20,-15 L-12,0 L-20,15 Z' fill='#ffda65'/></g>
      </g>}
    </svg>
  </AbsoluteFill>;
};
