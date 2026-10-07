"""
``pyrept`` command line.

    pyrept convert --from cucumber cucumber.json --html report.html --json report.json
    pyrept convert --from playwright results.json
    pyrept convert --from junit build/test-results/*.xml --baseline previous/report.json
    pyrept summary report.json --github-summary --fail-under 95
    pyrept history history/*.json --html history.html
"""
import argparse
import json
import os
import sys

from .compare import summary_line
from .history import DEFAULT_LIMIT, build_history, expand_inputs, load_runs, write_history
from .importers import DISPLAY_NAMES, IMPORTERS
from .notify import send_notifications
from .report import DEFAULT_HTML_REPORT_PATH, DEFAULT_JSON_REPORT_PATH, ReportCollector
from .summary import (
    evaluate_gates,
    failure_groups,
    parse_fail_under,
    render_markdown,
    report_url_from_env,
    write_github_summary,
    write_markdown,
)

_GATE_OPTION_NAMES = {'fail_under': '--fail-under', 'ignore_known_failures': '--ignore-known-failures',
                      'baseline': '--baseline'}


def _percentage(value):
    try:
        return parse_fail_under(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc))


def _url(value):
    if not value.lower().startswith(('http://', 'https://')):
        raise argparse.ArgumentTypeError('must be an http(s) URL, got %r' % value)
    return value


def _add_summary_options(parser):
    parser.add_argument('--markdown', default=None, metavar='PATH', help='Also write a Markdown summary.')
    parser.add_argument('--github-summary', action='store_true',
                        help='Append the Markdown summary to the GitHub Actions job summary ($GITHUB_STEP_SUMMARY).')
    parser.add_argument('--report-url', type=_url, default=None, metavar='URL',
                        help='Link to the published HTML report, used in summaries and notifications '
                             '(default: $PYREPT_REPORT_URL).')


def _add_gate_options(parser):
    parser.add_argument('--fail-on-failure', action='store_true',
                        help='Exit with status 1 if any test failed or errored (useful in CI).')
    parser.add_argument('--ignore-known-failures', action='store_true',
                        help='With --fail-on-failure: only fail when a test fails that did not fail in the baseline.')
    parser.add_argument('--fail-under', type=_percentage, default=None, metavar='PERCENT',
                        help='Exit with status 1 if the pass rate is below PERCENT.')


def _version_text():
    try:
        from importlib.metadata import PackageNotFoundError, version
        number = version('pyrept')
    except (ImportError, PackageNotFoundError):  # pragma: no cover - running from a plain source checkout
        number = 'unknown'
    return 'pyrept %s, developed by Pankaj Kumar Nayak' % number


def build_parser():
    parser = argparse.ArgumentParser(prog='pyrept', description='Searchable HTML and JSON test reports.',
                                     epilog='Developed by Pankaj Kumar Nayak: '
                                            'https://github.com/pankajnayak1994/pyrept')
    parser.add_argument('--version', action='version', version=_version_text())
    sub = parser.add_subparsers(dest='command')
    sub.required = True

    convert = sub.add_parser('convert', help='Convert another tool\'s report into a pyrept report.')
    convert.add_argument('inputs', nargs='+',
                         help='Input report file(s) (for allure: the allure-results directory); several are merged.')
    convert.add_argument('--from', dest='source', required=True, choices=sorted(IMPORTERS),
                         help='Format of the input report(s).')
    convert.add_argument('--html', default=DEFAULT_HTML_REPORT_PATH, help='HTML output path.')
    convert.add_argument('--json', default=DEFAULT_JSON_REPORT_PATH, help='JSON output path.')
    convert.add_argument('--junit', default=None, metavar='PATH', help='Also write a JUnit XML report.')
    convert.add_argument('--baseline', default=None, metavar='PATH',
                         help='Compare with an earlier pyrept JSON report (a missing file is ignored).')
    convert.add_argument('--title', default=None, help='Report title.')
    _add_summary_options(convert)
    _add_gate_options(convert)

    summary = sub.add_parser('summary', help='Summarise a pyrept JSON report as Markdown (job summaries, PR comments).')
    summary.add_argument('report', help='A pyrept JSON report.')
    _add_summary_options(summary)
    summary.add_argument('--notify', action='store_true',
                         help='Also send the notifications configured in the environment '
                              '(PYREPT_SLACK_WEBHOOK_URL, ...).')
    _add_gate_options(summary)

    history = sub.add_parser('history', help='Trends across many pyrept JSON reports: pass rate, flaky tests, streaks.')
    history.add_argument('inputs', nargs='+', help='pyrept JSON reports, or directories of them (one report per run).')
    history.add_argument('--html', default='history.html', help='HTML output path (default: history.html).')
    history.add_argument('--json', default=None, metavar='PATH', help='Also write the history as JSON.')
    history.add_argument('--title', default='Test History', help='Page title.')
    history.add_argument('--limit', type=int, default=DEFAULT_LIMIT, metavar='N',
                         help='Use only the newest N runs (default: %d; 0 for all).' % DEFAULT_LIMIT)
    return parser


