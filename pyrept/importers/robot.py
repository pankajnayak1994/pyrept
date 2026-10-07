"""
Import a Robot Framework ``output.xml`` (Robot Framework 3.x to 7.x).

Each test becomes one entry named ``Suite.Sub suite.Test name``, like Robot's
own long names; tags and documentation are kept.
"""
import xml.etree.ElementTree as ET
from datetime import datetime

from ..report import ReportCollector
from .junit import _children, _local, _text

_OUTCOMES = {'PASS': 'passed', 'FAIL': 'failed', 'SKIP': 'skipped', 'NOT RUN': 'skipped', 'NOT_RUN': 'skipped'}


def _timestamp(value):
    for fmt in ('%Y%m%d %H:%M:%S.%f', '%Y-%m-%dT%H:%M:%S.%f', '%Y-%m-%dT%H:%M:%S'):
        try:
            return datetime.strptime(value, fmt)
        except (TypeError, ValueError):
            continue
    return None


def _duration(status):
    """Robot 7 writes ``elapsed`` (seconds); older versions write start and end times."""
    try:
        return round(max(float(status.get('elapsed')), 0.0), 4)
    except (TypeError, ValueError):
        pass
    start, end = _timestamp(status.get('starttime')), _timestamp(status.get('endtime'))
    if start and end and end >= start:
        return round((end - start).total_seconds(), 4)
    return 0.0


def _tests(suite, names):
    names = names + [suite.get('name') or 'Suite']
    for child in suite:
        tag = _local(child.tag)
        if tag == 'test':
            yield names, suite, child
        elif tag == 'suite':
            for item in _tests(child, names):
                yield item


def load_robot_xml(path, collector=None, title='Robot Framework Test Report'):
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise ValueError('%s is not valid XML: %s' % (path, exc))
    if _local(root.tag) != 'robot':
        raise ValueError('%s is not a Robot Framework output.xml (root element is <%s>)' % (path, _local(root.tag)))
    collector = collector or ReportCollector(title=title)
    for top in _children(root, 'suite'):
        for names, suite, test in _tests(top, []):
            statuses = _children(test, 'status')
            status = statuses[-1] if statuses else None
            raw = (status.get('status') if status is not None else '') or ''
            outcome = _OUTCOMES.get(raw.upper(), 'error')
            message = _text(status)
            if outcome == 'skipped':
                traceback = 'Skipped: %s' % message if message else None
            elif outcome == 'passed':
                traceback = None
            else:
                traceback = message or 'Status: %s' % (raw or 'missing')
            tags = [_text(t) for t in _children(test, 'tag') if _text(t)]
            for group in _children(test, 'tags'):  # Robot Framework 3.x
                tags += [_text(t) for t in _children(group, 'tag') if _text(t)]
            source = suite.get('source') or ''
            line = test.get('line')
            collector.add(
                name='.'.join(names + [test.get('name') or 'Test']),
                outcome=outcome,
                description=_text(_children(test, 'doc')[0]) if _children(test, 'doc') else None,
                traceback=traceback,
                metadata={'framework': 'robot', 'duration': _duration(status) if status is not None else 0.0,
                          'location': '%s:%s' % (source, line) if source and line else (source or None),
                          'tags': tags},
            )
    return collector
