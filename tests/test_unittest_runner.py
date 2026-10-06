import io
import json
import os
import shutil
import sys
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
        # Fresh loader: before Python 3.11 discover() caches the top-level dir on the
        # shared defaultTestLoader, which breaks the later unittest.main() based tests.
        return unittest.TestLoader().discover(self.tmp, pattern=self.mod + '.py', top_level_dir=self.tmp)

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

    def test_durations_skip_reasons_and_unexpected_success(self):
        with open(os.path.join(self.tmp, self.mod + '.py'), 'w') as fh:
            fh.write(textwrap.dedent('''
                import time
                import unittest

                class T(unittest.TestCase):
                    def test_slow(self):
                        time.sleep(0.05)

                    @unittest.skip("needs network")
                    def test_skip(self):
                        pass

                    @unittest.expectedFailure
                    def test_xpass(self):
                        pass
            '''))
        jsn = os.path.join(self.tmp, 'r.json')
        PyreptTestRunner(stream=io.StringIO(), html_path=os.path.join(self.tmp, 'r.html'),
                         json_path=jsn).run(self._suite())
        data = self._load(jsn)
        by_name = {r['name'].split('.')[-1]: r for r in data['test_results']}
        self.assertGreaterEqual(by_name['test_slow']['metadata']['duration'], 0.05)
        self.assertEqual(data['slowest_tests'][0]['name'].split('.')[-1], 'test_slow')
        self.assertEqual(by_name['test_skip']['traceback'], 'Skipped: needs network')
        self.assertEqual(by_name['test_xpass']['result'], 'failed')
        self.assertIn('Unexpected success', by_name['test_xpass']['traceback'])
        self.assertEqual(by_name['test_slow']['metadata']['framework'], 'unittest')

    def test_class_fixture_errors_are_reported(self):
        with open(os.path.join(self.tmp, self.mod + '.py'), 'w') as fh:
            fh.write(textwrap.dedent('''
                import unittest

                class Broken(unittest.TestCase):
                    @classmethod
                    def setUpClass(cls):
                        raise RuntimeError("db down")

                    def test_never_runs(self):
                        pass
            '''))
        jsn = os.path.join(self.tmp, 'r.json')
        PyreptTestRunner(stream=io.StringIO(), html_path=os.path.join(self.tmp, 'r.html'),
                         json_path=jsn).run(self._suite())
        data = self._load(jsn)
        self.assertEqual(data['test_summary']['error'], 1)
        self.assertIn('setUpClass', data['test_results'][0]['name'])
        self.assertIn('db down', data['test_results'][0]['traceback'])

    def test_failing_subtests_do_not_leak_start_times(self):
        stream = io.StringIO()
        runner = PyreptTestRunner(stream=stream, html_path=os.path.join(self.tmp, 'r.html'),
                                  json_path=os.path.join(self.tmp, 'r.json'))
        result = runner.run(self._suite())
        self.assertEqual(result._start_times, {})

    def test_main_title_option(self):
        jsn = os.path.join(self.tmp, 'cli.json')
        cwd = os.getcwd()
        os.chdir(self.tmp)
        try:
            with self.assertRaises(SystemExit):
                main(['prog', 'discover', '-p', self.mod + '.py', '-q', '--pyrept-json=' + jsn,
                      '--pyrept-html', os.path.join(self.tmp, 'cli.html'), '--pyrept-title', 'Nightly'])
        finally:
            os.chdir(cwd)
        self.assertEqual(self._load(jsn)['test_report_title'], 'Nightly')

    @unittest.skipIf(sys.version_info < (3, 12), '--durations was added in Python 3.12')
    def test_unittest_durations_flag_still_works(self):
        stream = io.StringIO()
        runner = PyreptTestRunner(stream=stream, durations=0, html_path=os.path.join(self.tmp, 'r.html'),
                                  json_path=os.path.join(self.tmp, 'r.json'))
        runner.run(self._suite())
        self.assertIn('Slowest test durations', stream.getvalue())


class PopOptionTests(unittest.TestCase):
    def test_forms_and_missing_value(self):
        from pyrept.unittest_runner import _pop_option
        self.assertEqual(_pop_option(['p', '--x=1', 'a'], '--x', 'd'), ('1', ['p', 'a']))
        self.assertEqual(_pop_option(['p', '--x', '2', 'a'], '--x', 'd'), ('2', ['p', 'a']))
        self.assertEqual(_pop_option(['p', 'a'], '--x', 'd'), ('d', ['p', 'a']))
        # A trailing flag without a value is left for unittest to complain about.
        self.assertEqual(_pop_option(['p', '--x'], '--x', 'd'), ('d', ['p', '--x']))
        # Prefix of another option is not consumed.
        self.assertEqual(_pop_option(['p', '--xy=1'], '--x', 'd'), ('d', ['p', '--xy=1']))
