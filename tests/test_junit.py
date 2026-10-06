import os
import shutil
import tempfile
import unittest
import xml.etree.ElementTree as ET

from pyrept.importers import load_junit_xml
from pyrept.junit import _message, build_junit, split_name
from pyrept.report import ReportCollector, make_attachment

FIXTURES = os.path.join(os.path.dirname(__file__), 'fixtures', 'junit')


class SplitNameTests(unittest.TestCase):
    def test_framework_name_styles(self):
        cases = {
            'tests/test_a.py::TestX::test_y': ('tests.test_a.TestX', 'test_y'),
            'tests/test_a.py::test_y[a::b-1.5]': ('tests.test_a', 'test_y[a::b-1.5]'),
            'tests/test_broken.py': ('', 'tests.test_broken'),
            'pkg.mod.py': ('', 'pkg.mod'),
            'tests\\win\\test_a.py::test_y': ('tests.win.test_a', 'test_y'),
            'pkg.test_mod.TestX.test_y': ('pkg.test_mod.TestX', 'test_y'),
            'pkg.test_mod.TestX.test_y (i=1)': ('pkg.test_mod.TestX', 'test_y (i=1)'),
            'setUpClass (pkg.test_mod.TestX)': ('', 'setUpClass (pkg.test_mod.TestX)'),
            'Login :: Wrong password': ('Login', 'Wrong password'),
            '[chromium] checkout.spec.ts › pays': ('', '[chromium] checkout.spec.ts › pays'),
            'plain name': ('', 'plain name'),
        }
        for name, expected in cases.items():
            self.assertEqual(split_name(name), expected, name)

    def test_failure_message_picks_the_error_line(self):
        self.assertEqual(_message('def t():\n>  assert 0\nE   AssertionError: x\nE   assert 0'), 'AssertionError: x')
        self.assertEqual(_message('Traceback (most recent call last):\n  File "a.py"\nValueError: bad'),
                         'ValueError: bad')
        self.assertEqual(_message('\n\nSkipped: no network'), 'Skipped: no network')
        self.assertEqual(_message(None), '')
        self.assertEqual(len(_message('x' * 1000)), 300)


