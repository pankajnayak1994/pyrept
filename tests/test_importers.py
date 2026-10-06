import json
import os
import shutil
import tempfile
import unittest

from pyrept.cli import main
from pyrept.importers import load_cucumber_json, load_playwright_json

FIXTURES = os.path.join(os.path.dirname(__file__), 'fixtures')


class CucumberImporterTests(unittest.TestCase):
    def setUp(self):
        collector = load_cucumber_json(os.path.join(FIXTURES, 'cucumber.json'))
        self.results = {r['name']: r for r in collector.test_results}

    def test_outcomes(self):
        self.assertEqual(self.results['Login :: Valid credentials']['result'], 'passed')
        self.assertEqual(self.results['Login :: Wrong password']['result'], 'failed')
        self.assertEqual(self.results['Login :: Single sign-on']['result'], 'error')  # undefined step

    def test_background_steps_and_tags_in_description(self):
        desc = self.results['Login :: Valid credentials']['description']
        self.assertTrue(desc.startswith('@smoke'))
        self.assertIn('Given the app is open', desc)

    def test_failure_details(self):
        failed = self.results['Login :: Wrong password']
        self.assertIn('expected banner', failed['traceback'])
        self.assertAlmostEqual(failed['metadata']['duration'], 0.151)
        self.assertEqual(failed['metadata']['attachments'][0]['content_type'], 'image/png')


class PlaywrightImporterTests(unittest.TestCase):
    def setUp(self):
        collector = load_playwright_json(os.path.join(FIXTURES, 'playwright.json'))
        self.results = {r['name']: r for r in collector.test_results}

    def test_outcomes_per_project(self):
        prefix = 'checkout.spec.ts › Checkout › '
        self.assertEqual(self.results['[chromium] ' + prefix + 'adds item to cart']['result'], 'passed')
        flaky = self.results['[firefox] ' + prefix + 'adds item to cart']
        self.assertEqual(flaky['result'], 'passed')
        self.assertTrue(flaky['metadata']['flaky'])
        self.assertEqual(flaky['metadata']['retries'], 1)
        self.assertEqual(self.results['[chromium] ' + prefix + 'pays with card']['result'], 'failed')
        self.assertEqual(self.results['[chromium] ' + prefix + 'applies coupon']['result'], 'skipped')
        self.assertEqual(self.results['[webkit] ' + prefix + 'slow network']['result'], 'error')

    def test_screenshot_is_embedded_and_trace_linked(self):
        failed = self.results['[chromium] checkout.spec.ts › Checkout › pays with card']
        attachments = {a['name']: a for a in failed['metadata']['attachments']}
        self.assertIn('data', attachments['screenshot'])
        self.assertNotIn('data', attachments['trace'])
        self.assertTrue(attachments['trace']['path'].endswith('trace.zip'))
        self.assertIn('toBeVisible', failed['traceback'])


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)

    def test_convert_merges_inputs_and_fail_flag(self):
        html = os.path.join(self.tmp, 'r.html')
        jsn = os.path.join(self.tmp, 'r.json')
        code = main(['convert', '--from', 'cucumber', os.path.join(FIXTURES, 'cucumber.json'),
                     os.path.join(FIXTURES, 'cucumber.json'), '--html', html, '--json', jsn,
                     '--fail-on-failure', '--title', 'BDD'])
        self.assertEqual(code, 1)
        with open(jsn, encoding='utf-8') as fh:
            data = json.load(fh)
        self.assertEqual(data['test_summary']['total'], 6)
        self.assertEqual(data['test_report_title'], 'BDD')
        with open(html, encoding='utf-8') as fh:
            self.assertIn('Wrong password', fh.read())

    def test_missing_input(self):
        self.assertEqual(main(['convert', '--from', 'playwright', os.path.join(self.tmp, 'nope.json')]), 2)


class _TmpDirMixin:
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)

    def _write(self, name, content, encoding='utf-8'):
        path = os.path.join(self.tmp, name)
        with open(path, 'w', encoding=encoding) as fh:
            fh.write(content if isinstance(content, str) else json.dumps(content))
        return path


def _scenario(name='S', steps=None, **extra):
    element = {'type': 'scenario', 'name': name, 'steps': steps if steps is not None else []}
    element.update(extra)
    return element


def _step(status, name='a step', duration=None, error=None):
    result = {'status': status}
    if duration is not None:
        result['duration'] = duration
    if error:
        result['error_message'] = error
    return {'keyword': 'Given ', 'name': name, 'result': result}


