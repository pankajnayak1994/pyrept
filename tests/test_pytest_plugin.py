import json

import pytest

SAMPLE_TESTS = '''
import pytest

def test_pass():
    """Checks the happy path. Bug 1234"""
    assert True

def test_fail():
    """Fails on purpose."""
    assert 1 == 2

@pytest.mark.skip(reason="not today")
def test_skip():
    pass

@pytest.fixture
def broken():
    raise RuntimeError("fixture exploded")

def test_setup_error(broken):
    pass

@pytest.mark.xfail
def test_expected_failure():
    assert False
'''


def _entry_point_installed():
    try:
        from importlib.metadata import entry_points
    except ImportError:  # pragma: no cover
        return False
    eps = entry_points()
    group = eps.select(group='pytest11') if hasattr(eps, 'select') else eps.get('pytest11', [])
    return any(ep.name == 'pyrept' for ep in group)


def _run(pytester, *args):
    # When pyrept is pip-installed, pytest auto-loads the plugin via its entry
    # point; otherwise load it explicitly.
    extra = () if _entry_point_installed() else ('-p', 'pyrept.pytest_plugin')
    return pytester.runpytest(*extra, *args)


def _load(path):
    with open(str(path), encoding='utf-8') as fh:
        return json.load(fh)


def test_plugin_is_inactive_by_default(pytester):
    pytester.makepyfile(SAMPLE_TESTS)
    _run(pytester)
    assert not (pytester.path / 'report.html').exists()
    assert not (pytester.path / 'report.json').exists()


def test_generates_html_and_json_reports(pytester):
    pytester.makepyfile(SAMPLE_TESTS)
    result = _run(pytester, '--pyrept')
    result.assert_outcomes(passed=1, failed=1, skipped=1, errors=1, xfailed=1)
    result.stdout.fnmatch_lines(['*pyrept HTML report:*report.html*'])

    html = (pytester.path / 'report.html').read_text(encoding='utf-8')
    assert 'test_pass' in html
    assert 'Checks the happy path' in html

    data = _load(pytester.path / 'report.json')
    summary = data['test_summary']
    assert summary['total'] == 5
    assert summary['passed'] == 1
    assert summary['failed'] == 1
    assert summary['error'] == 1
    assert summary['skipped'] == 2  # explicit skip + xfail
    assert summary['percentage'] == 33.33  # skipped tests are excluded from the pass rate

    by_name = {r['name'].split('::')[-1]: r for r in data['test_results']}
    assert by_name['test_pass']['description'].startswith('Checks the happy path')
    assert 'assert 1 == 2' in by_name['test_fail']['traceback']
    assert 'fixture exploded' in by_name['test_setup_error']['traceback']
    assert by_name['test_skip']['result'] == 'skipped'


def test_custom_paths_from_command_line(pytester):
    pytester.makepyfile(SAMPLE_TESTS)
    _run(pytester,
         '--pyrept-html=out/custom.html', '--pyrept-json=out/custom.json')
    assert (pytester.path / 'out' / 'custom.html').exists()
    assert (pytester.path / 'out' / 'custom.json').exists()


def test_failure_screenshot_from_page_fixture(pytester):
    pytester.makepyfile('''
        import pytest

        class FakePage:
            def screenshot(self, full_page=False):
                return b"\\x89PNG fake"

        @pytest.fixture
        def page():
            return FakePage()

        def test_ui_fails(page):
            assert False, "button missing"

        def test_ui_passes(page):
            assert True
    ''')
    _run(pytester, '--pyrept')
    data = _load(pytester.path / 'report.json')
    by_name = {r['name'].split('::')[-1]: r for r in data['test_results']}
    shots = by_name['test_ui_fails']['metadata']['attachments']
    assert shots[0]['content_type'] == 'image/png'
    assert shots[0]['data']
    assert 'attachments' not in by_name['test_ui_passes']['metadata']


def test_no_screenshots_flag(pytester):
    pytester.makepyfile('''
        import pytest

        @pytest.fixture
        def page():
            class P:
                def screenshot(self, full_page=False):
                    return b"png"
            return P()

        def test_ui_fails(page):
            assert False
    ''')
    _run(pytester, '--pyrept', '--pyrept-no-screenshots')
    data = _load(pytester.path / 'report.json')
    assert 'attachments' not in data['test_results'][0]['metadata']


def test_paths_from_ini(pytester):
    pytester.makeini('''
        [pytest]
        pyrept = true
        pyrept_html = ini/report.html
        pyrept_json = ini/report.json
    ''')
    pytester.makepyfile(SAMPLE_TESTS)
    _run(pytester)
    assert (pytester.path / 'ini' / 'report.html').exists()
    assert _load(pytester.path / 'ini' / 'report.json')['test_summary']['total'] == 5