def _exit_status(context, args):
    """Apply --fail-on-failure / --ignore-known-failures / --fail-under. Returns (status, messages)."""
    stats = context['test_summary']
    problems = stats.get('failed', 0) + stats.get('error', 0)
    messages = []
    if args.ignore_known_failures and not args.fail_on_failure:
        messages.append('--ignore-known-failures has no effect without --fail-on-failure')
    gate = evaluate_gates(context, fail_under=args.fail_under,
                          ignore_known_failures=args.ignore_known_failures and args.fail_on_failure,
                          option_names=_GATE_OPTION_NAMES)
    messages += gate.messages
    tests_ok = not (args.fail_on_failure and problems)
    return (0 if gate.successful(tests_ok) else 1), messages


def _convert(args):
    display = DISPLAY_NAMES.get(args.source, args.source.capitalize())
    title = args.title or '%s Test Report' % display
    collector = ReportCollector(title=title, environment={
        'Framework': display,
        'Source': ', '.join(os.path.basename(p) for p in args.inputs)})
    loader = IMPORTERS[args.source]
    missing = [path for path in args.inputs if not os.path.exists(path)]
    if missing:
        print('pyrept: input file not found: %s' % ', '.join(missing), file=sys.stderr)
        return 2
    for path in args.inputs:
        try:
            loader(path, collector=collector)
        except (OSError, ValueError) as exc:  # unreadable file, invalid JSON, wrong report format
            print('pyrept: cannot read %s report %s: %s' % (args.source, path, exc), file=sys.stderr)
            return 2
    markdown = os.path.realpath(args.markdown) if args.markdown else None
    context = collector.write(html_path=os.path.realpath(args.html), json_path=os.path.realpath(args.json),
                              junit_path=os.path.realpath(args.junit) if args.junit else None,
                              baseline_path=os.path.realpath(args.baseline) if args.baseline else None,
                              markdown_path=markdown, github_summary=args.github_summary,
                              report_url=args.report_url)
    stats = context['test_summary']
    print('pyrept: %d tests (%d passed, %d failed, %d errors, %d skipped)' % (
        stats['total'], stats.get('passed', 0), stats.get('failed', 0),
        stats.get('error', 0), stats.get('skipped', 0)))
    print('pyrept HTML report: %s' % os.path.realpath(args.html))
    print('pyrept JSON report: %s' % os.path.realpath(args.json))
    if args.junit:
        print('pyrept JUnit report: %s' % os.path.realpath(args.junit))
    if markdown:
        print('pyrept Markdown summary: %s' % markdown)
    if context['comparison']:
        print('pyrept: %s' % summary_line(context['comparison']))
    status, messages = _exit_status(context, args)
    for message in messages:
        print('pyrept: %s' % message)
    return status


def load_report(path):
    """Read a pyrept JSON report; raises ``ValueError`` when it is not one."""
    try:
        with open(path, encoding='utf-8-sig') as fh:
            data = json.load(fh)
    except ValueError as exc:
        raise ValueError('%s is not valid JSON: %s' % (path, exc))
    if not isinstance(data, dict) or not isinstance(data.get('test_results'), list) \
            or not isinstance(data.get('test_summary'), dict):
        raise ValueError('%s is not a pyrept JSON report' % path)
    for key in ('total', 'passed', 'failed', 'error', 'skipped', 'percentage'):
        value = data['test_summary'].get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            data['test_summary'][key] = 0
    if data.get('failure_groups') is None:
        data['failure_groups'] = failure_groups(data['test_results'])
    return data


def _summary(args):
    try:
        context = load_report(args.report)
    except (OSError, ValueError) as exc:
        print('pyrept: cannot read %s: %s' % (args.report, exc), file=sys.stderr)
        return 2
    report_url = args.report_url or report_url_from_env()
    if args.markdown:
        write_markdown(context, os.path.realpath(args.markdown), report_url=report_url)
    if args.github_summary:
        write_github_summary(context, report_url=report_url)
    if not args.markdown and not args.github_summary:
        sys.stdout.write(render_markdown(context, report_url=report_url))
    if args.notify:
        send_notifications(context, report_url=report_url)
    status, messages = _exit_status(context, args)
    for message in messages:
        print('pyrept: %s' % message, file=sys.stderr)
    return status


def _history(args):
    if args.limit < 0:
        print('pyrept: --limit must be 0 or more', file=sys.stderr)
        return 2
    missing = [path for path in args.inputs if not os.path.exists(path)]
    if missing:
        print('pyrept: not found: %s' % ', '.join(missing), file=sys.stderr)
        return 2
    runs, problems = load_runs(expand_inputs(args.inputs))
    for path, reason in problems:
        print('pyrept: skipped %s: %s' % (path, reason), file=sys.stderr)
    if not runs:
        print('pyrept: no pyrept JSON reports found in %s' % ', '.join(args.inputs), file=sys.stderr)
        return 2
    context = build_history(runs, title=args.title, limit=args.limit)
    html = os.path.realpath(args.html)
    json_path = os.path.realpath(args.json) if args.json else None
    write_history(context, html_path=html, json_path=json_path)
    sm = context['summary']
    print('pyrept: %d runs, %d tests, %d flaky, %d failing now'
          % (sm['runs'], sm['tests'], sm['flaky'], sm['failing_now']))
    print('pyrept history HTML: %s' % html)
    if json_path:
        print('pyrept history JSON: %s' % json_path)
    return 0


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.command == 'convert':
        return _convert(args)
    if args.command == 'summary':
        return _summary(args)
    if args.command == 'history':
        return _history(args)
    return 0  # pragma: no cover - argparse rejects unknown commands


if __name__ == '__main__':  # pragma: no cover
    sys.exit(main())