class JUnitWriterTests(unittest.TestCase):
    def _xml(self, collector):
        root = ET.fromstring(build_junit(collector.context()))
        return root, root.find('testsuite')

    def test_counts_outcomes_and_attributes(self):
        c = ReportCollector(title='Nightly', environment={'Build': '7'})
        ok_metadata = {'duration': 1.25, 'location': 'tests/test_a.py:3', 'tags': ['smoke'],
                       'retries': 1, 'flaky': True}
        c.add('tests/test_a.py::test_ok', 'passed', metadata=ok_metadata)
        c.add('tests/test_a.py::test_bad', 'failed', traceback='E   AssertionError: nope\nmore')
        c.add('tests/test_a.py::test_err', 'error', traceback='RuntimeError: boom')
        c.add('tests/test_a.py::test_skip', 'skipped', traceback='Skipped: later')
        c.add('tests/test_a.py::test_skip2', 'skipped')
        root, suite = self._xml(c)
        for element in (root, suite):
            self.assertEqual(element.get('name'), 'Nightly')
            self.assertEqual((element.get('tests'), element.get('failures'), element.get('errors'),
                              element.get('skipped')), ('5', '1', '1', '2'))
        self.assertRegex(suite.get('timestamp'), r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d$')
        self.assertEqual(suite.find("properties/property[@name='Build']").get('value'), '7')
        cases = {case.get('name'): case for case in suite.findall('testcase')}
        ok = cases['test_ok']
        self.assertEqual((ok.get('classname'), ok.get('time'), ok.get('file'), ok.get('line')),
                         ('tests.test_a', '1.250', 'tests/test_a.py', '3'))
        props = {(p.get('name'), p.get('value')) for p in ok.findall('properties/property')}
        self.assertEqual(props, {('retries', '1'), ('flaky', 'true'), ('tag', 'smoke')})
        self.assertEqual(cases['test_bad'].find('failure').get('message'), 'AssertionError: nope')
        self.assertIn('more', cases['test_bad'].find('failure').text)
        self.assertEqual(cases['test_err'].find('error').get('message'), 'RuntimeError: boom')
        self.assertEqual(cases['test_skip'].find('skipped').get('message'), 'later')
        self.assertEqual(cases['test_skip2'].find('skipped').get('message'), '')
        self.assertIsNone(ok.find('failure'))

    def test_invalid_xml_characters_and_markup_are_safe(self):
        c = ReportCollector(title='T <&>')
        c.add('test_\x00weird', 'failed', traceback='\x1b[31mred\x1b[0m <tag> & "q"\x07',
              attachments=[make_attachment('stdout', 'text/plain', text='out\x0cput')])
        xml = build_junit(c.context())
        root = ET.fromstring(xml)  # must parse
        case = root.find('testsuite/testcase')
        self.assertEqual(case.get('name'), 'test_weird')
        self.assertEqual(case.find('failure').text, '[31mred[0m <tag> & "q"')
        self.assertEqual(case.find('system-out').text, 'output')
        self.assertEqual(root.get('name'), 'T <&>')

    def test_empty_run_and_bad_values(self):
        root = ET.fromstring(build_junit({'test_results': [], 'timestamp': 'not a date'}))
        suite = root.find('testsuite')
        self.assertEqual((root.get('tests'), root.get('time')), ('0', '0.000'))
        self.assertIsNone(suite.get('timestamp'))
        c = ReportCollector()
        c.add('t', 'passed', metadata={'duration': -3, 'location': 'no-line-number'})
        case = ET.fromstring(build_junit(c.context())).find('testsuite/testcase')
        self.assertEqual(case.get('time'), '0.000')
        self.assertIsNone(case.get('file'))

    def test_written_with_reports(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        c = ReportCollector()
        c.add('t', 'passed')
        junit = os.path.join(tmp, 'nested', 'junit.xml')
        c.write(os.path.join(tmp, 'r.html'), os.path.join(tmp, 'r.json'), junit_path=junit)
        with open(junit, 'rb') as fh:
            content = fh.read()
        self.assertTrue(content.startswith(b"<?xml version='1.0' encoding='utf-8'?>"))
        self.assertEqual(ET.fromstring(content).get('tests'), '1')


class JUnitImporterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)

    def _write(self, content):
        path = os.path.join(self.tmp, 'r.xml')
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write(content)
        return path

    def _results(self, path):
        return {r['name']: r for r in load_junit_xml(path).test_results}

    def test_maven_surefire(self):
        results = self._results(os.path.join(FIXTURES, 'surefire.xml'))
        prefix = 'com.shop.CheckoutTest.'
        pay = results[prefix + 'paysWithCard']
        self.assertEqual(pay['result'], 'failed')
        self.assertTrue(pay['traceback'].startswith('org.opentest4j.AssertionFailedError: expected:<200>'))
        self.assertEqual(pay['metadata']['duration'], 1200.25)  # "1,200.25"
        shot = [a for a in pay['metadata']['attachments'] if a['name'] == 'pay.png'][0]
        self.assertEqual(shot['data'], 'iVBORw==')  # [[ATTACHMENT|...]] resolved next to the XML file
        load = results[prefix + 'loadsCart']
        self.assertEqual(load['result'], 'error')
        self.assertEqual(load['traceback'], 'java.net.ConnectException: Connection refused')
        self.assertEqual(results[prefix + 'appliesCoupon']['traceback'], 'Skipped: coupon service disabled')
        retried = results[prefix + 'retriesPayment']['metadata']
        self.assertEqual((results[prefix + 'retriesPayment']['result'], retried['retries'], retried['flaky']),
                         ('passed', 1, True))
        self.assertEqual(results[prefix + 'showsTotal']['result'], 'passed')
        self.assertEqual(results[prefix + 'showsTotal']['metadata']['suite'], 'com.shop.CheckoutTest')

    def test_jest_and_nested_suites(self):
        results = self._results(os.path.join(FIXTURES, 'jest.xml'))
        self.assertEqual(set(results), {'Cart adds item', 'Cart removes item', 'deep test'})
        self.assertIn('Expected: 0', results['Cart removes item']['traceback'])
        deep = results['deep test']['metadata']
        self.assertEqual(deep['suite'], 'Nested › Inner')
        self.assertEqual(deep['tags'], ['smoke', 'api'])

    def test_message_and_body_are_combined(self):
        results = self._results(self._write(
            '<testsuite><testcase classname="m" name="t">'
            '<failure message="short summary" type="AssertionError">long body\nline 2</failure>'
            '<failure message="second">  </failure>'
            '<system-err>warning text [[ATTACHMENT|/abs/video.webm]]</system-err>'
            '<properties><property name="owner" value="team-a"/><property name="tag"/></properties>'
            '</testcase></testsuite>'))
        r = results['m.t']
        self.assertEqual(r['traceback'], 'short summary\n\nlong body\nline 2\n\nsecond')
        self.assertEqual([a['name'] for a in r['metadata']['attachments']], ['system-err', 'video.webm'])
        self.assertEqual(r['metadata']['attachments'][1]['path'], '/abs/video.webm')
        self.assertEqual(r['metadata']['tags'], [])

    def test_single_testcase_root_namespaces_and_missing_values(self):
        results = self._results(self._write(
            '<testcase xmlns="urn:x" name="" time="abc"><skipped/></testcase>'))
        self.assertEqual(results['test']['result'], 'skipped')
        self.assertIsNone(results['test']['traceback'])
        self.assertEqual(results['test']['metadata']['duration'], 0)
        results = self._results(self._write(
            '<ns:testsuites xmlns:ns="urn:y"><ns:testsuite name="S"><ns:testcase name="a" time="-1"/>'
            '</ns:testsuite></ns:testsuites>'))
        self.assertEqual(results['a']['metadata']['duration'], 0)

    def test_rejects_invalid_or_foreign_xml(self):
        with self.assertRaises(ValueError):
            load_junit_xml(self._write('<testsuite><testcase'))
        with self.assertRaises(ValueError):
            load_junit_xml(self._write('<html><body/></html>'))

    def test_pytest_junitxml_output(self):
        import subprocess
        import sys
        test_file = os.path.join(self.tmp, 'test_sample.py')
        with open(test_file, 'w') as fh:
            fh.write('import pytest\n\ndef test_ok():\n    pass\n\ndef test_bad():\n    assert 1 == 2\n\n'
                     '@pytest.mark.skip(reason="later")\ndef test_skip():\n    pass\n')
        xml = os.path.join(self.tmp, 'pytest.xml')
        subprocess.run([sys.executable, '-m', 'pytest', '-p', 'no:cacheprovider', '-p', 'no:pyrept',
                        test_file, '--junitxml', xml], cwd=self.tmp, capture_output=True, check=False)
        results = self._results(xml)
        self.assertEqual({k.split('.')[-1]: v['result'] for k, v in results.items()},
                         {'test_ok': 'passed', 'test_bad': 'failed', 'test_skip': 'skipped'})
        bad = [v for k, v in results.items() if k.endswith('test_bad')][0]
        self.assertIn('assert 1 == 2', bad['traceback'])

    def test_round_trip_through_pyrept_junit(self):
        c = ReportCollector()
        c.add('tests/test_a.py::test_ok', 'passed', metadata={'duration': 0.5})
        c.add('tests/test_a.py::test_bad', 'failed', traceback='E   AssertionError: nope')
        c.add('tests/test_a.py::test_skip', 'skipped', traceback='Skipped: later')
        path = os.path.join(self.tmp, 'out.xml')
        with open(path, 'wb') as fh:
            fh.write(build_junit(c.context()))
        results = self._results(path)
        self.assertEqual({k: v['result'] for k, v in results.items()},
                         {'tests.test_a.test_ok': 'passed', 'tests.test_a.test_bad': 'failed',
                          'tests.test_a.test_skip': 'skipped'})
        self.assertEqual(results['tests.test_a.test_ok']['metadata']['duration'], 0.5)
        self.assertEqual(results['tests.test_a.test_skip']['traceback'], 'Skipped: later')
