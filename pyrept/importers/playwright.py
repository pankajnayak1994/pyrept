"""
Import a Playwright Test JSON report (``npx playwright test --reporter=json``).
Each test x project (browser) becomes one test; screenshots are embedded.
"""
import base64
import json
import os

from ..report import ReportCollector, make_attachment


def _walk_specs(suite, titles):
    title = suite.get('title')
    path = titles + [title] if title else titles
    for spec in suite.get('specs') or []:
        yield path, spec
    for child in suite.get('suites') or []:
        for item in _walk_specs(child, path):
            yield item


def _outcome(test, last_result):
    status = test.get('status')  # expected | unexpected | flaky | skipped
    if status == 'skipped' or (last_result or {}).get('status') == 'skipped':
        return 'skipped'
    if status in ('expected', 'flaky'):
        return 'passed'
    result_status = (last_result or {}).get('status')
    if result_status in ('timedOut', 'interrupted'):
        return 'error'
    return 'failed'


def _error_text(result):
    errors = result.get('errors') or ([result['error']] if result.get('error') else [])
    parts = []
    for err in errors:
        parts.append(err.get('stack') or err.get('message') or json.dumps(err))
    return '\n\n'.join(parts) or None


def _output_text(chunks):
    # Each chunk is {"text": ...} or, for binary output, {"buffer": <base64>}.
    parts = []
    for chunk in chunks or []:
        if not isinstance(chunk, dict):
            continue
        if chunk.get('text') is not None:
            parts.append(chunk['text'])
        elif chunk.get('buffer'):
            try:
                parts.append(base64.b64decode(chunk['buffer']).decode('utf-8', 'replace'))
            except (ValueError, TypeError):
                pass
    return ''.join(parts)


def load_playwright_json(path, collector=None, title='Playwright Test Report'):
    with open(path, encoding='utf-8-sig') as fh:
        report = json.load(fh)
    if not isinstance(report, dict) or not isinstance(report.get('suites', []), list):
        raise ValueError('%s is not a Playwright JSON report (expected an object with "suites")' % path)
    base_dir = os.path.dirname(os.path.abspath(path))
    collector = collector or ReportCollector(title=title)

    for root in report.get('suites') or []:
        for titles, spec in _walk_specs(root, []):
            for test in spec.get('tests') or []:
                results = test.get('results') or []
                last = results[-1] if results else {}
                project = test.get('projectName') or ''
                name = ' › '.join([t for t in titles if t] + [spec.get('title', '')])
                if project:
                    name = '[%s] %s' % (project, name)

                attachments = []
                for att in last.get('attachments') or []:
                    att_path = att.get('path')
                    if att_path and not os.path.isabs(att_path):
                        att_path = os.path.join(base_dir, att_path)
                    attachments.append(make_attachment(
                        name=att.get('name', 'attachment'),
                        content_type=att.get('contentType'),
                        data=att.get('body'),  # already base64 in the JSON reporter
                        path=att_path))

                for stream in ('stdout', 'stderr'):
                    output = _output_text(last.get(stream))
                    if output.strip():
                        attachments.append(make_attachment(stream, 'text/plain', text=output))

                collector.add(
                    name=name,
                    outcome=_outcome(test, last),
                    description=' '.join('@' + t.lstrip('@') for t in spec.get('tags') or []) or None,
                    traceback=_error_text(last) if last else None,
                    metadata={
                        'framework': 'playwright',
                        'project': project,
                        'location': '%s:%s' % (spec.get('file', ''), spec.get('line', '')),
                        'duration': round((last.get('duration') or 0) / 1000.0, 4),
                        'retries': max(len(results) - 1, 0),
                        'flaky': test.get('status') == 'flaky',
                    },
                    attachments=attachments or None,
                )

    # Errors outside any test (config errors, a spec file that fails to import, ...).
    for err in report.get('errors') or []:
        if not isinstance(err, dict):
            continue
        location = err.get('location') or {}
        collector.add(
            name='Global error' + (' in %s' % location['file'] if location.get('file') else ''),
            outcome='error',
            traceback=err.get('stack') or err.get('message') or json.dumps(err),
            metadata={'framework': 'playwright',
                      'location': '%s:%s' % (location.get('file', ''), location.get('line', ''))},
        )
    return collector