class CucumberEdgeCaseTests(_TmpDirMixin, unittest.TestCase):
    def _load(self, features):
        collector = load_cucumber_json(self._write('c.json', features))
        return {r['name']: r for r in collector.test_results}

    def test_rejects_non_cucumber_json(self):
        for content in ({'suites': []}, [1, 2], 'text'):
            with self.assertRaises(ValueError):
                load_cucumber_json(self._write('bad.json', content))

    def test_empty_and_null_reports(self):
        self.assertEqual(load_cucumber_json(self._write('e.json', [])).test_results, [])
        self.assertEqual(load_cucumber_json(self._write('n.json', 'null')).test_results, [])

    def test_utf8_bom_is_accepted(self):
        path = self._write('bom.json', [{'name': 'F', 'elements': [_scenario(steps=[_step('passed')])]}],
                           encoding='utf-8-sig')
        self.assertEqual(len(load_cucumber_json(path).test_results), 1)

    def test_unnamed_feature_and_scenario(self):
        results = self._load([{'uri': 'a.feature', 'elements': [{'type': 'scenario', 'steps': []}]}])
        self.assertIn('a.feature :: Scenario', results)

    def test_outcome_rules(self):
        results = self._load([{'name': 'F', 'elements': [
            _scenario('no steps'),
            _scenario('pending', [_step('passed'), _step('pending')]),
            _scenario('ambiguous', [_step('ambiguous')]),
            _scenario('strange status', [_step('weird')]),
            _scenario('fail then skip', [_step('failed', error='boom'), _step('skipped')]),
        ]}])
        self.assertEqual(results['F :: no steps']['result'], 'skipped')
        self.assertEqual(results['F :: pending']['result'], 'skipped')
        self.assertEqual(results['F :: ambiguous']['result'], 'error')
        self.assertEqual(results['F :: strange status']['result'], 'error')
        self.assertEqual(results['F :: fail then skip']['result'], 'failed')
        self.assertIn('boom', results['F :: fail then skip']['traceback'])

    def test_hook_failures(self):
        failed_hook = [{'result': {'status': 'failed', 'error_message': 'browser crashed'}}]
        results = self._load([{'name': 'F', 'elements': [
            _scenario('after hook', [_step('passed')], after=failed_hook),
            _scenario('step and hook', [_step('failed', error='assert')], before=failed_hook),
        ]}])
        self.assertEqual(results['F :: after hook']['result'], 'error')
        self.assertIn('after hook failed', results['F :: after hook']['traceback'])
        self.assertEqual(results['F :: step and hook']['result'], 'failed')
        self.assertIn('assert', results['F :: step and hook']['traceback'])
        self.assertIn('browser crashed', results['F :: step and hook']['traceback'])

    def test_background_only_applies_to_next_scenario(self):
        results = self._load([{'name': 'F', 'elements': [
            {'type': 'background', 'steps': [_step('passed', name='bg')]},
            _scenario('first', [_step('passed', name='one')]),
            _scenario('second', [_step('passed', name='two')]),
        ]}])
        self.assertIn('bg', results['F :: first']['description'])
        self.assertNotIn('bg', results['F :: second']['description'])

    def test_durations_in_nanoseconds_and_seconds(self):
        results = self._load([{'name': 'F', 'elements': [
            _scenario('cucumber-jvm', [_step('passed', duration=1500000000)]),
            _scenario('behave json', [_step('passed', duration=0.25)]),
            _scenario('missing', [_step('passed'), _step('passed', duration='bogus')]),
        ]}])
        self.assertEqual(results['F :: cucumber-jvm']['metadata']['duration'], 1.5)
        self.assertEqual(results['F :: behave json']['metadata']['duration'], 0.25)
        self.assertEqual(results['F :: missing']['metadata']['duration'], 0)


