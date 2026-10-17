import copy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from studio.render_media import inspect_video, sanitize_timeline


class RenderMediaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def timeline(self, **bg):
        return {'beats': [{'id': 'test', 'bgs': [{'type': 'video', 'src': 'clip.mp4', 'from': 2, **bg}]}]}

    def test_empty_and_missing_use_card_preserving_start(self):
        (self.root / 'clip.mp4').write_bytes(b'')
        for name in ('clip.mp4', 'missing.mp4'):
            data = self.timeline(src=name)
            sanitize_timeline(data, self.root, lambda _: None)
            bg = data['beats'][0]['bgs'][0]
            self.assertEqual((bg['type'], bg['from']), ('graphic', 2))
            self.assertEqual(bg['g']['kind'], 'headline')

    def test_long_slot_holds_before_eof_and_repeated_asset_decodes_once(self):
        data = self.timeline(rate=0.5, start=1, freezeAt=200)
        data['beats'][0]['bgs'].append(copy.deepcopy(data['beats'][0]['bgs'][0]))
        with patch('studio.render_media.inspect_video', return_value={'duration': 8, 'fps': 30, 'frames': 240}) as probe:
            sanitize_timeline(data, self.root, lambda _: None)
        probe.assert_called_once()
        hold = data['beats'][0]['bgs'][0]['freezeAt']
        self.assertLess(1 + hold * 0.5, 8)
        self.assertGreater(hold, 13)

    def test_invalid_start_or_rate_and_path_escape_use_card(self):
        for bg in ({'start': 9}, {'rate': 0}, {'rate': float('nan')}, {'src': '../outside.mp4'}):
            with self.subTest(bg=bg), patch('studio.render_media.inspect_video', return_value={'duration': 8, 'fps': 30, 'frames': 240}):
                data = self.timeline(**bg)
                sanitize_timeline(data, self.root, lambda _: None)
                self.assertEqual(data['beats'][0]['bgs'][0]['type'], 'graphic')

    def test_cancel_does_not_become_fallback(self):
        with self.assertRaisesRegex(RuntimeError, 'cancelled'):
            sanitize_timeline(self.timeline(), self.root, lambda _: None, lambda: True)

    def test_loop_is_bounded_and_graphics_are_untouched(self):
        data = self.timeline(loop=100, rate=1)
        graphic = {'type': 'graphic', 'from': 5, 'g': {'kind': 'headline', 'text': 'Keep'}}
        data['beats'][0]['bgs'].append(copy.deepcopy(graphic))
        with patch('studio.render_media.inspect_video', return_value={'duration': 8, 'fps': 30, 'frames': 240}):
            sanitize_timeline(data, self.root, lambda _: None)
        self.assertLess(data['beats'][0]['bgs'][0]['loop'], 8)
        self.assertEqual(data['beats'][0]['bgs'][1], graphic)

    def test_full_decode_healthy_and_truncated_file(self):
        path = self.root / 'clip.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=128x72:rate=30:duration=1',
            '-c:v', 'libx264', '-movflags', '+faststart', str(path)], check=True, capture_output=True)
        self.assertEqual(inspect_video(path)['frames'], 30)
        raw = path.read_bytes()
        path.write_bytes(raw[:len(raw) // 2])
        with self.assertRaises(ValueError):
            inspect_video(path)


if __name__ == '__main__':
    unittest.main()
