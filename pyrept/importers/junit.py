"""
Import a JUnit XML report: pytest ``--junitxml``, Maven Surefire/Gradle, Jest
(jest-junit), Go (go-junit-report / gotestsum), Cypress, .NET, Robot
Framework's xunit output, behave ``--junit`` and most other test runners.
"""
import os
import re
import xml.etree.ElementTree as ET

from ..report import ReportCollector, make_attachment

# Jenkins convention for attaching files from test output: [[ATTACHMENT|path/to/file]]
_ATTACHMENT = re.compile(r'\[\[ATTACHMENT\|([^\]]+)\]\]')
# Maven Surefire records retried tests as <flakyFailure>/<rerunFailure> children.
_RERUN_TAGS = ('flakyFailure', 'flakyError', 'rerunFailure', 'rerunError')


def _seconds(value):
    # Surefire writes locale-formatted numbers such as "1,234.5".
    try:
        seconds = float(str(value).replace(',', '')) if value not in (None, '') else 0.0
    except ValueError:
        return 0.0
    return seconds if seconds >= 0 else 0.0


def _local(tag):
    return tag.rsplit('}', 1)[-1] if isinstance(tag, str) else ''  # drop any XML namespace


def _children(element, *names):
    return [child for child in element if _local(child.tag) in names]


def _text(element):
    return (element.text or '').strip() if element is not None else ''


def _detail(element):
    """Message and body of a <failure>/<error>/<skipped> element."""
    message = (element.get('message') or '').strip()
    body = _text(element)
    kind = (element.get('type') or '').strip()
    if body and message and message not in body:
        return '%s\n\n%s' % (message, body)
    if body:
        return body
    if kind and message and kind not in message:
        return '%s: %s' % (kind, message)
    return message or kind


def _testcases(element, suites):
    """Yield (suite names, testcase) for every testcase, however deeply suites are nested."""
    name = _local(element.tag)
    if name == 'testcase':
        yield suites, element
        return
    if name == 'testsuite' and element.get('name'):
        suites = suites + [element.get('name')]
    for child in element:
        if _local(child.tag) in ('testsuite', 'testsuites', 'testcase'):
            for item in _testcases(child, suites):
                yield item


def load_junit_xml(path, collector=None, title='JUnit Test Report'):
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise ValueError('%s is not valid XML: %s' % (path, exc))
    if _local(root.tag) not in ('testsuites', 'testsuite', 'testcase'):
        raise ValueError('%s is not a JUnit XML report (root element is <%s>)' % (path, _local(root.tag)))
    base_dir = os.path.dirname(os.path.abspath(path))
    collector = collector or ReportCollector(title=title)

    for suites, case in _testcases(root, []):
        classname = (case.get('classname') or case.get('class') or '').strip()
        short = (case.get('name') or '').strip() or 'test'
        # jest-junit and others repeat the full title in both attributes
        name = '%s.%s' % (classname, short) if classname and classname != short else short

        errors = _children(case, 'error')
        failures = _children(case, 'failure')
        skipped = _children(case, 'skipped')
        reruns = _children(case, *_RERUN_TAGS)
        if errors:
            outcome, traceback = 'error', '\n\n'.join(_detail(e) for e in errors)
        elif failures:
            outcome, traceback = 'failed', '\n\n'.join(_detail(f) for f in failures)
        elif skipped:
            reason = _detail(skipped[0])
            if reason and not reason.startswith('Skipped'):
                reason = 'Skipped: %s' % reason
            outcome, traceback = 'skipped', reason or None
        else:
            outcome, traceback = 'passed', None

        attachments = []
        output = {}
        for stream in ('system-out', 'system-err'):
            text = '\n'.join(_text(e) for e in _children(case, stream) if _text(e))
            if text:
                output[stream] = text
                attachments.append(make_attachment(stream, 'text/plain', text=text))
        for stream_text in output.values():
            for attachment_path in _ATTACHMENT.findall(stream_text):
                attachment_path = attachment_path.strip()
                if not os.path.isabs(attachment_path):
                    attachment_path = os.path.join(base_dir, attachment_path)
                attachments.append(make_attachment(os.path.basename(attachment_path), path=attachment_path))

        tags = []
        for props in _children(case, 'properties'):
            for prop in _children(props, 'property'):
                if prop.get('name') in ('tag', 'tags', 'category') and prop.get('value'):
                    tags.extend(t.strip() for t in prop.get('value').split(',') if t.strip())

        metadata = {
            'framework': 'junit',
            'duration': round(_seconds(case.get('time')), 4),
            'location': '%s:%s' % (case.get('file'), case.get('line')) if case.get('file') and case.get('line')
            else (case.get('file') or classname),
            'tags': tags,
        }
        if suites:
            metadata['suite'] = ' › '.join(suites)
        if reruns:
            metadata['retries'] = len(reruns)
            metadata['flaky'] = outcome == 'passed'

        collector.add(name=name, outcome=outcome, traceback=traceback, metadata=metadata,
                      attachments=attachments or None)
    return collector
