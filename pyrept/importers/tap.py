"""
Import TAP, the Test Anything Protocol (versions 12 to 14): node-tap, Perl's
prove, bats, pg_prove and many shell-based test suites.

``# SKIP`` becomes skipped, ``# TODO`` failures become expected failures
(skipped), YAML diagnostic blocks become the error details, and a plan that
does not match the tests that ran (or ``Bail out!``) is reported as an error.
"""
import re

from ..report import ReportCollector

_TEST = re.compile(r'^(not )?ok\b\s*(\d+)?\s*(?:-\s*)?([^#]*?)\s*(?:#\s*(.*))?$', re.IGNORECASE)
_PLAN = re.compile(r'^1\.\.(\d+)')
_DIRECTIVE = re.compile(r'^(skip|todo)\S*\s*(.*)$', re.IGNORECASE)
_DURATION = re.compile(r'^\s*duration_ms:\s*([0-9.]+)', re.MULTILINE)


def load_tap(path, collector=None, title='TAP Test Report'):
    with open(path, encoding='utf-8-sig', errors='replace') as fh:
        lines = fh.read().splitlines()
    collector = collector or ReportCollector(title=title)
    tests, plan, bail_out = [], None, None
    current = None
    in_yaml = False
    for raw in lines:
        if in_yaml:
            if raw.strip() == '...':
                in_yaml = False
            else:  # a YAML block always follows a test line
                current['diagnostics'].append(raw[2:] if raw.startswith('  ') else raw.strip())
            continue
        if raw.startswith(' '):
            # Indented lines: a YAML block for the last test, or TAP 14 subtests (folded into their parent).
            if raw.strip() == '---' and current is not None:
                in_yaml = True
            continue
        line = raw.strip()
        if line.lower().startswith('bail out!'):
            bail_out = line[len('bail out!'):].strip() or 'Bail out!'
            break
        match = _PLAN.match(line)
        if match:
            plan = int(match.group(1))
            continue
        match = _TEST.match(line)
        if match:
            current = {'ok': not match.group(1), 'number': match.group(2), 'description': match.group(3).strip(),
                       'directive': (match.group(4) or '').strip(), 'diagnostics': []}
            tests.append(current)
    if not tests and plan is None and bail_out is None:
        raise ValueError('%s is not a TAP report (no "ok" / "not ok" lines or plan found)' % path)

    for index, test in enumerate(tests, 1):
        number = test['number'] or str(index)
        name = test['description'] or 'test %s' % number
        directive = _DIRECTIVE.match(test['directive'])
        diagnostics = '\n'.join(test['diagnostics']).strip()
        if directive and directive.group(1).lower().startswith('skip'):
            outcome, traceback = 'skipped', 'Skipped: %s' % directive.group(2) if directive.group(2) else None
        elif directive and directive.group(1).lower().startswith('todo'):
            outcome = 'passed' if test['ok'] else 'skipped'
            traceback = None if test['ok'] else 'Expected failure (TODO): %s' % directive.group(2)
        elif test['ok']:
            outcome, traceback = 'passed', None
        else:
            outcome, traceback = 'failed', diagnostics or 'not ok %s' % number
        duration = _DURATION.search(diagnostics)
        collector.add(name=name, outcome=outcome, traceback=traceback,
                      metadata={'framework': 'tap', 'location': '#%s' % number,
                                'duration': round(float(duration.group(1)) / 1000.0, 4) if duration else 0.0})
    if bail_out is not None:
        collector.add(name='Bail out', outcome='error', traceback='Bail out! %s' % bail_out,
                      metadata={'framework': 'tap'})
    elif plan is not None and plan != len(tests):
        collector.add(name='Test plan', outcome='error',
                      traceback='The plan announced %d tests but %d ran' % (plan, len(tests)),
                      metadata={'framework': 'tap'})
    return collector
