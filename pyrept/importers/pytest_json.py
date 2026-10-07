"""
Import a pytest-json-report file (``pytest --json-report``), for teams that
already produce one and want the pyrept HTML report without re-running tests.
"""
import json
import re

from ..report import ReportCollector, make_attachment

_STAGES = ('setup', 'call', 'teardown')
# pytest stores skip reasons as the repr of (file, line, reason)
_SKIP_TUPLE = re.compile(r'''^\(.*?, \d+, (['"])(.*)\1\)$''', re.DOTALL)


def _longrepr(stage):
    if not isinstance(stage, dict):
        return None
    return stage.get('longrepr') or (stage.get('crash') or {}).get('message') or None


def load_pytest_json(path, collector=None, title='pytest Test Report'):
    with open(path, encoding='utf-8-sig') as fh:
        report = json.load(fh)
    if not isinstance(report, dict) or not isinstance(report.get('tests'), list):
        raise ValueError('%s is not a pytest-json-report file (expected an object with "tests")' % path)
    collector = collector or ReportCollector(title=title)

    for collector_report in report.get('collectors') or []:
        if isinstance(collector_report, dict) and collector_report.get('outcome') == 'failed':
            collector.add(name=collector_report.get('nodeid') or '<collection>', outcome='error',
                          traceback=collector_report.get('longrepr') or 'Collection failed',
                          metadata={'framework': 'pytest', 'phase': 'collect'})

    for test in report['tests']:
        if not isinstance(test, dict) or not test.get('nodeid'):
            continue
        raw = str(test.get('outcome') or '').lower()
        stages = {name: test.get(name) for name in _STAGES if isinstance(test.get(name), dict)}
        if raw in ('passed', 'xpassed'):
            outcome, traceback = 'passed', None
        elif raw == 'failed':
            outcome, traceback = 'failed', _longrepr(stages.get('call'))
        elif raw == 'error':
            failing = next((stages[s] for s in _STAGES if s in stages and stages[s].get('outcome') == 'failed'), None)
            outcome, traceback = 'error', _longrepr(failing)
        elif raw == 'xfailed':
            outcome, traceback = 'skipped', 'Expected failure'
        else:  # skipped
            reason = _longrepr(stages.get('setup')) or _longrepr(stages.get('call'))
            match = _SKIP_TUPLE.match(reason) if isinstance(reason, str) else None
            if match:
                reason = match.group(2)
            outcome = 'skipped'
            traceback = reason if not reason or reason.startswith('Skipped') else 'Skipped: %s' % reason
        attachments = []
        if outcome in ('failed', 'error'):
            for stage_name, stage in stages.items():
                for stream in ('stdout', 'stderr', 'log'):
                    content = stage.get(stream)
                    if isinstance(content, list):  # "log" is a list of log records
                        content = '\n'.join(str(r.get('msg', r)) if isinstance(r, dict) else str(r) for r in content)
                    if content and str(content).strip():
                        attachments.append(make_attachment('Captured %s %s' % (stream, stage_name), 'text/plain',
                                                           text=str(content)))
        duration = sum(s.get('duration') or 0 for s in stages.values() if isinstance(s.get('duration'), (int, float)))
        nodeid = test['nodeid']
        lineno = test.get('lineno')
        collector.add(name=nodeid, outcome=outcome, traceback=traceback or None, attachments=attachments or None,
                      metadata={'framework': 'pytest', 'duration': round(duration, 4),
                                'location': '%s:%s' % (nodeid.split('::')[0], lineno + 1)
                                if isinstance(lineno, int) else nodeid.split('::')[0]})
    return collector