def _by_name(data):
    return {r['name']: r for r in data['test_results']}


def _has_plugin(module):
    try:
        __import__(module)
    except ImportError:
        return False
    return True


def test_collection_errors_are_reported(pytester):
    # Without this the report looked clean (0 tests) while pytest failed.
    pytester.makepyfile(test_ok='def test_ok():\n    pass\n',
                        test_broken='import module_that_does_not_exist\n')
    _run(pytester, '--pyrept')
    data = _load(pytester.path / 'report.json')
    assert data['test_summary']['error'] == 1
    broken = _by_name(data)['test_broken.py']
    assert broken['result'] == 'error'
    assert 'module_that_does_not_exist' in broken['traceback']
    assert broken['metadata']['phase'] == 'collect'


def test_module_level_skip_is_reported(pytester):
    pytester.makepyfile('''
        import pytest
        pytest.skip("windows only", allow_module_level=True)

        def test_never():
            pass
    ''')
    _run(pytester, '--pyrept')
    data = _load(pytester.path / 'report.json')
    assert data['test_summary']['skipped'] == 1
    assert data['test_results'][0]['traceback'] == 'Skipped: windows only'


def test_skip_and_xfail_reasons_and_strict_xpass(pytester):
    pytester.makepyfile('''
        import pytest

        @pytest.mark.skip(reason="not today")
        def test_skip():
            pass

        @pytest.mark.xfail(reason="bug 42")
        def test_xfail():
            assert False

        @pytest.mark.xfail(reason="bug 43")
        def test_xpass():
            pass

        @pytest.mark.xfail(strict=True)
        def test_strict_xpass():
            pass

        def test_skip_in_body():
            pytest.skip("runtime condition")

        @pytest.mark.skip(reason="")
        def test_skip_no_reason():
            pass

        @pytest.mark.xfail
        def test_xfail_no_reason():
            assert False

        def test_blank_output():
            print("   ")
            assert False
    ''')
    _run(pytester, '--pyrept')
    results = {k.split('::')[-1]: v for k, v in _by_name(_load(pytester.path / 'report.json')).items()}
    assert results['test_skip']['traceback'] == 'Skipped: not today'
    assert results['test_xfail']['result'] == 'skipped'
    assert results['test_xfail']['traceback'] == 'Expected failure: bug 42'
    assert results['test_xpass']['result'] == 'passed'
    assert results['test_strict_xpass']['result'] == 'failed'
    assert 'XPASS(strict)' in results['test_strict_xpass']['traceback']
    assert results['test_skip_in_body']['result'] == 'skipped'
    assert results['test_skip_in_body']['traceback'] == 'Skipped: runtime condition'
    assert results['test_skip_no_reason']['traceback'] is None
    assert results['test_xfail_no_reason']['traceback'] == 'Expected failure'
    assert 'attachments' not in results['test_blank_output']['metadata']  # whitespace-only output is dropped


def test_teardown_error_is_recorded_separately(pytester):
    pytester.makepyfile('''
        import pytest

        @pytest.fixture
        def res():
            yield
            raise RuntimeError("cleanup failed")

        def test_uses_res(res):
            pass
    ''')
    _run(pytester, '--pyrept')
    results = _by_name(_load(pytester.path / 'report.json'))
    assert results['test_teardown_error_is_recorded_separately.py::test_uses_res']['result'] == 'passed'
    teardown = results['test_teardown_error_is_recorded_separately.py::test_uses_res::teardown']
    assert teardown['result'] == 'error'
    assert 'cleanup failed' in teardown['traceback']


def test_metadata_tags_parametrize_and_captured_output(pytester):
    pytester.makepyfile('''
        import pytest

        @pytest.mark.smoke
        @pytest.mark.parametrize("n", [1, 2])
        def test_param(n):
            print("value is", n)
            assert n == 1
    ''')
    _run(pytester, '--pyrept', '--pyrept-title=Nightly')
    data = _load(pytester.path / 'report.json')
    assert data['test_report_title'] == 'Nightly'
    assert data['environment']['Framework'].startswith('pytest ')
    results = {k.split('::')[-1]: v for k, v in _by_name(data).items()}
    ok, bad = results['test_param[1]'], results['test_param[2]']
    assert ok['metadata']['tags'] == ['smoke']
    assert ok['metadata']['location'].endswith(':3')  # decorated functions start at their first decorator
    assert isinstance(ok['metadata']['duration'], float)
    assert 'attachments' not in ok['metadata']  # output only kept for problems
    stdout = [a for a in bad['metadata']['attachments'] if 'stdout' in a['name']]
    assert stdout and 'value is 2' in stdout[0]['text']


