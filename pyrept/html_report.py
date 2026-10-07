"""
nose2 plugin that generates HTML and JSON test reports.
"""
import copy
import logging
import os
import sys
import time
import traceback
import unittest

try:
    from nose2.events import Plugin
    from nose2.result import ERROR, FAIL, PASS, SKIP, SUBTEST
except ImportError as exc:  # nose2 is an optional extra
    raise ImportError('The pyrept nose2 plugin needs nose2: pip install "pyrept[nose2]"') from exc

from .compare import load_baseline, summary_line
from .summary import evaluate_gates, parse_fail_under
from .report import (
    DEFAULT_HTML_REPORT_PATH,
    DEFAULT_JSON_REPORT_PATH,
    DEFAULT_TEMPLATE_PATH,
    build_context,
    generate_search_terms,
    new_summary_stats,
    record_outcome,
    write_reports,
)

logger = logging.getLogger(__name__)


_PATH_OPTIONS = {
    # option / config key: (required extension, internal key, help)
    'html-report-path': ('.html', 'html_report_path', 'pyrept: HTML report path (default report.html)'),
    'json-report-path': ('.json', 'json_report_path', 'pyrept: JSON report path (default report.json)'),
    'junit-report-path': ('.xml', 'junit_report_path', 'pyrept: also write a JUnit XML report'),
    'baseline-report-path': ('.json', 'baseline_report_path',
                             'pyrept: compare with an earlier pyrept JSON report'),
    'markdown-report-path': ('.md', 'markdown_report_path', 'pyrept: also write a Markdown summary'),
}
_GATE_OPTION_NAMES = {'fail_under': 'fail-under', 'ignore_known_failures': 'ignore-known-failures',
                      'baseline': 'baseline-report-path'}


def _checked(option, path):
    extension = _PATH_OPTIONS[option][0]
    if not path.endswith(extension):
        raise ValueError("Invalid %s: %r must end with %s (e.g. --%s=report%s)"
                         % (option, path, extension, option, extension))
    return path


def fetch_file_path(argv=None):
    """
    Read report paths passed on the command line.

    Supports ``--html-report-path=<file>.html`` and ``--json-report-path=<file>.json``.
    Returns a dict whose values are ``None`` when the flag was not given, so the
    caller can fall back to the config file and then to the defaults.
    """
    paths = {'html-report-path': None, 'json-report-path': None}
    args = sys.argv[1:] if argv is None else argv
    for arg in args:
        for option in paths:
            if arg.startswith('--%s=' % option):
                paths[option] = _checked(option, arg.split('=', 1)[1])
    return paths


