"""
Framework-agnostic report building shared by the nose2 and pytest plugins.
"""
import base64
import json
import logging
import mimetypes
import os
import platform
from datetime import datetime, timezone

from .render import load_template, render_template

logger = logging.getLogger(__name__)

DEFAULT_TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), 'templates', 'report.html')
DEFAULT_HTML_REPORT_PATH = 'report.html'
DEFAULT_JSON_REPORT_PATH = 'report.json'


def new_summary_stats():
    return {'total': 0, 'passed': 0, 'failed': 0, 'error': 0, 'skipped': 0, 'percentage': 0}


def default_environment():
    return {
        'Python': platform.python_version(),
        'Platform': platform.platform(),
    }


VALID_OUTCOMES = ('passed', 'failed', 'error', 'skipped')


def make_attachment(name, content_type=None, data=None, path=None, text=None, embed=True):
    """
    Build an attachment entry for a test result.

    ``data`` is base64 text or raw bytes. When only ``path`` is given and the file
    is a small image, it is embedded so the HTML report stays self-contained.
    """
    content_type = content_type or (mimetypes.guess_type(path)[0] if path else None) or 'application/octet-stream'
    if isinstance(data, bytes):
        data = base64.b64encode(data).decode('ascii')
    if data is None and path and embed and content_type.startswith('image/') and os.path.isfile(path):
        try:
            if os.path.getsize(path) <= 5 * 1024 * 1024:
                with open(path, 'rb') as fh:
                    data = base64.b64encode(fh.read()).decode('ascii')
        except OSError:
            logger.warning("Could not read attachment %s", path)
    entry = {'name': name, 'content_type': content_type}
    if data is not None:
        entry['data'] = data
    if path is not None:
        entry['path'] = path
    if text is not None:
        entry['text'] = text
    return entry


def record_outcome(summary_stats, test_results, name, outcome, description=None,
                   traceback=None, metadata=None, attachments=None):
    """Append one test result and update the running summary counters."""
    summary_stats[outcome] = summary_stats.get(outcome, 0) + 1
    summary_stats['total'] += 1
    metadata = dict(metadata or {})
    if attachments:
        metadata.setdefault('attachments', []).extend(attachments)
    test_results.append({
        'name': name,
        'description': description,
        'result': outcome,
        'traceback': traceback,
        'metadata': metadata,
    })


class ReportCollector:
    """Collects results from any test framework and writes the HTML/JSON reports."""

    def __init__(self, title='Test Report', environment=None):
        self.title = title
        self.environment = dict(environment or {})
        self.summary_stats = new_summary_stats()
        self.test_results = []

    def add(self, name, outcome, description=None, traceback=None, metadata=None, attachments=None):
        if outcome not in VALID_OUTCOMES:
            raise ValueError('Unknown outcome %r; expected one of %s' % (outcome, ', '.join(VALID_OUTCOMES)))
        record_outcome(self.summary_stats, self.test_results, name, outcome, description=description,
                       traceback=traceback, metadata=metadata, attachments=attachments)

    def context(self):
        return build_context(self.summary_stats, self.test_results, title=self.title,
                             environment=self.environment)

    def write(self, html_path=DEFAULT_HTML_REPORT_PATH, json_path=DEFAULT_JSON_REPORT_PATH,
              template_path=DEFAULT_TEMPLATE_PATH):
        context = self.context()
        write_reports(context, html_path=html_path, json_path=json_path, template_path=template_path)
        return context


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


def build_context(summary_stats, test_results, title='Test Report', environment=None, duration=None):
    """Build the template/JSON context from collected results."""
    stats = dict(summary_stats)
    for key in ('passed', 'failed', 'error', 'skipped'):
        stats.setdefault(key, 0)
    executed = stats.get('total', 0) - stats['skipped']
    stats['percentage'] = round((stats['passed'] / executed) * 100, 2) if executed > 0 else 0
    durations = [r['metadata'].get('duration') for r in test_results
                 if isinstance(r.get('metadata'), dict) and isinstance(r['metadata'].get('duration'), (int, float))]
    if duration is None and durations:
        duration = sum(durations)
    slowest = sorted((r for r in test_results if isinstance((r.get('metadata') or {}).get('duration'), (int, float))),
                     key=lambda r: r['metadata']['duration'], reverse=True)[:5]
    env = default_environment()
    env.update(environment or {})
    return {
        'test_report_title': title,
        'test_summary': stats,
        'test_results': sorted(test_results, key=_sort_key),
        'autocomplete_terms': json.dumps(generate_search_terms(test_results)),
        'timestamp': datetime.now(timezone.utc).strftime('%Y/%m/%d %H:%M:%S UTC'),
        'duration': round(duration, 3) if duration is not None else None,
        'environment': env,
        'slowest_tests': [{'name': r['name'], 'duration': r['metadata']['duration']} for r in slowest],
    }


_RESULT_ORDER = {'error': 0, 'failed': 1, 'skipped': 2, 'passed': 3}


def _sort_key(result):
    # Problems first, then alphabetical - the things you need to look at are on top.
    return (_RESULT_ORDER.get(result['result'], 4), result['name'])


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
