"""
pytest plugin that generates the same HTML and JSON reports as the nose2 plugin.

The plugin is registered automatically through the ``pytest11`` entry point but
stays inactive until you opt in, either on the command line::

    pytest --pyrept
    pytest --pyrept-html=reports/report.html --pyrept-json=reports/report.json
    pytest --pyrept --pyrept-junit=junit.xml --pyrept-baseline=report.json

or in ``pytest.ini`` / ``pyproject.toml``::

    [pytest]
    pyrept = true
    pyrept_html = reports/report.html
    pyrept_json = reports/report.json
"""
import inspect
import os
import platform
import time

import pytest

from .compare import load_baseline, summary_line
from .report import (
    DEFAULT_HTML_REPORT_PATH,
    DEFAULT_JSON_REPORT_PATH,
    build_context,
    make_attachment,
    new_summary_stats,
    record_outcome,
    write_reports,
)

_PLUGIN_NAME = 'pyrept-reporter'
_ANNOTATOR_NAME = 'pyrept-annotator'
_IGNORED_MARKERS = ('parametrize', 'usefixtures', 'filterwarnings')


def pytest_addoption(parser):
    group = parser.getgroup('pyrept', 'HTML/JSON test reports (pyrept)')
    group.addoption('--pyrept', action='store_true', default=False,
                    help='Generate pyrept HTML and JSON reports.')
    group.addoption('--pyrept-html', action='store', default=None, metavar='PATH',
                    help='Path of the HTML report (implies --pyrept). Default: %s' % DEFAULT_HTML_REPORT_PATH)
    group.addoption('--pyrept-json', action='store', default=None, metavar='PATH',
                    help='Path of the JSON report (implies --pyrept). Default: %s' % DEFAULT_JSON_REPORT_PATH)
    group.addoption('--pyrept-junit', action='store', default=None, metavar='PATH',
                    help='Also write a JUnit XML report to PATH (implies --pyrept).')
    group.addoption('--pyrept-baseline', action='store', default=None, metavar='PATH',
                    help='Compare with an earlier pyrept JSON report (it may be the file this run overwrites). '
                         'A missing file is ignored.')
    group.addoption('--pyrept-title', action='store', default=None, help='Report title.')
    group.addoption('--pyrept-no-screenshots', action='store_true', default=False,
                    help='Do not capture Playwright/Selenium screenshots for failing tests.')
    parser.addini('pyrept', type='bool', default=False, help='Always generate pyrept reports.')
    parser.addini('pyrept_html', default='', help='Path of the pyrept HTML report.')
    parser.addini('pyrept_json', default='', help='Path of the pyrept JSON report.')
    parser.addini('pyrept_junit', default='', help='Path of an extra JUnit XML report.')
    parser.addini('pyrept_baseline', default='', help='Earlier pyrept JSON report to compare with.')


def _ini_dir(config):
    # Paths in an ini file are relative to that file, not to wherever pytest was started.
    inipath = getattr(config, 'inipath', None)
    if inipath:
        return os.path.dirname(str(inipath))
    # No ini file: the value came from ``-o pyrept_html=...`` on the command line.
    return str(config.invocation_params.dir)


def _resolve(config, cli_value, ini_name, default):
    if cli_value:
        base = str(config.invocation_params.dir)
        path = cli_value
    elif config.getini(ini_name):
        base = _ini_dir(config)
        path = config.getini(ini_name)
    elif default:
        base = str(config.invocation_params.dir)
        path = default
    else:
        return None
    return os.path.realpath(os.path.join(base, os.path.expanduser(path)))


