import shutil, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from studio import footage, short
class StockValidationTests(unittest.TestCase):
 def test_download_bad_file_discarded(self):
  with tempfile.TemporaryDirectory() as d:
   out=Path(d)/'clip.mp4'
   def bad(*a,**k): out.write_bytes(b'bad video')
   with patch('studio.footage.media.ff',side_effect=bad):
    with self.assertRaisesRegex(RuntimeError,'download of broken failed'):
     footage.fetch({'id':'broken','file':'unused'},out,3)
   self.assertFalse(out.exists())
 def test_download_and_cache_are_decoded(self):
  with tempfile.TemporaryDirectory() as d:
   source=Path(d)/'source.mp4'; out=Path(d)/'out.mp4'
   subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=128x72:rate=30:duration=1','-c:v','libx264',str(source)],check=True)
   def good(*a,**k): shutil.copy2(source,out)
   out.write_bytes(b'partial cache')
   with patch('studio.footage.media.ff',side_effect=good) as ff:
    self.assertEqual(footage.fetch({'id':'ok','file':'unused'},out,3),out)
    ff.assert_called_once()
   with patch('studio.footage.media.ff') as ff:
    footage.fetch({'id':'ok','file':'unused'},out,3)
    ff.assert_not_called()
 def test_truncated_download_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   source=Path(d)/'source.mp4';out=Path(d)/'out.mp4'
   subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=128x72:rate=30:duration=2','-c:v','libx264','-movflags','+faststart',str(source)],check=True)
   def bad(*a,**k):out.write_bytes(source.read_bytes()[:len(source.read_bytes())//2])
   with patch('studio.footage.media.ff',side_effect=bad):
    with self.assertRaises(RuntimeError):footage.fetch({'id':'truncated','file':'unused'},out,3)
   self.assertFalse(out.exists())
 def test_browser_override(self):
  with tempfile.TemporaryDirectory() as d:
   browser=Path(d)/'chrome.exe';browser.touch()
   self.assertEqual(short.render_browser_args({'remotion_browser_executable':str(browser)}),[f'--browser-executable={browser}'])
   with self.assertRaisesRegex(RuntimeError,'not found'):
    short.render_browser_args({'remotion_browser_executable':str(browser)+'missing'})
 def test_concurrency(self):
  for value in ['75%','100%','25%']:
   self.assertEqual(short.render_concurrency({'short_concurrency':value}),2)
  self.assertEqual(short.render_concurrency({'short_concurrency':1}),1)
if __name__=='__main__':unittest.main()
