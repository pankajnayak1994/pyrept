"""
Short summaries of a report: Markdown (GitHub job summaries, PR comments,
chat), common failure causes and CI quality gates.

    pytest --pyrept --pyrept-markdown=summary.md
    pytest --pyrept --pyrept-github-summary          # append to $GITHUB_STEP_SUMMARY
    pytest --pyrept --pyrept-fail-under=95           # fail when the pass rate drops below 95%
    pytest --pyrept --pyrept-baseline=report.json --pyrept-ignore-known-failures
"""
import html
import logging
import os
import re

logger = logging.getLogger(__name__)

PROBLEMS = ('failed', 'error')
GITHUB_SUMMARY_ENV = 'GITHUB_STEP_SUMMARY'
REPORT_URL_ENV = 'PYREPT_REPORT_URL'
PROJECT_URL = 'https://github.com/pankajnayak1994/pyrept'

# GitHub rejects a job summary larger than 1 MiB per step. These caps keep the
# Markdown below ~250 KB however large the run is.
MAX_FAILURE_DETAILS = 20
MAX_LIST_ITEMS = 50
MAX_NAME_LENGTH = 300
TRACEBACK_LINES = 40
TRACEBACK_CHARS = 4000
MAX_FAILURE_GROUPS = 10
MESSAGE_LIMIT = 300

_ANSI = re.compile(r'\x1b\[[0-9;?]*[ -/]*[@-~]')
_CONTROL = re.compile('[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')
_ADDRESS = re.compile(r'0x[0-9a-fA-F]{6,}')
_EXCEPTION_LINE = re.compile(r'^[A-Za-z_][\w.]*(Error|Exception|Failure|Exit|Interrupt|Warning)\b')


def clean_text(text):
    """Remove ANSI colour codes and control characters (tab and newlines are kept)."""
    return _CONTROL.sub('', _ANSI.sub('', str(text))) if text is not None else ''


def failure_message(traceback):
    """The most useful single line of a traceback: pytest's first ``E`` line, else the last exception line."""
    lines = [line.strip() for line in clean_text(traceback).splitlines() if line.strip()]
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
    return message[:MESSAGE_LIMIT]


def _signature(traceback):
    # Memory addresses differ between runs and tests ("<Foo object at 0x7f...>").
    return _ADDRESS.sub('0x…', failure_message(traceback))


def failure_groups(test_results, limit=MAX_FAILURE_GROUPS):
    """
    Group failed and errored tests that share an error message.

    Returns ``[{'message': ..., 'count': n, 'tests': [...]}, ...]`` for messages
    shared by at least two tests, the largest groups first: when 40 tests fail
    with the same ``ConnectionError``, that is one problem, not 40.
    """
    groups = {}
    for result in test_results:
        if not isinstance(result, dict) or result.get('result') not in PROBLEMS:
            continue
        signature = _signature(result.get('traceback'))
        if signature:
            groups.setdefault(signature, []).append(str(result.get('name')))
    shared = [{'message': message, 'count': len(names), 'tests': sorted(names)}
              for message, names in groups.items() if len(names) > 1]
    shared.sort(key=lambda g: (-g['count'], g['message']))
    return shared[:limit]


# --- quality gates ------------------------------------------------------------

class GateResult:
    """
    Outcome of the quality gates for one run.

    ``below_threshold``: the pass rate is lower than ``fail_under``.
    ``known_failures_only``: ``ignore_known_failures`` was asked for and every
    failing test was already failing in the baseline.
    """

    def __init__(self, below_threshold=False, known_failures_only=False, messages=None):
        self.below_threshold = below_threshold
        self.known_failures_only = known_failures_only
        self.messages = list(messages or [])

    def successful(self, tests_passed):
        """Whether the run should succeed, given whether the test runner itself saw only passes."""
        if self.below_threshold:
            return False
        return bool(tests_passed) or self.known_failures_only


