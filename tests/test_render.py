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


class DefaultLogoAndSignatureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)

    def _html(self, **env):
        for key, value in env.items():
            os.environ[key] = value  # removed again by the conftest fixture
        try:
            c = ReportCollector()
            c.add('t', 'passed')
            c.write(os.path.join(self.tmp, 'r.html'), os.path.join(self.tmp, 'r.json'))
        finally:
            for key in env:
                del os.environ[key]
        with open(os.path.join(self.tmp, 'r.html'), encoding='utf-8') as fh:
            return fh.read()

    def test_pyrept_logo_is_the_default_logo_and_favicon(self):
        from pyrept.branding import default_favicon, default_logo
        logo, favicon = default_logo(), default_favicon()
        for uri in (logo, favicon):
            self.assertTrue(uri.startswith('data:image/jpeg;base64,/9j/'))
        self.assertLess(len(logo) + len(favicon), 25000)  # small enough to embed in every report
        html = self._html()
        self.assertIn('<link rel="icon" href="%s">' % favicon, html)
        self.assertIn('<img src="%s" alt="">' % logo, html)
        with open(os.path.join(self.tmp, 'r.json'), encoding='utf-8') as fh:
            self.assertNotIn('/9j/', fh.read())

    def test_logo_can_be_turned_off_or_replaced(self):
        html = self._html(PYREPT_LOGO='none')
        self.assertNotIn('rel="icon"', html)
        self.assertIn('class="mark"', html)  # the built-in check mark instead
        html = self._html(PYREPT_LOGO='https://cdn.example/brand.svg')
        self.assertIn('<link rel="icon" href="https://cdn.example/brand.svg">', html)

    def test_unusable_logo_falls_back_to_the_pyrept_logo(self):
        from pyrept.branding import branding_from_env, default_logo
        with self.assertLogs('pyrept.branding', 'WARNING'):
            self.assertEqual(branding_from_env({'PYREPT_LOGO': os.path.join(self.tmp, 'missing.png')})['logo'],
                             default_logo())

    def test_missing_logo_asset(self):
        from unittest import mock
        from pyrept import branding
        branding.default_logo.cache_clear()
        self.addCleanup(branding.default_logo.cache_clear)
        with mock.patch.object(branding, 'DEFAULT_LOGO', os.path.join(self.tmp, 'gone.jpg')):
            self.assertIsNone(branding.default_logo())
            html = self._html()
        self.assertIn('class="mark"', html)  # falls back to the built-in check mark

    def test_developer_signature(self):
        from pyrept import AUTHOR, __author__
        self.assertEqual(AUTHOR, 'Pankaj Kumar Nayak')
        self.assertEqual(__author__, AUTHOR)
        self.assertIn('Developed by <a href="https://github.com/pankajnayak1994">Pankaj Kumar Nayak</a>', self._html())

    def test_version_mentions_the_developer(self):
        import contextlib
        import io
        from pyrept.cli import main
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
            main(['--version'])
        self.assertRegex(out.getvalue(), r'^pyrept \S+, developed by Pankaj Kumar Nayak')
