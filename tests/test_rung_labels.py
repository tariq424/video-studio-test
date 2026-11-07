"""Every beat says which ladder rung made its picture (scrubber, editor, Newsroom player): studio/edit.rung_label."""
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from studio import edit


class RungLabels(unittest.TestCase):
    def test_from_timeline_tags_and_paths(self):
        L = edit.rung_label
        self.assertEqual(L({"type": "video", "src": "media/stock/px5904780.mp4", "tag": "ILLUSTRATIVE"}), "Stock footage (Pexels)")
        self.assertEqual(L({"type": "layers", "tag": "GENERATED · CHATGPT"}), "ChatGPT image + parallax")
        self.assertEqual(L({"type": "image", "tag": "GENERATED · CLOUDFLARE"}), "Cloudflare image")
        self.assertEqual(L({"type": "video", "src": "media/fb/b8_0.mp4", "tag": "GRAPHICS"}), "Remotion graphics")
        self.assertEqual(L({"type": "video", "tag": "GENERATED · META"}), "Meta video")
        self.assertEqual(L({"type": "video", "src": "chain/b1_chain.mp4", "tag": "GENERATED · META"}), "Meta image → video (from a snapshot)")
        self.assertEqual(L({"type": "video", "tag": "GENERATED · FLOW"}), "Google Flow video")
        self.assertEqual(L({"type": "video", "tag": "GENERATED · BLENDER"}), "Blender scene")
        self.assertEqual(L({"type": "graphic", "g": {"kind": "sim", "synthetic": True}, "tag": "SYNTHETIC"}), "Physics simulation (synthetic data)")
        self.assertEqual(L({"type": "graphic", "g": {"kind": "headline"}}), "Headline card")
        self.assertEqual(L({"type": "video", "tag": "SOURCE · Peter H. Diamandis", "src": "source_excerpts/e4.mp4"}), "Source clip")
        self.assertEqual(L({"type": "video", "user": True}), "Your footage")
        self.assertEqual(L({"type": "image", "tag": "GENERATED"}), "WanGP still")

    def test_items_with_rung_and_site(self):
        self.assertEqual(edit.rung_label({"type": "layers", "rung": "imagegen", "site": "cloudflare"}), "Cloudflare image + parallax")
        self.assertEqual(edit._beat_rungs([{"rung": "graphics"}, {"tag": "GRAPHICS"}, {"rung": "headline"}]),
                         ["Remotion graphics", "Headline card"])


if __name__ == "__main__":
    unittest.main()
