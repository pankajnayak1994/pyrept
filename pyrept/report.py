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

from .branding import branding_from_env
from .compare import compare, load_baseline
from .junit import write_junit
from .notify import send_notifications
from .render import load_template, render_template
from .summary import failure_groups, report_url_from_env, write_github_summary, write_markdown

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
    summary_stats['total'] = summary_stats.get('total', 0) + 1
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
        if description is not None and not isinstance(description, str):
            description = str(description)
        record_outcome(self.summary_stats, self.test_results, str(name), outcome, description=description,
                       traceback=traceback, metadata=metadata, attachments=attachments)

    def context(self, baseline=None):
        return build_context(self.summary_stats, self.test_results, title=self.title,
                             environment=self.environment, baseline=baseline)

    def write(self, html_path=DEFAULT_HTML_REPORT_PATH, json_path=DEFAULT_JSON_REPORT_PATH,
              template_path=DEFAULT_TEMPLATE_PATH, junit_path=None, baseline_path=None,
              markdown_path=None, github_summary=False, report_url=None):
        """
        Write the reports and return the context.

        ``junit_path`` also writes a JUnit XML report. ``baseline_path`` compares the
        run with an earlier pyrept JSON report; it is read before anything is
        written, so it may be the same file as ``json_path``. ``markdown_path``
        writes a Markdown summary, and ``github_summary`` appends it to the GitHub
        Actions job summary. ``report_url`` (default: ``$PYREPT_REPORT_URL``) links
        the published HTML report from the summary and notifications.
        """
        context = self.context(baseline=load_baseline(baseline_path))
        write_reports(context, html_path=html_path, json_path=json_path, template_path=template_path,
                      junit_path=junit_path, markdown_path=markdown_path, github_summary=github_summary,
                      report_url=report_url)
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
        if test_result.get('description'):
            tokens.extend(str(test_result['description']).split())
        for token in tokens:
            names = search_terms.setdefault(token, [])
            if test_result['name'] not in names:
                names.append(test_result['name'])
    return search_terms


def build_context(summary_stats, test_results, title='Test Report', environment=None, duration=None,
                  baseline=None):
    """
    Build the template/JSON context from collected results.

    ``baseline`` is an earlier report (see :func:`pyrept.compare.load_baseline`);
    when given, the context gets a ``comparison`` section.
    """
    stats = dict(summary_stats)
    for key in ('passed', 'failed', 'error', 'skipped'):
        stats.setdefault(key, 0)
    executed = stats.get('total', 0) - stats['skipped']
    stats['percentage'] = round((stats['passed'] / executed) * 100, 2) if executed > 0 else 0
    timed = [r for r in test_results if _duration_of(r) is not None]
    if duration is None and timed:
        duration = sum(_duration_of(r) for r in timed)
    slowest = sorted((r for r in timed if _duration_of(r) > 0), key=_duration_of, reverse=True)[:5]
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
        'comparison': compare(test_results, baseline, current_percentage=stats['percentage']),
        'failure_groups': failure_groups(test_results),
    }


def _duration_of(result):
    value = (result.get('metadata') or {}).get('duration')
    # bool is an int subclass but never a duration
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    return None


_RESULT_ORDER = {'error': 0, 'failed': 1, 'skipped': 2, 'passed': 3}


def _sort_key(result):
    # Problems first, then alphabetical - the things you need to look at are on top.
    return (_RESULT_ORDER.get(result['result'], 4), str(result['name']))


def _ensure_parent_dir(path):
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def write_reports(context, html_path, json_path, template_path=DEFAULT_TEMPLATE_PATH, junit_path=None,
                  markdown_path=None, github_summary=False, notify=True, report_url=None):
    """
    Render the HTML report and dump the JSON report. Optionally write JUnit XML
    and a Markdown summary, append the summary to the GitHub Actions job
    summary, and send the notifications configured in the environment
    (see :mod:`pyrept.notify`).
    """
    template = load_template(template_path)
    rendered = render_template(template, dict(context, branding=branding_from_env()))
    _ensure_parent_dir(html_path)
    with open(html_path, 'w', encoding='utf-8') as fh:
        fh.write(rendered)
    logger.info("html report generated at : %s", html_path)
    _ensure_parent_dir(json_path)
    with open(json_path, 'w', encoding='utf-8') as fh:
        fh.write(json.dumps(context, indent=2, default=str))
    logger.info("json report generated at : %s", json_path)
    if junit_path:
        _ensure_parent_dir(junit_path)
        write_junit(context, junit_path)
        logger.info("junit report generated at : %s", junit_path)
    report_url = report_url or report_url_from_env()
    if markdown_path:
        write_markdown(context, markdown_path, report_url=report_url)
    if github_summary:
        write_github_summary(context, report_url=report_url)
    if notify:
        send_notifications(context, report_url=report_url)
