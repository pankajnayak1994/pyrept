"""
Plain ``unittest`` support - no nose2 or pytest needed.

Command line (same arguments as ``python -m unittest``)::

    python -m pyrept.unittest_runner discover -s tests
    python -m pyrept.unittest_runner tests.test_module --pyrept-html=reports/report.html
    python -m pyrept.unittest_runner discover -s tests --pyrept-title "Nightly run"
    python -m pyrept.unittest_runner discover -s tests --pyrept-junit=junit.xml --pyrept-baseline=report.json
    python -m pyrept.unittest_runner discover -s tests --pyrept-github-summary --pyrept-fail-under 95

In code::

    import unittest
    from pyrept.unittest_runner import PyreptTestRunner

    suite = unittest.defaultTestLoader.discover('tests')
    PyreptTestRunner(html_path='reports/report.html').run(suite)
"""
import os
import sys
import time
import unittest

from .compare import summary_line
from .report import DEFAULT_HTML_REPORT_PATH, DEFAULT_JSON_REPORT_PATH, ReportCollector
from .summary import evaluate_gates, parse_fail_under

_GATE_OPTION_NAMES = {'fail_under': '--pyrept-fail-under', 'ignore_known_failures': '--pyrept-ignore-known-failures',
                      'baseline': '--pyrept-baseline'}


def _test_name(test):
    return test.id()


def _description(test):
    doc = getattr(test, '_testMethodDoc', None)
    return doc.strip() if doc else None


class PyreptTestResult(unittest.TextTestResult):
    """TextTestResult that also feeds every outcome into a ReportCollector."""

    def __init__(self, stream, descriptions, verbosity, collector=None, **kwargs):
        super().__init__(stream, descriptions, verbosity, **kwargs)
        self.collector = collector if collector is not None else ReportCollector()
        self._start_times = {}
        self.pyrept_gate = None  # set by PyreptTestRunner once the report is written

    def wasSuccessful(self):
        passed = super().wasSuccessful()
        return self.pyrept_gate.successful(passed) if self.pyrept_gate is not None else passed

    def startTest(self, test):
        self._start_times[test.id()] = time.perf_counter()
        super().startTest(test)

    def _format(self, err, test):
        # Same formatting unittest uses for its own failure output.
        return self._exc_info_to_string(err, test)

    def _duration(self, test, final=True):
        start = self._start_times.pop(test.id(), None) if final else self._start_times.get(test.id())
        return None if start is None else round(time.perf_counter() - start, 4)

    def _add(self, test, outcome, err=None, name=None, traceback=None, metadata=None, final=True):
        metadata = dict(metadata or {}, framework='unittest')
        duration = self._duration(test, final=final)
        if duration is not None:
            metadata['duration'] = duration
        if traceback is None and err is not None:
            traceback = self._format(err, test)
        self.collector.add(
            name=name or _test_name(test),
            outcome=outcome,
            description=_description(test),
            traceback=traceback,
            metadata=metadata,
        )

    def addSuccess(self, test):
        super().addSuccess(test)
        self._add(test, 'passed')

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._add(test, 'failed', err)

    def addError(self, test, err):
        super().addError(test, err)
        # setUpClass/setUpModule errors arrive as _ErrorHolder objects
        self._add(test, 'error', err)

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self._add(test, 'skipped', traceback='Skipped: %s' % reason)

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self._add(test, 'skipped', traceback='Expected failure:\n' + self._format(err, test),
                  metadata={'expected_failure': True})

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self._add(test, 'failed', traceback='Unexpected success: test was marked @expectedFailure but passed.')

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        # Only failing subtests are reported individually; a passing parent test is
        # reported through addSuccess, which unittest does not call when a subtest fails.
        if err is not None:
            outcome = 'failed' if issubclass(err[0], test.failureException) else 'error'
            self._add(test, outcome, err, name=subtest.id(), final=False)

    def stopTest(self, test):
        super().stopTest(test)
        # Parent of failing subtests gets no addSuccess/addFailure call.
        self._start_times.pop(test.id(), None)


