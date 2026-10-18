import json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from studio.render_media import fallback_failed_video
class RuntimeRecoveryTests(unittest.TestCase):
 def test_only_reported_asset_replaced_and_retry_bounded(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);f=root/'teaser.json'
   data={'beats':[{'id':'b','words':[['Keep',0,1]],'bgs':[{'type':'video','src':'media/a.mp4','from':0},{'type':'video','src':'media/b.mp4','from':2}]}]}
   f.write_text(json.dumps(data))
   error='Could not extract frame (original source = http://localhost:3000/public/media/a.mp4).'
   self.assertTrue(fallback_failed_video(f,root,error,lambda _:None))
   result=json.loads(f.read_text());self.assertEqual(result['beats'][0]['bgs'][0]['g']['kind'],'headline')
   self.assertEqual(result['beats'][0]['bgs'][1],data['beats'][0]['bgs'][1])
   self.assertFalse(fallback_failed_video(f,root,error,lambda _:None))
 def test_encoded_timeout_and_unrelated_errors(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);f=root/'teaser.json'
   f.write_text(json.dumps({'beats':[{'id':'b','bgs':[{'type':'video','src':'media/a.mp4','from':3}]}]}))
   self.assertFalse(fallback_failed_video(f,root,'Network error http://localhost/public/media/a.mp4',lambda _:None))
   self.assertFalse(fallback_failed_video(f,root,'No frame found http://localhost/public/../a.mp4',lambda _:None))
   self.assertTrue(fallback_failed_video(f,root,'delayRender() Fetching http%3A%2F%2Flocalhost%3A3000%2Fpublic%2Fmedia%2Fa.mp4&time=7',lambda _:None))
   self.assertEqual(json.loads(f.read_text())['beats'][0]['bgs'][0]['from'],3)
if __name__=='__main__':unittest.main()
