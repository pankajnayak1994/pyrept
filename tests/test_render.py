import os
import shutil
import tempfile
import unittest

from pyrept.branding import accent_color, branding_from_env, logo_source
from pyrept.render import load_template, split_test_name
from pyrept.report import ReportCollector

PNG = b'\x89PNG\r\n\x1a\n'


class SplitTestNameTests(unittest.TestCase):
    def test_formats(self):
        cases = {
            'tests/test_a.py::test_x': ('tests/test_a.py::', 'test_x'),
            'tests/test_a.py::TestK::test_x[a::b]': ('tests/test_a.py::TestK::', 'test_x[a::b]'),
            'Login :: Wrong password': ('Login :: ', 'Wrong password'),
            '[chromium] cart.spec.ts › Cart › adds item': ('[chromium] cart.spec.ts › Cart › ', 'adds item'),
            'pkg.mod.TestX.test_y (i=1)': ('pkg.mod.TestX.', 'test_y (i=1)'),
            'Suite.Login.Valid Login': ('Suite.Login.', 'Valid Login'),
            'plain name': ('', 'plain name'),
            '': ('', ''),
            '::odd': ('', '::odd'),
        }
        for name, expected in cases.items():
            self.assertEqual(split_test_name(name), expected, name)
        self.assertEqual(split_test_name(42), ('', '42'))


class BrandingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)

    def test_logo_file_url_and_bad_values(self):
        path = os.path.join(self.tmp, 'logo.png')
        with open(path, 'wb') as fh:
            fh.write(PNG)
        self.assertEqual(logo_source(path), 'data:image/png;base64,iVBORw0KGgo=')
        self.assertEqual(logo_source('https://cdn.example/logo.svg'), 'https://cdn.example/logo.svg')
        self.assertIsNone(logo_source(''))
        with self.assertLogs('pyrept.branding', 'WARNING'):
            self.assertIsNone(logo_source(os.path.join(self.tmp, 'notes.txt')))
        with self.assertLogs('pyrept.branding', 'WARNING'):
            self.assertIsNone(logo_source(os.path.join(self.tmp, 'missing.png')))
        big = os.path.join(self.tmp, 'big.png')
        with open(big, 'wb') as fh:
            fh.write(b'0' * (1024 * 1024 + 1))
        with self.assertLogs('pyrept.branding', 'WARNING'):
            self.assertIsNone(logo_source(big))

    def test_accent_colour_is_validated(self):
        for good in ('#0f766e', '#ABC', '#11223344'):
            self.assertEqual(accent_color(good), good)
        for bad in ('red', '#12', '#0f766e; } body { display:none', 'url(x)'):
            with self.assertLogs('pyrept.branding', 'WARNING'):
                self.assertIsNone(accent_color(bad))
        self.assertIsNone(accent_color(None))

    def test_branding_in_html_but_not_json(self):
        path = os.path.join(self.tmp, 'logo.png')
        with open(path, 'wb') as fh:
            fh.write(PNG)
        os.environ['PYREPT_LOGO'] = path  # removed again by the conftest fixture
        os.environ['PYREPT_ACCENT_COLOR'] = '#0f766e'
        try:
            self.assertEqual(branding_from_env()['accent'], '#0f766e')
            c = ReportCollector()
            c.add('t', 'passed')
            c.write(os.path.join(self.tmp, 'r.html'), os.path.join(self.tmp, 'r.json'))
        finally:
            del os.environ['PYREPT_LOGO'], os.environ['PYREPT_ACCENT_COLOR']
        with open(os.path.join(self.tmp, 'r.html'), encoding='utf-8') as fh:
            html = fh.read()
        self.assertIn('--accent: #0f766e', html)
        self.assertIn('src="data:image/png;base64,iVBORw0KGgo="', html)
        with open(os.path.join(self.tmp, 'r.json'), encoding='utf-8') as fh:
            text = fh.read()
        self.assertNotIn('branding', text)
        self.assertNotIn('iVBORw0KGgo', text)


class TemplateLoadingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)

    def test_custom_template_can_include_the_theme(self):
        path = os.path.join(self.tmp, 'mine.html')
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write("<style>{% include '_theme.css' %}</style>"
                     "{{ test_report_title }}|{{ 'a::b'|split_test_name|join('+') }}")
        c = ReportCollector(title='Custom')
        c.add('t', 'passed')
        out = os.path.join(self.tmp, 'out.html')
        c.write(out, os.path.join(self.tmp, 'r.json'), template_path=path)
        with open(out, encoding='utf-8') as fh:
            text = fh.read()
        self.assertIn('pyrept design system', text)
        self.assertTrue(text.endswith('Custom|a::+b'))

    def test_missing_template(self):
        with self.assertRaises(FileNotFoundError):
            load_template(os.path.join(self.tmp, 'nope.html'))

    def test_report_page_features(self):
        c = ReportCollector(title='Shop')
        c.add('tests/test_a.py::test_ok', 'passed', metadata={'duration': 0.5, 'tags': ['smoke']})
        c.add('tests/test_a.py::test_bad', 'failed', traceback='boom', metadata={'duration': 2.0})
        out = os.path.join(self.tmp, 'r.html')
        c.write(out, os.path.join(self.tmp, 'r.json'))
        with open(out, encoding='utf-8') as fh:
            html = fh.read()
        self.assertIn('<title>✕ Shop</title>', html)
        self.assertIn('class="hero is-failed"', html)
        self.assertIn('<span class="where">tests/test_a.py::</span><span class="leaf">test_bad</span>', html)
        self.assertIn('class="map"', html)
        self.assertIn('data-target="t1"', html)
        self.assertIn('id="t2"', html)
        self.assertIn('data-duration="2.0"', html)
        self.assertIn('stroke-dasharray="50.000 50.000"', html)  # ring: half passed
