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
