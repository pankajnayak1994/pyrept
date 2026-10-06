import json
import unittest

from pyrept.report import build_context, generate_search_terms, record_outcome, new_summary_stats


class ReportTests(unittest.TestCase):
    def test_search_terms_when_token_matches_a_test_name(self):
        # A docstring token equal to another test's name used to crash with
        # "'str' object has no attribute 'append'".
        results = [
            {'name': 'test_a', 'description': 'see test_b', 'result': 'passed'},
            {'name': 'test_b', 'description': None, 'result': 'passed'},
        ]
        terms = generate_search_terms(results)
        self.assertEqual(sorted(terms['test_b']), ['test_a', 'test_b'])
        self.assertEqual(terms['see'], ['test_a'])

    def test_build_context_percentage_and_sorting(self):
        stats, results = new_summary_stats(), []
        record_outcome(stats, results, 'b_test', 'passed')
        record_outcome(stats, results, 'a_test', 'failed', traceback='boom')
        ctx = build_context(stats, results)
        self.assertEqual(ctx['test_summary']['percentage'], 50.0)
        self.assertEqual([r['name'] for r in ctx['test_results']], ['a_test', 'b_test'])
        json.loads(ctx['autocomplete_terms'])


class CollectorAndTemplateTests(unittest.TestCase):
    def test_rejects_unknown_outcome(self):
        from pyrept.report import ReportCollector
        with self.assertRaises(ValueError):
            ReportCollector().add('x', 'exploded')

    def test_pass_rate_excludes_skipped_and_problems_sort_first(self):
        stats, results = new_summary_stats(), []
        record_outcome(stats, results, 'a', 'passed')
        record_outcome(stats, results, 'b', 'skipped')
        record_outcome(stats, results, 'c', 'error')
        ctx = build_context(stats, results)
        self.assertEqual(ctx['test_summary']['percentage'], 50.0)
        self.assertEqual([r['name'] for r in ctx['test_results']], ['c', 'b', 'a'])

    def test_html_is_escaped_and_self_contained(self):
        import os
        import tempfile
        from pyrept.report import ReportCollector, make_attachment
        tmp = tempfile.mkdtemp()
        c = ReportCollector(title='T <1>')
        c.add('test_<script>', 'failed', traceback='<b>boom</b>',
              attachments=[make_attachment('shot', 'image/png', data=b'\x89PNG')])
        c.write(os.path.join(tmp, 'r.html'), os.path.join(tmp, 'r.json'))
        with open(os.path.join(tmp, 'r.html'), encoding='utf-8') as fh:
            html = fh.read()
        self.assertIn('test_&lt;script&gt;', html)
        self.assertIn('&lt;b&gt;boom&lt;/b&gt;', html)
        self.assertIn('data:image/png;base64,iVBORw==', html)
        self.assertNotIn('cdnjs', html)  # no external assets: works offline / in CI artifacts
