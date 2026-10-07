import os
import shutil
import tempfile
import unittest

from pyrept.report import ReportCollector, build_context, new_summary_stats, record_outcome
from pyrept.summary import (
    _code,
    _cell,
    _fenced,
    _trim,
    evaluate_gates,
    failure_groups,
    failure_message,
    parse_fail_under,
    render_markdown,
    report_url_from_env,
    write_github_summary,
    write_markdown,
)

PYTEST_TB = '''def test_pay():
>       assert total == 85
E       assert 90 == 85
E        +  where 90 = total

tests/test_pay.py:12: AssertionError'''


def _context(results, baseline=None, title='Suite'):
    stats, collected = new_summary_stats(), []
    for name, outcome, traceback in results:
        record_outcome(stats, collected, name, outcome, traceback=traceback, metadata={'duration': 0.5})
    return build_context(stats, collected, title=title, baseline=baseline)


class FailureMessageTests(unittest.TestCase):
    def test_pytest_e_line_wins(self):
        self.assertEqual(failure_message(PYTEST_TB), 'assert 90 == 85')

    def test_last_exception_line_of_python_traceback(self):
        tb = 'Traceback (most recent call last):\n  File "x.py", line 1\nKeyError: a\nValueError: bad'
        self.assertEqual(failure_message(tb), 'ValueError: bad')

    def test_ansi_codes_and_empty(self):
        self.assertEqual(failure_message('\x1b[31mE   assert 1 == 2\x1b[0m'), 'assert 1 == 2')
        self.assertEqual(failure_message(None), '')
        self.assertEqual(failure_message('   \n  '), '')

    def test_falls_back_to_first_line_and_truncates(self):
        self.assertEqual(failure_message('Timeout after 30s\nmore'), 'Timeout after 30s')
        self.assertEqual(len(failure_message('x' * 1000)), 300)


class FailureGroupTests(unittest.TestCase):
    def test_groups_shared_messages_largest_first(self):
        results = [{'name': 't%d' % i, 'result': 'error', 'traceback': 'ConnectionError: redis down'}
                   for i in range(3)]
        results += [{'name': 'a', 'result': 'failed', 'traceback': PYTEST_TB},
                    {'name': 'b', 'result': 'failed', 'traceback': PYTEST_TB},
                    {'name': 'c', 'result': 'failed', 'traceback': 'unique failure'},
                    {'name': 'p', 'result': 'passed', 'traceback': PYTEST_TB},
                    {'name': 's', 'result': 'skipped', 'traceback': 'Skipped: later'}]
        groups = failure_groups(results)
        self.assertEqual([(g['count'], g['message']) for g in groups],
                         [(3, 'ConnectionError: redis down'), (2, 'assert 90 == 85')])
        self.assertEqual(groups[1]['tests'], ['a', 'b'])

    def test_memory_addresses_are_ignored(self):
        results = [{'name': n, 'result': 'error', 'traceback': 'TypeError: <Foo object at 0x7f%s>' % addr}
                   for n, addr in (('a', '1234abcd'), ('b', '99887766'))]
        self.assertEqual(failure_groups(results)[0]['count'], 2)

    def test_limit_and_junk(self):
        results = [{'name': '%s%d' % (m, i), 'result': 'failed', 'traceback': 'Error%d: x' % m}
                   for m in range(15) for i in range(2)]
        results += ['not a dict', {'name': 'x', 'result': 'failed', 'traceback': None}]
        self.assertEqual(len(failure_groups(results)), 10)
        self.assertEqual(failure_groups([]), [])

    def test_context_has_groups(self):
        ctx = _context([('a', 'failed', 'boom'), ('b', 'failed', 'boom'), ('c', 'passed', None)])
        self.assertEqual(ctx['failure_groups'], [{'message': 'boom', 'count': 2, 'tests': ['a', 'b']}])


class MarkdownEscapingTests(unittest.TestCase):
    def test_code_span_survives_backticks_and_newlines(self):
        self.assertEqual(_code('plain'), '`plain`')
        self.assertEqual(_code('has `tick`'), '`` has `tick` ``')
        self.assertEqual(_code('a ``b`` c'), '```a ``b`` c```')
        self.assertEqual(_code('`edge`'), '`` `edge` ``')
        self.assertEqual(_code('two\nlines'), '`two lines`')
        self.assertTrue(_code('x' * 1000).endswith('…`'))

    def test_table_cells_escape_pipes(self):
        self.assertEqual(_cell('test[a|b]'), '`test[a\\|b]`')

    def test_fence_longer_than_content(self):
        self.assertTrue(_fenced('code ``` inside').startswith('````text\n'))
        self.assertTrue(_fenced('plain').startswith('```text\n'))

    def test_trim_keeps_the_end(self):
        text = '\n'.join('line %d' % i for i in range(100))
        trimmed = _trim(text)
        self.assertTrue(trimmed.startswith('… 60 earlier lines omitted …'))
        self.assertTrue(trimmed.endswith('line 99'))
        long_line = 'y' * 10000
        self.assertLessEqual(len(_trim('first\n' + long_line)), 4100)
        self.assertEqual(_trim('short'), 'short')