def test_ini_paths_are_relative_to_the_ini_file(pytester, monkeypatch):
    pytester.makeini('''
        [pytest]
        pyrept = true
        pyrept_html = reports/report.html
        pyrept_json = reports/report.json
    ''')
    sub = pytester.mkpydir('pkg')
    (sub / 'test_x.py').write_text('def test_x():\n    pass\n')
    monkeypatch.chdir(sub)
    _run(pytester, '--rootdir', str(pytester.path), '-c', str(pytester.path / 'tox.ini'))
    assert (pytester.path / 'reports' / 'report.json').exists()
    assert not (sub / 'reports').exists()


def test_ini_override_without_ini_file_is_relative_to_the_invocation_dir(pytester, monkeypatch):
    sub = pytester.mkpydir('pkg')
    (sub / 'test_x.py').write_text('def test_x():\n    pass\n')
    monkeypatch.chdir(sub)
    _run(pytester, '-o', 'pyrept=true', '-o', 'pyrept_json=o/out.json')
    assert (sub / 'o' / 'out.json').exists()


def test_cli_paths_are_relative_to_the_invocation_dir(pytester, monkeypatch):
    sub = pytester.mkpydir('pkg')
    (sub / 'test_x.py').write_text('def test_x():\n    pass\n')
    monkeypatch.chdir(sub)
    _run(pytester, '--pyrept-json=out.json')
    assert (sub / 'out.json').exists()
    assert (sub / 'report.html').exists()


def test_screenshot_failure_does_not_break_the_run(pytester):
    pytester.makepyfile('''
        import pytest

        class ClosedPage:
            def screenshot(self, full_page=False):
                raise RuntimeError("Target page, context or browser has been closed")

        class Driver:
            def get_screenshot_as_png(self):
                return b"selenium"

        class DeadDriver:
            def get_screenshot_as_png(self):
                raise RuntimeError("invalid session id")

        @pytest.fixture
        def page():
            return ClosedPage()

        @pytest.fixture
        def driver():
            return Driver()

        def test_closed_page(page):
            assert False

        def test_selenium(driver):
            assert False

        @pytest.fixture
        def browser():
            return DeadDriver()

        def test_dead_selenium(browser):
            assert False
    ''')
    _run(pytester, '--pyrept')
    results = {k.split('::')[-1]: v for k, v in _by_name(_load(pytester.path / 'report.json')).items()}
    assert all(a['name'] != 'Screenshot on failure'
               for a in results['test_closed_page']['metadata'].get('attachments', []))
    shots = [a for a in results['test_selenium']['metadata']['attachments'] if a['name'] == 'Screenshot on failure']
    assert shots[0]['data'] == 'c2VsZW5pdW0='
    assert results['test_dead_selenium']['result'] == 'failed'
    assert 'attachments' not in results['test_dead_selenium']['metadata']


@pytest.mark.skipif(not _has_plugin('pytest_rerunfailures'), reason='pytest-rerunfailures not installed')
def test_reruns_are_not_counted_as_skipped(pytester):
    pytester.makepyfile('''
        import pytest
        calls = []

        @pytest.mark.flaky(reruns=2)
        def test_flaky():
            calls.append(1)
            assert len(calls) == 2

        @pytest.mark.flaky(reruns=1)
        def test_always_fails():
            assert False
    ''')
    _run(pytester, '--pyrept')
    data = _load(pytester.path / 'report.json')
    assert data['test_summary'] == dict(data['test_summary'], total=2, passed=1, failed=1, skipped=0)
    results = {k.split('::')[-1]: v for k, v in _by_name(data).items()}
    assert results['test_flaky']['metadata']['retries'] == 1
    assert results['test_flaky']['metadata']['flaky'] is True
    assert results['test_always_fails']['metadata']['retries'] == 1
    assert results['test_always_fails']['metadata']['flaky'] is False


@pytest.mark.skipif(not _has_plugin('xdist'), reason='pytest-xdist not installed')
def test_xdist_keeps_descriptions_and_writes_one_report(pytester):
    pytester.makepyfile('''
        import pytest

        @pytest.mark.smoke
        def test_a():
            """Documented A."""

        def test_b():
            """Documented B."""
            assert False
    ''')
    result = _run(pytester, '--pyrept', '-n', '2')
    result.assert_outcomes(passed=1, failed=1)
    data = _load(pytester.path / 'report.json')
    assert data['test_summary']['total'] == 2
    results = {k.split('::')[-1]: v for k, v in _by_name(data).items()}
    assert results['test_a']['description'] == 'Documented A.'
    assert results['test_a']['metadata']['tags'] == ['smoke']
    assert results['test_b']['description'] == 'Documented B.'


