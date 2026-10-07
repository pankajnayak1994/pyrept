import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest

from pyrept.cli import main
from pyrept.history import build_history, expand_inputs, load_runs

P, F, E, S = 'passed', 'failed', 'error', 'skipped'


def _report(day, results, flaky=()):
    return {'test_report_title': 'Nightly', 'timestamp': '2026/09/%02d 02:00:00 UTC' % day,
            'test_summary': {'total': len(results)}, 'duration': 10.0 + day,
            'test_results': [{'name': n, 'result': r,
                              'metadata': {'duration': 1.0 + day / 10.0, 'flaky': n in flaky}}
                             for n, r in results.items()]}


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)

    def _write(self, name, data):
        path = os.path.join(self.tmp, name)
        with open(path, 'w', encoding='utf-8') as fh:
            if isinstance(data, str):
                fh.write(data)
            else:
                json.dump(data, fh)
        return path

    def _history(self, outcomes_per_run, **kwargs):
        """outcomes_per_run: {test: 'PFF.P'} with one letter per run, '.' = not run."""
        letters = {'P': P, 'F': F, 'E': E, 'S': S}
        runs = len(next(iter(outcomes_per_run.values())))
        for day in range(runs):
            results = {name: letters[o[day]] for name, o in outcomes_per_run.items() if o[day] != '.'}
            # written out of order: history must sort by timestamp, not by file name
            self._write('z%02d.json' % (runs - day), _report(day + 1, results, **kwargs))
        loaded, problems = load_runs(expand_inputs([self.tmp]))
        self.assertEqual(problems, [])
        return build_history(loaded)

    def test_flaky_needs_two_separate_failing_stretches(self):
        h = self._history({'flaky': 'PFPPFP', 'regression': 'PPFFPP', 'broken': 'PPPPFF', 'stable': 'PPPPPP',
                           'skips': 'PFSFPP'})
        self.assertEqual([t['name'] for t in h['flaky_tests']], ['flaky'])
        flaky = h['flaky_tests'][0]
        self.assertEqual((flaky['flips'], flaky['failing_stretches'], flaky['failure_rate']), (4, 2, 33.3))
        # skips are ignored, so F S F is one stretch
        self.assertNotIn('skips', [t['name'] for t in h['flaky_tests']])

    def test_retried_tests_are_flaky_even_without_failures(self):
        h = self._history({'retried': 'PPP', 'other': 'PPP'}, flaky=('retried',))
        self.assertEqual([t['name'] for t in h['flaky_tests']], ['retried'])

    def test_failure_streaks(self):
        h = self._history({'broken': 'PPFF', 'gap': 'PF.F', 'old': 'FFPP', 'removed': 'PFF.', 'always': 'EEEE'})
        streaks = {t['name']: (t['streak'], t['since']) for t in h['failure_streaks']}
        self.assertEqual(streaks, {'always': (4, '2026/09/01 02:00:00 UTC'),
                                   'broken': (2, '2026/09/03 02:00:00 UTC'),
                                   'gap': (2, '2026/09/02 02:00:00 UTC')})
        self.assertEqual(h['summary']['failing_now'], 3)
        self.assertEqual(h['failure_streaks'][0]['name'], 'always')

    def test_runs_summary_and_limit(self):
        h = self._history({'a': 'PPPF', 'b': 'PPSP'})
        self.assertEqual([r['percentage'] for r in h['runs']], [100.0, 100.0, 100.0, 50.0])
        self.assertEqual(h['runs'][0]['timestamp'], '2026/09/01 02:00:00 UTC')
        self.assertEqual(h['summary']['percentage_change'], -50.0)
        self.assertEqual(h['summary']['runs'], 4)
        self.assertEqual(h['most_failing'][0]['name'], 'a')
        self.assertEqual(h['slowest_tests'][0]['max'], 1.4)
        loaded, _ = load_runs(expand_inputs([self.tmp]))
        limited = build_history(loaded, limit=2)
        self.assertEqual(len(limited['runs']), 2)
        self.assertEqual(limited['runs'][-1]['timestamp'], '2026/09/04 02:00:00 UTC')
        self.assertEqual(len(limited['most_failing'][0]['outcomes']), 2)

    def test_bad_files_are_reported_not_fatal(self):
        self._write('good.json', _report(1, {'a': P}))
        self._write('broken.json', '{nope')
        self._write('other.json', {'suites': []})
        self._write('notes.txt', 'ignored: not json')
        runs, problems = load_runs(expand_inputs([self.tmp]))
        self.assertEqual(len(runs), 1)
        self.assertEqual(sorted(os.path.basename(p) for p, _ in problems), ['broken.json', 'other.json'])

    def test_expand_inputs_dedupes(self):
        path = self._write('a.json', _report(1, {'a': P}))
        self.assertEqual(expand_inputs([path, self.tmp, path]), [path])

    def test_missing_timestamp_uses_file_time(self):
        data = _report(1, {'a': P})
        del data['timestamp']
        self._write('a.json', data)
        runs, _ = load_runs(expand_inputs([self.tmp]))
        self.assertEqual(len(build_history(runs)['runs']), 1)

    def test_empty_history_context(self):
        h = build_history([])
        self.assertEqual(h['summary']['runs'], 0)
        self.assertIsNone(h['summary']['percentage_change'])


class HistoryCommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.dir = os.path.join(self.tmp, 'history')
        os.makedirs(self.dir)
        for day, outcome in enumerate((P, F, P, F, F), 1):
            with open(os.path.join(self.dir, 'run-%d.json' % day), 'w', encoding='utf-8') as fh:
                json.dump(_report(day, {'tests/test_a.py::test_x': outcome, 'tests/test_a.py::test_<y>': P}), fh)

    def _run(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_writes_html_and_json(self):
        html = os.path.join(self.tmp, 'out', 'history.html')
        jsn = os.path.join(self.tmp, 'out', 'history.json')
        code, out, _ = self._run('history', self.dir, '--html', html, '--json', jsn, '--title', 'Nightly <trend>')
        self.assertEqual(code, 0)
        self.assertIn('pyrept: 5 runs, 2 tests, 1 flaky, 1 failing now', out)
        with open(html, encoding='utf-8') as fh:
            page = fh.read()
        self.assertIn('Nightly &lt;trend&gt;', page)
        self.assertIn('tests/test_a.py::test_&lt;y&gt;', page)
        self.assertNotIn('test_<y>', page)
        self.assertIn('Pass rate over time', page)
        self.assertNotIn('cdnjs', page)
        with open(jsn, encoding='utf-8') as fh:
            self.assertEqual(json.load(fh)['summary']['runs'], 5)

    def test_single_run_renders(self):
        html = os.path.join(self.tmp, 'one.html')
        code, _, _ = self._run('history', os.path.join(self.dir, 'run-1.json'), '--html', html)
        self.assertEqual(code, 0)
        with open(html, encoding='utf-8') as fh:
            self.assertIn('1 run ·', fh.read())

    def test_errors(self):
        self.assertEqual(self._run('history', os.path.join(self.tmp, 'missing'))[0], 2)
        empty = os.path.join(self.tmp, 'empty')
        os.makedirs(empty)
        code, _, err = self._run('history', empty, '--html', os.path.join(self.tmp, 'x.html'))
        self.assertEqual(code, 2)
        self.assertIn('no pyrept JSON reports', err)
        self.assertEqual(self._run('history', self.dir, '--limit', '-1')[0], 2)
        with open(os.path.join(self.dir, 'junk.json'), 'w') as fh:
            fh.write('[1, 2]')
        code, _, err = self._run('history', self.dir, '--html', os.path.join(self.tmp, 'y.html'))
        self.assertEqual(code, 0)
        self.assertIn('skipped', err)
