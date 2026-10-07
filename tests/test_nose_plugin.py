import sys
import unittest
from nose2 import events, result
from nose2.session import Session

from pyrept.html_report import HTMLReporter


def _test_func():
    """
    A dummy test function.
    Bug 1234
    """
    pass


def _test_func_fail():
    """
    Test case that fails.
    """
    assert 1 == 2


for func in [_test_func, _test_func_fail]:
    setattr(func, '_testMethodDoc', func.__doc__)
setattr(_test_func, 'id', lambda: _test_func.__name__)
setattr(_test_func_fail, 'id', lambda: _test_func_fail.__name__)


def create_plugin_instance():
    return HTMLReporter(session=Session())


class NosePluginTests(unittest.TestCase):
    def test_outcome_processing_successful_test(self):
        test_function = _test_func
        ev = events.TestOutcomeEvent(test_function, None, result.PASS, expected=True)

        reporter = create_plugin_instance()
        reporter.testOutcome(ev)

        self.assertEqual(len(reporter.test_results), 1, 'Actual contents: %s' % reporter.test_results)
        test_result = reporter.test_results[0]
        self.assertEqual(test_result['result'], result.PASS)
        self.assertEqual(test_result['name'], test_function.__name__)
        self.assertEqual(test_result['description'], test_function.__doc__)
        self.assertIsNone(test_result['traceback'])

    def test_outcome_with_failed_test(self):
        test_function = _test_func_fail
        try:
            test_function()
        except AssertionError:
            exc_info = sys.exc_info()
        ev = events.TestOutcomeEvent(test_function, None, result.FAIL, exc_info=exc_info)

        reporter = create_plugin_instance()
        reporter.testOutcome(ev)

        self.assertEqual(len(reporter.test_results), 1, 'Actual contents: %s' % reporter.test_results)
        test_result = reporter.test_results[0]
        self.assertEqual(test_result['result'], result.FAIL)
        self.assertEqual(test_result['name'], test_function.__name__)
        self.assertEqual(test_result['description'], test_function.__doc__)
        self.assertIsNotNone(test_result['traceback'])
        self.assertIn('assert 1 == 2', test_result['traceback'])

    def test_summary_stats_new_test(self):
        ev = events.TestOutcomeEvent(_test_func, None, result.PASS, expected=True)
        reporter = create_plugin_instance()
        reporter.testOutcome(ev)

        self.assertIn('passed', reporter.summary_stats)
        self.assertEqual(reporter.summary_stats['passed'], 1)

    def test_summary_stats_increment(self):
        ev = events.TestOutcomeEvent(_test_func, None, result.PASS, expected=True)
        reporter = create_plugin_instance()
        reporter.summary_stats['passed'] = 10
        reporter.testOutcome(ev)

        self.assertIn('passed', reporter.summary_stats)
        self.assertEqual(reporter.summary_stats['passed'], 11)

    def test_summary_stats_total(self):
        ev = events.TestOutcomeEvent(_test_func, None, result.PASS, expected=True)
        reporter = create_plugin_instance()
        for i in range(0, 20):
            reporter.testOutcome(ev)

        self.assertIn('passed', reporter.summary_stats)
        self.assertEqual(reporter.summary_stats['total'], 20)

    def test_outcome_with_error_test_result(self):
        test_function = _test_func_fail
        try:
            test_function()
        except AssertionError:
            exc_info = sys.exc_info()
        ev = events.TestOutcomeEvent(test_function, None, result.ERROR, exc_info=exc_info)

        reporter = create_plugin_instance()
        reporter.testOutcome(ev)

        self.assertEqual(len(reporter.test_results), 1, 'Actual contents: %s' % reporter.test_results)
        test_result = reporter.test_results[0]
        self.assertEqual(test_result['result'], result.ERROR)
        self.assertEqual(test_result['name'], test_function.__name__)
        self.assertEqual(test_result['description'], test_function.__doc__)
        self.assertIsNotNone(test_result['traceback'])
        self.assertIn('assert 1 == 2', test_result['traceback'])


