import json
import logging
import os
import shutil
import tempfile
import unittest

from pyrept.compare import compare, load_baseline, summary_line
from pyrept.report import ReportCollector


def _result(name, outcome, duration=None):
    return {'name': name, 'result': outcome, 'description': None, 'traceback': None,
            'metadata': {} if duration is None else {'duration': duration}}


def _baseline(*results, percentage=50.0):
    return {'_source': '/x/prev.json', 'timestamp': '2026/10/01 10:00:00 UTC', 'test_report_title': 'Prev',
            'test_summary': {'total': len(results), 'percentage': percentage}, 'test_results': list(results)}


class CompareTests(unittest.TestCase):
    def test_no_baseline(self):
        self.assertIsNone(compare([_result('a', 'passed')], None))
        self.assertIsNone(summary_line(None))

    def test_classification(self):
        baseline = _baseline(
            _result('stays_green', 'passed'),
            _result('breaks', 'passed'),
            _result('breaks_from_skip', 'skipped'),
            _result('gets_fixed', 'failed'),
            _result('error_fixed', 'error'),
            _result('still_bad', 'error'),
            _result('bad_now_skipped', 'failed'),
            _result('deleted', 'passed'),
        )
        now = [
            _result('stays_green', 'passed'),
            _result('breaks', 'failed'),
            _result('breaks_from_skip', 'error'),
            _result('gets_fixed', 'passed'),
            _result('error_fixed', 'passed'),
            _result('still_bad', 'failed'),
            _result('bad_now_skipped', 'skipped'),
            _result('brand_new_ok', 'passed'),
            _result('brand_new_bad', 'failed'),
        ]
        c = compare(now, baseline, current_percentage=60.0)
        self.assertEqual(c['new_failures'], ['brand_new_bad', 'breaks', 'breaks_from_skip'])
        self.assertEqual(c['fixed'], ['error_fixed', 'gets_fixed'])
        self.assertEqual(c['still_failing'], ['still_bad'])
        self.assertEqual(c['new_tests'], ['brand_new_bad', 'brand_new_ok'])
        self.assertEqual(c['removed_tests'], ['deleted'])
        self.assertEqual(c['changes'], {
            'breaks': 'new-failure', 'breaks_from_skip': 'new-failure', 'brand_new_bad': 'new-failure',
            'gets_fixed': 'fixed', 'error_fixed': 'fixed', 'still_bad': 'still-failing', 'brand_new_ok': 'new'})
        self.assertNotIn('stays_green', c['changes'])
        self.assertNotIn('bad_now_skipped', c['changes'])  # neither fixed nor failing
        self.assertEqual(c['percentage_delta'], 10.0)
        self.assertEqual(c['baseline'], {'source': 'prev.json', 'title': 'Prev',
                                         'timestamp': '2026/10/01 10:00:00 UTC', 'percentage': 50.0,
                                         'total': 8})

    def test_slower_tests_ignore_noise(self):
        baseline = _baseline(_result('much_slower', 'passed', 1.0), _result('tiny_jump', 'passed', 0.01),
                             _result('small_ratio', 'passed', 10.0), _result('faster', 'passed', 5.0),
                             _result('no_old_time', 'passed'), _result('zero_old', 'passed', 0),
                             _result('slower_x4', 'passed', 1.0))
        now = [_result('much_slower', 'passed', 2.0), _result('tiny_jump', 'passed', 0.4),
               _result('small_ratio', 'passed', 14.0), _result('faster', 'passed', 1.0),
               _result('no_old_time', 'passed', 9.0), _result('zero_old', 'passed', 9.0),
               _result('slower_x4', 'failed', 4.0)]
        slower = compare(now, baseline)['slower']
        self.assertEqual([s['name'] for s in slower], ['slower_x4', 'much_slower'])
        self.assertEqual(slower[1], {'name': 'much_slower', 'before': 1.0, 'after': 2.0, 'ratio': 2.0})

    def test_slower_list_is_capped(self):
        baseline = _baseline(*[_result('t%02d' % i, 'passed', 1.0) for i in range(25)])
        now = [_result('t%02d' % i, 'passed', 2.0 + i) for i in range(25)]
        slower = compare(now, baseline)['slower']
        self.assertEqual(len(slower), 10)
        self.assertEqual(slower[0]['name'], 't24')

    def test_malformed_baseline_entries_are_tolerated(self):
        baseline = {'test_results': [None, 'x', {'no_name': 1}, {'name': 7, 'result': 'failed'}],
                    'test_summary': 'broken'}
        c = compare([_result('7', 'passed')], baseline, current_percentage=100.0)
        self.assertEqual(c['fixed'], ['7'])
        self.assertIsNone(c['percentage_delta'])
        self.assertIsNone(c['baseline']['percentage'])

    def test_summary_line(self):
        c = compare([_result('a', 'failed'), _result('b', 'passed')],
                    _baseline(_result('a', 'passed'), _result('c', 'passed')))
        self.assertEqual(summary_line(c), '1 new failure, 0 fixed, 0 still failing, 1 new, 1 removed (vs prev.json)')
        c = compare([_result('a', 'failed'), _result('b', 'failed')], {'test_results': []})
        self.assertEqual(summary_line(c), '2 new failures, 0 fixed, 0 still failing, 2 new (vs baseline)')
        c = compare([_result('a', 'passed', 3.0)], _baseline(_result('a', 'passed', 1.0)))
        self.assertEqual(summary_line(c), '0 new failures, 0 fixed, 0 still failing, 1 slower (vs prev.json)')


class LoadBaselineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)

    def _write(self, content, encoding='utf-8'):
        path = os.path.join(self.tmp, 'b.json')
        with open(path, 'w', encoding=encoding) as fh:
            fh.write(content)
        return path

    def test_missing_or_invalid_baselines_are_skipped_with_a_warning(self):
        self.assertIsNone(load_baseline(None))
        self.assertIsNone(load_baseline(''))
        for path in (os.path.join(self.tmp, 'missing.json'), self._write('{not json'), self._write('[1, 2]'),
                     self._write('{"test_results": "nope"}'), self.tmp):
            with self.assertLogs('pyrept.compare', level=logging.WARNING):
                self.assertIsNone(load_baseline(path), path)

    def test_valid_baseline_with_bom(self):
        path = self._write(json.dumps({'test_results': []}), encoding='utf-8-sig')
        self.assertEqual(load_baseline(path), {'test_results': [], '_source': path})


class BaselineReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.html = os.path.join(self.tmp, 'r.html')
        self.json = os.path.join(self.tmp, 'r.json')

    def _run(self, outcomes, baseline=None):
        c = ReportCollector(title='Run')
        for name, outcome in outcomes.items():
            c.add(name, outcome)
        context = c.write(self.html, self.json, baseline_path=baseline)
        with open(self.html, encoding='utf-8') as fh:
            return context, fh.read()

    def test_same_file_baseline_and_html(self):
        context, html = self._run({'a': 'passed', 'b': 'passed'}, baseline=self.json)  # first run: no file yet
        self.assertIsNone(context['comparison'])
        self.assertNotIn('Compared with previous run', html)
        self.assertNotIn('data-filter="new-failure"', html)

        context, html = self._run({'a': 'failed', 'b': 'passed', '<new>': 'passed'}, baseline=self.json)
        self.assertEqual(context['comparison']['new_failures'], ['a'])
        self.assertIn('Compared with previous run', html)
        self.assertIn('data-filter="new-failure"', html)
        self.assertIn('data-change="new-failure"', html)
        self.assertIn('<span class="change c-new">new</span>', html)
        self.assertIn('&lt;new&gt;', html)
        self.assertNotIn('<new>', html)
        self.assertIn('-33.33 pts', html)  # 66.67% now vs 100% before
        with open(self.json, encoding='utf-8') as fh:
            saved = json.load(fh)
        self.assertEqual(saved['comparison']['changes'], {'a': 'new-failure', '<new>': 'new'})

        context, html = self._run({'a': 'passed', 'b': 'passed'}, baseline=self.json)
        self.assertEqual(context['comparison']['fixed'], ['a'])
        self.assertEqual(context['comparison']['removed_tests'], ['<new>'])
        self.assertIn('+33.33 pts', html)

    def test_long_lists_are_truncated_in_html(self):
        with open(self.json, 'w', encoding='utf-8') as fh:
            json.dump({'test_results': []}, fh)
        _, html = self._run({'t%03d' % i: 'failed' for i in range(250)}, baseline=self.json)
        self.assertIn('… 50 more', html)