@pytest.mark.skipif(int(pytest.__version__.split('.')[0]) < 9 and not _has_plugin('pytest_subtests'),
                    reason='needs pytest >= 9 or pytest-subtests')
def test_subtests_get_distinct_names(pytester):
    pytester.makepyfile('''
        import unittest

        class T(unittest.TestCase):
            def test_sub(self):
                for i in range(3):
                    with self.subTest(i=i):
                        self.assertNotEqual(i, 1)

            def test_labels(self):
                with self.subTest("named"):
                    self.fail("message only")
                with self.subTest():
                    self.fail("no message, no params")
                with self.subTest(case="skip"):
                    self.skipTest("not here")
    ''')
    _run(pytester, '--pyrept')
    results = _by_name(_load(pytester.path / 'report.json'))
    labels = {name.split('::')[-1]: r['result'] for name, r in results.items() if 'test_labels ' in name}
    assert labels['test_labels [named]'] == 'failed'
    assert labels['test_labels (<subtest>)'] == 'failed'
    skipped_labels = [(name, result) for name, result in labels.items() if name.startswith('test_labels (case=')]
    assert len(skipped_labels) == 1, labels
    assert 'skip' in skipped_labels[0][0]
    assert skipped_labels[0][1] == 'skipped'
    names = [n for n in results if 'test_sub' in n]
    assert len(names) == len(set(names)), names
    failed = [n for n in names if '(i=1)' in n]
    assert failed, names
    assert not any('(i=0)' in n or '(i=2)' in n for n in names)  # passing subtests are not listed


def test_junit_and_baseline_options(pytester):
    import xml.etree.ElementTree as ET
    pytester.makepyfile(test_a='def test_one():\n    pass\n\ndef test_two():\n    pass\n')
    first = _run(pytester, '--pyrept-baseline=report.json', '--pyrept-junit=out/junit.xml')
    first.stdout.fnmatch_lines(['*pyrept JUnit report:*junit.xml*'])
    assert 'new failure' not in first.stdout.str()  # no baseline on the first run
    assert _load(pytester.path / 'report.json')['comparison'] is None
    suite = ET.parse(str(pytester.path / 'out' / 'junit.xml')).getroot().find('testsuite')
    assert [c.get('name') for c in suite.findall('testcase')] == ['test_one', 'test_two']

    pytester.makepyfile(test_a='def test_one():\n    assert False\n\ndef test_three():\n    pass\n')
    second = _run(pytester, '--pyrept-baseline=report.json')
    second.stdout.fnmatch_lines(
        ['*pyrept: 1 new failure, 0 fixed, 0 still failing, 1 new, 1 removed (vs report.json)*'])
    comparison = _load(pytester.path / 'report.json')['comparison']
    assert comparison['new_failures'] == ['test_a.py::test_one']
    assert comparison['removed_tests'] == ['test_a.py::test_two']
    assert 'data-change="new-failure"' in (pytester.path / 'report.html').read_text(encoding='utf-8')


def test_junit_and_baseline_from_ini(pytester):
    pytester.makeini('''
        [pytest]
        pyrept = true
        pyrept_junit = reports/junit.xml
        pyrept_baseline = reports/previous.json
    ''')
    (pytester.path / 'reports').mkdir()
    (pytester.path / 'reports' / 'previous.json').write_text(
        '{"test_results": [{"name": "test_b.py::test_x", "result": "failed"}]}', encoding='utf-8')
    pytester.makepyfile(test_b='def test_x():\n    pass\n')
    _run(pytester)
    assert (pytester.path / 'reports' / 'junit.xml').exists()
    assert _load(pytester.path / 'report.json')['comparison']['fixed'] == ['test_b.py::test_x']


def test_unreadable_baseline_does_not_fail_the_run(pytester):
    (pytester.path / 'broken.json').write_text('{oops', encoding='utf-8')
    pytester.makepyfile(test_c='def test_ok():\n    pass\n')
    result = _run(pytester, '--pyrept-baseline=broken.json')
    assert result.ret == 0
    assert _load(pytester.path / 'report.json')['comparison'] is None


KNOWN_FAILURE_TESTS = '''
def test_ok():
    pass

def test_known_bug():
    assert 1 == 2
'''


