"""Converters added for .NET, Robot Framework, TAP, Allure, pytest-json-report and pyrept JSON."""
import json
import os
import shutil
import tempfile
import unittest

from pyrept.cli import main
from pyrept.importers import (
    IMPORTERS,
    load_allure_results,
    load_nunit_xml,
    load_pyrept_json,
    load_pytest_json,
    load_robot_xml,
    load_tap,
    load_trx,
    load_xunit_xml,
)
from pyrept.report import ReportCollector

FIXTURES = os.path.join(os.path.dirname(__file__), 'fixtures')


def _fixture(name):
    return os.path.join(FIXTURES, name)


def _results(collector):
    return {r['name']: r for r in collector.test_results}


class TrxTests(unittest.TestCase):
    def setUp(self):
        self.r = _results(load_trx(_fixture('dotnet.trx')))

    def test_outcomes_and_names(self):
        self.assertEqual({n: r['result'] for n, r in self.r.items()}, {
            'Shop.Tests.CartTests.AddsItem': 'passed',
            'Shop.Tests.CartTests.ComputesTotal': 'failed',
            'Shop.Tests.PaymentTests.Refund': 'skipped',
            'Shop.Tests.PaymentTests.Checkout': 'error',
            'Shop.Tests.CartTests.Quantity (1)': 'passed',
            'Shop.Tests.CartTests.Quantity (2)': 'failed',
        })

    def test_details(self):
        failed = self.r['Shop.Tests.CartTests.ComputesTotal']
        self.assertIn('Expected:<85>. Actual:<90>.', failed['traceback'])
        self.assertIn('CartTests.cs:line 21', failed['traceback'])
        self.assertEqual(failed['metadata']['duration'], 1.5)
        attachments = {a['name']: a for a in failed['metadata']['attachments']}
        self.assertEqual(attachments['stdout']['text'], 'computing total')
        self.assertTrue(attachments['screenshot.png']['path'].endswith(os.path.join(
            'ci_runner_2026-10-07_09_00_00', 'In', 'e0000000-0000-4000-8000-000000000002', 'screenshot.png')))
        self.assertEqual(self.r['Shop.Tests.PaymentTests.Refund']['traceback'], 'Skipped: Payment sandbox offline')
        self.assertEqual(self.r['Shop.Tests.PaymentTests.Checkout']['traceback'], 'Test outcome: Timeout')
        self.assertEqual(self.r['Shop.Tests.PaymentTests.Checkout']['metadata']['duration'], 30.0)


class NUnitTests(unittest.TestCase):
    def test_nunit3(self):
        r = _results(load_nunit_xml(_fixture('nunit3.xml')))
        self.assertEqual({n: x['result'] for n, x in r.items()}, {
            'Shop.Tests.CartTests.AddsItem': 'passed', 'Shop.Tests.CartTests.ComputesTotal': 'failed',
            'Shop.Tests.CartTests.LoadsDb': 'error', 'Shop.Tests.PaymentTests.Refund': 'skipped',
            'Shop.Tests.PaymentTests.Explicit': 'skipped'})
        self.assertEqual(r['Shop.Tests.CartTests.AddsItem']['metadata']['tags'], ['smoke'])
        total = r['Shop.Tests.CartTests.ComputesTotal']
        self.assertIn('But was:  90', total['traceback'])
        names = [a['name'] for a in total['metadata']['attachments']]
        self.assertEqual(names, ['output', 'Screenshot'])
        self.assertEqual(r['Shop.Tests.PaymentTests.Refund']['traceback'], 'Skipped: sandbox offline')
        self.assertEqual(r['Shop.Tests.PaymentTests.Explicit']['traceback'], 'Skipped: explicit')

    def test_nunit2(self):
        r = _results(load_nunit_xml(_fixture('nunit2.xml')))
        self.assertEqual({n: x['result'] for n, x in r.items()}, {
            'Shop.Tests.CartTests.AddsItem': 'passed', 'Shop.Tests.CartTests.ComputesTotal': 'failed',
            'Shop.Tests.CartTests.LoadsDb': 'error', 'Shop.Tests.CartTests.Refund': 'skipped'})
        self.assertEqual(r['Shop.Tests.CartTests.ComputesTotal']['metadata']['duration'], 1.5)
        self.assertEqual(r['Shop.Tests.CartTests.AddsItem']['metadata']['tags'], ['smoke'])

    def test_xunit(self):
        r = _results(load_xunit_xml(_fixture('xunit.xml')))
        self.assertEqual({n: x['result'] for n, x in r.items()}, {
            'Shop.Tests.CartTests.AddsItem': 'passed', 'Shop.Tests.CartTests.ComputesTotal': 'failed',
            'Shop.Tests.CartTests.LoadsDb': 'error', 'Shop.Tests.CartTests.Refund': 'skipped'})
        self.assertEqual(r['Shop.Tests.CartTests.AddsItem']['metadata']['tags'], ['smoke', 'Owner=cart-team'])
        self.assertTrue(r['Shop.Tests.CartTests.LoadsDb']['traceback'].startswith(
            'System.InvalidOperationException: db down'))
        self.assertEqual(r['Shop.Tests.CartTests.Refund']['traceback'], 'Skipped: sandbox offline')

    def test_wrong_format_is_rejected(self):
        for loader in (load_nunit_xml, load_xunit_xml, load_trx, load_robot_xml):
            with self.assertRaises(ValueError):
                loader(_fixture('junit/surefire.xml'))


