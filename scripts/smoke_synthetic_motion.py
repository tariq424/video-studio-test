import json, sys, hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app'))
from studio import graphics, physics, config, media
from studio.render_media import inspect_video
OUT=Path(r'F:\videos_test\jobs\synthetic-motion'); OUT.mkdir(parents=True,exist_ok=True)
source=Path(r'F:\videos\video_studio\jobs\20261016_190435\src\transcript.txt')
raw=source.read_bytes(); text=raw.decode('utf-8')
# Forced fixtures anchored to original transcript topics; not represented as verbatim quotations.
import re
lines=[text[max(0,m.start()-100):m.end()+200] for m in re.finditer(r'radar|ships?|hormuz',text,re.I)]
(OUT/'source-excerpts.txt').write_text('\n'.join(lines),encoding='utf-8')
beats={'radar': 'God\'s Eye View shows rain radar sweeping across the weather panel.',
       'ship': 'God\'s Eye View tracks ships moving through the Strait of Hormuz into the Gulf of Oman.'}
(OUT/'space.json').write_text(json.dumps({'w':1920,'h':1080,'orient':'landscape'}))
cfg=config.load(); report={}
for name,vo in beats.items():
    sec={'vo':vo,'visuals':[{'g':{'kind':'abstract','text':'placeholder'}}]}
    choice=graphics.classify(cfg,sec,print)
    assert choice['template']=='motion'
    (OUT/f'{name}.json').write_text(json.dumps(choice,indent=2),encoding='utf-8')
    dest=OUT/f'{name}.mp4'
    graphics.render_template(cfg,OUT,'motion',choice['data'],4,dest,print)
    validation=inspect_video(dest); assert validation['frames'] >= 119,validation
    # Pixel comparison only inside animation region, excluding heading/captions.
    frames=[]
    for t in (0.8,2.6):
        import subprocess
        p=subprocess.run(['ffmpeg','-v','error','-ss',str(t),'-i',str(dest),'-frames:v','1','-vf','crop=1400:580:260:220,scale=160:90','-pix_fmt','rgb24','-f','rawvideo','-'],capture_output=True,check=True)
        frames.append(p.stdout)
    delta=sum(abs(a-b) for a,b in zip(*frames))/len(frames[0]); assert delta>0.1,delta
    media.ff('-ss',1.6,'-i',dest,'-frames:v',1,OUT/f'{name}.png')
    report[name]={'validation':validation,'motion_pixel_mean_delta':delta,'fixture':vo}
assert hashlib.sha256(source.read_bytes()).digest()==hashlib.sha256(raw).digest()
report['source_sha256']=hashlib.sha256(raw).hexdigest()
(OUT/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report,indent=2))