class RenderMarkdownTests(unittest.TestCase):
    def test_all_passed(self):
        md = render_markdown(_context([('a', 'passed', None), ('b', 'skipped', 'Skipped: x')]))
        self.assertIn('### ✅ Suite: all 1 test passed', md)
        self.assertIn('| 2 | 1 | 0 | 0 | 1 | 100.0% | 1.00s |', md)
        self.assertNotIn('#### Failures', md)
        self.assertIn('Generated by [pyrept]', md)
        self.assertIn('developed by Pankaj Kumar Nayak', md)

    def test_no_tests(self):
        self.assertIn('no tests were run', render_markdown(_context([])))

    def test_failures_comparison_groups_and_link(self):
        baseline = {'test_results': [{'name': 'old', 'result': 'passed'}, {'name': 'a', 'result': 'passed'},
                                     {'name': 'gone', 'result': 'passed'}],
                    'test_summary': {'percentage': 100.0}, '_source': 'prev.json', 'timestamp': 'T0'}
        ctx = _context([('a', 'failed', PYTEST_TB), ('b', 'error', PYTEST_TB), ('old', 'passed', None)],
                       baseline=baseline, title='<Nightly>')
        md = render_markdown(ctx, report_url='https://example.com/r (1).html')
        self.assertIn('### ❌ &lt;Nightly&gt;: 1 failed, 1 error', md)
        self.assertIn('**Compared with previous run** (prev.json, T0): pass rate 100.0% then, -66.67 pts now', md)
        self.assertIn('2 new failures · 0 fixed · 0 still failing · 1 new · 1 removed', md)
        self.assertIn('<details open><summary><b>New failures (2)</b></summary>', md)
        self.assertIn('| 2 | `assert 90 == 85` |', md)
        self.assertIn('<summary><code>a</code> (failed, new failure)</summary>', md)
        self.assertIn('```text\n', md)
        self.assertIn('[Open the full report](https://example.com/r%20(1%29.html)', md)

    def test_failure_details_are_capped(self):
        ctx = _context([('t%02d' % i, 'failed', 'boom %d' % i) for i in range(25)])
        md = render_markdown(ctx)
        self.assertEqual(md.count('<summary><code>'), 20)
        self.assertIn('… and 5 more in the full report.', md)

    def test_html_in_test_names_is_escaped(self):
        md = render_markdown(_context([('test_<script>', 'failed', 'x')]))
        self.assertIn('<code>test_&lt;script&gt;</code>', md)

    def test_huge_reports_stay_under_the_github_limit(self):
        huge = '\n'.join('ж' * 3990 for _ in range(60))  # multi-byte characters
        ctx = _context([('t%04d' % i + 'ж' * 400, 'failed', huge + str(i)) for i in range(400)],
                       baseline={'test_results': [], 'test_summary': {}})
        md = render_markdown(ctx)
        self.assertLess(len(md.encode('utf-8')), 250 * 1024)  # GitHub's limit is 1 MiB
        self.assertIn('Compared with previous run', md)

    def test_old_reports_without_groups(self):
        ctx = _context([('a', 'failed', 'same'), ('b', 'failed', 'same')])
        del ctx['failure_groups']
        self.assertIn('Common failure causes', render_markdown(ctx))

    def test_slowest_tests_table(self):
        md = render_markdown(_context([('a|b', 'passed', None)]))
        self.assertIn('| `a\\|b` | 0.500s |', md)


