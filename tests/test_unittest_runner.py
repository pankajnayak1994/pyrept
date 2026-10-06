import io
import json
import os
import shutil
import tempfile
import textwrap
import unittest
import uuid

from pyrept.unittest_runner import PyreptTestRunner, main

SAMPLE = textwrap.dedent('''
    import unittest

    class Sample(unittest.TestCase):
        def test_ok(self):
            """Works fine."""

        def test_fail(self):
            self.assertEqual(1, 2)

        def test_error(self):
            raise RuntimeError("boom")

        @unittest.skip("later")
        def test_skip(self):
            pass

        @unittest.expectedFailure
        def test_expected_failure(self):
            self.assertTrue(False)

        def test_subtests(self):
            for i in range(3):
                with self.subTest(i=i):
                    self.assertNotEqual(i, 1)
''')


class UnittestRunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.mod = 'test_sample_%s' % uuid.uuid4().hex[:8]
        with open(os.path.join(self.tmp, self.mod + '.py'), 'w') as fh:
            fh.write(SAMPLE)
        self.addCleanup(shutil.rmtree, self.tmp)

    def _suite(self):
        return unittest.defaultTestLoader.discover(self.tmp, pattern=self.mod + '.py', top_level_dir=self.tmp)

    def _load(self, path):
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)

    def test_runner_writes_reports(self):
        html = os.path.join(self.tmp, 'out', 'r.html')
        jsn = os.path.join(self.tmp, 'out', 'r.json')
        result = PyreptTestRunner(stream=io.StringIO(), html_path=html, json_path=jsn).run(self._suite())
        self.assertFalse(result.wasSuccessful())
        self.assertTrue(os.path.exists(html))
        data = self._load(jsn)
        stats = data['test_summary']
        self.assertEqual(stats['total'], 6)
        self.assertEqual(stats['passed'], 1)
        self.assertEqual(stats['failed'], 2)  # test_fail + subtest i=1
        self.assertEqual(stats['error'], 1)
        self.assertEqual(stats['skipped'], 2)  # skip + expected failure
        by_name = {r['name'].split('.')[-1]: r for r in data['test_results']}
        self.assertEqual(by_name['test_ok']['description'], 'Works fine.')
        self.assertIn('boom', by_name['test_error']['traceback'])
        self.assertIn('test_subtests (i=1)', by_name)
        self.assertEqual(data['environment']['Framework'], 'unittest')

    def test_main_parses_pyrept_options(self):
        html = os.path.join(self.tmp, 'cli.html')
        jsn = os.path.join(self.tmp, 'cli.json')
        cwd = os.getcwd()
        os.chdir(self.tmp)
        try:
            with self.assertRaises(SystemExit):
                main(['prog', 'discover', '-p', self.mod + '.py', '-q',
                      '--pyrept-html=' + html, '--pyrept-json', jsn])
        finally:
            os.chdir(cwd)
        self.assertEqual(self._load(jsn)['test_summary']['total'], 6)