def parse_fail_under(value):
    """Validate a ``fail-under`` value (a percentage); ``None`` and ``''`` mean "no threshold"."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError('fail-under must be a number between 0 and 100, got %r' % (value,))
    if not 0 <= number <= 100:
        raise ValueError('fail-under must be between 0 and 100, got %r' % (value,))
    return number


def evaluate_gates(context, fail_under=None, ignore_known_failures=False, option_names=None):
    """
    Check a report context against the quality gates.

    ``option_names`` maps ``fail_under`` / ``ignore_known_failures`` / ``baseline``
    to the option spelling of the calling integration, for the messages.
    """
    names = {'fail_under': 'fail-under', 'ignore_known_failures': 'ignore-known-failures', 'baseline': 'baseline'}
    names.update(option_names or {})
    stats = context.get('test_summary') or {}
    messages = []
    below = False
    executed = (stats.get('total') or 0) - (stats.get('skipped') or 0)
    if fail_under is not None and executed <= 0:
        messages.append('no tests were executed, so %s was not checked' % names['fail_under'])
    elif fail_under is not None:
        rate = stats.get('percentage') or 0
        if rate < fail_under:
            below = True
            messages.append('pass rate %s%% is below %s=%s' % (rate, names['fail_under'], _number(fail_under)))
    known_only = False
    problems = (stats.get('failed') or 0) + (stats.get('error') or 0)
    if ignore_known_failures and problems:
        comparison = context.get('comparison')
        if not comparison:
            messages.append('%s needs a %s report; failures were not ignored'
                            % (names['ignore_known_failures'], names['baseline']))
        elif comparison.get('new_failures'):
            count = len(comparison['new_failures'])
            messages.append('%d new failure%s, so %s does not apply'
                            % (count, '' if count == 1 else 's', names['ignore_known_failures']))
        else:
            known_only = True
            messages.append('%d known failure%s ignored: all of them were already failing in the baseline'
                            % (problems, '' if problems == 1 else 's'))
    return GateResult(below, known_only, messages)


def _number(value):
    return ('%f' % value).rstrip('0').rstrip('.') if isinstance(value, float) else str(value)


# --- Markdown -----------------------------------------------------------------

def _code(text):
    """``text`` as a Markdown code span, whatever backticks it contains."""
    text = clean_text(text).replace('\r', ' ').replace('\n', ' ')
    if len(text) > MAX_NAME_LENGTH:
        text = text[:MAX_NAME_LENGTH - 1] + '…'
    longest = max((len(run) for run in re.findall('`+', text)), default=0)
    fence = '`' * (longest + 1)
    if text.startswith('`') or text.endswith('`') or not text.strip():
        text = ' %s ' % text
    return '%s%s%s' % (fence, text, fence)


def _cell(text):
    # GitHub splits table cells on "|" even inside code spans.
    return _code(text).replace('|', '\\|')


def _fenced(text):
    longest = max((len(run) for run in re.findall('`+', text)), default=0)
    fence = '`' * max(3, longest + 1)
    return '%stext\n%s\n%s' % (fence, text, fence)


def _trim(text):
    lines = clean_text(text).rstrip().splitlines()
    omitted = 0
    if len(lines) > TRACEBACK_LINES:
        omitted = len(lines) - TRACEBACK_LINES
        lines = lines[-TRACEBACK_LINES:]  # the end of a traceback has the error
    body = '\n'.join(lines)
    if len(body) > TRACEBACK_CHARS:
        cut = body[-TRACEBACK_CHARS:]
        omitted += body[:-TRACEBACK_CHARS].count('\n') + 1
        body = cut.split('\n', 1)[1] if '\n' in cut else cut
    if omitted:
        body = '… %d earlier line%s omitted …\n%s' % (omitted, '' if omitted == 1 else 's', body)
    return body


def _plural(count, word):
    return '%d %s%s' % (count, word, '' if count == 1 else 's')


def _headline(context):
    stats = context.get('test_summary') or {}
    title = html.escape(clean_text(context.get('test_report_title') or 'Test Report'), quote=False)
    total = stats.get('total') or 0
    failed, errors = stats.get('failed') or 0, stats.get('error') or 0
    if not total:
        return '### ⚠️ %s: no tests were run' % title
    if failed or errors:
        parts = []
        if failed:
            parts.append('%d failed' % failed)
        if errors:
            parts.append(_plural(errors, 'error'))
        return '### ❌ %s: %s' % (title, ', '.join(parts))
    return '### ✅ %s: all %s passed' % (title, _plural(total - (stats.get('skipped') or 0), 'test'))


def _name_list(title, names, limit, open_=False):
    if not names:
        return []
    shown = names[:limit]
    lines = ['<details%s><summary><b>%s (%d)</b></summary>' % (' open' if open_ else '', title, len(names)), '']
    lines += ['- %s' % _code(name) for name in shown]
    if len(names) > len(shown):
        lines.append('- … and %d more' % (len(names) - len(shown)))
    lines += ['', '</details>', '']
    return lines


def _comparison_lines(comparison, limit):
    base = comparison.get('baseline') or {}
    source = ' (%s)' % ', '.join(clean_text(v) for v in (base.get('source'), base.get('timestamp')) if v) \
        if base.get('source') or base.get('timestamp') else ''
    delta = comparison.get('percentage_delta')
    rate = ''
    if isinstance(base.get('percentage'), (int, float)) and isinstance(delta, (int, float)):
        rate = ': pass rate %s%% then, %+.2f pts now' % (base['percentage'], delta)
    counts = [_plural(len(comparison.get('new_failures') or []), 'new failure'),
              '%d fixed' % len(comparison.get('fixed') or []),
              '%d still failing' % len(comparison.get('still_failing') or [])]
    if comparison.get('new_tests'):
        counts.append('%d new' % len(comparison['new_tests']))
    if comparison.get('removed_tests'):
        counts.append('%d removed' % len(comparison['removed_tests']))
    if comparison.get('slower'):
        counts.append('%d slower' % len(comparison['slower']))
    lines = ['**Compared with previous run**%s%s' % (source, rate), '', ' · '.join(counts), '']
    lines += _name_list('New failures', comparison.get('new_failures') or [], limit, open_=True)
    lines += _name_list('Fixed', comparison.get('fixed') or [], limit)
    lines += _name_list('Still failing', comparison.get('still_failing') or [], limit)
    lines += _name_list('Removed tests', comparison.get('removed_tests') or [], limit)
    slower = comparison.get('slower') or []
    if slower:
        lines += ['<details><summary><b>Slower tests (%d)</b></summary>' % len(slower), '',
                  '| Test | Before | After | |', '|---|---:|---:|---:|']
        lines += ['| %s | %.3fs | %.3fs | ×%s |' % (_cell(s.get('name')), s.get('before') or 0,
                                                    s.get('after') or 0, s.get('ratio')) for s in slower]
        lines += ['', '</details>', '']
    return lines


def render_markdown(context, report_url=None):
    """
    Render a report context as GitHub-flavoured Markdown.

    Used for GitHub job summaries and pull request comments; it also reads
    fine as plain text. ``report_url`` adds a link to the full HTML report.
    """
    return _render(context, report_url, MAX_FAILURE_DETAILS, MAX_LIST_ITEMS)


def _render(context, report_url, max_failures, list_limit):
    stats = context.get('test_summary') or {}
    lines = [_headline(context), '']
    duration = context.get('duration')
    lines += ['| Total | Passed | Failed | Errors | Skipped | Pass rate | Duration |',
              '|---:|---:|---:|---:|---:|---:|---:|',
              '| %d | %d | %d | %d | %d | %s%% | %s |' % (
                  stats.get('total') or 0, stats.get('passed') or 0, stats.get('failed') or 0,
                  stats.get('error') or 0, stats.get('skipped') or 0, stats.get('percentage') or 0,
                  '%.2fs' % duration if isinstance(duration, (int, float)) else '–'), '']

    comparison = context.get('comparison')
    if comparison:
        lines += _comparison_lines(comparison, list_limit)

    results = context.get('test_results') or []
    problems = [r for r in results if isinstance(r, dict) and r.get('result') in PROBLEMS]
    groups = context.get('failure_groups')
    if groups is None:  # reports written by older pyrept versions
        groups = failure_groups(results)
    if groups:
        lines += ['#### Common failure causes', '', '| Tests | Error |', '|---:|---|']
        lines += ['| %d | %s |' % (g['count'], _cell(g['message'])) for g in groups]
        lines.append('')

    if problems and max_failures:
        changes = (comparison or {}).get('changes') or {}
        lines += ['#### Failures', '']
        for result in problems[:max_failures]:
            change = changes.get(str(result.get('name')))
            label = result.get('result') + (', %s' % change.replace('-', ' ') if change else '')
            lines += ['<details><summary><code>%s</code> (%s)</summary>' % (
                html.escape(clean_text(result.get('name'))[:MAX_NAME_LENGTH]), label), '']
            traceback = _trim(result.get('traceback') or '')
            lines += [_fenced(traceback) if traceback else '_No error details were recorded._', '', '</details>', '']
        if len(problems) > max_failures:
            lines += ['… and %d more in the full report.' % (len(problems) - max_failures), '']

    slowest = context.get('slowest_tests') or []
    if slowest:
        lines += ['<details><summary><b>Slowest tests</b></summary>', '', '| Test | Duration |', '|---|---:|']
        lines += ['| %s | %.3fs |' % (_cell(t.get('name')), t.get('duration') or 0) for t in slowest]
        lines += ['', '</details>', '']

    if report_url:
        lines += ['[Open the full report](%s)' % report_url.replace(' ', '%20').replace(')', '%29'), '']
    lines.append('<sub>Generated by [pyrept](%s) · developed by Pankaj Kumar Nayak</sub>' % PROJECT_URL)
    return '\n'.join(lines) + '\n'


def report_url_from_env(environ=None):
    environ = os.environ if environ is None else environ
    url = (environ.get(REPORT_URL_ENV) or '').strip()
    return url if url.lower().startswith(('http://', 'https://')) else None


def write_markdown(context, path, report_url=None):
    """Write the Markdown summary to ``path`` (overwriting it)."""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(render_markdown(context, report_url=report_url))
    logger.info('markdown summary generated at : %s', path)


def write_github_summary(context, report_url=None, environ=None):
    """
    Append the Markdown summary to the GitHub Actions job summary.

    Returns the summary file path, or ``None`` outside GitHub Actions (where
    ``$GITHUB_STEP_SUMMARY`` is not set) or when the file cannot be written;
    neither ever fails the test run.
    """
    environ = os.environ if environ is None else environ
    path = environ.get(GITHUB_SUMMARY_ENV)
    if not path:
        logger.info('pyrept: $%s is not set (not running in GitHub Actions); skipping the job summary',
                    GITHUB_SUMMARY_ENV)
        return None
    try:
        with open(path, 'a', encoding='utf-8') as fh:
            fh.write(render_markdown(context, report_url=report_url) + '\n')
    except OSError as exc:
        logger.warning('pyrept: cannot write the GitHub job summary: %s', exc)
        return None
    return path
