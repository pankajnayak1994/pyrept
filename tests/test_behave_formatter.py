import unittest

try:
    import behave  # noqa: F401
    HAS_BEHAVE = True
except ImportError:  # behave is an optional extra
    HAS_BEHAVE = False


@unittest.skipUnless(HAS_BEHAVE, 'behave not installed')
class BehaveStatusMappingTests(unittest.TestCase):
    def test_status_mapping(self):
        from behave.model_core import Status
        from pyrept.behave_formatter import map_status
        self.assertEqual(map_status(Status.passed), 'passed')
        self.assertEqual(map_status(Status.failed), 'failed')
        self.assertEqual(map_status(Status.skipped), 'skipped')
        self.assertEqual(map_status(Status.undefined), 'error')
        self.assertEqual(map_status('untested'), 'skipped')


@unittest.skipUnless(HAS_BEHAVE, 'behave not installed')
class BehaveEndToEndTests(unittest.TestCase):
    def test_runs_feature_and_writes_report(self):
        import json
        import os
        import shutil
        import subprocess
        import sys
        import tempfile
        import textwrap
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        os.makedirs(os.path.join(tmp, 'features', 'steps'))
        with open(os.path.join(tmp, 'features', 'demo.feature'), 'w') as fh:
            fh.write(textwrap.dedent('''
                Feature: Demo
                  @smoke
                  Scenario: Passing
                    Given a step that passes
                  Scenario: Failing
                    Given a step that fails
                  Scenario: Undefined
                    Given a step nobody wrote
            '''))
        with open(os.path.join(tmp, 'features', 'steps', 'steps.py'), 'w') as fh:
            fh.write(textwrap.dedent('''
                from behave import given

                @given('a step that passes')
                def ok(context):
                    pass

                @given('a step that fails')
                def bad(context):
                    assert 1 == 2, "nope"
            '''))
        subprocess.run([sys.executable, '-m', 'behave', '-f', 'pyrept.behave_formatter:PyreptFormatter',
                        '-o', os.devnull, '-D', 'pyrept_json=out.json', '-D', 'pyrept_html=out.html'],
                       cwd=tmp, check=False, capture_output=True)
        with open(os.path.join(tmp, 'out.json'), encoding='utf-8') as fh:
            data = json.load(fh)
        results = {r['name']: r for r in data['test_results']}
        self.assertEqual(results['Demo :: Passing']['result'], 'passed')
        self.assertEqual(results['Demo :: Failing']['result'], 'failed')
        self.assertIn('nope', results['Demo :: Failing']['traceback'])
        self.assertEqual(results['Demo :: Undefined']['result'], 'error')
        self.assertIn('@smoke', results['Demo :: Passing']['metadata']['tags'])

    def test_attachments_outlines_hooks_and_multiple_features(self):
        import json
        import os
        import shutil
        import subprocess
        import sys
        import tempfile
        import textwrap
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        os.makedirs(os.path.join(tmp, 'features', 'steps'))
        files = {
            'features/shop.feature': '''
                @shop
                Feature: Shop
                  Background:
                    Given a step that passes

                  Scenario: Attach
                    Given a step that attaches

                  Scenario Outline: Small <n>
                    Given number <n> is small
                    Examples:
                      | n |
                      | 1 |
                      | 9 |

                  Scenario: Hook breaks
                    Given a step that passes
            ''',
            'features/other.feature': '''
                Feature: Other
                  Scenario: Plain
                    Given a step that passes
            ''',
            'features/steps/steps.py': '''
                from behave import given

                @given('a step that passes')
                def ok(context):
                    pass

                @given('a step that attaches')
                def attach(context):
                    context.attach('image/png', b'\\x89PNG')
                    context.attach('text/plain', b'hello')

                @given('number {n:d} is small')
                def small(context, n):
                    assert n < 5, 'too big'
            ''',
            'features/environment.py': '''
                def after_scenario(context, scenario):
                    if scenario.name == 'Hook breaks':
                        raise RuntimeError('hook boom')
            ''',
        }
        for name, body in files.items():
            with open(os.path.join(tmp, name), 'w') as fh:
                fh.write(textwrap.dedent(body))
        subprocess.run([sys.executable, '-m', 'behave', '-f', 'pyrept.behave_formatter:PyreptFormatter',
                        '-o', os.devnull, '-D', 'pyrept_json=out/r.json', '-D', 'pyrept_html=out/r.html',
                        '-D', 'pyrept_title=Shop BDD'],
                       cwd=tmp, check=False, capture_output=True)
        with open(os.path.join(tmp, 'out', 'r.json'), encoding='utf-8') as fh:
            data = json.load(fh)
        self.assertEqual(data['test_report_title'], 'Shop BDD')
        results = {r['name']: r for r in data['test_results']}
        self.assertEqual(sorted(results), sorted([
            'Shop :: Attach', 'Shop :: Small 1 -- @1.1', 'Shop :: Small 9 -- @1.2',
            'Shop :: Hook breaks', 'Other :: Plain']))
        attached = results['Shop :: Attach']['metadata']['attachments']
        self.assertEqual([a['content_type'] for a in attached], ['image/png', 'text/plain'])
        self.assertEqual(attached[0]['data'], 'iVBORw==')
        self.assertEqual(results['Shop :: Small 9 -- @1.2']['result'], 'failed')
        self.assertIn('too big', results['Shop :: Small 9 -- @1.2']['traceback'])
        self.assertEqual(results['Shop :: Hook breaks']['result'], 'error')
        self.assertIn('hook boom', results['Shop :: Hook breaks']['traceback'])
        self.assertIn('@shop', results['Shop :: Attach']['metadata']['tags'])
        self.assertEqual(results['Other :: Plain']['metadata']['tags'], [])
        self.assertIn('Given a step that passes', results['Shop :: Attach']['description'])  # background step
        with open(os.path.join(tmp, 'out', 'r.html'), encoding='utf-8') as fh:
            self.assertIn('data:image/png;base64,iVBORw==', fh.read())