class GateTests(unittest.TestCase):
    def test_parse_fail_under(self):
        self.assertIsNone(parse_fail_under(None))
        self.assertIsNone(parse_fail_under('  '))
        self.assertEqual(parse_fail_under('95.5'), 95.5)
        self.assertEqual(parse_fail_under(0), 0.0)
        for bad in ('abc', '101', -1, [1]):
            with self.assertRaises(ValueError):
                parse_fail_under(bad)

    def test_fail_under(self):
        ctx = _context([('a', 'passed', None), ('b', 'failed', 'x')])
        gate = evaluate_gates(ctx, fail_under=60)
        self.assertTrue(gate.below_threshold)
        self.assertFalse(gate.successful(True))
        self.assertIn('pass rate 50.0% is below fail-under=60', gate.messages[0])
        self.assertTrue(evaluate_gates(ctx, fail_under=50).successful(True))
        self.assertIn('fail-under=99.5', evaluate_gates(ctx, fail_under=99.5).messages[0])

    def test_ignore_known_failures(self):
        baseline = {'test_results': [{'name': 'b', 'result': 'failed'}], 'test_summary': {}}
        known = _context([('a', 'passed', None), ('b', 'failed', 'x')], baseline=baseline)
        gate = evaluate_gates(known, ignore_known_failures=True)
        self.assertTrue(gate.known_failures_only)
        self.assertTrue(gate.successful(False))
        self.assertIn('1 known failure ignored', gate.messages[0])

        new = _context([('a', 'failed', 'x'), ('b', 'failed', 'x')], baseline=baseline)
        gate = evaluate_gates(new, ignore_known_failures=True)
        self.assertFalse(gate.successful(False))
        self.assertIn('1 new failure, so ignore-known-failures does not apply', gate.messages[0])

        no_baseline = _context([('b', 'failed', 'x')])
        gate = evaluate_gates(no_baseline, ignore_known_failures=True,
                              option_names={'baseline': '--pyrept-baseline'})
        self.assertFalse(gate.successful(False))
        self.assertIn('needs a --pyrept-baseline report', gate.messages[0])

    def test_threshold_beats_known_failures(self):
        baseline = {'test_results': [{'name': 'b', 'result': 'failed'}], 'test_summary': {}}
        ctx = _context([('a', 'passed', None), ('b', 'failed', 'x')], baseline=baseline)
        self.assertFalse(evaluate_gates(ctx, fail_under=90, ignore_known_failures=True).successful(False))

    def test_fail_under_with_nothing_executed(self):
        gate = evaluate_gates(_context([('a', 'skipped', None)]), fail_under=90)
        self.assertFalse(gate.below_threshold)
        self.assertIn('no tests were executed', gate.messages[0])
        self.assertFalse(evaluate_gates(_context([]), fail_under=90).below_threshold)

    def test_nothing_to_do(self):
        gate = evaluate_gates(_context([('a', 'passed', None)]), ignore_known_failures=True)
        self.assertEqual(gate.messages, [])
        self.assertTrue(gate.successful(True))
        self.assertFalse(gate.successful(False))


class WriterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.ctx = _context([('a', 'failed', 'boom')])

    def test_write_markdown_creates_directories(self):
        path = os.path.join(self.tmp, 'deep', 'dir', 'summary.md')
        write_markdown(self.ctx, path)
        with open(path, encoding='utf-8') as fh:
            self.assertIn('❌ Suite', fh.read())

    def test_github_summary_appends(self):
        path = os.path.join(self.tmp, 'step_summary.md')
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write('existing\n')
        env = {'GITHUB_STEP_SUMMARY': path}
        self.assertEqual(write_github_summary(self.ctx, environ=env), path)
        write_github_summary(self.ctx, environ=env)
        with open(path, encoding='utf-8') as fh:
            text = fh.read()
        self.assertTrue(text.startswith('existing\n'))
        self.assertEqual(text.count('❌ Suite'), 2)

    def test_github_summary_outside_actions_and_unwritable(self):
        self.assertIsNone(write_github_summary(self.ctx, environ={}))
        env = {'GITHUB_STEP_SUMMARY': os.path.join(self.tmp, 'missing-dir', 'x.md')}
        with self.assertLogs('pyrept.summary', 'WARNING'):
            self.assertIsNone(write_github_summary(self.ctx, environ=env))

    def test_report_url_from_env(self):
        self.assertEqual(report_url_from_env({'PYREPT_REPORT_URL': ' https://x/r.html '}), 'https://x/r.html')
        self.assertIsNone(report_url_from_env({'PYREPT_REPORT_URL': 'javascript:alert(1)'}))
        self.assertIsNone(report_url_from_env({}))

    def test_collector_writes_markdown_and_github_summary(self):
        summary_file = os.path.join(self.tmp, 'gh.md')
        os.environ['GITHUB_STEP_SUMMARY'] = summary_file  # cleared again by the conftest fixture
        try:
            c = ReportCollector(title='API')
            c.add('t', 'passed')
            c.write(os.path.join(self.tmp, 'r.html'), os.path.join(self.tmp, 'r.json'),
                    markdown_path=os.path.join(self.tmp, 'md', 's.md'), github_summary=True,
                    report_url='https://ci.example/r.html')
        finally:
            del os.environ['GITHUB_STEP_SUMMARY']
        for path in (os.path.join(self.tmp, 'md', 's.md'), summary_file):
            with open(path, encoding='utf-8') as fh:
                text = fh.read()
            self.assertIn('✅ API: all 1 test passed', text)
            self.assertIn('https://ci.example/r.html', text)

    def test_html_report_shows_failure_groups(self):
        c = ReportCollector()
        c.add('a', 'error', traceback='ConnectionError: <redis>')
        c.add('b', 'error', traceback='ConnectionError: <redis>')
        html_path = os.path.join(self.tmp, 'r.html')
        c.write(html_path, os.path.join(self.tmp, 'r.json'))
        with open(html_path, encoding='utf-8') as fh:
            html = fh.read()
        self.assertIn('Common failure causes', html)
        self.assertIn('ConnectionError: &lt;redis&gt;', html)