class FetchFilePathTests(unittest.TestCase):
    def test_defaults_are_none_so_config_can_apply(self):
        from pyrept.html_report import fetch_file_path
        self.assertEqual(fetch_file_path([]), {'html-report-path': None, 'json-report-path': None})

    def test_cli_paths(self):
        from pyrept.html_report import fetch_file_path
        paths = fetch_file_path(['--html-report-path=out/r.html', '--json-report-path=out/r.json'])
        self.assertEqual(paths, {'html-report-path': 'out/r.html', 'json-report-path': 'out/r.json'})

    def test_invalid_extension(self):
        from pyrept.html_report import fetch_file_path
        with self.assertRaises(ValueError):
            fetch_file_path(['--html-report-path=out/r.txt'])
        with self.assertRaises(ValueError):
            fetch_file_path(['--json-report-path=out/r.txt'])


class ConfigPathTests(unittest.TestCase):
    def _reporter_with_cfg(self, body):
        import os
        import tempfile
        tmp = tempfile.mkdtemp()
        cfg = os.path.join(tmp, 'nose2.cfg')
        with open(cfg, 'w') as fh:
            fh.write(body.format(tmp=tmp))
        session = Session()
        session.loadConfigFiles(cfg)
        return tmp, HTMLReporter(session=session)

    def test_config_file_paths_are_used(self):
        import os
        tmp, reporter = self._reporter_with_cfg(
            '[html-report]\nhtml-report-path = {tmp}/x.html\njson-report-path = {tmp}/x.json\n')
        self.assertEqual(reporter._config['html_report_path'], os.path.realpath(os.path.join(tmp, 'x.html')))
        self.assertEqual(reporter._config['json_report_path'], os.path.realpath(os.path.join(tmp, 'x.json')))

    def test_legacy_path_key(self):
        import os
        tmp, reporter = self._reporter_with_cfg('[html-report]\npath = {tmp}/legacy.html\n')
        self.assertEqual(reporter._config['html_report_path'], os.path.realpath(os.path.join(tmp, 'legacy.html')))


class _Sample(unittest.TestCase):
    """Real TestCase so events carry real ids, docstrings and subtests."""

    def test_method(self):
        """Sample docstring."""


def _exc_info(exc):
    try:
        raise exc
    except BaseException:
        return sys.exc_info()


