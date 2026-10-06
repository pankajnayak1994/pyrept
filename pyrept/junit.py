"""
Write a JUnit XML report, the format CI servers (GitLab, Jenkins, Azure
DevOps, CircleCI, GitHub test-report actions, ...) show in their test tabs.
"""
import re
import xml.etree.ElementTree as ET
from datetime import datetime

# Characters XML 1.0 does not allow (ANSI escape codes in tracebacks, NUL bytes, ...).
_INVALID_XML = re.compile('[^\u0009\u000a\u000d -퟿-�\U00010000-\U0010ffff]')
_DOTTED_ID = re.compile(r'^[A-Za-z_][\w]*(\.[A-Za-z_][\w]*)+$')
_MESSAGE_LIMIT = 300


def _clean(text):
    return _INVALID_XML.sub('', str(text)) if text is not None else ''


def split_name(name):
    """
    Split a pyrept test name into JUnit ``(classname, name)``.

    ``tests/test_a.py::TestX::test_y[p]``  -> ``('tests.test_a.TestX', 'test_y[p]')``  (pytest)
    ``pkg.test_mod.TestX.test_y (i=1)``    -> ``('pkg.test_mod.TestX', 'test_y (i=1)')``  (unittest)
    ``Login :: Wrong password``            -> ``('Login', 'Wrong password')``  (BDD)
    """
    name = str(name)
    if ' :: ' in name:
        classname, _, short = name.rpartition(' :: ')
        return classname, short
    head, bracket, params = name.partition('[')  # never split inside parametrize ids
    if head.endswith('.py') and not bracket:  # pytest collection error: just a file path
        return '', _module(head)
    if '::' in head:
        parts = head.split('::')
        return '.'.join([_module(parts[0])] + parts[1:-1]), parts[-1] + bracket + params
    base, space, rest = name.partition(' ')
    if _DOTTED_ID.match(base):
        classname, _, short = base.rpartition('.')
        return classname, short + space + rest
    return '', name


_EXCEPTION_LINE = re.compile(r'^[A-Za-z_][\w.]*(Error|Exception|Failure|Exit|Interrupt|Warning)\b')


def _module(path):
    if path.endswith('.py'):
        path = path[:-3]
    return path.replace('\\', '/').strip('/').replace('/', '.')


def _property_value(value):
    return str(value).lower() if isinstance(value, bool) else _clean(value)


def _message(traceback):
    """The most useful single line of a traceback, for the ``message`` attribute."""
    lines = [line.strip() for line in (traceback or '').splitlines() if line.strip()]
    if not lines:
        return ''
    pytest_lines = [line[1:].strip() for line in lines if line.startswith('E ')]  # pytest's "E   assert ..."
    exception_lines = [line for line in lines if _EXCEPTION_LINE.match(line)]  # "ValueError: bad value"
    if pytest_lines:
        message = pytest_lines[0]
    elif exception_lines:
        message = exception_lines[-1]
    else:
        message = lines[0]
    return message[:_MESSAGE_LIMIT]


def _seconds(result):
    value = (result.get('metadata') or {}).get('duration')
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
        return value
    return 0.0


def _testcase(result):
    classname, short = split_name(result.get('name'))
    metadata = result.get('metadata') or {}
    case = ET.Element('testcase', {'classname': _clean(classname), 'name': _clean(short),
                                   'time': '%.3f' % _seconds(result)})
    location = str(metadata.get('location') or '')
    file_part, _, line_part = location.rpartition(':')
    if file_part and line_part.isdigit():
        case.set('file', _clean(file_part))
        case.set('line', line_part)

    properties = [(key, metadata[key]) for key in ('retries', 'flaky', 'project') if metadata.get(key)]
    properties += [('tag', tag) for tag in metadata.get('tags') or []]
    if properties:
        props = ET.SubElement(case, 'properties')
        for key, value in properties:
            ET.SubElement(props, 'property', {'name': key, 'value': _property_value(value)})

    outcome = result.get('result')
    traceback = result.get('traceback')
    if outcome in ('failed', 'error'):
        child = ET.SubElement(case, 'failure' if outcome == 'failed' else 'error',
                              {'message': _clean(_message(traceback))})
        child.text = _clean(traceback)
    elif outcome == 'skipped':
        message = _message(traceback)
        if message.startswith('Skipped: '):
            message = message[len('Skipped: '):]
        ET.SubElement(case, 'skipped', {'message': _clean(message)})

    output = [a.get('text') for a in metadata.get('attachments') or []
              if isinstance(a, dict) and a.get('text')]
    if output:
        ET.SubElement(case, 'system-out').text = _clean('\n'.join(output))
    return case


def _iso_timestamp(value):
    # pyrept stores "2026/10/06 17:03:54 UTC"; JUnit expects ISO 8601.
    try:
        return datetime.strptime(str(value), '%Y/%m/%d %H:%M:%S UTC').strftime('%Y-%m-%dT%H:%M:%S')
    except ValueError:
        return None


def build_junit(context):
    """Return the JUnit XML document (as bytes) for a report context."""
    results = context.get('test_results') or []
    total_time = context.get('duration')
    if not isinstance(total_time, (int, float)):
        total_time = sum(_seconds(r) for r in results)
    counts = {
        'tests': str(len(results)),
        'failures': str(sum(1 for r in results if r.get('result') == 'failed')),
        'errors': str(sum(1 for r in results if r.get('result') == 'error')),
        'skipped': str(sum(1 for r in results if r.get('result') == 'skipped')),
        'time': '%.3f' % total_time,
    }
    title = _clean(context.get('test_report_title') or 'Test Report')
    root = ET.Element('testsuites', dict(counts, name=title))
    suite = ET.SubElement(root, 'testsuite', dict(counts, name=title))
    timestamp = _iso_timestamp(context.get('timestamp'))
    if timestamp:
        suite.set('timestamp', timestamp)
    env = context.get('environment') or {}
    if env:
        props = ET.SubElement(suite, 'properties')
        for key, value in env.items():
            ET.SubElement(props, 'property', {'name': _clean(key), 'value': _clean(value)})
    for result in results:
        suite.append(_testcase(result))
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)


def write_junit(context, path):
    with open(path, 'wb') as fh:
        fh.write(build_junit(context))
