"""
Html Report generator source code
"""
import json
import logging
import copy
import os
import sys
import traceback
import unittest
from nose2.events import Plugin
from datetime import datetime

from .render import load_template, render_template

logger = logging.getLogger(__name__)


def fetch_file_path():
    final_out_json = {'html-report-path': 'report.html', 'json-report-path': 'report.json'}
    try:
        command_line_args = sys.argv[1:]
    except Exception as e:
        logger.error(f"Error reading command-line arguments: {e}")
        return final_out_json
    for arg in command_line_args:
        if arg.startswith("--html-report-path="):
            file_path = arg.split("=", 1)[1]
            if file_path.endswith('.html'):
                final_out_json['html-report-path'] = file_path
            else:
                raise ValueError("Invalid HTML file path. Use --html-report-path=report.html")
        elif arg.startswith("--json-report-path="):
            file_path = arg.split("=", 1)[1]
            if file_path.endswith('.json'):
                final_out_json['json-report-path'] = file_path
            else:
                raise ValueError("Invalid JSON file path. Use --json-report-path=report.json")
    return final_out_json


class HTMLReporter(Plugin):
    configSection = 'html-report'
    commandLineSwitch = (None, 'html-report', 'Generate an HTML report containing test results')

    def __init__(self, *args, **kwargs):
        super(HTMLReporter, self).__init__(*args, **kwargs)
        report_file_path_json = fetch_file_path()
        self.summary_stats = {
            'total': 0,
            'passed': 0,
            'failed': 0,
            'percentage': 0
        }
        self.test_results = []
        default_template_path = os.path.join(os.path.dirname(__file__), 'templates', 'report.html')
        if report_file_path_json['html-report-path']:
            default_html_report_path = os.path.realpath(report_file_path_json['html-report-path'])
        else:
            default_html_report_path = os.path.realpath(self.config.as_str('html-report-path', default='report.html'))
        if report_file_path_json['json-report-path']:
            default_json_report_path = os.path.realpath(report_file_path_json['json-report-path'])
        else:
            default_json_report_path = os.path.realpath(self.config.as_str('json-report-path', default='report.json'))

        self._config = {
            'html_report_path': default_html_report_path,
            'json_report_path': default_json_report_path,
            'template': os.path.realpath(self.config.as_str('template', default=default_template_path))
        }

    def _sort_test_results(self):
        return sorted(self.test_results, key=lambda x: x['name'])

    def _generate_search_terms(self):
        """
        Map search terms to what test case(s) they're related to

        Returns:
            dict: maps search terms to what test case(s) it's relevant to

        Example:
        {
            '12034': ['ui.tests.TestSomething.test_hello_world'],
            'buggy': ['ui.tests.TestSomething.test_hello_world', 'ui.tests.TestSomething.buggy_test_case'],
            'ui.tests.TestAnother.test_fail': ['ui.tests.TestAnother.test_fail']
        }
        """
        search_terms = {}

        for test_result in self.test_results:
            # search for the test name itself maps to the test case
            search_terms[test_result['name']] = test_result['name']

            if test_result['description']:
                for token in test_result['description'].split():
                    if token in search_terms:
                        search_terms[token].append(test_result['name'])
                    else:
                        search_terms[token] = [test_result['name']]

        return search_terms

    def testOutcome(self, event):
        """
        Reports the outcome of each test
        """
        test_case_import_path = event.test.id()

        # Ignore _ErrorHolder (for arbitrary errors like module import errors),
        # as there will be no doc string in these scenarios
        test_case_doc = None
        if not isinstance(event.test, unittest.suite._ErrorHolder):
            test_case_doc = event.test._testMethodDoc

        formatted_traceback = None
        if event.outcome in ['failed', 'error']:
            if event.exc_info:
                exception_type = event.exc_info[0]
                exception_message = event.exc_info[1]
                exception_traceback = event.exc_info[2]
                formatted_traceback = ''.join(traceback.format_exception(
                    exception_type, exception_message, exception_traceback))

        if event.outcome in self.summary_stats:
            self.summary_stats[event.outcome] += 1
        else:
            self.summary_stats[event.outcome] = 1
        self.summary_stats['total'] += 1

        self.test_results.append({
            'name': test_case_import_path,
            'description': test_case_doc,
            'result': event.outcome,
            'traceback': formatted_traceback,
            'metadata': copy.copy(event.metadata)
        })

    def afterSummaryReport(self, event):
        """
        After everything is done, generate the report
        """
        logger.info('Generating HTML report...')

        sorted_test_results = self._sort_test_results()
        percentage = 0
        if bool(self.summary_stats) and self.summary_stats['passed'] > 0:
            percentage = (self.summary_stats['passed'] / self.summary_stats['total']) * 100
            percentage = round(percentage, 2)
        self.summary_stats['percentage'] = percentage

        context = {
            'test_report_title': 'Test Report',
            'test_summary': self.summary_stats,
            'test_results': sorted_test_results,
            'autocomplete_terms': json.dumps(self._generate_search_terms()),
            'timestamp': datetime.utcnow().strftime('%Y/%m/%d %H:%M:%S UTC')
        }
        template = load_template(self._config['template'])
        rendered_template = render_template(template, context)
        with open(self._config['html_report_path'], 'w') as template_file:
            template_file.write(rendered_template)
        with open(self._config['json_report_path'], 'w') as template_file:
            template_file.write(json.dumps(context, indent=2))
            logger.info("json report generated at : {}".format(self._config['json_report_path']))