class OutcomeMappingTests(unittest.TestCase):
    """nose2 reports expected failures, unexpected successes and subtests through
    the generic failed/passed/subtest outcomes; they need the same mapping as
    the unittest runner."""

    def setUp(self):
        self.test = _Sample('test_method')
        self.reporter = create_plugin_instance()

    def _make_subtest(self, **params):
        # TestCase.subTest() is a no-op outside a running test, so build one directly.
        from unittest.case import _SubTest, _subtest_msg_sentinel
        return _SubTest(self.test, _subtest_msg_sentinel, params)

    def _only_result(self):
        self.assertEqual(len(self.reporter.test_results), 1, self.reporter.test_results)
        return self.reporter.test_results[0]

    def test_expected_failure_is_skipped(self):
        ev = events.TestOutcomeEvent(self.test, None, result.FAIL, _exc_info(AssertionError('x')), expected=True)
        self.reporter.testOutcome(ev)
        r = self._only_result()
        self.assertEqual(r['result'], 'skipped')
        self.assertTrue(r['traceback'].startswith('Expected failure:'))
        self.assertTrue(r['metadata']['expected_failure'])
        self.assertEqual(self.reporter.summary_stats['failed'], 0)

    def test_unexpected_success_is_failed(self):
        self.reporter.testOutcome(events.TestOutcomeEvent(self.test, None, result.PASS, expected=False))
        r = self._only_result()
        self.assertEqual(r['result'], 'failed')
        self.assertIn('Unexpected success', r['traceback'])

    def test_passing_subtest_is_not_counted(self):
        subtest = self._make_subtest(i=0)
        self.reporter.testOutcome(events.TestOutcomeEvent(subtest, None, result.SUBTEST, None))
        self.assertEqual(self.reporter.test_results, [])
        self.assertEqual(self.reporter.summary_stats['total'], 0)
        self.assertNotIn('subtest', self.reporter.summary_stats)

    def test_failing_and_erroring_subtests(self):
        subtest = self._make_subtest(i=1)
        self.reporter.testOutcome(events.TestOutcomeEvent(
            subtest, None, result.SUBTEST, _exc_info(AssertionError('bad'))))
        self.reporter.testOutcome(events.TestOutcomeEvent(
            subtest, None, result.SUBTEST, _exc_info(KeyError('k'))))
        failed, errored = self.reporter.test_results
        self.assertEqual(failed['result'], 'failed')
        self.assertEqual(errored['result'], 'error')
        self.assertIn('(i=1)', failed['name'])
        self.assertEqual(failed['description'], 'Sample docstring.')
        self.assertNotIn('subtest', self.reporter.summary_stats)

    def test_skip_reason_is_kept(self):
        self.reporter.testOutcome(events.TestOutcomeEvent(self.test, None, result.SKIP, reason='no network'))
        r = self._only_result()
        self.assertEqual(r['result'], 'skipped')
        self.assertEqual(r['traceback'], 'Skipped: no network')

    def test_duration_from_start_test(self):
        import time
        self.reporter.startTest(events.StartTestEvent(self.test, None, time.time() - 0.25))
        self.reporter.testOutcome(events.TestOutcomeEvent(self.test, None, result.PASS, expected=True))
        self.assertGreaterEqual(self._only_result()['metadata']['duration'], 0.25)

    def test_module_import_errors_have_no_description(self):
        holder = unittest.suite._ErrorHolder('setUpModule (broken_module)')
        self.reporter.testOutcome(events.TestOutcomeEvent(holder, None, result.ERROR, _exc_info(ImportError('x'))))
        r = self._only_result()
        self.assertEqual(r['result'], 'error')
        self.assertIsNone(r['description'])
        self.assertIn('ImportError', r['traceback'])

    def test_after_summary_report_writes_both_files(self):
        import json
        import os
        import shutil
        import tempfile
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        self.reporter._config.update(html_report_path=os.path.join(tmp, 'r.html'),
                                     json_report_path=os.path.join(tmp, 'r.json'))
        self.reporter.testOutcome(events.TestOutcomeEvent(self.test, None, result.PASS, expected=True))
        self.reporter.afterSummaryReport(None)
        with open(os.path.join(tmp, 'r.json'), encoding='utf-8') as fh:
            data = json.load(fh)
        self.assertEqual(data['test_summary']['percentage'], 100.0)
        self.assertTrue(data['environment']['Framework'].startswith('nose2'))
        self.assertTrue(os.path.exists(os.path.join(tmp, 'r.html')))

    def test_comparison_without_output_stream_is_logged(self):
        import json
        import os
        import shutil
        import tempfile
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        baseline = os.path.join(tmp, 'b.json')
        with open(baseline, 'w', encoding='utf-8') as fh:
            json.dump({'test_results': []}, fh)
        self.reporter._config.update(html_report_path=os.path.join(tmp, 'r.html'),
                                     json_report_path=os.path.join(tmp, 'r.json'), baseline_report_path=baseline)
        self.reporter.testOutcome(events.TestOutcomeEvent(self.test, None, result.PASS, expected=True))
        with self.assertLogs('pyrept.html_report', level='INFO') as logs:
            self.reporter.afterSummaryReport(None)
        self.assertTrue(any('0 new failures' in line for line in logs.output))

    def test_event_metadata_is_not_mutated(self):
        ev = events.TestOutcomeEvent(self.test, None, result.PASS, expected=True)
        ev.metadata['custom'] = 1
        self.reporter.testOutcome(ev)
        self.reporter.test_results[0]['metadata']['extra'] = 2
        self.assertEqual(ev.metadata, {'custom': 1})


