"""Inject one compositor failure, then run the real Short renderer and verify recovery."""
import io,json,shutil,sys,subprocess,hashlib
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'app'))
from studio import short,config,media
from studio.render_media import inspect_video
JOB=Path(r'F:\videos_test\jobs\runtime_recovery_smoke');PUB=JOB/'short/public';PUB.mkdir(parents=True,exist_ok=True)
SOURCE=Path(r'F:\videos\video_studio\jobs\20261017_165408\short/public')
for name,src in [('bad.mp4','media/stock/px34337855.mp4'),('good.mp4','media/fb/b1_1.mp4')]:shutil.copy2(SOURCE/src,PUB/name)
source_hash=hashlib.sha256((PUB/'bad.mp4').read_bytes()).hexdigest()
media.ff('-f','lavfi','-i','sine=frequency=220:duration=4',PUB/'audio.wav')
data={'w':1080,'h':1920,'audio':'audio.wav','total':4,'tag':'RECOVERY TEST','beats':[{'id':'b0','start':0,'dur':4,'graphics':[],'words':[],'bgs':[{'type':'video','src':'bad.mp4','from':0,'rate':1},{'type':'video','src':'good.mp4','from':2,'rate':1}]}]}
(PUB/'teaser.json').write_text(json.dumps(data));(JOB/'short/stock').mkdir(exist_ok=True);(JOB/'short/stock/pick.json').write_text('{}')
real_popen=subprocess.Popen;calls=[]
class Failed:
 stdout=io.StringIO('Error: Could not extract frame from compositor (original source = http://localhost:3000/public/bad.mp4).\n')
 def wait(self):return 1
 def kill(self):pass
def popen(cmd,*args,**kwargs):
 if isinstance(cmd,list) and 'Teaser' in cmd and 'render' in cmd:
  calls.append(cmd)
  if len(calls)==1:return Failed()
 return real_popen(cmd,*args,**kwargs)
logs=[]
def log(s):logs.append(s);print(s,flush=True)
cfg=config.load();cfg['short_concurrency']='75%'
with patch('studio.short.build',return_value=4),patch('studio.short.subprocess.Popen',side_effect=popen),patch('studio.edit.ensure_keyframes',return_value=None):
 output=short.do_render(JOB,{'title':'Runtime recovery smoke'},{**cfg},{'title':'Test'},log,lambda:False)
report={'validation':inspect_video(output),'render_attempts':len(calls),'source_retained':hashlib.sha256((PUB/'bad.mp4').read_bytes()).hexdigest()==source_hash,'recovered_timeline':json.loads((PUB/'teaser.json').read_text())}
assert len(calls)==2 and report['source_retained']
assert report['recovered_timeline']['beats'][0]['bgs'][0]['type']=='video'
assert report['recovered_timeline']['beats'][0]['bgs'][0]['decoder']=='browser'
assert report['recovered_timeline']['beats'][0]['bgs'][1]['type']=='video'
(JOB/'report.json').write_text(json.dumps(report,indent=2));(JOB/'workflow.log').write_text('\n'.join(logs),encoding='utf-8');print('PASS',output,flush=True)