def pytest_configure(config):
    html_opt = config.getoption('pyrept_html')
    json_opt = config.getoption('pyrept_json')
    junit_opt = config.getoption('pyrept_junit')
    baseline_opt = config.getoption('pyrept_baseline')
    enabled = (config.getoption('pyrept') or html_opt or json_opt or junit_opt or baseline_opt
               or config.getini('pyrept'))
    if not enabled:
        return
    # Reports are built where the test runs (also inside xdist workers, whose
    # reports are sent to the controller with these extra attributes).
    config.pluginmanager.register(
        PyreptAnnotator(screenshots=not config.getoption('pyrept_no_screenshots')), _ANNOTATOR_NAME)
    # Do not write reports from xdist worker processes; the controller collects all results.
    if hasattr(config, 'workerinput'):
        return
    reporter = PyreptReporter(
        html_path=_resolve(config, html_opt, 'pyrept_html', DEFAULT_HTML_REPORT_PATH),
        json_path=_resolve(config, json_opt, 'pyrept_json', DEFAULT_JSON_REPORT_PATH),
        title=config.getoption('pyrept_title') or 'Test Report',
        junit_path=_resolve(config, junit_opt, 'pyrept_junit', None),
        baseline_path=_resolve(config, baseline_opt, 'pyrept_baseline', None),
    )
    config.pluginmanager.register(reporter, _PLUGIN_NAME)


def pytest_unconfigure(config):
    for name in (_PLUGIN_NAME, _ANNOTATOR_NAME):
        plugin = config.pluginmanager.get_plugin(name)
        if plugin is not None:
            config.pluginmanager.unregister(plugin)


def _description(item):
    obj = getattr(item, 'obj', None)
    doc = inspect.getdoc(obj) if obj is not None else None
    return doc or None


def _capture_screenshot(item):
    """
    Screenshot the browser of a failing test while it is still open.

    Works with pytest-playwright (``page`` fixture) and pytest-selenium /
    custom Selenium fixtures (``driver`` / ``selenium`` / ``browser``).
    """
    funcargs = getattr(item, 'funcargs', {}) or {}
    page = funcargs.get('page')
    if page is not None and hasattr(page, 'screenshot'):
        try:
            return make_attachment('Screenshot on failure', 'image/png', data=page.screenshot(full_page=True))
        except Exception:  # browser already closed, page crashed, ...
            return None
    for key in ('driver', 'selenium', 'browser'):
        driver = funcargs.get(key)
        if driver is not None and hasattr(driver, 'get_screenshot_as_png'):
            try:
                return make_attachment('Screenshot on failure', 'image/png', data=driver.get_screenshot_as_png())
            except Exception:
                return None
    return None


def _subtest_label(report):
    """`` [msg] (k=v)`` for subtest reports (pytest >= 9 or pytest-subtests), else ``None``."""
    context = getattr(report, 'context', None)
    if context is None or not hasattr(context, 'kwargs'):
        return None
    parts = []
    if getattr(context, 'msg', None) is not None:
        parts.append('[%s]' % context.msg)
    if context.kwargs:
        parts.append('(%s)' % ', '.join('%s=%r' % item for item in context.kwargs.items()))
    return ' '.join(parts) or '(<subtest>)'


def _skip_reason(report):
    longrepr = report.longrepr
    if isinstance(longrepr, tuple) and len(longrepr) == 3:
        reason = longrepr[2]
        reason = reason[len('Skipped: '):] if reason.startswith('Skipped: ') else reason
    else:
        reason = str(longrepr) if longrepr else ''
    # pytest uses the bare word "Skipped" when no reason was given
    return reason if reason and reason != 'Skipped' else None


class PyreptAnnotator:
    """Adds description, markers and failure screenshots to each test report."""

    def __init__(self, screenshots=True):
        self.screenshots = screenshots

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_makereport(self, item, call):
        outcome = yield
        report = outcome.get_result()
        report.pyrept_description = _description(item)
        report.pyrept_attachments = []
        report.pyrept_markers = sorted({m.name for m in item.iter_markers() if m.name not in _IGNORED_MARKERS})
        if self.screenshots and report.when == 'call' and report.failed:
            shot = _capture_screenshot(item)
            if shot:
                report.pyrept_attachments.append(shot)