def test_markdown_summary_and_github_job_summary(pytester, monkeypatch):
    pytester.makepyfile(SAMPLE_TESTS)
    summary = pytester.path / 'step_summary.md'
    monkeypatch.setenv('GITHUB_STEP_SUMMARY', str(summary))
    result = _run(pytester, '--pyrept-markdown=out/summary.md', '--pyrept-github-summary')
    result.stdout.fnmatch_lines(['*pyrept Markdown summary: *summary.md*'])
    markdown = (pytester.path / 'out' / 'summary.md').read_text(encoding='utf-8')
    assert '### ❌ Test Report: 1 failed, 1 error' in markdown
    assert '<code>test_generates' not in markdown  # names come from the module under test
    assert 'test_fail' in markdown and 'fixture exploded' in markdown
    assert summary.read_text(encoding='utf-8') == markdown + '\n'
    assert (pytester.path / 'report.html').exists()  # --pyrept-markdown turns reporting on


def test_github_summary_outside_github_actions_is_skipped(pytester):
    pytester.makepyfile('def test_ok():\n    pass\n')
    result = _run(pytester, '--pyrept-github-summary')
    assert result.ret == 0
    assert (pytester.path / 'report.json').exists()


def test_fail_under(pytester):
    pytester.makepyfile(KNOWN_FAILURE_TESTS)
    result = _run(pytester, '--pyrept-fail-under=40')
    assert result.ret == 1  # a test failed: the threshold never turns that into a pass
    pytester.makepyfile('def test_ok():\n    pass\n\ndef test_skip():\n    import pytest; pytest.skip()\n')
    assert _run(pytester, '--pyrept-fail-under=100').ret == 0


def test_fail_under_limits_known_failures(pytester):
    pytester.makepyfile(KNOWN_FAILURE_TESTS)
    _run(pytester, '--pyrept')
    args = ('--pyrept-baseline=report.json', '--pyrept-ignore-known-failures')
    assert _run(pytester, *args, '--pyrept-fail-under=40').ret == 0  # 50% pass rate, known failure
    result = _run(pytester, *args, '--pyrept-fail-under=60')
    assert result.ret == 1
    result.stdout.fnmatch_lines(['*pyrept: pass rate 50.0% is below --pyrept-fail-under=60*'])


def test_fail_under_ignores_runs_where_everything_was_skipped(pytester):
    pytester.makepyfile('import pytest\n\ndef test_skip():\n    pytest.skip("later")\n')
    result = _run(pytester, '--pyrept-fail-under=90')
    assert result.ret == 0
    result.stdout.fnmatch_lines(['*no tests were executed, so --pyrept-fail-under was not checked*'])


def test_invalid_fail_under_is_a_usage_error(pytester):
    pytester.makepyfile('def test_ok():\n    pass\n')
    result = _run(pytester, '--pyrept-fail-under=lots')
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    result.stderr.fnmatch_lines(['*pyrept: fail-under must be a number between 0 and 100*'])


def test_ignore_known_failures(pytester):
    pytester.makepyfile(KNOWN_FAILURE_TESTS)
    assert _run(pytester, '--pyrept').ret == 1  # first run: writes the baseline
    result = _run(pytester, '--pyrept-baseline=report.json', '--pyrept-ignore-known-failures')
    assert result.ret == 0
    result.stdout.fnmatch_lines(['*pyrept: 1 known failure ignored*'])

    pytester.makepyfile(KNOWN_FAILURE_TESTS + '\ndef test_new_bug():\n    assert False\n')
    result = _run(pytester, '--pyrept-baseline=report.json', '--pyrept-ignore-known-failures')
    assert result.ret == 1
    result.stdout.fnmatch_lines(['*1 new failure, so --pyrept-ignore-known-failures does not apply*'])


def test_ignore_known_failures_needs_a_baseline(pytester):
    pytester.makepyfile(KNOWN_FAILURE_TESTS)
    result = _run(pytester, '--pyrept-ignore-known-failures')
    assert result.ret == 1
    result.stdout.fnmatch_lines(['*needs a --pyrept-baseline report*'])


def test_ignore_known_failures_keeps_failures_from_other_plugins(pytester):
    pytester.makepyfile(KNOWN_FAILURE_TESTS)
    _run(pytester, '--pyrept')
    # Like pytest-cov's --cov-fail-under: another plugin fails the run by counting a failure.
    pytester.makeconftest('''
import pytest

@pytest.hookimpl(tryfirst=True)
def pytest_sessionfinish(session):
    session.testsfailed += 1
''')
    result = _run(pytester, '--pyrept-baseline=report.json', '--pyrept-ignore-known-failures')
    assert result.ret == 1
    result.stdout.fnmatch_lines(['*another plugin also failed the run*'])