class RobotTests(unittest.TestCase):
    def test_robot7_output(self):
        r = _results(load_robot_xml(_fixture('robot-output.xml')))
        self.assertEqual({n: x['result'] for n, x in r.items()}, {
            'Suite.Checkout.Pay With Card': 'passed', 'Suite.Login.Valid Login': 'passed',
            'Suite.Login.Wrong Password': 'failed', 'Suite.Login.Not Ready': 'skipped'})
        valid = r['Suite.Login.Valid Login']
        self.assertEqual(valid['description'], 'User can sign in')
        self.assertEqual(valid['metadata']['tags'], ['login', 'smoke'])
        self.assertEqual(valid['metadata']['location'], '/home/ci/shop/suite/login.robot:5')
        self.assertEqual(r['Suite.Login.Wrong Password']['traceback'], 'expected banner: welcome != error')
        self.assertEqual(r['Suite.Login.Not Ready']['traceback'], 'Skipped: feature flag off')
        self.assertGreater(r['Suite.Checkout.Pay With Card']['metadata']['duration'], 0.09)

    def test_robot3_output(self):
        r = _results(load_robot_xml(_fixture('robot3-output.xml')))
        self.assertEqual(r['Shop.Login.Valid Login']['metadata']['duration'], 0.25)
        self.assertEqual(r['Shop.Login.Valid Login']['metadata']['tags'], ['smoke'])
        self.assertEqual(r['Shop.Login.Wrong Password']['metadata']['duration'], 1.0)
        self.assertEqual(r['Shop.Login.Wrong Password']['result'], 'failed')