@unittest.skipUnless(HAS_BEHAVE, 'behave not installed')
class BehaveFormatterUnitTests(unittest.TestCase):
    """Drives the formatter in-process with stand-in model objects."""

    def setUp(self):
        import shutil
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)

    def _formatter(self, **userdata):
        import io
        import os
        from types import SimpleNamespace
        from behave.formatter.base import StreamOpener
        from pyrept.behave_formatter import PyreptFormatter
        userdata.setdefault('pyrept_html', os.path.join(self.tmp, 'r.html'))
        userdata.setdefault('pyrept_json', os.path.join(self.tmp, 'r.json'))
        return PyreptFormatter(StreamOpener(stream=io.StringIO()), SimpleNamespace(userdata=userdata))

    def test_junit_and_baseline_userdata(self):
        import json
        import os
        import xml.etree.ElementTree as ET
        from behave.model_core import Status
        baseline = os.path.join(self.tmp, 'previous.json')
        with open(baseline, 'w', encoding='utf-8') as fh:
            json.dump({'test_results': [{'name': 'F :: a', 'result': 'failed'}]}, fh)
        junit = os.path.join(self.tmp, 'j.xml')
        formatter = self._formatter(pyrept_junit=junit, pyrept_baseline=baseline)
        self._run(formatter, [('F', [self._scenario('a', Status.passed, [self._step(Status.passed)])])])
        case = ET.parse(junit).getroot().find('testsuite/testcase')
        self.assertEqual((case.get('classname'), case.get('name')), ('F', 'a'))
        with open(os.path.join(self.tmp, 'r.json'), encoding='utf-8') as fh:
            self.assertEqual(json.load(fh)['comparison']['fixed'], ['F :: a'])

    def _step(self, status, name='a step', error=None):
        from types import SimpleNamespace
        return SimpleNamespace(keyword='Given ', name=name, status=status, error_message=error)

    def _scenario(self, name, status, steps, **extra):
        from types import SimpleNamespace
        values = dict(name=name, status=status, steps=steps, all_steps=steps, tags=[], effective_tags=[],
                      location='f.feature:3', duration=0.5, error_message=None)
        values.update(extra)
        return SimpleNamespace(**values)

    def _run(self, formatter, features):
        from types import SimpleNamespace
        for feature_name, scenarios in features:
            formatter.feature(SimpleNamespace(name=feature_name))
            for scenario in scenarios:
                formatter.scenario(scenario)
            formatter.eof()
        formatter.close()
        return {r['name']: r for r in formatter.collector.test_results}

    def test_outcomes_tracebacks_and_attachments(self):
        from behave.model_core import Status
        formatter = self._formatter(pyrept_title='Unit BDD')
        formatter.embedding('image/png', b'ignored: no scenario yet')
        ok = self._scenario('ok', Status.passed, [self._step(Status.passed)], effective_tags=['smoke'])
        bad_steps = [self._step(Status.passed), self._step(Status.failed, 'boom step', 'AssertionError: x'),
                     self._step(Status.skipped)]
        bad = self._scenario('bad', Status.failed, bad_steps)
        hook = self._scenario('hook', 'hook_error', [self._step(Status.passed)],
                              error_message='HOOK-ERROR in before_scenario')
        from types import SimpleNamespace
        formatter.feature(SimpleNamespace(name='F'))
        formatter.scenario(ok)
        formatter.embedding('image/png', b'\x89PNG')
        formatter.embedding('text/plain', 'text data')
        formatter.scenario(bad)
        formatter.scenario(hook)
        formatter.eof()
        formatter.close()
        results = {r['name']: r for r in formatter.collector.test_results}

        self.assertEqual(formatter.collector.title, 'Unit BDD')
        self.assertEqual(results['F :: ok']['result'], 'passed')
        self.assertEqual(results['F :: ok']['metadata']['tags'], ['@smoke'])
        self.assertTrue(results['F :: ok']['description'].startswith('@smoke\nGiven a step  [passed]'))
        attachments = results['F :: ok']['metadata']['attachments']
        self.assertEqual([a['name'] for a in attachments], ['Attachment 1', 'Attachment 2'])
        self.assertEqual(attachments[1]['data'], 'dGV4dCBkYXRh')
        self.assertEqual(results['F :: bad']['result'], 'failed')
        self.assertTrue(results['F :: bad']['traceback'].startswith('Given boom step  [failed]'))
        self.assertIn('AssertionError: x', results['F :: bad']['traceback'])
        self.assertNotIn('attachments', results['F :: bad']['metadata'])
        self.assertEqual(results['F :: hook']['result'], 'error')
        self.assertEqual(results['F :: hook']['traceback'], 'HOOK-ERROR in before_scenario')

    def test_scenarios_are_grouped_by_feature_and_written(self):
        import json
        import os
        from behave.model_core import Status
        results = self._run(self._formatter(), [
            ('First', [self._scenario('a', Status.passed, [self._step(Status.passed)])]),
            ('', [self._scenario('  ', Status.skipped, [], tags=['wip'], effective_tags=None, all_steps=None)]),
        ])
        self.assertIn('First :: a', results)
        unnamed = results['Scenario']  # no feature name, blank scenario name
        self.assertEqual(unnamed['result'], 'skipped')
        self.assertEqual(unnamed['metadata']['tags'], ['@wip'])
        with open(os.path.join(self.tmp, 'r.json'), encoding='utf-8') as fh:
            self.assertEqual(json.load(fh)['test_summary']['total'], 2)

    def test_status_strings_and_unknown_status(self):
        from pyrept.behave_formatter import map_status
        self.assertEqual(map_status(None), 'skipped')
        self.assertEqual(map_status('hook_error'), 'error')
        self.assertEqual(map_status('pending_warn'), 'skipped')
        self.assertEqual(map_status('something_new'), 'error')


