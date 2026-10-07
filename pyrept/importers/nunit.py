"""
Import NUnit XML (NUnit 3 ``TestResult.xml`` and the older NUnit 2 format)
and xUnit.net v2 XML (``dotnet test --logger xunit`` / ``-xml``).
"""
import os
import xml.etree.ElementTree as ET

from ..report import ReportCollector, make_attachment
from .junit import _children, _local, _seconds, _text


def _parse(path, roots, kind):
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise ValueError('%s is not valid XML: %s' % (path, exc))
    if _local(root.tag) not in roots:
        raise ValueError('%s is not an %s report (root element is <%s>)' % (path, kind, _local(root.tag)))
    return root


def _child(element, name):
    found = _children(element, name) if element is not None else []
    return found[0] if found else None


def _walk(element, name):
    if _local(element.tag) == name:
        yield element
        return
    for child in element:
        for found in _walk(child, name):
            yield found


def _detail(element):
    """``<failure>`` / ``<reason>``: message and stack trace."""
    if element is None:
        return None
    parts = [_text(_child(element, 'message')), _text(_child(element, 'stack-trace'))]
    return '\n\n'.join(p for p in parts if p) or None


def _categories(case):
    tags = []
    props = _child(case, 'properties')
    for prop in _children(props, 'property') if props is not None else []:
        if (prop.get('name') or '').lower() == 'category' and prop.get('value'):
            tags.append(prop.get('value'))
    categories = _child(case, 'categories')  # NUnit 2
    for category in _children(categories, 'category') if categories is not None else []:
        if category.get('name'):
            tags.append(category.get('name'))
    return tags


def load_nunit_xml(path, collector=None, title='NUnit Test Report'):
    root = _parse(path, ('test-run', 'test-results'), 'NUnit XML')
    collector = collector or ReportCollector(title=title)
    base_dir = os.path.dirname(os.path.abspath(path))
    nunit2 = _local(root.tag) == 'test-results'
    for case in _walk(root, 'test-case'):
        name = case.get('fullname') or case.get('name') or 'test'
        result = (case.get('result') or '').strip().lower()
        label = (case.get('label') or '').strip().lower()
        failure, reason = _detail(_child(case, 'failure')), _detail(_child(case, 'reason'))
        if nunit2 and case.get('executed', 'True').lower() == 'false':
            result = 'skipped'
        if result in ('passed', 'success', 'warning'):
            outcome, traceback = 'passed', None
        elif result in ('failed', 'failure'):
            outcome = 'error' if label in ('error', 'invalid', 'cancelled') else 'failed'
            traceback = failure or reason
        elif result in ('error', 'notrunnable', 'cancelled'):
            outcome, traceback = 'error', failure or reason
        else:  # skipped, ignored, inconclusive, explicit
            outcome = 'skipped'
            traceback = 'Skipped: %s' % (reason or label or result) if (reason or label or result) else None
        attachments = []
        output = _text(_child(case, 'output'))
        if output:
            attachments.append(make_attachment('output', 'text/plain', text=output))
        files = _child(case, 'attachments')
        for attachment in _children(files, 'attachment') if files is not None else []:
            file_path = _text(_child(attachment, 'filePath'))
            if file_path:
                if not os.path.isabs(file_path):
                    file_path = os.path.join(base_dir, file_path)
                attachments.append(make_attachment(_text(_child(attachment, 'description'))
                                                   or os.path.basename(file_path), path=file_path))
        seconds = case.get('duration') if case.get('duration') is not None else case.get('time')
        collector.add(name=name, outcome=outcome, traceback=traceback, attachments=attachments or None,
                      metadata={'framework': 'nunit', 'duration': round(_seconds(seconds), 4),
                                'location': case.get('classname') or None, 'tags': _categories(case)})
    return collector


def load_xunit_xml(path, collector=None, title='xUnit.net Test Report'):
    root = _parse(path, ('assemblies', 'assembly'), 'xUnit.net XML')
    collector = collector or ReportCollector(title=title)
    for test in _walk(root, 'test'):
        result = (test.get('result') or '').strip().lower()
        failure = _child(test, 'failure')
        if result == 'pass':
            outcome, traceback = 'passed', None
        elif result == 'fail':
            detail = _detail(failure)
            exception = (failure.get('exception-type') or '') if failure is not None else ''
            # xUnit.net reports assertion failures and crashes alike; assertion exceptions are failures.
            outcome = 'failed' if not exception or exception.startswith('Xunit.Sdk.') else 'error'
            traceback = '%s: %s' % (exception, detail) if exception and detail and exception not in detail else detail
        else:  # skip, notrun
            reason = _text(_child(test, 'reason'))
            outcome, traceback = 'skipped', 'Skipped: %s' % reason if reason else None
        tags = []
        traits = _child(test, 'traits')
        for trait in _children(traits, 'trait') if traits is not None else []:
            if trait.get('value'):
                tags.append(trait.get('value') if (trait.get('name') or '').lower() == 'category'
                            else '%s=%s' % (trait.get('name'), trait.get('value')))
        output = _text(_child(test, 'output'))
        collector.add(name=test.get('name') or test.get('method') or 'test', outcome=outcome, traceback=traceback,
                      attachments=[make_attachment('output', 'text/plain', text=output)] if output else None,
                      metadata={'framework': 'xunit', 'duration': round(_seconds(test.get('time')), 4),
                                'location': test.get('type') or None, 'tags': tags})
    return collector
