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
    assert summary['percentage'] == 20.0

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
