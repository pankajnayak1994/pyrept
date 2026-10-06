"""
pytest plugin that generates the same HTML and JSON reports as the nose2 plugin.

The plugin is registered automatically through the ``pytest11`` entry point but
stays inactive until you opt in, either on the command line::

    pytest --pyrept
    pytest --pyrept-html=reports/report.html --pyrept-json=reports/report.json

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


def pytest_addoption(parser):
    group = parser.getgroup('pyrept', 'HTML/JSON test reports (pyrept)')
    group.addoption('--pyrept', action='store_true', default=False,
                    help='Generate pyrept HTML and JSON reports.')
    group.addoption('--pyrept-html', action='store', default=None, metavar='PATH',
                    help='Path of the HTML report (implies --pyrept). Default: %s' % DEFAULT_HTML_REPORT_PATH)
    group.addoption('--pyrept-json', action='store', default=None, metavar='PATH',
                    help='Path of the JSON report (implies --pyrept). Default: %s' % DEFAULT_JSON_REPORT_PATH)
    group.addoption('--pyrept-title', action='store', default=None, help='Report title.')
    group.addoption('--pyrept-no-screenshots', action='store_true', default=False,
                    help='Do not capture Playwright/Selenium screenshots for failing tests.')
    parser.addini('pyrept', type='bool', default=False, help='Always generate pyrept reports.')
    parser.addini('pyrept_html', default='', help='Path of the pyrept HTML report.')
    parser.addini('pyrept_json', default='', help='Path of the pyrept JSON report.')


def pytest_configure(config):
    html_opt = config.getoption('pyrept_html')
    json_opt = config.getoption('pyrept_json')
    enabled = config.getoption('pyrept') or html_opt or json_opt or config.getini('pyrept')
    # Do not write reports from xdist worker processes; the controller collects all results.
    if not enabled or hasattr(config, 'workerinput'):
        return
    html_path = html_opt or config.getini('pyrept_html') or DEFAULT_HTML_REPORT_PATH
    json_path = json_opt or config.getini('pyrept_json') or DEFAULT_JSON_REPORT_PATH
    reporter = PyreptReporter(
        html_path=os.path.realpath(os.path.join(str(config.invocation_params.dir), html_path)),
        json_path=os.path.realpath(os.path.join(str(config.invocation_params.dir), json_path)),
        title=config.getoption('pyrept_title') or 'Test Report',
        screenshots=not config.getoption('pyrept_no_screenshots'),
    )
    config.pluginmanager.register(reporter, _PLUGIN_NAME)


def pytest_unconfigure(config):
    reporter = config.pluginmanager.get_plugin(_PLUGIN_NAME)
    if reporter is not None:
        config.pluginmanager.unregister(reporter)


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


class PyreptReporter:
    def __init__(self, html_path, json_path, title='Test Report', screenshots=True):
        self.html_path = html_path
        self.json_path = json_path
        self.title = title
        self.screenshots = screenshots
        self.summary_stats = new_summary_stats()
        self.test_results = []
        self._start = time.time()

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_makereport(self, item, call):
        outcome = yield
        report = outcome.get_result()
        report.pyrept_description = _description(item)
        report.pyrept_attachments = []
        report.pyrept_markers = sorted({m.name for m in item.iter_markers()
                                        if m.name not in ('parametrize', 'usefixtures', 'filterwarnings')})
        if self.screenshots and report.when == 'call' and report.failed:
            shot = _capture_screenshot(item)
            if shot:
                report.pyrept_attachments.append(shot)

    def _record(self, report, name, result):
        traceback = None
        if result in ('failed', 'error') and report.longrepr is not None:
            traceback = str(report.longrepr)
        record_outcome(
            self.summary_stats,
            self.test_results,
            name=name,
            outcome=result,
            description=getattr(report, 'pyrept_description', None),
            traceback=traceback,
            metadata={
                'framework': 'pytest',
                'duration': round(report.duration, 4),
                'phase': report.when,
                'location': '%s:%s' % (report.location[0], (report.location[1] or 0) + 1),
                'tags': getattr(report, 'pyrept_markers', []),
            },
            attachments=getattr(report, 'pyrept_attachments', None) or None,
        )

    def pytest_runtest_logreport(self, report):
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

    def pytest_sessionfinish(self, session):
        context = build_context(self.summary_stats, self.test_results, title=self.title,
                                environment={'Framework': 'pytest %s' % pytest.__version__,
                                             'Python': platform.python_version(),
                                             'Platform': platform.platform()},
                                duration=time.time() - self._start)
        write_reports(context, html_path=self.html_path, json_path=self.json_path)

    def pytest_terminal_summary(self, terminalreporter):
        terminalreporter.write_sep('-', 'pyrept HTML report: %s' % self.html_path)
        terminalreporter.write_sep('-', 'pyrept JSON report: %s' % self.json_path)