def test_ignore_known_failures_never_hides_collection_errors(pytester):
    pytester.makepyfile(KNOWN_FAILURE_TESTS)
    _run(pytester, '--pyrept')
    pytester.makepyfile(test_broken='import does_not_exist\n')
    result = _run(pytester, '--pyrept-baseline=report.json', '--pyrept-ignore-known-failures')
    assert result.ret == pytest.ExitCode.INTERRUPTED


def test_summary_and_gate_ini_options(pytester):
    pytester.makepyfile(KNOWN_FAILURE_TESTS)
    pytester.makeini('''
[pytest]
pyrept = true
pyrept_json = reports/report.json
pyrept_markdown = reports/summary.md
pyrept_baseline = reports/report.json
pyrept_fail_under = 10
pyrept_ignore_known_failures = true
''')
    assert _run(pytester).ret == 1  # no baseline yet
    assert (pytester.path / 'reports' / 'summary.md').exists()
    assert _run(pytester).ret == 0  # known failure, 50% >= 10%

    pytester.makeini('''
[pytest]
pyrept = true
pyrept_fail_under = 80
''')
    assert _run(pytester).ret == 1


def test_markdown_path_alone_in_ini_does_not_enable(pytester):
    pytester.makepyfile('def test_ok():\n    pass\n')
    pytester.makeini('[pytest]\npyrept_markdown = summary.md\npyrept_fail_under = 99\n')
    _run(pytester)
    assert not (pytester.path / 'summary.md').exists()
    assert not (pytester.path / 'report.html').exists()


def test_plugin_hooks_add_environment_attachments_and_context(pytester):
    pytester.makeconftest('''
from pyrept import make_attachment

def pytest_pyrept_environment(config):
    return {'Build': '1842'}

def pytest_pyrept_attachments(item, report):
    if report.when == 'call' and report.failed:
        return [make_attachment('server.log', 'text/plain', text='500 on /pay')]

def pytest_pyrept_context(config, context):
    context['test_report_title'] = 'Changed by a hook'
''')
    pytester.makepyfile('def test_ok():\n    pass\n\ndef test_bad():\n    assert False\n')
    _run(pytester, '--pyrept')
    data = _load(pytester.path / 'report.json')
    assert data['environment']['Build'] == '1842'
    assert data['test_report_title'] == 'Changed by a hook'
    results = {r['name'].split('::')[-1]: r for r in data['test_results']}
    attachments = results['test_bad']['metadata']['attachments']
    assert [a['text'] for a in attachments if a['name'] == 'server.log'] == ['500 on /pay']
    assert 'attachments' not in results['test_ok']['metadata']


def test_hooks_are_optional(pytester):
    pytester.makepyfile('def test_ok():\n    pass\n')
    assert _run(pytester, '--pyrept').ret == 0


FAKE_BROWSER = '''
import os
import pytest


class FakePage:
    def __init__(self):
        self.handlers = {}

    def on(self, event, handler):
        self.handlers.setdefault(event, []).append(handler)

    def remove_listener(self, event, handler):
        self.handlers[event].remove(handler)

    def emit(self, event, value):
        for handler in list(self.handlers.get(event, [])):
            handler(value)

    def screenshot(self, full_page=True):
        return b"\\x89PNG"


class Message:
    def __init__(self, type_, text):
        self.type, self.text = type_, text


@pytest.fixture
def output_path(tmp_path_factory, request):
    return str(tmp_path_factory.getbasetemp() / "test-results" / request.node.name)


@pytest.fixture
def page(output_path, request):
    page = FakePage()
    yield page
    assert page.handlers.get("console") == [], "listeners must be removed after the test"
    failed = getattr(request.node, "_pyrept_failed", False)
    if failed:  # like pytest-playwright with --tracing/--video retain-on-failure
        os.makedirs(output_path, exist_ok=True)
        for name in ("trace.zip", "video.webm", "test-failed-1.png"):
            open(os.path.join(output_path, name), "wb").close()
'''