class TapTests(unittest.TestCase):
    def test_node_test_runner_output(self):
        r = _results(load_tap(_fixture('node.tap')))
        self.assertEqual({n: x['result'] for n, x in r.items()}, {
            'adds item': 'passed', 'computes total': 'failed', 'refund': 'skipped', 'rounding': 'skipped',
            'cart': 'passed'})
        self.assertIn('90 !== 85', r['computes total']['traceback'])
        self.assertEqual(r['refund']['traceback'], 'Skipped: sandbox offline')
        self.assertEqual(r['rounding']['traceback'], 'Expected failure (TODO): known bug')

    def test_edge_cases(self):
        collector = load_tap(_fixture('edge-cases.tap'))
        r = _results(collector)
        self.assertEqual(r['first']['result'], 'passed')
        self.assertEqual(r['unnumbered']['result'], 'passed')
        self.assertEqual(r['broken thing']['result'], 'failed')
        self.assertIn("expected 1, got 2", r['broken thing']['traceback'])
        self.assertEqual(r['broken thing']['metadata']['duration'], 1.5)
        self.assertEqual(r['test 4']['result'], 'skipped')
        self.assertEqual(r['flaky one']['result'], 'skipped')
        self.assertNotIn('inner', r)  # TAP 14 subtests are folded into their parent
        self.assertEqual(r['Test plan']['result'], 'error')
        self.assertIn('announced 6 tests but 5 ran', r['Test plan']['traceback'])

    def test_bail_out(self):
        r = _results(load_tap(_fixture('bailout.tap')))
        self.assertEqual(sorted(r), ['Bail out', 'starts'])
        self.assertIn('database unavailable', r['Bail out']['traceback'])

    def test_not_tap(self):
        with self.assertRaises(ValueError):
            load_tap(_fixture('cucumber.json'))

    def test_empty_plan(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        path = os.path.join(tmp, 'skip-all.tap')
        with open(path, 'w') as fh:
            fh.write('1..0 # SKIP not on this platform\n')
        self.assertEqual(load_tap(path).test_results, [])


class AllureTests(unittest.TestCase):
    def setUp(self):
        self.r = _results(load_allure_results(_fixture('allure-results')))

    def test_outcomes(self):
        by_short = {n.split('#')[-1]: x['result'] for n, x in self.r.items()}
        self.assertEqual(by_short, {
            'test_add_item': 'passed', 'test_total': 'failed', 'test_needs_db': 'error',
            'test_refund': 'skipped', 'test_rounding': 'skipped',
            'test_qty (qty=1)': 'passed', 'test_qty (qty=2)': 'failed'})

    def test_details(self):
        r = {n.split('#')[-1]: x for n, x in self.r.items()}
        self.assertEqual(r['test_add_item']['metadata']['tags'], ['cart', 'smoke'])
        self.assertEqual(r['test_add_item']['metadata']['framework'], 'pytest')
        self.assertIn('assert 90 == 85', r['test_total']['traceback'])
        attachment = r['test_qty (qty=2)']['metadata']['attachments'][0]
        self.assertEqual(attachment['content_type'], 'image/png')
        self.assertIn('data', attachment)  # small images are embedded
        self.assertTrue(r['test_refund']['traceback'].startswith('Skipped: '))

    def test_retries_are_folded(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        for i, (status, stop) in enumerate((('failed', 2000), ('passed', 5000), ('broken', 1000))):
            with open(os.path.join(tmp, 'r%d-result.json' % i), 'w') as fh:
                json.dump({'name': 'test_flaky', 'fullName': 'm#test_flaky', 'historyId': 'h1', 'status': status,
                           'start': stop - 500, 'stop': stop}, fh)
        r = _results(load_allure_results(tmp))
        self.assertEqual(r['m#test_flaky']['result'], 'passed')
        self.assertEqual(r['m#test_flaky']['metadata']['retries'], 2)
        self.assertTrue(r['m#test_flaky']['metadata']['flaky'])
        self.assertEqual(r['m#test_flaky']['metadata']['duration'], 0.5)

    def test_empty_or_wrong_directory(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        with self.assertRaises(ValueError):
            load_allure_results(tmp)
        with open(os.path.join(tmp, 'x-result.json'), 'w') as fh:
            json.dump({'suites': []}, fh)
        with self.assertRaises(ValueError):
            load_allure_results(tmp)


class PytestJsonTests(unittest.TestCase):
    def setUp(self):
        self.r = _results(load_pytest_json(_fixture('pytest-json.json')))

    def test_outcomes(self):
        self.assertEqual({n: x['result'] for n, x in self.r.items()}, {
            'test_broken.py': 'error', 'test_shop.py::test_add_item': 'passed',
            'test_shop.py::test_total': 'failed', 'test_shop.py::test_needs_db': 'error',
            'test_shop.py::test_refund': 'skipped', 'test_shop.py::test_rounding': 'skipped',
            'test_shop.py::test_qty[1]': 'passed', 'test_shop.py::test_qty[2]': 'failed'})

    def test_details(self):
        self.assertIn('not_a_module', self.r['test_broken.py']['traceback'])
        self.assertIn('assert 90 == 85', self.r['test_shop.py::test_total']['traceback'])
        self.assertIn('db down', self.r['test_shop.py::test_needs_db']['traceback'])
        self.assertEqual(self.r['test_shop.py::test_refund']['traceback'],
                         'Skipped: payment sandbox offline, retry later')
        self.assertEqual(self.r['test_shop.py::test_rounding']['traceback'], 'Expected failure')
        attachments = {a['name']: a['text'] for a in self.r['test_shop.py::test_total']['metadata']['attachments']}
        self.assertIn('computing total', attachments['Captured stdout call'])
        self.assertIn('price feed slow', attachments['Captured log call'])
        self.assertEqual(self.r['test_shop.py::test_total']['metadata']['location'], 'test_shop.py:13')

    def test_wrong_format(self):
        with self.assertRaises(ValueError):
            load_pytest_json(_fixture('cucumber.json'))


class PyreptMergeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)

    def _shard(self, name, results, env=None):
        collector = ReportCollector(title='Shard', environment=env or {})
        for test_name, outcome in results:
            collector.add(test_name, outcome, metadata={'duration': 1.0, 'tags': ['t']})
        path = os.path.join(self.tmp, name)
        collector.write(path.replace('.json', '.html'), path)
        return path

    def test_merges_shards_and_keeps_metadata(self):
        a = self._shard('a.json', [('t1', 'passed'), ('t2', 'failed')], env={'Shard': '1'})
        b = self._shard('b.json', [('t3', 'skipped')], env={'Shard': '2'})
        collector = load_pyrept_json(a)
        load_pyrept_json(b, collector=collector)
        r = _results(collector)
        self.assertEqual({n: x['result'] for n, x in r.items()}, {'t1': 'passed', 't2': 'failed', 't3': 'skipped'})
        self.assertEqual(r['t1']['metadata']['tags'], ['t'])
        self.assertEqual(collector.environment['Shard'], '1')  # the first shard's value is kept
        self.assertEqual(collector.title, 'Shard')

    def test_skips_broken_entries_and_rejects_other_files(self):
        path = os.path.join(self.tmp, 'odd.json')
        with open(path, 'w') as fh:
            json.dump({'test_results': [{'name': 'ok', 'result': 'passed'}, {'name': 'x', 'result': 'weird'},
                                        'junk', {'result': 'passed'}, {'name': 'm', 'result': 'failed',
                                                                       'metadata': 'not a dict'}]}, fh)
        self.assertEqual(sorted(_results(load_pyrept_json(path))), ['m', 'ok'])
        with self.assertRaises(ValueError):
            load_pyrept_json(_fixture('playwright.json'))


class ConvertCommandFormatTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)

    def test_every_format_converts(self):
        inputs = {'allure': 'allure-results', 'nunit': 'nunit3.xml', 'pytest-json': 'pytest-json.json',
                  'robot': 'robot-output.xml', 'tap': 'node.tap', 'trx': 'dotnet.trx', 'xunit': 'xunit.xml',
                  'cucumber': 'cucumber.json', 'playwright': 'playwright.json'}
        for source, name in inputs.items():
            out = os.path.join(self.tmp, source)
            code = main(['convert', '--from', source, _fixture(name), '--html', out + '.html', '--json', out + '.json',
                         '--junit', out + '.xml'])
            self.assertEqual(code, 0, source)
            with open(out + '.json', encoding='utf-8') as fh:
                data = json.load(fh)
            self.assertGreater(data['test_summary']['total'], 0, source)
        self.assertEqual(set(IMPORTERS), set(inputs) | {'junit', 'pyrept'})

    def test_pyrept_merge_via_cli(self):
        first = os.path.join(self.tmp, 'first.json')
        main(['convert', '--from', 'tap', _fixture('node.tap'), '--html', os.path.join(self.tmp, 'f.html'),
              '--json', first])
        merged = os.path.join(self.tmp, 'merged.json')
        code = main(['convert', '--from', 'pyrept', first, first, '--html', os.path.join(self.tmp, 'm.html'),
                     '--json', merged, '--title', 'All shards'])
        self.assertEqual(code, 0)
        with open(merged, encoding='utf-8') as fh:
            data = json.load(fh)
        self.assertEqual(data['test_summary']['total'], 10)
        self.assertEqual(data['environment']['Framework'], 'pyrept')

    def test_wrong_format_exits_2(self):
        code = main(['convert', '--from', 'robot', _fixture('nunit3.xml'), '--html', os.path.join(self.tmp, 'x.html'),
                     '--json', os.path.join(self.tmp, 'x.json')])
        self.assertEqual(code, 2)
