"""Synthetic tests; no personal documents or live services are used."""
import base64
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'weread_optimize.py'
PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+i2ioAAAAASUVORK5CYII=')


class HtmlPreservation(unittest.TestCase):
    def convert(self, markup):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'sample.png').write_bytes(PNG)
            (root / '01-sample.html').write_text('<html><body><article>' + markup + '</article></body></html>', encoding='utf-8')
            env = dict(os.environ, WEREAD_INPUT_DIR=str(root), WEREAD_OUTPUT_DIR=str(root / 'out'), WEREAD_HTML_ONLY='1', WEREAD_COMBINE_HTML='1')
            result = subprocess.run([sys.executable, str(SCRIPT)], env=env, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            with zipfile.ZipFile(next((root / 'out' / 'epub').glob('*.epub'))) as archive:
                return {name: archive.read(name) for name in archive.namelist()}

    def test_relative_image_is_embedded(self):
        files = self.convert('<h1>Image</h1><p>Before</p><img src="sample.png"/><p>After</p>')
        self.assertTrue(any(name.endswith('.png') for name in files))
        text = '\n'.join(data.decode() for name, data in files.items() if name.endswith('.xhtml'))
        self.assertIn('<img ', text)
        self.assertLess(text.index('Before'), text.index('<img '))
        self.assertLess(text.index('<img '), text.index('After'))

    def test_media_omission_is_visible_in_book(self):
        files = self.convert('<h1>Media</h1><p>Text</p><video src="sample.mp4"></video>')
        text = '\n'.join(data.decode() for name, data in files.items() if name.endswith('.xhtml'))
        self.assertIn('未嵌入该媒体', text)

    def test_image_outside_input_is_not_read(self):
        files = self.convert('<h1>Boundary</h1><img src="../outside.png"/>')
        text = '\n'.join(data.decode() for name, data in files.items() if name.endswith('.xhtml'))
        self.assertIn('图片未嵌入', text)
        self.assertFalse(any(name.endswith('.png') for name in files))


if __name__ == '__main__':
    unittest.main()
