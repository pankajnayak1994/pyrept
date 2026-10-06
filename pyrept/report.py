"""
Framework-agnostic report building shared by the nose2 and pytest plugins.
"""
import json
import logging
import os
from datetime import datetime, timezone

from .render import load_template, render_template

logger = logging.getLogger(__name__)

DEFAULT_TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), 'templates', 'report.html')
DEFAULT_HTML_REPORT_PATH = 'report.html'
DEFAULT_JSON_REPORT_PATH = 'report.json'


def new_summary_stats():
    return {'total': 0, 'passed': 0, 'failed': 0, 'percentage': 0}


def record_outcome(summary_stats, test_results, name, outcome, description=None,
                   traceback=None, metadata=None):
    """Append one test result and update the running summary counters."""
    summary_stats[outcome] = summary_stats.get(outcome, 0) + 1
    summary_stats['total'] += 1
    test_results.append({
        'name': name,
        'description': description,
        'result': outcome,
        'traceback': traceback,
        'metadata': metadata or {},
    })


def generate_search_terms(test_results):
    """
    Map search terms to the test case(s) they relate to.

    Example:
    {
        'ui.tests.TestSomething.test_hello_world': ['ui.tests.TestSomething.test_hello_world'],
        'buggy': ['ui.tests.TestSomething.test_hello_world', 'ui.tests.TestSomething.buggy_test_case'],
    }
    """
    search_terms = {}
    for test_result in test_results:
        tokens = [test_result['name']]
        if test_result['description']:
            tokens.extend(test_result['description'].split())
        for token in tokens:
            names = search_terms.setdefault(token, [])
            if test_result['name'] not in names:
                names.append(test_result['name'])
    return search_terms


def build_context(summary_stats, test_results, title='Test Report'):
    """Build the template/JSON context from collected results."""
    stats = dict(summary_stats)
    percentage = 0
    if stats.get('total') and stats.get('passed', 0) > 0:
        percentage = round((stats['passed'] / stats['total']) * 100, 2)
    stats['percentage'] = percentage
    return {
        'test_report_title': title,
        'test_summary': stats,
        'test_results': sorted(test_results, key=lambda x: x['name']),
        'autocomplete_terms': json.dumps(generate_search_terms(test_results)),
        'timestamp': datetime.now(timezone.utc).strftime('%Y/%m/%d %H:%M:%S UTC'),
    }


def _ensure_parent_dir(path):
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def write_reports(context, html_path, json_path, template_path=DEFAULT_TEMPLATE_PATH):
    """Render the HTML report and dump the JSON report."""
    template = load_template(template_path)
    rendered = render_template(template, context)
    _ensure_parent_dir(html_path)
    with open(html_path, 'w', encoding='utf-8') as fh:
        fh.write(rendered)
    logger.info("html report generated at : %s", html_path)
    _ensure_parent_dir(json_path)
    with open(json_path, 'w', encoding='utf-8') as fh:
        fh.write(json.dumps(context, indent=2, default=str))
    logger.info("json report generated at : %s", json_path)
