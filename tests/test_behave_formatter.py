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