class NoseEndToEndTests(unittest.TestCase):
    def test_real_nose2_run(self):
        import json
        import os
        import shutil
        import subprocess
        import tempfile
        import textwrap
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        with open(os.path.join(tmp, 'test_sample.py'), 'w') as fh:
            fh.write(textwrap.dedent('''
                import unittest

                class T(unittest.TestCase):
                    def test_ok(self):
                        """Works."""

                    def test_fail(self):
                        self.assertEqual(1, 2)

                    @unittest.expectedFailure
                    def test_xfail(self):
                        self.assertTrue(False)

                    @unittest.expectedFailure
                    def test_xpass(self):
                        pass

                    @unittest.skip("later")
                    def test_skip(self):
                        pass

                    def test_subtests(self):
                        for i in range(3):
                            with self.subTest(i=i):
                                self.assertNotEqual(i, 1)
            '''))
        with open(os.path.join(tmp, 'nose2.cfg'), 'w') as fh:
            fh.write('[unittest]\nplugins = pyrept.html_report\n'
                     '[html-report]\nalways-on = True\n'
                     'html-report-path = out/r.html\njson-report-path = out/r.json\n')
        subprocess.run([sys.executable, '-m', 'nose2'], cwd=tmp, check=False, capture_output=True)
        with open(os.path.join(tmp, 'out', 'r.json'), encoding='utf-8') as fh:
            data = json.load(fh)
        stats = data['test_summary']
        self.assertEqual(stats['total'], 6)
        self.assertEqual(stats['passed'], 1)
        self.assertEqual(stats['failed'], 3)  # test_fail, unexpected success, subtest i=1
        self.assertEqual(stats['skipped'], 2)  # skip + expected failure
        self.assertNotIn('subtest', stats)
        results = {r['name'].split('.')[-1]: r['result'] for r in data['test_results']}
        self.assertEqual(results['test_xfail'], 'skipped')
        self.assertEqual(results['test_xpass'], 'failed')
        self.assertEqual(results['test_subtests (i=1)'], 'failed')
        self.assertTrue(os.path.exists(os.path.join(tmp, 'out', 'r.html')))


class NoseCommandLineTests(unittest.TestCase):
    """Report options on the nose2 command line (nose2 used to reject them as unknown)."""

    def setUp(self):
        import os
        import shutil
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        with open(os.path.join(self.tmp, 'test_cli_sample.py'), 'w') as fh:
            fh.write('import unittest\n\nclass T(unittest.TestCase):\n    def test_ok(self):\n        pass\n')
        with open(os.path.join(self.tmp, 'nose2.cfg'), 'w') as fh:
            fh.write('[unittest]\nplugins = pyrept.html_report\n')

    def _nose2(self, *args):
        import subprocess
        return subprocess.run([sys.executable, '-m', 'nose2', '--html-report'] + list(args), cwd=self.tmp,
                              capture_output=True, text=True, check=False)

    def test_path_options_junit_and_baseline(self):
        import json
        import os
        import xml.etree.ElementTree as ET
        args = ['--html-report-path=out/r.html', '--json-report-path=out/r.json', '--junit-report-path=out/j.xml']
        first = self._nose2(*args)
        self.assertEqual(first.returncode, 0, first.stderr)
        for name in ('r.html', 'r.json', 'j.xml'):
            self.assertTrue(os.path.exists(os.path.join(self.tmp, 'out', name)), name)
        self.assertEqual(ET.parse(os.path.join(self.tmp, 'out', 'j.xml')).getroot().get('tests'), '1')

        second = self._nose2('--html-report-path=out/r.html', '--json-report-path=out/r.json',
                             '--baseline-report-path=out/r.json')
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn('pyrept: 0 new failures, 0 fixed, 0 still failing (vs r.json)', second.stderr + second.stdout)
        with open(os.path.join(self.tmp, 'out', 'r.json'), encoding='utf-8') as fh:
            self.assertEqual(json.load(fh)['comparison']['new_failures'], [])

    def test_config_file_keys(self):
        import os
        with open(os.path.join(self.tmp, 'nose2.cfg'), 'a') as fh:
            fh.write('[html-report]\njunit-report-path = cfg/j.xml\nbaseline-report-path = cfg/none.json\n')
        result = self._nose2()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(os.path.exists(os.path.join(self.tmp, 'cfg', 'j.xml')))
        self.assertTrue(os.path.exists(os.path.join(self.tmp, 'report.html')))

    def test_wrong_extension_is_rejected(self):
        result = self._nose2('--junit-report-path=out/j.txt')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('must end with .xml', result.stderr)