def test_browser_console_and_playwright_artifacts(pytester):
    pytester.makeconftest(FAKE_BROWSER)
    pytester.makepyfile('''
from conftest import Message

def test_checkout(page):
    page.emit("console", Message("error", "Uncaught TypeError: x is undefined"))
    page.emit("pageerror", "ReferenceError: y")
    assert False

def test_fine(page):
    page.emit("console", Message("log", "hello"))
''')
    result = _run(pytester, '--pyrept-html=reports/report.html', '--pyrept-json=reports/report.json')
    assert result.ret == 1
    results = {r['name'].split('::')[-1]: r for r in _load(pytester.path / 'reports' / 'report.json')['test_results']}
    attachments = {a['name']: a for a in results['test_checkout']['metadata']['attachments']}
    assert attachments['Browser console']['text'] == (
        '[error] Uncaught TypeError: x is undefined\n[pageerror] ReferenceError: y')
    assert 'Screenshot on failure' in attachments
    trace = attachments['Playwright trace (open at https://trace.playwright.dev)']
    assert trace['path'].endswith('test-results/test_checkout/trace.zip')
    assert not trace['path'].startswith('/')  # relative to the HTML report
    assert attachments['Video']['content_type'] == 'video/webm'
    assert 'attachments' not in results['test_fine']['metadata']


def test_no_screenshots_option_disables_browser_evidence(pytester):
    pytester.makeconftest(FAKE_BROWSER)
    pytester.makepyfile('''
from conftest import Message

def test_checkout(page):
    page.emit("console", Message("error", "boom"))
    assert False
''')
    _run(pytester, '--pyrept', '--pyrept-no-screenshots')
    result = _load(pytester.path / 'report.json')['test_results'][0]
    assert 'attachments' not in result['metadata']


def test_pytest_bdd_scenarios(pytester):
    pytest.importorskip('pytest_bdd')
    pytester.makefile('.feature', checkout='''
Feature: Checkout
    @smoke
    Scenario: Pay with card
        Given a cart with 2 items
        When I pay with a declined card
        Then I see the confirmation page

    Scenario: Empty cart
        Given an empty cart
        Then the pay button is disabled
''')
    pytester.makepyfile(test_checkout='''
from pytest_bdd import given, scenarios, then, when

scenarios("checkout.feature")

@given("a cart with 2 items")
def cart():
    pass

@when("I pay with a declined card")
def pay():
    raise RuntimeError("card declined")

@then("I see the confirmation page")
def confirmation():
    pass

@given("an empty cart")
def empty():
    pass

@then("the pay button is disabled")
def disabled():
    pass
''')
    _run(pytester, '--pyrept')
    results = {r['name'].split('::')[-1]: r for r in _load(pytester.path / 'report.json')['test_results']}
    paid = results['test_pay_with_card']
    assert paid['result'] == 'failed'
    assert paid['description'].splitlines() == [
        'Feature: Checkout', 'Scenario: Pay with card',
        '  Given a cart with 2 items  [passed]',
        '  When I pay with a declined card  [failed]',
        '  Then I see the confirmation page  [skipped]']
    assert 'smoke' in paid['metadata']['tags']
    assert results['test_empty_cart']['description'].endswith('Then the pay button is disabled  [passed]')


@pytest.mark.skipif(not _has_plugin('xdist'), reason='pytest-xdist not installed')
def test_xdist_keeps_console_artifacts_and_hook_attachments(pytester):
    pytester.makeconftest(FAKE_BROWSER + '''
from pyrept import make_attachment

def pytest_pyrept_attachments(item, report):
    if report.when == "call" and report.failed:
        return [make_attachment("worker.log", "text/plain", text="from a worker")]
''')
    pytester.makepyfile('''
from conftest import Message

def test_checkout(page):
    page.emit("console", Message("error", "boom"))
    assert False

def test_other(page):
    pass
''')
    _run(pytester, '--pyrept', '-n', '2')
    results = {r['name'].split('::')[-1]: r for r in _load(pytester.path / 'report.json')['test_results']}
    names = [a['name'] for a in results['test_checkout']['metadata']['attachments']]
    assert names == ['Screenshot on failure', 'Browser console', 'worker.log',
                     'Playwright trace (open at https://trace.playwright.dev)', 'Video']


def test_browser_page_edge_cases(pytester):
    pytester.makeconftest(FAKE_BROWSER + '''

class BrokenPage(FakePage):
    def on(self, event, handler):
        raise RuntimeError("page closed")


class ClosingPage(FakePage):
    def remove_listener(self, event, handler):
        raise RuntimeError("page closed")


@pytest.fixture
def broken_page():
    return BrokenPage()


@pytest.fixture
def closing_page():
    return ClosingPage()
''')
    pytester.makepyfile('''
import pytest
from conftest import Message

def test_many_messages(page):
    for i in range(250):
        page.emit("console", Message("log", "line %d" % i))
        page.emit("pageerror", "err %d" % i)
    assert False

@pytest.fixture
def page_cannot_listen(broken_page):
    return broken_page

def test_listeners_fail(request, page_cannot_listen):
    assert False

def test_page_closed(closing_page):
    assert False
''')
    # The last two tests use other fixture names; alias them to "page" for the plugin.
    pytester.makeconftest(pytester.path.joinpath('conftest.py').read_text() + '''

@pytest.fixture(autouse=True)
def _alias(request):
    for name in ("broken_page", "closing_page"):
        if name in request.fixturenames:
            request.node.funcargs["page"] = request.getfixturevalue(name)
''')
    result = _run(pytester, '--pyrept')
    assert result.ret == 1
    results = {r['name'].split('::')[-1]: r for r in _load(pytester.path / 'report.json')['test_results']}
    console = [a for a in results['test_many_messages']['metadata']['attachments'] if a['name'] == 'Browser console']
    assert len(console[0]['text'].splitlines()) == 200
    for name in ('test_listeners_fail', 'test_page_closed'):
        assert results[name]['result'] == 'failed'


