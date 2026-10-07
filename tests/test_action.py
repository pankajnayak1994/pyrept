"""The GitHub Action (action.yml) and the script that does its work."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, 'action', 'pyrept-action.sh')
ACTION = os.path.join(ROOT, 'action.yml')
FIXTURES = os.path.join(ROOT, 'tests', 'fixtures')
BASH = shutil.which('bash')


@unittest.skipIf(BASH is None or sys.platform.startswith('win'), 'needs bash')
class ActionScriptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.output = os.path.join(self.tmp, 'github_output')
        self.step_summary = os.path.join(self.tmp, 'step_summary.md')

    def _run(self, **inputs):
        env = {k: v for k, v in os.environ.items() if not k.startswith(('PYREPT_', 'GITHUB_'))}
        env.update({'PYREPT_PYTHON': sys.executable, 'RUNNER_TEMP': self.tmp, 'GITHUB_OUTPUT': self.output,
                    'GITHUB_STEP_SUMMARY': self.step_summary, 'PYTHONPATH': ROOT})
        env.update({'PYREPT_INPUT_' + k.upper(): v for k, v in inputs.items()})
        result = subprocess.run([BASH, SCRIPT], cwd=self.tmp, env=env, capture_output=True, text=True, check=False)
        outputs = {}
        if os.path.exists(self.output):
            with open(self.output, encoding='utf-8') as fh:
                outputs = dict(line.split('=', 1) for line in fh.read().splitlines() if '=' in line)
        return result, outputs

    def _report(self, outcomes, name='report.json'):
        path = os.path.join(self.tmp, name)
        results = [{'name': n, 'result': r, 'metadata': {}} for n, r in outcomes.items()]
        counts = {k: sum(1 for r in outcomes.values() if r == k) for k in ('passed', 'failed', 'error', 'skipped')}
        executed = len(outcomes) - counts['skipped']
        counts.update(total=len(outcomes), percentage=round(counts['passed'] * 100.0 / executed, 2) if executed else 0)
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump({'test_report_title': 'CI', 'test_summary': counts, 'test_results': results}, fh)
        return path

    def test_summary_outputs_and_job_summary(self):
        self._report({'a': 'passed', 'b': 'failed'})
        result, outputs = self._run(report='report.json')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((outputs['total'], outputs['failed'], outputs['pass-rate'], outputs['gate-status']),
                         ('2', '1', '50.0', '0'))
        with open(outputs['summary-file'], encoding='utf-8') as fh:
            self.assertIn('❌ CI: 1 failed', fh.read())
        with open(self.step_summary, encoding='utf-8') as fh:
            self.assertIn('❌ CI: 1 failed', fh.read())

    def test_job_summary_can_be_turned_off(self):
        self._report({'a': 'passed'})
        result, _ = self._run(report='report.json', job_summary='false')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(os.path.exists(self.step_summary))

    def test_gates_are_reported_not_raised(self):
        self._report({'a': 'passed', 'b': 'failed'})
        result, outputs = self._run(report='report.json', fail_on_failure='true')
        self.assertEqual(result.returncode, 0, result.stderr)  # the action's last step fails the job
        self.assertEqual(outputs['gate-status'], '1')
        _, outputs = self._run(report='report.json', fail_under='40')
        self.assertEqual(outputs['gate-status'], '0')

    def test_convert_with_globs(self):
        os.makedirs(os.path.join(self.tmp, 'results'))
        for name in ('surefire.xml', 'jest.xml'):
            shutil.copy(os.path.join(FIXTURES, 'junit', name), os.path.join(self.tmp, 'results', name))
        result, outputs = self._run(report='out/report.json', convert_from='junit',
                                    convert_inputs='results/*.xml', title='Java + JS',
                                    junit='out/junit.xml', report_url='https://ci.example/r.html')
        self.assertEqual(result.returncode, 0, result.stderr)
        for name in ('report.json', 'report.html', 'junit.xml'):
            self.assertTrue(os.path.exists(os.path.join(self.tmp, 'out', name)), name)
        self.assertGreater(int(outputs['total']), 0)
        with open(outputs['summary-file'], encoding='utf-8') as fh:
            text = fh.read()
        self.assertIn('Java + JS', text)
        self.assertIn('(https://ci.example/r.html)', text)

    def test_errors(self):
        result, _ = self._run(report='missing.json')
        self.assertEqual(result.returncode, 2)
        self.assertIn('::error::pyrept report not found', result.stderr)
        result, _ = self._run(convert_from='junit', convert_inputs='nothing/*.xml')
        self.assertEqual(result.returncode, 2)
        self.assertIn('no files match', result.stderr)
        result, _ = self._run(convert_from='junit')
        self.assertEqual(result.returncode, 2)
        self._report({'a': 'passed'})
        result, _ = self._run(report='report.json', fail_under='lots')
        self.assertEqual(result.returncode, 2)


class ActionDefinitionTests(unittest.TestCase):
    def test_every_input_reaches_the_script(self):
        with open(ACTION, encoding='utf-8') as fh:
            action = fh.read()
        with open(SCRIPT, encoding='utf-8') as fh:
            script = fh.read()
        inputs_block = action.split('\ninputs:\n', 1)[1].split('\noutputs:\n', 1)[0]
        inputs = re.findall(r'^  ([a-z][a-z-]*):$', inputs_block, re.MULTILINE)
        self.assertIn('fail-under', inputs)
        for name in inputs:
            if name == 'pr-comment':
                continue  # used by the comment step in action.yml itself
            variable = 'PYREPT_INPUT_' + name.upper().replace('-', '_')
            self.assertIn('%s: ${{ inputs.%s }}' % (variable, name), action, name)
            self.assertIn(variable, script, name)

    def test_outputs_are_written_by_the_script(self):
        with open(ACTION, encoding='utf-8') as fh:
            action = fh.read()
        with open(SCRIPT, encoding='utf-8') as fh:
            script = fh.read()
        for name in re.findall(r'steps\.summary\.outputs\.([a-z-]+)', action):
            self.assertIn("print('%s=" % name, script, name)
