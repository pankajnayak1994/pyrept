"""
Import a Visual Studio / .NET TRX report (``dotnet test --logger trx``),
including data-driven tests and result files.
"""
import os
import xml.etree.ElementTree as ET

from ..report import ReportCollector, make_attachment
from .junit import _children, _local, _text

_OUTCOMES = {
    'passed': 'passed', 'passedbutrunaborted': 'passed', 'completed': 'passed', 'warning': 'passed',
    'failed': 'failed',
    'error': 'error', 'timeout': 'error', 'aborted': 'error', 'disconnected': 'error',
    'notexecuted': 'skipped', 'inconclusive': 'skipped', 'pending': 'skipped', 'notrunnable': 'skipped',
    'inprogress': 'skipped',
}


def _duration(value):
    """TRX durations look like ``00:00:01.2345678``."""
    try:
        hours, minutes, seconds = str(value).split(':')
        return round(int(hours) * 3600 + int(minutes) * 60 + float(seconds), 4)
    except (TypeError, ValueError):
        return 0.0


def _first(element, *path):
    for name in path:
        if element is None:
            return None
        found = _children(element, name)
        element = found[0] if found else None
    return element


def _definitions(root):
    """testId -> (class name, method name)."""
    found = {}
    definitions = _first(root, 'TestDefinitions')
    for unit_test in _children(definitions, 'UnitTest') if definitions is not None else []:
        method = _first(unit_test, 'TestMethod')
        if method is not None:
            found[unit_test.get('id')] = ((method.get('className') or '').split(',')[0].strip(),
                                          method.get('name') or '')
    return found


def _results(element):
    """Leaf UnitTestResults: a data-driven test's rows replace its parent entry."""
    for result in element:
        if _local(result.tag) != 'UnitTestResult':
            continue
        inner = _first(result, 'InnerResults')
        rows = [r for r in inner if _local(r.tag) == 'UnitTestResult'] if inner is not None else []
        if rows:
            for row in _results(inner):
                yield row
        else:
            yield result


def load_trx(path, collector=None, title='.NET Test Report'):
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise ValueError('%s is not valid XML: %s' % (path, exc))
    if _local(root.tag) != 'TestRun':
        raise ValueError('%s is not a TRX report (root element is <%s>)' % (path, _local(root.tag)))
    collector = collector or ReportCollector(title=title)
    definitions = _definitions(root)
    deployment = _first(root, 'TestSettings', 'Deployment')
    run_root = deployment.get('runDeploymentRoot') if deployment is not None else None
    base_dir = os.path.dirname(os.path.abspath(path))

    results = _first(root, 'Results')
    for result in _results(results) if results is not None else []:
        classname, method = definitions.get(result.get('testId'), ('', ''))
        short = (result.get('testName') or method or 'test').strip()
        name = '%s.%s' % (classname, short) if classname and not short.startswith(classname + '.') else short
        outcome = _OUTCOMES.get((result.get('outcome') or '').strip().lower(), 'error')

        output = _first(result, 'Output')
        message = _text(_first(output, 'ErrorInfo', 'Message'))
        stack = _text(_first(output, 'ErrorInfo', 'StackTrace'))
        traceback = '\n\n'.join(part for part in (message, stack) if part) or None
        if outcome == 'skipped' and traceback and not traceback.startswith('Skipped'):
            traceback = 'Skipped: %s' % traceback
        if outcome == 'error' and not traceback:
            traceback = 'Test outcome: %s' % result.get('outcome')

        attachments = []
        for stream, label in (('StdOut', 'stdout'), ('StdErr', 'stderr'), ('DebugTrace', 'debug trace')):
            text = _text(_first(output, stream))
            if text:
                attachments.append(make_attachment(label, 'text/plain', text=text))
        files = _first(result, 'ResultFiles')
        for result_file in _children(files, 'ResultFile') if files is not None else []:
            file_path = result_file.get('path') or ''
            if not file_path:
                continue
            if not os.path.isabs(file_path) and run_root:
                file_path = os.path.join(base_dir, run_root, 'In', result.get('executionId') or '', file_path)
            attachments.append(make_attachment(os.path.basename(file_path), path=file_path))

        collector.add(name=name, outcome=outcome, traceback=traceback, attachments=attachments or None,
                      metadata={'framework': 'trx', 'duration': _duration(result.get('duration')),
                                'location': classname or None})
    return collector
