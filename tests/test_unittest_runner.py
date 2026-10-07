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


class UnittestJUnitAndBaselineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.mod = 'test_jb_%s' % uuid.uuid4().hex[:8]

    def _run_module(self, body, **kwargs):
        with open(os.path.join(self.tmp, self.mod + '.py'), 'w') as fh:
            fh.write(textwrap.dedent(body))
        sys.modules.pop(self.mod, None)  # the second run must import the rewritten module
        suite = unittest.TestLoader().discover(self.tmp, pattern=self.mod + '.py', top_level_dir=self.tmp)
        stream = io.StringIO()
        PyreptTestRunner(stream=stream, html_path=os.path.join(self.tmp, 'r.html'),
                         json_path=os.path.join(self.tmp, 'r.json'), **kwargs).run(suite)
        with open(os.path.join(self.tmp, 'r.json'), encoding='utf-8') as fh:
            return stream.getvalue(), json.load(fh)

    def test_junit_and_same_file_baseline(self):
        import xml.etree.ElementTree as ET
        junit = os.path.join(self.tmp, 'junit.xml')
        baseline = os.path.join(self.tmp, 'r.json')
        out, data = self._run_module('''
            import unittest
            class T(unittest.TestCase):
                def test_a(self):
                    pass
        ''', junit_path=junit, baseline_path=baseline)
        self.assertIn('pyrept JUnit report: %s' % os.path.realpath(junit), out)
        self.assertIsNone(data['comparison'])
        case = ET.parse(junit).getroot().find('testsuite/testcase')
        self.assertEqual((case.get('classname'), case.get('name')), ('%s.T' % self.mod, 'test_a'))

        out, data = self._run_module('''
            import unittest
            class T(unittest.TestCase):
                def test_a(self):
                    self.fail("broken")
        ''', baseline_path=baseline)
        self.assertIn('pyrept: 1 new failure', out)
        self.assertEqual(data['comparison']['new_failures'], ['%s.T.test_a' % self.mod])

    def test_main_options(self):
        with open(os.path.join(self.tmp, self.mod + '.py'), 'w') as fh:
            fh.write('import unittest\n\nclass T(unittest.TestCase):\n    def test_a(self):\n        pass\n')
        junit = os.path.join(self.tmp, 'cli-junit.xml')
        cwd = os.getcwd()
        os.chdir(self.tmp)
        try:
            with self.assertRaises(SystemExit):
                main(['prog', 'discover', '-p', self.mod + '.py', '-q', '--pyrept-junit', junit,
                      '--pyrept-baseline=' + os.path.join(self.tmp, 'missing.json'),
                      '--pyrept-json', os.path.join(self.tmp, 'cli.json'),
                      '--pyrept-html', os.path.join(self.tmp, 'cli.html')])
        finally:
            os.chdir(cwd)
        self.assertTrue(os.path.exists(junit))


class UnittestSummaryAndGateTests(unittest.TestCase):
    KNOWN = '''
        import unittest
        class T(unittest.TestCase):
            def test_ok(self):
                pass
            def test_known_bug(self):
                self.assertEqual(1, 2)
    '''

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.mod = 'test_gate_%s' % uuid.uuid4().hex[:8]

    def _write(self, body):
        with open(os.path.join(self.tmp, self.mod + '.py'), 'w') as fh:
            fh.write(textwrap.dedent(body))
        sys.modules.pop(self.mod, None)

    def _main(self, *args):
        """Run main() like the command line; returns (exit code, output)."""
        stream = io.StringIO()
        cwd = os.getcwd()
        os.chdir(self.tmp)
        try:
            argv = ['prog', 'discover', '-p', self.mod + '.py',
                    '--pyrept-json', os.path.join(self.tmp, 'r.json'),
                    '--pyrept-html', os.path.join(self.tmp, 'r.html')] + list(args)
            stderr, sys.stderr = sys.stderr, stream
            try:
                with self.assertRaises(SystemExit) as raised:
                    main(argv)
            finally:
                sys.stderr = stderr
        finally:
            os.chdir(cwd)
        code = raised.exception.code
        return (int(code) if code not in (None, True, False) else int(bool(code))), stream.getvalue()

    def test_markdown_and_github_summary(self):
        self._write(self.KNOWN)
        summary = os.path.join(self.tmp, 'gh.md')
        os.environ['GITHUB_STEP_SUMMARY'] = summary  # removed again by the conftest fixture
        try:
            code, out = self._main('--pyrept-markdown', os.path.join(self.tmp, 'md', 's.md'), '--pyrept-github-summary')
        finally:
            del os.environ['GITHUB_STEP_SUMMARY']
        self.assertEqual(code, 1)
        self.assertIn('pyrept Markdown summary:', out)
        for path in (os.path.join(self.tmp, 'md', 's.md'), summary):
            with open(path, encoding='utf-8') as fh:
                self.assertIn('❌ Test Report: 1 failed', fh.read())

    def test_ignore_known_failures_and_fail_under(self):
        self._write(self.KNOWN)
        self.assertEqual(self._main()[0], 1)
        baseline = '--pyrept-baseline=' + os.path.join(self.tmp, 'r.json')
        code, out = self._main(baseline, '--pyrept-ignore-known-failures')
        self.assertEqual(code, 0, out)
        self.assertIn('pyrept: 1 known failure ignored', out)
        code, out = self._main(baseline, '--pyrept-ignore-known-failures', '--pyrept-fail-under', '75')
        self.assertEqual(code, 1, out)
        self.assertIn('pass rate 50.0% is below --pyrept-fail-under=75', out)

        self._write(self.KNOWN + '''
            def test_new_bug(self):
                raise RuntimeError("new")
        ''')
        code, out = self._main(baseline, '--pyrept-ignore-known-failures')
        self.assertEqual(code, 1, out)
        with open(os.path.join(self.tmp, 'r.json'), encoding='utf-8') as fh:
            self.assertEqual(json.load(fh)['comparison']['new_failures'], ['%s.T.test_new_bug' % self.mod])

    def test_invalid_fail_under(self):
        self._write(self.KNOWN)
        code, out = self._main('--pyrept-fail-under=high')
        self.assertEqual(code, 2)
        self.assertIn('fail-under must be a number', out)

    def test_runner_api_validates_fail_under(self):
        with self.assertRaises(ValueError):
            PyreptTestRunner(stream=io.StringIO(), fail_under=150)

    def test_pop_flag(self):
        from pyrept.unittest_runner import _pop_flag
        self.assertEqual(_pop_flag(['p', '--f', 'a', '--f'], '--f'), (True, ['p', 'a']))
        self.assertEqual(_pop_flag(['p', '--fx'], '--f'), (False, ['p', '--fx']))
