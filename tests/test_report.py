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


def _render(collector):
    import os
    import shutil
    import tempfile
    tmp = tempfile.mkdtemp()
    try:
        collector.write(os.path.join(tmp, 'r.html'), os.path.join(tmp, 'r.json'))
        with open(os.path.join(tmp, 'r.html'), encoding='utf-8') as fh:
            html = fh.read()
        with open(os.path.join(tmp, 'r.json'), encoding='utf-8') as fh:
            data = json.load(fh)
    finally:
        shutil.rmtree(tmp)
    return html, data


class MakeAttachmentTests(unittest.TestCase):
    def setUp(self):
        import shutil
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)

    def _file(self, name, content):
        import os
        path = os.path.join(self.tmp, name)
        with open(path, 'wb') as fh:
            fh.write(content)
        return path

    def test_bytes_are_base64_encoded(self):
        from pyrept.report import make_attachment
        a = make_attachment('shot', 'image/png', data=b'\x89PNG')
        self.assertEqual(a, {'name': 'shot', 'content_type': 'image/png', 'data': 'iVBORw=='})

    def test_small_image_path_is_embedded_and_type_guessed(self):
        from pyrept.report import make_attachment
        path = self._file('s.png', b'\x89PNG')
        a = make_attachment('shot', path=path)
        self.assertEqual(a['content_type'], 'image/png')
        self.assertEqual(a['data'], 'iVBORw==')
        self.assertEqual(a['path'], path)

    def test_non_image_and_missing_files_are_only_linked(self):
        from pyrept.report import make_attachment
        trace = make_attachment('trace', path=self._file('trace.zip', b'PK'))
        self.assertNotIn('data', trace)
        missing = make_attachment('gone', path='/does/not/exist.png')
        self.assertNotIn('data', missing)
        self.assertEqual(missing['content_type'], 'image/png')

    def test_large_or_unembedded_images_are_not_inlined(self):
        from unittest import mock
        from pyrept.report import make_attachment
        path = self._file('big.png', b'\x89PNG')
        with mock.patch('os.path.getsize', return_value=6 * 1024 * 1024):
            self.assertNotIn('data', make_attachment('big', path=path))
        self.assertNotIn('data', make_attachment('x', path=path, embed=False))

    def test_unknown_type_and_text(self):
        from pyrept.report import make_attachment
        a = make_attachment('log', text='hello')
        self.assertEqual(a['content_type'], 'application/octet-stream')
        self.assertEqual(a['text'], 'hello')


class BuildContextEdgeCaseTests(unittest.TestCase):
    def test_empty_run(self):
        ctx = build_context(new_summary_stats(), [])
        self.assertEqual(ctx['test_summary']['percentage'], 0)
        self.assertIsNone(ctx['duration'])
        self.assertEqual(ctx['slowest_tests'], [])
        self.assertEqual(ctx['test_results'], [])

    def test_all_skipped_has_zero_pass_rate_not_division_error(self):
        stats, results = new_summary_stats(), []
        record_outcome(stats, results, 'a', 'skipped')
        self.assertEqual(build_context(stats, results)['test_summary']['percentage'], 0)

    def test_missing_counters_are_filled(self):
        stats, results = {}, []
        record_outcome(stats, results, 'a', 'passed')
        summary = build_context(stats, results)['test_summary']
        self.assertEqual((summary['total'], summary['failed'], summary['error'], summary['skipped']), (1, 0, 0, 0))

    def test_duration_and_slowest(self):
        stats, results = new_summary_stats(), []
        for i, duration in enumerate([0.5, 2, 0, 1.25, 3, 0.1, 4]):
            record_outcome(stats, results, 't%d' % i, 'passed', metadata={'duration': duration})
        record_outcome(stats, results, 'no_timing', 'passed')
        record_outcome(stats, results, 'bad_timing', 'passed', metadata={'duration': True})
        ctx = build_context(stats, results)
        self.assertEqual(ctx['duration'], 10.85)
        self.assertEqual([t['name'] for t in ctx['slowest_tests']], ['t6', 't4', 't1', 't3', 't0'])

    def test_explicit_duration_and_environment_override(self):
        ctx = build_context(new_summary_stats(), [], duration=1.23456, environment={'Python': 'custom', 'CI': 'yes'})
        self.assertEqual(ctx['duration'], 1.235)
        self.assertEqual(ctx['environment']['Python'], 'custom')
        self.assertEqual(ctx['environment']['CI'], 'yes')
        self.assertIn('Platform', ctx['environment'])

    def test_collector_coerces_names_and_descriptions(self):
        from pyrept.report import ReportCollector
        c = ReportCollector()
        c.add(None, 'passed')
        c.add(42, 'failed', description=7)
        c.add('b', 'failed')
        ctx = c.context()  # must not raise on sorting mixed names
        self.assertEqual([r['name'] for r in ctx['test_results']], ['42', 'b', 'None'])
        self.assertEqual(c.test_results[1]['description'], '7')

    def test_collector_does_not_share_or_mutate_metadata(self):
        from pyrept.report import ReportCollector, make_attachment
        meta = {'k': 1}
        c = ReportCollector()
        c.add('a', 'passed', metadata=meta, attachments=[make_attachment('x', text='y')])
        self.assertEqual(meta, {'k': 1})
        self.assertEqual(len(c.test_results[0]['metadata']['attachments']), 1)


class TemplateSafetyTests(unittest.TestCase):
    def test_attachment_data_cannot_break_out_of_attributes(self):
        from pyrept.report import ReportCollector, make_attachment
        c = ReportCollector()
        c.add('t', 'failed', attachments=[make_attachment('shot', 'image/png', data='x" onerror="alert(1)')])
        html, _ = _render(c)
        self.assertNotIn('onerror="alert(1)"', html)
        self.assertIn('x&#34; onerror=&#34;alert(1)', html)

    def test_script_urls_are_not_linked(self):
        from pyrept.report import ReportCollector, make_attachment
        c = ReportCollector()
        c.add('t', 'failed', attachments=[make_attachment('evil', 'text/plain', path=' JavaScript:alert(1)'),
                                          make_attachment('trace', 'application/zip', path='results/trace.zip')])
        html, _ = _render(c)
        self.assertNotIn('href=" JavaScript', html)
        self.assertIn('href="results/trace.zip"', html)

    def test_non_image_data_is_offered_as_download(self):
        from pyrept.report import ReportCollector, make_attachment
        c = ReportCollector()
        c.add('t', 'passed', attachments=[make_attachment('log.txt', 'text/plain', data=b'hello')])
        html, _ = _render(c)
        self.assertIn('href="data:text/plain;base64,aGVsbG8=" download="log.txt"', html)

    def test_empty_report_renders(self):
        from pyrept.report import ReportCollector
        html, data = _render(ReportCollector(title='Nothing'))
        self.assertIn('donut empty', html)
        self.assertIn('No tests match the current filter.', html)
        self.assertEqual(data['test_summary']['total'], 0)

    def test_unicode_and_nested_output_dirs(self):
        import os
        import shutil
        import tempfile
        from pyrept.report import ReportCollector
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        c = ReportCollector(title='Résumé ✓')
        c.add('test_ünïcode', 'passed', description='日本語')
        html_path = os.path.join(tmp, 'a', 'b', 'r.html')
        json_path = os.path.join(tmp, 'c', 'r.json')
        c.write(html_path, json_path)
        with open(html_path, encoding='utf-8') as fh:
            self.assertIn('日本語', fh.read())
        with open(json_path, encoding='utf-8') as fh:
            self.assertEqual(json.load(fh)['test_report_title'], 'Résumé ✓')
