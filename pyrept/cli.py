"""
``pyrept`` command line.

    pyrept convert --from cucumber cucumber.json --html report.html --json report.json
    pyrept convert --from playwright results.json
"""
import argparse
import os
import sys

from .importers import IMPORTERS
from .report import DEFAULT_HTML_REPORT_PATH, DEFAULT_JSON_REPORT_PATH, ReportCollector


def build_parser():
    parser = argparse.ArgumentParser(prog='pyrept', description='Searchable HTML and JSON test reports.')
    sub = parser.add_subparsers(dest='command')
    sub.required = True

    convert = sub.add_parser('convert', help='Convert another tool\'s JSON report into a pyrept report.')
    convert.add_argument('inputs', nargs='+', help='Input report file(s); several files are merged.')
    convert.add_argument('--from', dest='source', required=True, choices=sorted(IMPORTERS),
                         help='Format of the input report(s).')
    convert.add_argument('--html', default=DEFAULT_HTML_REPORT_PATH, help='HTML output path.')
    convert.add_argument('--json', default=DEFAULT_JSON_REPORT_PATH, help='JSON output path.')
    convert.add_argument('--title', default=None, help='Report title.')
    convert.add_argument('--fail-on-failure', action='store_true',
                         help='Exit with status 1 if any test failed or errored (useful in CI).')
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.command == 'convert':
        title = args.title or '%s Test Report' % args.source.capitalize()
        collector = ReportCollector(title=title, environment={
            'Framework': args.source.capitalize(),
            'Source': ', '.join(os.path.basename(p) for p in args.inputs)})
        loader = IMPORTERS[args.source]
        missing = [path for path in args.inputs if not os.path.isfile(path)]
        if missing:
            print('pyrept: input file not found: %s' % ', '.join(missing), file=sys.stderr)
            return 2
        for path in args.inputs:
            try:
                loader(path, collector=collector)
            except (OSError, ValueError) as exc:  # unreadable file, invalid JSON, wrong report format
                print('pyrept: cannot read %s report %s: %s' % (args.source, path, exc), file=sys.stderr)
                return 2
        context = collector.write(html_path=os.path.realpath(args.html), json_path=os.path.realpath(args.json))
        stats = context['test_summary']
        print('pyrept: %d tests (%d passed, %d failed, %d errors, %d skipped)' % (
            stats['total'], stats.get('passed', 0), stats.get('failed', 0),
            stats.get('error', 0), stats.get('skipped', 0)))
        print('pyrept HTML report: %s' % os.path.realpath(args.html))
        print('pyrept JSON report: %s' % os.path.realpath(args.json))
        if args.fail_on_failure and (stats.get('failed', 0) or stats.get('error', 0)):
            return 1
    return 0


if __name__ == '__main__':  # pragma: no cover
    sys.exit(main())
