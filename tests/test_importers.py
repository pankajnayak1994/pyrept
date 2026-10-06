import json
import os
import shutil
import tempfile
import unittest

from pyrept.cli import main
from pyrept.importers import load_cucumber_json, load_playwright_json

FIXTURES = os.path.join(os.path.dirname(__file__), 'fixtures')


class CucumberImporterTests(unittest.TestCase):
    def setUp(self):
        collector = load_cucumber_json(os.path.join(FIXTURES, 'cucumber.json'))
        self.results = {r['name']: r for r in collector.test_results}

    def test_outcomes(self):
        self.assertEqual(self.results['Login :: Valid credentials']['result'], 'passed')
        self.assertEqual(self.results['Login :: Wrong password']['result'], 'failed')
        self.assertEqual(self.results['Login :: Single sign-on']['result'], 'error')  # undefined step

    def test_background_steps_and_tags_in_description(self):
        desc = self.results['Login :: Valid credentials']['description']
        self.assertTrue(desc.startswith('@smoke'))
        self.assertIn('Given the app is open', desc)

    def test_failure_details(self):
        failed = self.results['Login :: Wrong password']
        self.assertIn('expected banner', failed['traceback'])
        self.assertAlmostEqual(failed['metadata']['duration'], 0.151)
        self.assertEqual(failed['metadata']['attachments'][0]['content_type'], 'image/png')


class PlaywrightImporterTests(unittest.TestCase):
    def setUp(self):
        collector = load_playwright_json(os.path.join(FIXTURES, 'playwright.json'))
        self.results = {r['name']: r for r in collector.test_results}

    def test_outcomes_per_project(self):
        prefix = 'checkout.spec.ts › Checkout › '
        self.assertEqual(self.results['[chromium] ' + prefix + 'adds item to cart']['result'], 'passed')
        flaky = self.results['[firefox] ' + prefix + 'adds item to cart']
        self.assertEqual(flaky['result'], 'passed')
        self.assertTrue(flaky['metadata']['flaky'])
        self.assertEqual(flaky['metadata']['retries'], 1)
        self.assertEqual(self.results['[chromium] ' + prefix + 'pays with card']['result'], 'failed')
        self.assertEqual(self.results['[chromium] ' + prefix + 'applies coupon']['result'], 'skipped')
        self.assertEqual(self.results['[webkit] ' + prefix + 'slow network']['result'], 'error')

    def test_screenshot_is_embedded_and_trace_linked(self):
        failed = self.results['[chromium] checkout.spec.ts › Checkout › pays with card']
        attachments = {a['name']: a for a in failed['metadata']['attachments']}
        self.assertIn('data', attachments['screenshot'])
        self.assertNotIn('data', attachments['trace'])
        self.assertTrue(attachments['trace']['path'].endswith('trace.zip'))
        self.assertIn('toBeVisible', failed['traceback'])


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)

    def test_convert_merges_inputs_and_fail_flag(self):
        html = os.path.join(self.tmp, 'r.html')
        jsn = os.path.join(self.tmp, 'r.json')
        code = main(['convert', '--from', 'cucumber', os.path.join(FIXTURES, 'cucumber.json'),
                     os.path.join(FIXTURES, 'cucumber.json'), '--html', html, '--json', jsn,
                     '--fail-on-failure', '--title', 'BDD'])
        self.assertEqual(code, 1)
        with open(jsn, encoding='utf-8') as fh:
            data = json.load(fh)
        self.assertEqual(data['test_summary']['total'], 6)
        self.assertEqual(data['test_report_title'], 'BDD')
        with open(html, encoding='utf-8') as fh:
            self.assertIn('Wrong password', fh.read())

    def test_missing_input(self):
        self.assertEqual(main(['convert', '--from', 'playwright', os.path.join(self.tmp, 'nope.json')]), 2)
