"""
Trends across many runs: pass rate, durations, flaky tests and failure streaks.

    pyrept history history/*.json --html history.html

Each input is a pyrept JSON report (or a directory of them). Keep one report
per CI run, for example by copying ``report.json`` to
``history/<run number>.json`` and caching that directory between runs.
"""
import glob
import json
import logging
import os
from datetime import datetime, timezone

from .summary import PROBLEMS

logger = logging.getLogger(__name__)

TIMESTAMP_FORMAT = '%Y/%m/%d %H:%M:%S UTC'
DEFAULT_LIMIT = 50
MAX_ROWS = 25


def _timestamp(report, path):
    try:
        return datetime.strptime(str(report.get('timestamp')), TIMESTAMP_FORMAT).replace(tzinfo=timezone.utc)
    except ValueError:
        return datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc)


def expand_inputs(inputs):
    """Files as given, directories as their ``*.json`` files; duplicates removed, order kept."""
    seen, paths = set(), []
    for item in inputs:
        found = sorted(glob.glob(os.path.join(item, '*.json'))) if os.path.isdir(item) else [item]
        for path in found:
            real = os.path.realpath(path)
            if real not in seen:
                seen.add(real)
                paths.append(path)
    return paths


def load_runs(paths):
    """
    Load the reports, oldest first. Returns ``(runs, problems)`` where ``problems``
    lists ``(path, reason)`` for files that were skipped.
    """
    runs, problems = [], []
    for path in paths:
        try:
            with open(path, encoding='utf-8-sig') as fh:
                report = json.load(fh)
        except (OSError, ValueError) as exc:
            problems.append((path, str(exc)))
            continue
        if not isinstance(report, dict) or not isinstance(report.get('test_results'), list):
            problems.append((path, 'not a pyrept JSON report'))
            continue
        runs.append((_timestamp(report, path), path, report))
    runs.sort(key=lambda run: (run[0], run[1]))
    return runs, problems


def _outcome(result):
    return result.get('result') if isinstance(result, dict) else None


def _duration(result):
    value = (result.get('metadata') or {}).get('duration') if isinstance(result, dict) else None
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _summary(report):
    stats = report.get('test_summary') if isinstance(report.get('test_summary'), dict) else {}
    results = [r for r in report['test_results'] if isinstance(r, dict)]
    counts = {key: sum(1 for r in results if r.get('result') == key)
              for key in ('passed', 'failed', 'error', 'skipped')}
    counts['total'] = len(results)
    executed = counts['total'] - counts['skipped']
    counts['percentage'] = round(counts['passed'] * 100.0 / executed, 2) if executed else 0
    duration = report.get('duration')
    if not isinstance(duration, (int, float)) or isinstance(duration, bool):
        duration = sum(d for d in (_duration(r) for r in results) if d is not None)
    counts['duration'] = round(duration, 3)
    # Prefer the report's own numbers when they are consistent with its results.
    if stats.get('total') == counts['total'] and isinstance(stats.get('percentage'), (int, float)):
        counts['percentage'] = stats['percentage']
    return counts


