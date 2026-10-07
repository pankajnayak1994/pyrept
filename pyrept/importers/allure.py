"""
Import Allure results: the ``allure-results`` directory written by
allure-pytest, allure-java (JUnit 5, TestNG, Cucumber), allure-js
(Jest, Mocha, Playwright, Cypress), allure-csharp and others.

Pass the directory (or single ``*-result.json`` files). Retries of the same
test (same ``historyId``) are folded into one entry with ``retries``.
"""
import glob
import json
import os

from ..report import ReportCollector, make_attachment

_OUTCOMES = {'passed': 'passed', 'failed': 'failed', 'broken': 'error', 'skipped': 'skipped', 'unknown': 'error'}
_TAG_LABELS = ('tag', 'severity', 'epic', 'feature', 'story')


def _files(path):
    if os.path.isdir(path):
        return sorted(glob.glob(os.path.join(path, '*-result.json')))
    return [path]


def _label(result, name):
    for label in result.get('labels') or []:
        if isinstance(label, dict) and label.get('name') == name and label.get('value'):
            return str(label['value'])
    return None


def _name(result):
    name = str(result.get('fullName') or result.get('name') or 'test')
    params = [p for p in result.get('parameters') or [] if isinstance(p, dict) and p.get('mode') != 'hidden']
    if params:
        rendered = ', '.join('%s=%s' % (p.get('name'), p.get('value')) for p in params)
        if rendered not in name:
            name = '%s (%s)' % (name, rendered)
    return name


def _attachments(result, base_dir):
    found = []
    stack = [result]
    while stack:  # attachments of the test and of all its (nested) steps
        node = stack.pop(0)
        for att in node.get('attachments') or []:
            if isinstance(att, dict) and att.get('source'):
                found.append(make_attachment(att.get('name') or att['source'], content_type=att.get('type'),
                                             path=os.path.join(base_dir, att['source'])))
        stack.extend(s for s in node.get('steps') or [] if isinstance(s, dict))
    return found


def load_allure_results(path, collector=None, title='Allure Test Report'):
    files = _files(path)
    if not files:
        raise ValueError('%s contains no Allure *-result.json files' % path)
    latest = {}
    for file_path in files:
        with open(file_path, encoding='utf-8-sig') as fh:
            result = json.load(fh)
        if not isinstance(result, dict) or 'status' not in result or not (result.get('name') or result.get('fullName')):
            raise ValueError('%s is not an Allure result (expected "name" and "status")' % file_path)
        result['_base_dir'] = os.path.dirname(os.path.abspath(file_path))
        key = result.get('historyId') or result.get('uuid') or file_path
        attempts = latest.setdefault(key, [])
        attempts.append(result)

    collector = collector or ReportCollector(title=title)
    for attempts in latest.values():
        attempts.sort(key=lambda r: r.get('stop') or r.get('start') or 0)
        result = attempts[-1]
        outcome = _OUTCOMES.get(str(result.get('status')).lower(), 'error')
        details = result.get('statusDetails') if isinstance(result.get('statusDetails'), dict) else {}
        message, trace = details.get('message') or '', details.get('trace') or ''
        traceback = '\n\n'.join(p for p in (message, trace) if p) or None
        if outcome == 'skipped' and traceback and not traceback.startswith('Skipped'):
            traceback = 'Skipped: %s' % traceback
        start, stop = result.get('start'), result.get('stop')
        duration = round((stop - start) / 1000.0, 4) if isinstance(start, (int, float)) \
            and isinstance(stop, (int, float)) and stop >= start else 0.0
        tags = [str(label['value']) for label in result.get('labels') or []
                if isinstance(label, dict) and label.get('name') in _TAG_LABELS and label.get('value')]
        metadata = {'framework': _label(result, 'framework') or 'allure', 'duration': duration,
                    'location': _label(result, 'testClass') or _label(result, 'suite'), 'tags': tags}
        if len(attempts) > 1:
            metadata['retries'] = len(attempts) - 1
            metadata['flaky'] = outcome == 'passed'
        elif details.get('flaky'):
            metadata['flaky'] = True
        collector.add(name=_name(result), outcome=outcome, traceback=traceback,
                      description=result.get('description') or None,
                      attachments=_attachments(result, result['_base_dir']) or None, metadata=metadata)
    return collector
