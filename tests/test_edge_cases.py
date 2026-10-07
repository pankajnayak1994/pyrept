"""Malformed and unusual inputs: converters, history, summaries and report writing must not crash."""
import json
import os
import shutil
import tempfile
import unittest

from pyrept.history import build_history, load_runs, write_history
from pyrept.importers import (
    load_allure_results,
    load_nunit_xml,
    load_pytest_json,
    load_robot_xml,
    load_trx,
    load_xunit_xml,
)
from pyrept.report import ReportCollector, build_context, new_summary_stats, record_outcome, write_reports
from pyrept.summary import render_markdown, write_markdown


class _TempDir(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)

    def _file(self, name, text):
        path = os.path.join(self.tmp, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write(text if isinstance(text, str) else json.dumps(text))
        return path

    def _results(self, collector):
        return {r['name']: r for r in collector.test_results}


class XmlConverterEdgeCases(_TempDir):
    def test_invalid_xml_is_a_value_error(self):
        path = self._file('broken.xml', '<TestRun><Results>')
        for loader in (load_trx, load_nunit_xml, load_xunit_xml, load_robot_xml):
            with self.assertRaises(ValueError, msg=loader.__name__):
                loader(path)

    def test_trx_odd_entries(self):
        path = self._file('odd.trx', '''<?xml version="1.0"?>
<TestRun xmlns="http://microsoft.com/schemas/VisualStudio/TeamTest/2010">
  <Results>
    <TestResultAggregation testId="x" />
    <UnitTestResult testId="t1" testName="NoDefinition" duration="not-a-time" outcome="Passed">
      <ResultFiles>
        <ResultFile path="" /><ResultFile path="/abs/shot.png" /><ResultFile path="relative.txt" />
      </ResultFiles>
    </UnitTestResult>
    <UnitTestResult testId="t2" testName="Weird" outcome="SomethingNew" />
  </Results>
  <TestDefinitions><UnitTest name="NoMethod" id="t2" /></TestDefinitions>
</TestRun>''')
        r = self._results(load_trx(path))
        passed = r['NoDefinition']
        self.assertEqual(passed['metadata']['duration'], 0.0)
        paths = [a['path'] for a in passed['metadata']['attachments']]
        self.assertEqual(paths, ['/abs/shot.png', 'relative.txt'])  # no deployment root: left as given
        self.assertEqual(r['Weird']['result'], 'error')  # unknown outcomes are not hidden

    def test_nunit_odd_properties_and_attachments(self):
        path = self._file('nunit.xml', '''<test-run>
  <test-case fullname="A.B.Test" result="Passed">
    <properties><property name="Owner" value="me" /><property name="Category" value="" /></properties>
    <categories><category /></categories>
    <attachments><attachment><filePath></filePath></attachment>
                 <attachment><filePath>/abs/log.txt</filePath></attachment></attachments>
  </test-case>
</test-run>''')
        result = self._results(load_nunit_xml(path))['A.B.Test']
        self.assertEqual(result['metadata']['tags'], [])
        self.assertEqual([a['path'] for a in result['metadata']['attachments']], ['/abs/log.txt'])

    def test_xunit_trait_without_value(self):
        path = self._file('x.xml', '<assemblies><assembly><collection><test name="T.t" result="Pass">'
                                   '<traits><trait name="Category" /></traits></test>'
                                   '</collection></assembly></assemblies>')
        self.assertEqual(self._results(load_xunit_xml(path))['T.t']['metadata']['tags'], [])

    def test_robot_without_times_or_status(self):
        path = self._file('output.xml', '''<robot>
  <suite name="S">
    <test name="No times"><status status="PASS" starttime="garbage" endtime="also garbage"/></test>
    <test name="No status"></test>
  </suite>
</robot>''')
        r = self._results(load_robot_xml(path))
        self.assertEqual(r['S.No times']['metadata']['duration'], 0.0)
        self.assertEqual(r['S.No status']['result'], 'error')
        self.assertEqual(r['S.No status']['traceback'], 'Status: missing')


class JsonConverterEdgeCases(_TempDir):
    def test_allure_single_file_params_and_flags(self):
        att_dir = os.path.join(self.tmp, 'res')
        path = self._file('res/one-result.json', {
            'name': 'test_x[1]', 'fullName': 'm#test_x[qty=1]', 'status': 'passed',
            'parameters': [{'name': 'qty', 'value': '1'}, {'name': 'secret', 'value': 'x', 'mode': 'hidden'}],
            'statusDetails': {'flaky': True},
            'attachments': [{'name': 'no source'}, 'junk'],
            'steps': [{'attachments': [{'name': 'log', 'source': 'log.txt', 'type': 'text/plain'}]}]})
        result = self._results(load_allure_results(path))['m#test_x[qty=1]']  # params already in the name
        self.assertTrue(result['metadata']['flaky'])
        self.assertEqual([a['path'] for a in result['metadata']['attachments']], [os.path.join(att_dir, 'log.txt')])

    def test_pytest_json_odd_entries(self):
        path = self._file('report.json', {'tests': [
            'junk', {'outcome': 'passed'},
            {'nodeid': 't.py::test_skip', 'outcome': 'skipped', 'setup': {'longrepr': 'plain reason'}},
            {'nodeid': 't.py::test_fail', 'outcome': 'failed'},
        ]})
        r = self._results(load_pytest_json(path))
        self.assertEqual(sorted(r), ['t.py::test_fail', 't.py::test_skip'])
        self.assertEqual(r['t.py::test_skip']['traceback'], 'Skipped: plain reason')
        self.assertIsNone(r['t.py::test_fail']['traceback'])
        self.assertEqual(r['t.py::test_fail']['metadata']['location'], 't.py')


class HistoryEdgeCases(_TempDir):
    def test_missing_durations_names_and_limit_zero(self):
        self._file('a.json', {'timestamp': '2026/09/01 02:00:00 UTC',
                              'test_results': [{'name': 'a', 'result': 'passed', 'metadata': {'duration': 2}},
                                               {'name': 'b', 'result': 'failed'}, {'result': 'passed'}, 'junk']})
        runs, _ = load_runs([os.path.join(self.tmp, 'a.json')])
        history = build_history(runs, limit=0)
        self.assertEqual(history['runs'][0]['duration'], 2.0)  # computed from the tests
        self.assertEqual(history['runs'][0]['total'], 3)
        self.assertEqual(history['summary']['tests'], 2)

    def test_json_only(self):
        runs, _ = load_runs([self._file('a.json', {'test_results': []})])
        out = os.path.join(self.tmp, 'out', 'h.json')
        write_history(build_history(runs), json_path=out)
        self.assertTrue(os.path.exists(out))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, 'out', 'history.html')))