def test_missing_playwright_output_folder(pytester):
    pytester.makeconftest(FAKE_BROWSER.replace('if failed:', 'if False:'))
    pytester.makepyfile('def test_checkout(page):\n    assert False\n')
    _run(pytester, '--pyrept')
    names = [a['name'] for a in _load(pytester.path / 'report.json')['test_results'][0]['metadata']['attachments']]
    assert names == ['Screenshot on failure']


def test_bdd_step_matching_helpers():
    from types import SimpleNamespace
    from pyrept.pytest_plugin import PyreptAnnotator, _bdd_step_index
    bdd = {'steps': [('Given', 'a'), ('Given', 'a')], 'status': {0: 'passed'}}
    assert _bdd_step_index(bdd, SimpleNamespace(keyword='Given ', name='a')) == 1
    assert _bdd_step_index(bdd, SimpleNamespace(keyword='When', name='other')) is None
    request = SimpleNamespace(node=SimpleNamespace())
    annotator = PyreptAnnotator()
    annotator.pytest_bdd_after_step(request, SimpleNamespace(keyword='Given', name='a'))  # no scenario recorded
    annotator.pytest_bdd_step_error(request, SimpleNamespace(keyword='Given', name='a'))
    request.node._pyrept_bdd = {'steps': [('Given', 'a')], 'status': {}}
    annotator.pytest_bdd_step_error(request, SimpleNamespace(keyword='Then', name='unknown'))
    assert request.node._pyrept_bdd['status'] == {}


def test_hooks_returning_junk_are_ignored(pytester):
    pytester.makeconftest('''
def pytest_pyrept_environment(config):
    return ["not", "a", "dict"]

def pytest_pyrept_attachments(item, report):
    return ["not a dict", None]
''')
    pytester.makepyfile('def test_bad():\n    assert False\n')
    _run(pytester, '--pyrept')
    data = _load(pytester.path / 'report.json')
    assert 'not' not in data['environment']
    assert 'attachments' not in data['test_results'][0]['metadata']


def test_fail_under_overrides_a_forced_success(pytester):
    pytester.makepyfile(KNOWN_FAILURE_TESTS)
    pytester.makeconftest('''
import pytest

@pytest.hookimpl(tryfirst=True)
def pytest_sessionfinish(session):
    session.exitstatus = 0  # e.g. a plugin that tolerates failures
''')
    assert _run(pytester, '--pyrept').ret == 0
    result = _run(pytester, '--pyrept-fail-under=90')
    assert result.ret == 1
    result.stdout.fnmatch_lines(['*pass rate 50.0% is below --pyrept-fail-under=90*'])


def test_artifacts_attach_to_subtests_and_ignore_unknown_tests(tmp_path):
    from types import SimpleNamespace
    from pyrept.pytest_plugin import PyreptReporter
    reporter = PyreptReporter(html_path=str(tmp_path / 'report.html'), json_path=str(tmp_path / 'report.json'))
    reporter.test_results = [{'name': 't.py::test_x [step] (i=1)', 'metadata': {}}]
    artifact = {'name': 'Video', 'content_type': 'video/webm', 'path': str(tmp_path / 'test-results' / 'video.webm')}
    reporter._attach_artifacts(SimpleNamespace(nodeid='t.py::test_x', pyrept_artifacts=[artifact]))
    assert reporter.test_results[0]['metadata']['attachments'][0]['path'] == 'test-results/video.webm'
    reporter._attach_artifacts(SimpleNamespace(nodeid='t.py::test_other', pyrept_artifacts=[artifact]))
    reporter._attach_artifacts(SimpleNamespace(nodeid='t.py::test_x', pyrept_artifacts=[]))
    assert len(reporter.test_results[0]['metadata']['attachments']) == 1