class NoseSummaryAndGateTests(unittest.TestCase):
    KNOWN = ('import unittest\n\nclass T(unittest.TestCase):\n    def test_ok(self):\n        pass\n'
             '    def test_known_bug(self):\n        self.assertEqual(1, 2)\n')

    def setUp(self):
        import os
        import shutil
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self._write(self.KNOWN)
        with open(os.path.join(self.tmp, 'nose2.cfg'), 'w') as fh:
            fh.write('[unittest]\nplugins = pyrept.html_report\n')

    def _write(self, body):
        import os
        with open(os.path.join(self.tmp, 'test_gate_sample.py'), 'w') as fh:
            fh.write(body)

    def _nose2(self, *args, **env):
        import os
        import subprocess
        return subprocess.run([sys.executable, '-m', 'nose2', '--html-report'] + list(args), cwd=self.tmp,
                              capture_output=True, text=True, check=False, env=dict(os.environ, **env))

    def test_markdown_and_github_summary(self):
        import os
        summary = os.path.join(self.tmp, 'gh.md')
        result = self._nose2('--markdown-report-path=out/s.md', '--pyrept-github-summary',
                             GITHUB_STEP_SUMMARY=summary)
        self.assertEqual(result.returncode, 1, result.stderr)
        for path in (os.path.join(self.tmp, 'out', 's.md'), summary):
            with open(path, encoding='utf-8') as fh:
                self.assertIn('❌ Test Report: 1 failed', fh.read())

    def test_markdown_path_must_end_in_md(self):
        result = self._nose2('--markdown-report-path=out/s.txt')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('must end with .md', result.stderr)

    def test_ignore_known_failures_and_fail_under(self):
        self.assertEqual(self._nose2().returncode, 1)
        known = self._nose2('--baseline-report-path=report.json', '--pyrept-ignore-known-failures')
        self.assertEqual(known.returncode, 0, known.stderr)
        self.assertIn('pyrept: 1 known failure ignored', known.stderr)
        floor = self._nose2('--baseline-report-path=report.json', '--pyrept-ignore-known-failures',
                            '--pyrept-fail-under=60')
        self.assertEqual(floor.returncode, 1, floor.stderr)
        self.assertIn('pass rate 50.0% is below fail-under=60', floor.stderr)
        no_baseline = self._nose2('--pyrept-ignore-known-failures')
        self.assertEqual(no_baseline.returncode, 1)
        self.assertIn('needs a baseline-report-path report', no_baseline.stderr)

        self._write(self.KNOWN + '    def test_new_bug(self):\n        raise RuntimeError("new")\n')
        new = self._nose2('--baseline-report-path=report.json', '--pyrept-ignore-known-failures')
        self.assertEqual(new.returncode, 1, new.stderr)

    def test_config_file_keys(self):
        import os
        self._nose2()  # baseline with the known failure
        with open(os.path.join(self.tmp, 'nose2.cfg'), 'a') as fh:
            fh.write('[html-report]\nbaseline-report-path = report.json\nignore-known-failures = true\n'
                     'fail-under = 10\nmarkdown-report-path = cfg/s.md\n')
        result = self._nose2()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(os.path.exists(os.path.join(self.tmp, 'cfg', 's.md')))

    def test_without_gates_nose2_decides(self):
        import os
        with open(os.path.join(self.tmp, 'test_gate_sample.py'), 'w') as fh:
            fh.write('import unittest\n\nclass T(unittest.TestCase):\n    def test_ok(self):\n        pass\n')
        self.assertEqual(self._nose2().returncode, 0)


class MissingNose2Tests(unittest.TestCase):
    def test_helpful_error_without_nose2(self):
        import subprocess
        code = ('import sys; sys.modules["nose2"] = None\n'
                'try:\n    import pyrept.html_report\nexcept ImportError as exc:\n    print(exc)\n')
        out = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, check=True).stdout
        self.assertIn('pip install "pyrept[nose2]"', out)