class PyreptReporter:
    def __init__(self, html_path, json_path, title='Test Report', junit_path=None, baseline_path=None):
        self.html_path = html_path
        self.json_path = json_path
        self.junit_path = junit_path
        self.baseline_path = baseline_path
        self.comparison = None
        self.title = title
        self.summary_stats = new_summary_stats()
        self.test_results = []
        self._reruns = {}
        self._start = time.time()

    def _record(self, report, name, result):
        traceback = None
        if result in ('failed', 'error') and report.longrepr is not None:
            traceback = str(report.longrepr)
        elif result == 'skipped':
            reason = _skip_reason(report)
            if hasattr(report, 'wasxfail'):
                traceback = 'Expected failure: %s' % report.wasxfail if report.wasxfail else 'Expected failure'
            elif reason:
                traceback = 'Skipped: %s' % reason
        location = report.location or (report.nodeid, None, '')
        metadata = {
            'framework': 'pytest',
            'duration': round(getattr(report, 'duration', 0) or 0, 4),
            'phase': report.when,
            'location': '%s:%s' % (location[0], (location[1] or 0) + 1),
            'tags': getattr(report, 'pyrept_markers', []),
        }
        retries = self._reruns.pop(report.nodeid, 0) if report.when in ('call', 'setup') else 0
        if retries:
            metadata['retries'] = retries
            metadata['flaky'] = result == 'passed'
        attachments = list(getattr(report, 'pyrept_attachments', None) or [])
        if result in ('failed', 'error'):
            # Captured stdout/stderr/log of the failing test, as pytest shows it in the terminal.
            for title, content in getattr(report, 'sections', None) or []:
                if content and content.strip():
                    attachments.append(make_attachment(title, 'text/plain', text=content))
        record_outcome(
            self.summary_stats,
            self.test_results,
            name=name,
            outcome=result,
            description=getattr(report, 'pyrept_description', None),
            traceback=traceback,
            metadata=metadata,
            attachments=attachments or None,
        )

    def pytest_runtest_logreport(self, report):
        if report.outcome == 'rerun':  # pytest-rerunfailures: the final attempt is reported normally
            self._reruns[report.nodeid] = self._reruns.get(report.nodeid, 0) + 1
            return
        subtest = _subtest_label(report)
        if subtest is not None:
            # Passing subtests are covered by the outcome of the test that contains them.
            if report.failed:
                self._record(report, '%s %s' % (report.nodeid, subtest), 'failed')
            elif report.skipped:
                self._record(report, '%s %s' % (report.nodeid, subtest), 'skipped')
            return
        xfail = hasattr(report, 'wasxfail')
        if report.when == 'call':
            if xfail:
                result = 'skipped' if report.skipped else 'passed'  # xfailed / xpassed
            elif report.passed:
                result = 'passed'
            elif report.failed:
                result = 'failed'
            else:
                result = 'skipped'
            self._record(report, report.nodeid, result)
        elif report.when == 'setup':
            if report.failed:
                self._record(report, report.nodeid, 'error')
            elif report.skipped:
                self._record(report, report.nodeid, 'skipped')
        elif report.when == 'teardown' and report.failed:
            self._record(report, report.nodeid + '::teardown', 'error')

    def pytest_collectreport(self, report):
        # Import errors, syntax errors, module-level skips: without this the
        # report would look clean while pytest itself fails.
        if report.failed:
            outcome = 'error'
        elif report.skipped:
            outcome = 'skipped'
        else:
            return
        if outcome == 'error':
            traceback = str(report.longrepr)
        else:
            reason = _skip_reason(report)
            traceback = 'Skipped: %s' % reason if reason else None
        record_outcome(
            self.summary_stats,
            self.test_results,
            name=report.nodeid or '<collection>',
            outcome=outcome,
            traceback=traceback,
            metadata={'framework': 'pytest', 'phase': 'collect', 'location': report.nodeid},
        )

    def pytest_sessionfinish(self, session):
        context = build_context(self.summary_stats, self.test_results, title=self.title,
                                environment={'Framework': 'pytest %s' % pytest.__version__,
                                             'Python': platform.python_version(),
                                             'Platform': platform.platform()},
                                duration=time.time() - self._start,
                                baseline=load_baseline(self.baseline_path))
        self.comparison = context['comparison']
        write_reports(context, html_path=self.html_path, json_path=self.json_path, junit_path=self.junit_path)

    def pytest_terminal_summary(self, terminalreporter):
        terminalreporter.write_sep('-', 'pyrept HTML report: %s' % self.html_path)
        terminalreporter.write_sep('-', 'pyrept JSON report: %s' % self.json_path)
        if self.junit_path:
            terminalreporter.write_sep('-', 'pyrept JUnit report: %s' % self.junit_path)
        if self.comparison:
            terminalreporter.write_sep('-', 'pyrept: %s' % summary_line(self.comparison))
