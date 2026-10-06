"""
Import a Cucumber JSON report (cucumber-jvm, cucumber-js, cucumber-ruby, behave's
``-f json``, godog, ...). Each scenario becomes one test.
"""
import json

from ..report import ReportCollector, make_attachment

_STEP_STATUS = {
    'passed': 'passed',
    'failed': 'failed',
    'skipped': 'skipped',
    'pending': 'skipped',
    'undefined': 'error',
    'ambiguous': 'error',
    'unknown': 'skipped',
}
_SEVERITY = {'passed': 0, 'skipped': 1, 'failed': 2, 'error': 3}


def _step_status(step):
    return _STEP_STATUS.get(((step.get('result') or {}).get('status') or 'unknown').lower(), 'error')


def _steps_outcome(steps):
    if not steps:
        return 'skipped'
    statuses = [_step_status(s) for s in steps]
    if 'failed' in statuses or 'error' in statuses:
        return max(statuses, key=lambda s: _SEVERITY[s])
    if all(s == 'passed' for s in statuses):
        return 'passed'
    return 'skipped'


def _hook_errors(element):
    for key in ('before', 'after'):
        for hook in element.get(key) or []:
            result = hook.get('result') or {}
            if (result.get('status') or '').lower() == 'failed':
                yield '%s hook failed\n%s' % (key, result.get('error_message', ''))


def load_cucumber_json(path, collector=None, title='Cucumber Test Report'):
    with open(path, encoding='utf-8') as fh:
        features = json.load(fh)
    collector = collector or ReportCollector(title=title)

    for feature in features or []:
        feature_name = feature.get('name') or feature.get('uri') or 'Feature'
        background_steps = []
        for element in feature.get('elements') or []:
            steps = element.get('steps') or []
            if element.get('type') == 'background':
                background_steps = steps  # applies to the scenario that follows
                continue
            all_steps = background_steps + steps
            background_steps = []

            outcome = _steps_outcome(all_steps)
            hook_errors = list(_hook_errors(element))
            failing = next((s for s in all_steps if _step_status(s) in ('failed', 'error')), None)
            traceback = None
            if failing is not None:
                result = failing.get('result') or {}
                traceback = '%s%s  [%s]\n\n%s' % (failing.get('keyword', ''), failing.get('name', ''),
                                                   result.get('status'), result.get('error_message', ''))
            if hook_errors:
                outcome = 'error' if outcome != 'failed' else outcome
                traceback = '\n\n'.join(filter(None, [traceback] + hook_errors))

            duration_ns = sum((s.get('result') or {}).get('duration') or 0 for s in all_steps)
            tags = [t.get('name') for t in element.get('tags') or [] if t.get('name')]
            description = '\n'.join(
                ([' '.join(tags)] if tags else [])
                + ['%s%s  [%s]' % (s.get('keyword', ''), s.get('name', ''),
                                   (s.get('result') or {}).get('status', 'unknown')) for s in all_steps])

            attachments = []
            for step in all_steps:
                for emb in step.get('embeddings') or []:
                    attachments.append(make_attachment(
                        name=emb.get('name') or step.get('name') or 'attachment',
                        content_type=emb.get('mime_type') or (emb.get('media') or {}).get('type'),
                        data=emb.get('data')))

            collector.add(
                name='%s :: %s' % (feature_name, element.get('name') or element.get('id')),
                outcome=outcome,
                description=description,
                traceback=traceback,
                metadata={
                    'framework': 'cucumber',
                    'location': '%s:%s' % (feature.get('uri', ''), element.get('line', '')),
                    # Cucumber reports durations in nanoseconds
                    'duration': round(duration_ns / 1e9, 4),
                    'tags': tags,
                },
                attachments=attachments or None,
            )
    return collector
