import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest

from pyrept.cli import load_report, main

FIXTURES = os.path.join(os.path.dirname(__file__), 'fixtures')
CUCUMBER = os.path.join(FIXTURES, 'cucumber.json')  # 1 passed, 1 failed, 1 error


def _run(*argv):
    """Run the CLI; returns (exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = main(list(argv))
        except SystemExit as exc:  # argparse errors
            code = exc.code
    return code, out.getvalue(), err.getvalue()


class ConvertOptionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)

    def _convert(self, *extra):
        return _run('convert', '--from', 'cucumber', CUCUMBER, '--html', self._p('r.html'),
                    '--json', self._p('r.json'), *extra)

    def _p(self, name):
        return os.path.join(self.tmp, name)

    def test_markdown_github_summary_and_report_url(self):
        summary = self._p('gh.md')
        os.environ['GITHUB_STEP_SUMMARY'] = summary  # removed again by the conftest fixture
        try:
            code, out, _ = self._convert('--markdown', self._p('md/s.md'), '--github-summary',
                                         '--report-url', 'https://ci.example/r.html')
        finally:
            del os.environ['GITHUB_STEP_SUMMARY']
        self.assertEqual(code, 0)
        self.assertIn('pyrept Markdown summary: %s' % os.path.realpath(self._p('md/s.md')), out)
        for path in (self._p('md/s.md'), summary):
            with open(path, encoding='utf-8') as fh:
                text = fh.read()
            self.assertIn('❌ Cucumber Test Report: 1 failed, 1 error', text)
            self.assertIn('(https://ci.example/r.html)', text)

    def test_fail_under(self):
        self.assertEqual(self._convert('--fail-under', '30')[0], 0)
        code, out, _ = self._convert('--fail-under', '50')
        self.assertEqual(code, 1)
        self.assertIn('pass rate 33.33% is below --fail-under=50', out)

    def test_ignore_known_failures(self):
        self.assertEqual(self._convert('--fail-on-failure')[0], 1)
        code, out, _ = self._convert('--fail-on-failure', '--ignore-known-failures', '--baseline', self._p('r.json'))
        self.assertEqual(code, 0, out)
        self.assertIn('2 known failures ignored', out)
        code, out, _ = self._convert('--fail-on-failure', '--ignore-known-failures')
        self.assertEqual(code, 1)
        self.assertIn('needs a --baseline report', out)

    def test_ignore_known_failures_alone_is_a_no_op(self):
        code, out, _ = self._convert('--ignore-known-failures')
        self.assertEqual(code, 0)
        self.assertIn('--ignore-known-failures has no effect without --fail-on-failure', out)

    def test_invalid_values(self):
        for args in (('--fail-under', 'abc'), ('--fail-under', '120'), ('--report-url', 'ftp://x')):
            code, _, err = self._convert(*args)
            self.assertEqual(code, 2, args)
            self.assertIn('error', err)


class SummaryCommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.report = os.path.join(self.tmp, 'report.json')
        _run('convert', '--from', 'cucumber', CUCUMBER, '--html', os.path.join(self.tmp, 'r.html'),
             '--json', self.report)

    def test_prints_markdown_to_stdout(self):
        code, out, err = _run('summary', self.report)
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith('### ❌ Cucumber Test Report'))
        self.assertEqual(err, '')

    def test_writes_files_instead(self):
        summary = os.path.join(self.tmp, 'gh.md')
        os.environ['GITHUB_STEP_SUMMARY'] = summary
        try:
            code, out, _ = _run('summary', self.report, '--markdown', os.path.join(self.tmp, 's.md'),
                                '--github-summary')
        finally:
            del os.environ['GITHUB_STEP_SUMMARY']
        self.assertEqual((code, out), (0, ''))
        self.assertTrue(os.path.exists(os.path.join(self.tmp, 's.md')))
        self.assertTrue(os.path.exists(summary))

    def test_gates_report_on_stderr(self):
        code, out, err = _run('summary', self.report, '--fail-on-failure')
        self.assertEqual(code, 1)
        code, out, err = _run('summary', self.report, '--fail-under', '90')
        self.assertEqual(code, 1)
        self.assertIn('below --fail-under=90', err)
        self.assertNotIn('below', out)

    def test_report_url_from_environment(self):
        os.environ['PYREPT_REPORT_URL'] = 'https://pages.example/report.html'
        try:
            _, out, _ = _run('summary', self.report)
        finally:
            del os.environ['PYREPT_REPORT_URL']
        self.assertIn('[Open the full report](https://pages.example/report.html)', out)

    def test_notify_flag(self):
        from unittest import mock
        with mock.patch('pyrept.cli.send_notifications') as send:
            _run('summary', self.report)
            send.assert_not_called()
            _run('summary', self.report, '--notify', '--report-url', 'https://x.example/r')
            self.assertEqual(send.call_args[1]['report_url'], 'https://x.example/r')

    def test_bad_inputs(self):
        not_json = os.path.join(self.tmp, 'bad.json')
        with open(not_json, 'w') as fh:
            fh.write('{nope')
        other = os.path.join(self.tmp, 'other.json')
        with open(other, 'w') as fh:
            json.dump({'suites': []}, fh)
        for path, message in ((os.path.join(self.tmp, 'missing.json'), 'cannot read'),
                              (not_json, 'not valid JSON'), (other, 'not a pyrept JSON report')):
            code, _, err = _run('summary', path)
            self.assertEqual(code, 2, path)
            self.assertIn(message, err)

    def test_old_and_odd_reports(self):
        with open(self.report, encoding='utf-8') as fh:
            data = json.load(fh)
        del data['failure_groups']
        data['test_summary']['percentage'] = None
        data['test_summary'].pop('error')
        with open(self.report, 'w', encoding='utf-8') as fh:
            json.dump(data, fh)
        loaded = load_report(self.report)
        self.assertEqual(loaded['test_summary']['percentage'], 0)
        self.assertEqual(loaded['test_summary']['error'], 0)
        self.assertIsInstance(loaded['failure_groups'], list)
        self.assertEqual(_run('summary', self.report)[0], 0)
