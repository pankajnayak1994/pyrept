"""
Compare a run with an earlier pyrept JSON report (the "baseline").

    pytest --pyrept --pyrept-baseline=report.json   # compare with the previous report.json

The baseline is read before the new reports are written, so it can be the
same file the run is about to overwrite.
"""
import json
import logging
import os

logger = logging.getLogger(__name__)

PROBLEMS = ('failed', 'error')
# A test counts as slower when it takes at least SLOWER_RATIO times as long as
# in the baseline and at least SLOWER_MIN_DELTA seconds more, so noise on
# millisecond tests is ignored.
SLOWER_RATIO = 1.5
SLOWER_MIN_DELTA = 0.5
MAX_SLOWER = 10

# Values of ``comparison['changes']`` (also used as data-change in the HTML).
NEW_FAILURE = 'new-failure'
FIXED = 'fixed'
STILL_FAILING = 'still-failing'
NEW_TEST = 'new'


def load_baseline(path):
    """
    Read a pyrept JSON report to compare against.

    Returns ``None`` (and logs a warning) when the file is missing or is not a
    pyrept report: the first run in CI has no baseline, and that must not fail
    the test run.
    """
    if not path:
        return None
    if not os.path.isfile(path):
        logger.warning('pyrept: baseline %s not found; skipping comparison', path)
        return None
    try:
        with open(path, encoding='utf-8-sig') as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        logger.warning('pyrept: cannot read baseline %s: %s', path, exc)
        return None
    if not isinstance(data, dict) or not isinstance(data.get('test_results'), list):
        logger.warning('pyrept: %s is not a pyrept JSON report; skipping comparison', path)
        return None
    data['_source'] = path
    return data


def _duration(result):
    value = (result.get('metadata') or {}).get('duration')
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _index(results):
    index = {}
    for result in results:
        if isinstance(result, dict) and 'name' in result:
            index[str(result['name'])] = result
    return index


def compare(test_results, baseline, current_percentage=None):
    """
    Build the ``comparison`` section of the report context.

    ``test_results`` are the current results, ``baseline`` is a dict returned by
    :func:`load_baseline`. Returns ``None`` when there is no baseline.
    """
    if not baseline:
        return None
    before = _index(baseline.get('test_results') or [])
    now = _index(test_results)

    changes = {}
    new_failures, fixed, still_failing, new_tests, slower = [], [], [], [], []
    for name, result in now.items():
        old = before.get(name)
        is_problem = result.get('result') in PROBLEMS
        was_problem = old is not None and old.get('result') in PROBLEMS
        if old is None:
            new_tests.append(name)
            changes[name] = NEW_TEST
        if is_problem and not was_problem:
            new_failures.append(name)
            changes[name] = NEW_FAILURE
        elif is_problem and was_problem:
            still_failing.append(name)
            changes[name] = STILL_FAILING
        elif was_problem and result.get('result') == 'passed':
            fixed.append(name)
            changes[name] = FIXED
        if old is not None:
            old_duration, new_duration = _duration(old), _duration(result)
            if (old_duration and new_duration is not None and new_duration >= old_duration * SLOWER_RATIO
                    and new_duration - old_duration >= SLOWER_MIN_DELTA):
                slower.append({'name': name, 'before': round(old_duration, 3), 'after': round(new_duration, 3),
                               'ratio': round(new_duration / old_duration, 2)})
    removed = sorted(name for name in before if name not in now)
    slower.sort(key=lambda s: (-s['ratio'], s['name']))

    old_summary = baseline.get('test_summary') if isinstance(baseline.get('test_summary'), dict) else {}
    old_percentage = old_summary.get('percentage')
    delta = None
    if isinstance(old_percentage, (int, float)) and isinstance(current_percentage, (int, float)):
        delta = round(current_percentage - old_percentage, 2)
    return {
        'baseline': {
            'source': os.path.basename(str(baseline.get('_source', ''))),
            'title': baseline.get('test_report_title'),
            'timestamp': baseline.get('timestamp'),
            'percentage': old_percentage,
            'total': old_summary.get('total'),
        },
        'percentage_delta': delta,
        'new_failures': sorted(new_failures),
        'fixed': sorted(fixed),
        'still_failing': sorted(still_failing),
        'new_tests': sorted(new_tests),
        'removed_tests': removed,
        'slower': slower[:MAX_SLOWER],
        'changes': changes,
    }


def summary_line(comparison):
    """One line for terminal output, e.g. ``2 new failures, 1 fixed, 3 still failing``."""
    if not comparison:
        return None
    new_failures = len(comparison['new_failures'])
    parts = ['%d new failure%s' % (new_failures, '' if new_failures == 1 else 's'),
             '%d fixed' % len(comparison['fixed']),
             '%d still failing' % len(comparison['still_failing'])]
    if comparison['new_tests']:
        parts.append('%d new' % len(comparison['new_tests']))
    if comparison['removed_tests']:
        parts.append('%d removed' % len(comparison['removed_tests']))
    if comparison['slower']:
        parts.append('%d slower' % len(comparison['slower']))
    return ', '.join(parts) + ' (vs %s)' % (comparison['baseline']['source'] or 'baseline')
