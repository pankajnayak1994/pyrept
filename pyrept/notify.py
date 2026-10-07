"""
Post a one-line result to Slack, Microsoft Teams or any webhook after a run.

Configured with environment variables, so it works the same for every
integration and keeps webhook URLs (which are secrets) out of command lines::

    PYREPT_SLACK_WEBHOOK_URL   Slack incoming webhook
    PYREPT_TEAMS_WEBHOOK_URL   Teams workflow ("When a Teams webhook request is received") or incoming webhook
    PYREPT_WEBHOOK_URL         any endpoint; receives the summary as JSON
    PYREPT_NOTIFY_ON           always (default) | failure | new-failures
    PYREPT_REPORT_URL          link to the published HTML report, added to every message

A notification that cannot be delivered is logged as a warning and never fails the run.
"""
import json
import logging
import os
import urllib.request

from .summary import PROBLEMS, report_url_from_env

logger = logging.getLogger(__name__)

TARGETS = (
    ('slack', 'PYREPT_SLACK_WEBHOOK_URL'),
    ('teams', 'PYREPT_TEAMS_WEBHOOK_URL'),
    ('webhook', 'PYREPT_WEBHOOK_URL'),
)
NOTIFY_ON_ENV = 'PYREPT_NOTIFY_ON'
NOTIFY_ON_CHOICES = ('always', 'failure', 'new-failures')
TIMEOUT = 10


def _counts(context):
    stats = context.get('test_summary') or {}
    return {key: stats.get(key) or 0 for key in ('total', 'passed', 'failed', 'error', 'skipped', 'percentage')}


def status(context):
    """``passed``, ``failed`` or ``empty`` (no tests ran)."""
    counts = _counts(context)
    if not counts['total']:
        return 'empty'
    return 'failed' if counts['failed'] or counts['error'] else 'passed'


def summary_text(context):
    """``❌ Checkout: 2 failed, 1 error of 13 tests (pass rate 75.0%, -8.33 pts) · 2 new failures, 1 fixed``"""
    counts = _counts(context)
    title = str(context.get('test_report_title') or 'Test Report')
    state = status(context)
    if state == 'empty':
        return '⚠️ %s: no tests were run' % title
    if state == 'passed':
        executed = counts['total'] - counts['skipped']
        text = '✅ %s: all %d test%s passed' % (title, executed, '' if executed == 1 else 's')
    else:
        parts = ['%d failed' % counts['failed']] if counts['failed'] else []
        if counts['error']:
            parts.append('%d error%s' % (counts['error'], '' if counts['error'] == 1 else 's'))
        text = '❌ %s: %s of %d test%s' % (title, ', '.join(parts), counts['total'], '' if counts['total'] == 1 else 's')
    comparison = context.get('comparison') or {}
    delta = comparison.get('percentage_delta')
    rate = 'pass rate %s%%' % counts['percentage']
    if isinstance(delta, (int, float)):
        rate += ', %+.2f pts' % delta
    text += ' (%s)' % rate
    if comparison:
        new_failures, fixed = len(comparison.get('new_failures') or []), len(comparison.get('fixed') or [])
        text += ' · %d new failure%s, %d fixed' % (new_failures, '' if new_failures == 1 else 's', fixed)
    return text


def _should_notify(context, mode):
    if mode == 'failure':
        return status(context) != 'passed'
    if mode == 'new-failures':
        return bool((context.get('comparison') or {}).get('new_failures'))
    return True


def slack_payload(context, report_url=None):
    text = summary_text(context)
    if report_url:
        text += ' · <%s|Open the report>' % report_url
    return {'text': text}


def teams_payload(context, report_url=None):
    counts = _counts(context)
    card = {
        '$schema': 'http://adaptivecards.io/schemas/adaptive-card.json',
        'type': 'AdaptiveCard',
        'version': '1.4',
        'body': [
            {'type': 'TextBlock', 'text': summary_text(context), 'wrap': True, 'weight': 'Bolder'},
            {'type': 'FactSet', 'facts': [
                {'title': 'Total', 'value': str(counts['total'])},
                {'title': 'Passed', 'value': str(counts['passed'])},
                {'title': 'Failed', 'value': str(counts['failed'])},
                {'title': 'Errors', 'value': str(counts['error'])},
                {'title': 'Skipped', 'value': str(counts['skipped'])},
                {'title': 'Pass rate', 'value': '%s%%' % counts['percentage']},
            ]},
        ],
    }
    if report_url:
        card['actions'] = [{'type': 'Action.OpenUrl', 'title': 'Open the report', 'url': report_url}]
    return {'type': 'message',
            'attachments': [{'contentType': 'application/vnd.microsoft.card.adaptive', 'content': card}]}


def webhook_payload(context, report_url=None):
    comparison = context.get('comparison') or {}
    return {
        'title': context.get('test_report_title'),
        'status': status(context),
        'text': summary_text(context),
        'summary': _counts(context),
        'duration': context.get('duration'),
        'timestamp': context.get('timestamp'),
        'report_url': report_url,
        'comparison': {key: comparison.get(key) for key in (
            'percentage_delta', 'new_failures', 'fixed', 'still_failing', 'new_tests', 'removed_tests')}
        if comparison else None,
        'failures': sorted(str(r.get('name')) for r in context.get('test_results') or []
                           if isinstance(r, dict) and r.get('result') in PROBLEMS),
    }


_PAYLOADS = {'slack': slack_payload, 'teams': teams_payload, 'webhook': webhook_payload}


def _post(url, payload, timeout):
    request = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), method='POST',
                                     headers={'Content-Type': 'application/json',
                                              'User-Agent': 'pyrept (+https://pypi.org/project/pyrept/)'})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - scheme checked by caller
        return response.status


def send_notifications(context, environ=None, timeout=TIMEOUT, report_url=None):
    """
    Send the configured notifications. Returns ``{target: delivered}`` for each configured target.

    Webhook URLs are secrets: they are never logged, only the target name is.
    """
    environ = os.environ if environ is None else environ
    configured = [(name, (environ.get(var) or '').strip(), var) for name, var in TARGETS]
    configured = [(name, url, var) for name, url, var in configured if url]
    if not configured:
        return {}
    mode = (environ.get(NOTIFY_ON_ENV) or 'always').strip().lower()
    if mode not in NOTIFY_ON_CHOICES:
        logger.warning('pyrept: unknown %s=%r (expected %s); notifying always',
                       NOTIFY_ON_ENV, mode, ', '.join(NOTIFY_ON_CHOICES))
        mode = 'always'
    if not _should_notify(context, mode):
        return {}
    report_url = report_url or report_url_from_env(environ)
    delivered = {}
    for name, url, var in configured:
        if not url.lower().startswith(('https://', 'http://')):
            logger.warning('pyrept: %s must be an http(s) URL; %s notification skipped', var, name)
            delivered[name] = False
            continue
        try:
            _post(url, _PAYLOADS[name](context, report_url=report_url), timeout)
            delivered[name] = True
        except Exception as exc:  # network down, HTTP 4xx/5xx, timeout: never fail the test run
            code = getattr(exc, 'code', None)
            logger.warning('pyrept: %s notification failed: %s%s', name, type(exc).__name__,
                           ' (HTTP %s)' % code if code else '')
            delivered[name] = False
    return delivered