@unittest.skipUnless(HAS_BEHAVE, 'behave not installed')
class BehaveSummaryTests(unittest.TestCase):
    def test_markdown_and_github_summary_userdata(self):
        import os
        import shutil
        import subprocess
        import sys
        import tempfile
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        os.makedirs(os.path.join(tmp, 'features', 'steps'))
        with open(os.path.join(tmp, 'features', 'demo.feature'), 'w') as fh:
            fh.write('Feature: Demo\n  Scenario: Failing\n    Given a step that fails\n')
        with open(os.path.join(tmp, 'features', 'steps', 'steps.py'), 'w') as fh:
            fh.write('from behave import given\n\n@given("a step that fails")\ndef bad(context):\n'
                     '    assert False, "nope"\n')
        summary = os.path.join(tmp, 'gh.md')
        env = dict(os.environ, GITHUB_STEP_SUMMARY=summary)
        subprocess.run([sys.executable, '-m', 'behave', '-f', 'pyrept.behave_formatter:PyreptFormatter',
                        '-o', os.devnull, '-D', 'pyrept_json=out.json', '-D', 'pyrept_html=out.html',
                        '-D', 'pyrept_markdown=out/summary.md', '-D', 'pyrept_github_summary=yes'],
                       cwd=tmp, check=False, capture_output=True, env=env)
        for path in (os.path.join(tmp, 'out', 'summary.md'), summary):
            with open(path, encoding='utf-8') as fh:
                text = fh.read()
            self.assertIn('❌ BDD Test Report: 1 failed', text)
            self.assertIn('Demo :: Failing', text)

    def test_truthy(self):
        from pyrept.behave_formatter import _truthy
        for value in ('1', 'true', 'YES', ' on '):
            self.assertTrue(_truthy(value))
        for value in ('', '0', 'false', 'no', None):
            self.assertFalse(_truthy(value))