class HTMLReporter(Plugin):
    configSection = 'html-report'
    commandLineSwitch = (None, 'html-report', 'Generate an HTML report containing test results')

    def __init__(self, *args, **kwargs):
        super(HTMLReporter, self).__init__(*args, **kwargs)
        self.summary_stats = new_summary_stats()
        self.test_results = []
        self._start_times = {}

        # Precedence: command line > nose2.cfg > defaults.
        # ``path`` is accepted as a legacy alias of ``html-report-path``.
        defaults = {
            'html-report-path': self.config.as_str('path', default='') or DEFAULT_HTML_REPORT_PATH,
            'json-report-path': DEFAULT_JSON_REPORT_PATH,
            'junit-report-path': '',
            'baseline-report-path': '',
            'markdown-report-path': '',
        }
        self._config = {'template': os.path.realpath(
            self.config.as_str('template', default='') or DEFAULT_TEMPLATE_PATH)}
        for option, (_, key, help_text) in _PATH_OPTIONS.items():
            path = self.config.as_str(option, default='') or defaults[option]
            self._config[key] = os.path.realpath(path) if path else None
            # Registering the option lets nose2's own argument parser accept it.
            self.addArgument(self._path_setter(option), None, option, help_text)
        self._config['github_summary'] = self.config.as_bool('github-summary', default=False)
        self._config['ignore_known_failures'] = self.config.as_bool('ignore-known-failures', default=False)
        self._config['fail_under'] = parse_fail_under(self.config.as_str('fail-under', default=''))
        self.addFlag(self._enable('github_summary'), None, 'pyrept-github-summary',
                     'pyrept: append the Markdown summary to the GitHub Actions job summary')
        self.addFlag(self._enable('ignore_known_failures'), None, 'pyrept-ignore-known-failures',
                     'pyrept: succeed when every failing test was already failing in the baseline')
        self.addArgument(self._set_fail_under, None, 'pyrept-fail-under',
                         'pyrept: fail the run when the pass rate is below this percentage')
        self._context = None
        self._gate = None

    def _enable(self, key):
        def enable(*_):
            self._config[key] = True
        return enable

    def _set_fail_under(self, values):
        self._config['fail_under'] = parse_fail_under(values[0])

    def _path_setter(self, option):
        key = _PATH_OPTIONS[option][1]

        def set_path(values):
            self._config[key] = os.path.realpath(_checked(option, values[0]))
        return set_path

    def _sort_test_results(self):
        return sorted(self.test_results, key=lambda x: x['name'])

    def _generate_search_terms(self):
        return generate_search_terms(self.test_results)

    def startTest(self, event):
        self._start_times[event.test.id()] = event.startTime

    def testOutcome(self, event):
        """
        Reports the outcome of each test
        """
        test = event.test
        test_case_import_path = test.id()

        # Ignore _ErrorHolder (for arbitrary errors like module import errors),
        # as there will be no doc string in these scenarios. Subtests carry
        # the docstring of the test method they belong to.
        test_case_doc = None
        if not isinstance(test, unittest.suite._ErrorHolder):
            doc_source = getattr(test, 'test_case', test)
            test_case_doc = getattr(doc_source, '_testMethodDoc', None)

        formatted_traceback = None
        if event.exc_info:
            formatted_traceback = ''.join(traceback.format_exception(*event.exc_info))

        metadata = copy.copy(event.metadata) or {}
        outcome = event.outcome
        if outcome == SUBTEST:
            if not event.exc_info:
                # Passing subtests are covered by the parent test's own outcome.
                return
            failure_exception = getattr(test, 'failureException', AssertionError)
            outcome = FAIL if issubclass(event.exc_info[0], failure_exception) else ERROR
        elif outcome == FAIL and event.expected:
            outcome = SKIP
            formatted_traceback = 'Expected failure:\n' + (formatted_traceback or '')
            metadata['expected_failure'] = True
        elif outcome == PASS and not event.expected:
            outcome = FAIL
            formatted_traceback = 'Unexpected success: test was marked @expectedFailure but passed.'
        elif outcome == SKIP and event.reason:
            formatted_traceback = 'Skipped: %s' % event.reason

        start = self._start_times.pop(test_case_import_path, None)
        if start is not None and 'duration' not in metadata:
            metadata['duration'] = round(max(time.time() - start, 0), 4)

        record_outcome(
            self.summary_stats,
            self.test_results,
            name=test_case_import_path,
            outcome=outcome,
            description=test_case_doc,
            traceback=formatted_traceback,
            metadata=metadata,
        )

    def _build_context(self):
        # Built once all tests have run: nose2 asks wasSuccessful() before afterSummaryReport.
        if self._context is None:
            import nose2
            self._context = build_context(self.summary_stats, self.test_results,
                                          environment={'Framework': 'nose2 %s' % getattr(nose2, '__version__', '')},
                                          baseline=load_baseline(self._config['baseline_report_path']))
            if self._config['fail_under'] is not None or self._config['ignore_known_failures']:
                self._gate = evaluate_gates(self._context, fail_under=self._config['fail_under'],
                                            ignore_known_failures=self._config['ignore_known_failures'],
                                            option_names=_GATE_OPTION_NAMES)
        return self._context

    def wasSuccessful(self, event):
        """Apply ``fail-under`` / ``ignore-known-failures`` to nose2's own verdict."""
        if self._config['fail_under'] is None and not self._config['ignore_known_failures']:
            return
        self._build_context()
        event.success = self._gate.successful(event.success is not False)

    def afterSummaryReport(self, event):
        """
        After everything is done, generate the report
        """
        logger.info('Generating HTML report...')
        context = self._build_context()
        self.summary_stats['percentage'] = context['test_summary']['percentage']
        write_reports(
            context,
            html_path=self._config['html_report_path'],
            json_path=self._config['json_report_path'],
            template_path=self._config['template'],
            junit_path=self._config['junit_report_path'],
            markdown_path=self._config['markdown_report_path'],
            github_summary=self._config['github_summary'],
        )
        lines = [summary_line(context['comparison'])] + (self._gate.messages if self._gate else [])
        stream = getattr(event, 'stream', None)
        for line in filter(None, lines):
            if stream is not None:
                stream.writeln('pyrept: %s' % line)
            else:
                logger.info('pyrept: %s', line)