class PyreptTestRunner(unittest.TextTestRunner):
    """TextTestRunner that writes pyrept HTML and JSON reports after the run."""

    resultclass = PyreptTestResult

    def __init__(self, *args, html_path=DEFAULT_HTML_REPORT_PATH, json_path=DEFAULT_JSON_REPORT_PATH,
                 title='Test Report', junit_path=None, baseline_path=None, markdown_path=None,
                 github_summary=False, fail_under=None, ignore_known_failures=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.html_path = os.path.realpath(html_path)
        self.json_path = os.path.realpath(json_path)
        self.junit_path = os.path.realpath(junit_path) if junit_path else None
        self.baseline_path = os.path.realpath(baseline_path) if baseline_path else None
        self.markdown_path = os.path.realpath(markdown_path) if markdown_path else None
        self.github_summary = github_summary
        self.fail_under = parse_fail_under(fail_under)
        self.ignore_known_failures = ignore_known_failures
        self.collector = ReportCollector(title=title, environment={'Framework': 'unittest'})

    def _makeResult(self):
        kwargs = {'collector': self.collector}
        if getattr(self, 'durations', None) is not None:  # Python >= 3.12: --durations
            kwargs['durations'] = self.durations
        return self.resultclass(self.stream, self.descriptions, self.verbosity, **kwargs)

    def run(self, test):
        result = super().run(test)
        context = self.collector.write(html_path=self.html_path, json_path=self.json_path,
                                       junit_path=self.junit_path, baseline_path=self.baseline_path,
                                       markdown_path=self.markdown_path, github_summary=self.github_summary)
        self.stream.writeln('pyrept HTML report: %s' % self.html_path)
        self.stream.writeln('pyrept JSON report: %s' % self.json_path)
        if self.junit_path:
            self.stream.writeln('pyrept JUnit report: %s' % self.junit_path)
        if self.markdown_path:
            self.stream.writeln('pyrept Markdown summary: %s' % self.markdown_path)
        if context['comparison']:
            self.stream.writeln('pyrept: %s' % summary_line(context['comparison']))
        if self.fail_under is not None or self.ignore_known_failures:
            result.pyrept_gate = evaluate_gates(context, fail_under=self.fail_under,
                                                ignore_known_failures=self.ignore_known_failures,
                                                option_names=_GATE_OPTION_NAMES)
            for message in result.pyrept_gate.messages:
                self.stream.writeln('pyrept: %s' % message)
        self.stream.flush()
        return result


def _pop_option(argv, flag, default):
    """Remove ``--flag=value`` / ``--flag value`` from argv and return value."""
    value = default
    rest = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg.startswith(flag + '='):
            value = arg.split('=', 1)[1]
        elif arg == flag and i + 1 < len(argv):
            value = argv[i + 1]
            i += 1
        else:
            rest.append(arg)
        i += 1
    return value, rest


def _pop_flag(argv, flag):
    """Remove every ``--flag`` from argv; return whether it was there."""
    rest = [arg for arg in argv if arg != flag]
    return len(rest) != len(argv), rest


def main(argv=None):
    argv = list(sys.argv if argv is None else argv) or ['']
    html_path, argv = _pop_option(argv, '--pyrept-html', DEFAULT_HTML_REPORT_PATH)
    json_path, argv = _pop_option(argv, '--pyrept-json', DEFAULT_JSON_REPORT_PATH)
    title, argv = _pop_option(argv, '--pyrept-title', 'Test Report')
    junit_path, argv = _pop_option(argv, '--pyrept-junit', None)
    baseline_path, argv = _pop_option(argv, '--pyrept-baseline', None)
    markdown_path, argv = _pop_option(argv, '--pyrept-markdown', None)
    fail_under, argv = _pop_option(argv, '--pyrept-fail-under', None)
    github_summary, argv = _pop_flag(argv, '--pyrept-github-summary')
    ignore_known_failures, argv = _pop_flag(argv, '--pyrept-ignore-known-failures')
    try:
        fail_under = parse_fail_under(fail_under)
    except ValueError as exc:
        print('pyrept: %s' % exc, file=sys.stderr)
        raise SystemExit(2)

    class _ConfiguredRunner(PyreptTestRunner):
        # unittest.main instantiates the runner class itself, passing
        # verbosity/failfast/buffer/...; bind the report paths here.
        def __init__(self, *args, **kwargs):
            kwargs.setdefault('html_path', html_path)
            kwargs.setdefault('json_path', json_path)
            kwargs.setdefault('title', title)
            kwargs.setdefault('junit_path', junit_path)
            kwargs.setdefault('baseline_path', baseline_path)
            kwargs.setdefault('markdown_path', markdown_path)
            kwargs.setdefault('github_summary', github_summary)
            kwargs.setdefault('fail_under', fail_under)
            kwargs.setdefault('ignore_known_failures', ignore_known_failures)
            super().__init__(*args, **kwargs)

    argv[0] = 'python -m pyrept.unittest_runner'
    # A fresh loader keeps main() reusable in one process: before Python 3.11,
    # discovery cached its top-level directory on the shared defaultTestLoader.
    return unittest.main(module=None, argv=argv, testRunner=_ConfiguredRunner, testLoader=unittest.TestLoader())


if __name__ == '__main__':  # pragma: no cover
    main()