class PlaywrightEdgeCaseTests(_TmpDirMixin, unittest.TestCase):
    def _load(self, report):
        collector = load_playwright_json(self._write('p.json', report))
        return {r['name']: r for r in collector.test_results}

    def _spec(self, title, tests):
        spec = {'title': title, 'file': 'file.spec.ts', 'line': 3, 'tests': tests}
        return {'title': 'file.spec.ts', 'specs': [spec]}

    def test_rejects_non_playwright_json(self):
        for content in ([], {'suites': 'nope'}, '"text"'):
            with self.assertRaises(ValueError):
                load_playwright_json(self._write('bad.json', content))

    def test_global_errors_are_reported(self):
        results = self._load({'suites': [], 'errors': [
            {'message': 'Error: Cannot find module', 'stack': 'Error: Cannot find module\n at x',
             'location': {'file': 'broken.spec.ts', 'line': 1}},
            {'message': 'no location'},
            'not-a-dict',
        ]})
        self.assertEqual(results['Global error in broken.spec.ts']['result'], 'error')
        self.assertIn('at x', results['Global error in broken.spec.ts']['traceback'])
        self.assertEqual(results['Global error']['traceback'], 'no location')

    def test_stdout_stderr_and_binary_output(self):
        results = self._load({'suites': [self._spec('t', [{
            'projectName': '', 'status': 'expected',
            'results': [{'status': 'passed', 'duration': 10,
                         'stdout': [{'text': 'hello '}, {'buffer': 'd29ybGQ='}, 'junk'],
                         'stderr': [{'text': 'warn'}]}]}])]})
        attachments = {a['name']: a for a in results['file.spec.ts › t']['metadata']['attachments']}
        self.assertEqual(attachments['stdout']['text'], 'hello world')
        self.assertEqual(attachments['stderr']['text'], 'warn')

    def test_status_mapping(self):
        def test(status, result_status, **extra):
            return dict({'projectName': status, 'status': status,
                         'results': [{'status': result_status, 'duration': 1}] if result_status else []}, **extra)
        results = self._load({'suites': [self._spec('t', [
            test('expected', 'passed'),
            test('unexpected', 'timedOut'),
            test('unexpected', 'failed', projectName='plain-fail'),
            test('skipped', None),
            test('flaky', 'passed'),
        ])]})
        self.assertEqual(results['[expected] file.spec.ts › t']['result'], 'passed')
        self.assertEqual(results['[unexpected] file.spec.ts › t']['result'], 'error')
        self.assertEqual(results['[plain-fail] file.spec.ts › t']['result'], 'failed')
        self.assertEqual(results['[skipped] file.spec.ts › t']['result'], 'skipped')
        self.assertIsNone(results['[skipped] file.spec.ts › t']['traceback'])
        self.assertTrue(results['[flaky] file.spec.ts › t']['metadata']['flaky'])


class CliEdgeCaseTests(_TmpDirMixin, unittest.TestCase):
    def _outputs(self):
        return ['--html', os.path.join(self.tmp, 'r.html'), '--json', os.path.join(self.tmp, 'r.json')]

    def _main(self, *args):
        import contextlib
        import io
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_invalid_json_is_a_clean_error(self):
        code, _, err = self._main('convert', '--from', 'cucumber', self._write('x.json', 'not json'), *self._outputs())
        self.assertEqual(code, 2)
        self.assertIn('cannot read cucumber report', err)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, 'r.html')))

    def test_wrong_format_is_a_clean_error(self):
        code, _, err = self._main('convert', '--from', 'playwright', os.path.join(FIXTURES, 'cucumber.json'),
                                  *self._outputs())
        self.assertEqual(code, 2)
        self.assertIn('not a Playwright JSON report', err)

    def test_all_missing_inputs_listed_before_any_work(self):
        code, _, err = self._main('convert', '--from', 'cucumber', os.path.join(FIXTURES, 'cucumber.json'),
                                  'a.json', 'b.json', '--json', os.path.join(self.tmp, 'r.json'))
        self.assertEqual(code, 2)
        self.assertIn('a.json, b.json', err)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, 'r.json')))

    def test_success_without_fail_flag_and_default_title(self):
        jsn = os.path.join(self.tmp, 'r.json')
        code, out, _ = self._main('convert', '--from', 'playwright', os.path.join(FIXTURES, 'playwright.json'),
                                  '--html', os.path.join(self.tmp, 'r.html'), '--json', jsn)
        self.assertEqual(code, 0)
        self.assertIn('pyrept HTML report:', out)
        with open(jsn, encoding='utf-8') as fh:
            data = json.load(fh)
        self.assertEqual(data['test_report_title'], 'Playwright Test Report')
        self.assertEqual(data['environment']['Source'], 'playwright.json')

    def test_requires_a_command(self):
        import contextlib
        import io
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as ctx:
            main([])
        self.assertEqual(ctx.exception.code, 2)

    def test_module_entry_point(self):
        import subprocess
        import sys
        proc = subprocess.run([sys.executable, '-m', 'pyrept', '--help'], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0)
        self.assertIn('convert', proc.stdout)
