"""Render the failing production timeline from private test copies, with bounded workers."""
import hashlib,json,shutil,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'app'))
from studio import short,config
from studio.render_media import inspect_video
SOURCE=Path(r'F:\videos\video_studio\jobs\20261017_165408\short\public')
OUT=Path(r'F:\videos_test\jobs\stock_validation_smoke');OUT.mkdir(parents=True,exist_ok=True)
PUBLIC=OUT/'public'
files=[SOURCE/'teaser.json',SOURCE/'media/stock/px34337855.mp4',SOURCE/'media/fb/b0_0.mp4']
before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
print('Copying failing timeline and media into test directory...',flush=True)
shutil.copytree(SOURCE,PUBLIC,dirs_exist_ok=True)
cfg=config.load(); cfg['short_concurrency']='75%'; workers=short.render_concurrency(cfg)
cmd=[short._npx(),'remotion','render','src/Root.tsx','Teaser',str(OUT/'result.mp4'),f'--public-dir={PUBLIC}',f'--concurrency={workers}','--jpeg-quality=95','--crf=16','--log=info',f'--gl={short._gl(cfg)}']
cmd.extend(short.render_browser_args(cfg))
print('Explicit browser:',short.render_browser_args(cfg),flush=True)
start=time.time()
with (OUT/'render.log').open('w',encoding='utf-8') as log:
 result=subprocess.run(cmd,cwd=ROOT/'remotion',stdout=log,stderr=subprocess.STDOUT)
print('Render exit',result.returncode,flush=True)
if result.returncode:raise RuntimeError((OUT/'render.log').read_text(encoding='utf-8')[-2000:])
report={'workers':workers,'elapsed_seconds':time.time()-start,'validation':inspect_video(OUT/'result.mp4'),'source_unchanged':all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==h for p,h in before.items())}
assert report['source_unchanged']
(OUT/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report),flush=True)
