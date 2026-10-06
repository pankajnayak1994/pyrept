"""
nose2 plugin that generates HTML and JSON test reports.
"""
import copy
import logging
import os
import sys
import traceback
import unittest

from nose2.events import Plugin

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
        if arg.startswith("--html-report-path="):
            file_path = arg.split("=", 1)[1]
            if not file_path.endswith('.html'):
                raise ValueError("Invalid HTML file path. Use --html-report-path=report.html")
            paths['html-report-path'] = file_path
        elif arg.startswith("--json-report-path="):
            file_path = arg.split("=", 1)[1]
            if not file_path.endswith('.json'):
                raise ValueError("Invalid JSON file path. Use --json-report-path=report.json")
            paths['json-report-path'] = file_path
    return paths


class HTMLReporter(Plugin):
    configSection = 'html-report'
    commandLineSwitch = (None, 'html-report', 'Generate an HTML report containing test results')

    def __init__(self, *args, **kwargs):
        super(HTMLReporter, self).__init__(*args, **kwargs)
        cli_paths = fetch_file_path()
        self.summary_stats = new_summary_stats()
        self.test_results = []

        # Precedence: command line > nose2.cfg > defaults.
        # ``path`` is accepted as a legacy alias of ``html-report-path``.
        html_path = (
            cli_paths['html-report-path']
            or self.config.as_str('html-report-path', default='')
            or self.config.as_str('path', default='')
            or DEFAULT_HTML_REPORT_PATH
        )
        json_path = (
            cli_paths['json-report-path']
            or self.config.as_str('json-report-path', default='')
            or DEFAULT_JSON_REPORT_PATH
        )
        template_path = self.config.as_str('template', default='') or DEFAULT_TEMPLATE_PATH

        self._config = {
            'html_report_path': os.path.realpath(html_path),
            'json_report_path': os.path.realpath(json_path),
            'template': os.path.realpath(template_path),
        }

    def _sort_test_results(self):
        return sorted(self.test_results, key=lambda x: x['name'])

    def _generate_search_terms(self):
        return generate_search_terms(self.test_results)

    def testOutcome(self, event):
        """
        Reports the outcome of each test
        """
        test_case_import_path = event.test.id()

        # Ignore _ErrorHolder (for arbitrary errors like module import errors),
        # as there will be no doc string in these scenarios
        test_case_doc = None
        if not isinstance(event.test, unittest.suite._ErrorHolder):
            test_case_doc = getattr(event.test, '_testMethodDoc', None)

        formatted_traceback = None
        if event.outcome in ['failed', 'error'] and event.exc_info:
            formatted_traceback = ''.join(traceback.format_exception(*event.exc_info))

        record_outcome(
            self.summary_stats,
            self.test_results,
            name=test_case_import_path,
            outcome=event.outcome,
            description=test_case_doc,
            traceback=formatted_traceback,
            metadata=copy.copy(event.metadata),
        )

    def afterSummaryReport(self, event):
        """
        After everything is done, generate the report
        """
        logger.info('Generating HTML report...')
        context = build_context(self.summary_stats, self.test_results)
        self.summary_stats['percentage'] = context['test_summary']['percentage']
        write_reports(
            context,
            html_path=self._config['html_report_path'],
            json_path=self._config['json_report_path'],
            template_path=self._config['template'],
        )
