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