class SummaryAndReportEdgeCases(_TempDir):
    def _context(self, outcomes, baseline=None):
        stats, results = new_summary_stats(), []
        for name, outcome, duration in outcomes:
            record_outcome(stats, results, name, outcome, traceback='boom' if outcome != 'passed' else None,
                           metadata={'duration': duration})
        return build_context(stats, results, baseline=baseline)

    def test_errors_only_headline_and_slower_table(self):
        baseline = {'test_results': [{'name': 'slow', 'result': 'passed', 'metadata': {'duration': 1.0}}],
                    'test_summary': {}}
        md = render_markdown(self._context([('slow', 'passed', 4.0), ('e', 'error', 0.1)], baseline=baseline))
        self.assertIn('### ❌ Test Report: 1 error', md)
        self.assertIn('1 slower', md)
        self.assertIn('<summary><b>Slower tests (1)</b></summary>', md)
        self.assertIn('| `slow` | 1.000s | 4.000s | ×4.0 |', md)

    def test_markdown_in_current_directory(self):
        cwd = os.getcwd()
        os.chdir(self.tmp)
        try:
            write_markdown(self._context([('a', 'passed', 0.1)]), 'summary.md')
        finally:
            os.chdir(cwd)
        self.assertTrue(os.path.exists(os.path.join(self.tmp, 'summary.md')))

    def test_write_reports_without_notifications(self):
        os.environ['PYREPT_WEBHOOK_URL'] = 'http://127.0.0.1:9/never'  # removed again by the conftest fixture
        try:
            write_reports(self._context([('a', 'passed', 0.1)]), os.path.join(self.tmp, 'r.html'),
                          os.path.join(self.tmp, 'r.json'), notify=False)
        finally:
            del os.environ['PYREPT_WEBHOOK_URL']
        self.assertTrue(os.path.exists(os.path.join(self.tmp, 'r.json')))

    def test_reports_in_current_directory(self):
        cwd = os.getcwd()
        os.chdir(self.tmp)
        try:
            c = ReportCollector()
            c.add('a', 'passed')
            c.write('r.html', 'r.json', markdown_path='s.md')
        finally:
            os.chdir(cwd)
        self.assertEqual(sorted(os.listdir(self.tmp)), ['r.html', 'r.json', 's.md'])


class AttachmentEdgeCases(_TempDir):
    def test_unreadable_image_is_linked_not_embedded(self):
        from unittest import mock
        from pyrept.report import make_attachment
        path = self._file('shot.png', 'png bytes')
        with mock.patch('builtins.open', side_effect=OSError('permission denied')):
            with self.assertLogs('pyrept.report', 'WARNING'):
                attachment = make_attachment('shot', path=path)
        self.assertNotIn('data', attachment)
        self.assertEqual(attachment['path'], path)


class SmallHelperEdgeCases(unittest.TestCase):
    def test_junit_module_name_without_py_suffix(self):
        from pyrept.junit import _module
        self.assertEqual(_module('tests/test_a.py'), 'tests.test_a')
        self.assertEqual(_module('tests/features/login'), 'tests.features.login')

    def test_cucumber_passing_hooks_are_not_errors(self):
        from pyrept.importers.cucumber import _hook_errors
        element = {'before': [{'result': {'status': 'passed'}}],
                   'after': [{'result': {'status': 'failed', 'error_message': 'screenshot failed'}}]}
        self.assertEqual(list(_hook_errors(element)), ['after hook failed\nscreenshot failed'])
