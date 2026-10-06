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
    assert labels == {'test_labels [named]': 'failed', 'test_labels (<subtest>)': 'failed',
                      "test_labels (case='skip')": 'skipped'}, labels
    names = [n for n in results if 'test_sub' in n]
    assert len(names) == len(set(names)), names
    failed = [n for n in names if '(i=1)' in n]
    assert failed, names
    assert not any('(i=0)' in n or '(i=2)' in n for n in names)  # passing subtests are not listed