def build_history(runs, title='Test History', limit=DEFAULT_LIMIT):
    """
    Build the history context from ``load_runs`` output (oldest first).

    ``limit`` keeps only the newest runs.
    """
    if limit:
        runs = runs[-limit:]
    run_rows = []
    per_test = {}  # name -> list of (outcome or None) per run
    durations = {}  # name -> list of durations
    flagged_flaky = set()
    for index, (stamp, path, report) in enumerate(runs):
        row = _summary(report)
        row.update({'index': index, 'timestamp': stamp.strftime(TIMESTAMP_FORMAT),
                    'source': os.path.basename(path), 'title': report.get('test_report_title')})
        run_rows.append(row)
        for result in report['test_results']:
            if not isinstance(result, dict) or 'name' not in result:
                continue
            name = str(result['name'])
            per_test.setdefault(name, [None] * len(runs))[index] = _outcome(result)
            duration = _duration(result)
            if duration is not None:
                durations.setdefault(name, []).append(duration)
            if (result.get('metadata') or {}).get('flaky'):
                flagged_flaky.add(name)

    flaky, failing, streaks = [], [], []
    for name, outcomes in per_test.items():
        present = [o for o in outcomes if o is not None]
        problems = sum(1 for o in present if o in PROBLEMS)
        passes = sum(1 for o in present if o == 'passed')
        # A flip is a change between passing and failing in consecutive runs (skips are ignored).
        # Breaking once and being fixed is one failing stretch (a regression); failing in two or
        # more separate stretches with passes in between is flakiness.
        decided = [o in PROBLEMS for o in present if o in PROBLEMS or o == 'passed']
        flips = sum(1 for a, b in zip(decided, decided[1:]) if a != b)
        stretches = sum(1 for i, failed in enumerate(decided) if failed and (i == 0 or not decided[i - 1]))
        entry = {'name': name, 'outcomes': outcomes, 'runs': len(present), 'failures': problems,
                 'passes': passes, 'flips': flips, 'failing_stretches': stretches,
                 'failure_rate': round(problems * 100.0 / len(present), 1) if present else 0}
        if (stretches >= 2 and passes) or name in flagged_flaky:
            flaky.append(entry)
        if problems:
            failing.append(entry)
        if outcomes[-1] in PROBLEMS:  # failing in the newest run: how long has it been failing?
            streak, since = 0, len(outcomes) - 1
            for i in range(len(outcomes) - 1, -1, -1):
                if outcomes[i] is None:
                    continue  # not run that time
                if outcomes[i] not in PROBLEMS:
                    break
                streak, since = streak + 1, i
            streaks.append(dict(entry, streak=streak, since=run_rows[since]['timestamp']))
    flaky.sort(key=lambda e: (-e['failing_stretches'], -e['flips'], -e['failures'], e['name']))
    failing.sort(key=lambda e: (-e['failures'], -e['failure_rate'], e['name']))
    streaks.sort(key=lambda e: (-e['streak'], e['name']))

    slowest = []
    for name, values in durations.items():
        slowest.append({'name': name, 'average': round(sum(values) / len(values), 3), 'max': round(max(values), 3),
                        'latest': round(values[-1], 3), 'runs': len(values)})
    slowest.sort(key=lambda e: (-e['average'], e['name']))

    latest, first = (run_rows[-1], run_rows[0]) if run_rows else ({}, {})
    return {
        'history_title': title,
        'generated': datetime.now(timezone.utc).strftime(TIMESTAMP_FORMAT),
        'runs': run_rows,
        'summary': {
            'runs': len(run_rows),
            'tests': len(per_test),
            'latest_percentage': latest.get('percentage'),
            'average_percentage': round(sum(r['percentage'] for r in run_rows) / len(run_rows), 2) if run_rows else 0,
            'percentage_change': round(latest['percentage'] - first['percentage'], 2) if len(run_rows) > 1 else None,
            'flaky': len(flaky),
            'failing_now': len(streaks),
        },
        'flaky_tests': flaky[:MAX_ROWS],
        'failure_streaks': streaks[:MAX_ROWS],
        'most_failing': failing[:MAX_ROWS],
        'slowest_tests': slowest[:10],
    }


def write_history(context, html_path=None, json_path=None, template_path=None):
    from .branding import branding_from_env
    from .render import load_template, render_template

    for path in (html_path, json_path):
        parent = os.path.dirname(path) if path else ''
        if parent:
            os.makedirs(parent, exist_ok=True)
    if html_path:
        template = load_template(template_path or os.path.join(os.path.dirname(__file__), 'templates',
                                                               'history.html'))
        with open(html_path, 'w', encoding='utf-8') as fh:
            fh.write(render_template(template, dict(context, branding=branding_from_env())))
    if json_path:
        with open(json_path, 'w', encoding='utf-8') as fh:
            json.dump(context, fh, indent=2)
