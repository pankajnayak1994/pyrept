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

import pytest

from .report import (
    DEFAULT_HTML_REPORT_PATH,
    DEFAULT_JSON_REPORT_PATH,
    build_context,
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


class PyreptReporter:
    def __init__(self, html_path, json_path):
        self.html_path = html_path
        self.json_path = json_path
        self.summary_stats = new_summary_stats()
        self.test_results = []

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_makereport(self, item, call):
        outcome = yield
        report = outcome.get_result()
        report.pyrept_description = _description(item)

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
            metadata={'duration': round(report.duration, 4), 'phase': report.when},
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
        context = build_context(self.summary_stats, self.test_results)
        write_reports(context, html_path=self.html_path, json_path=self.json_path)

    def pytest_terminal_summary(self, terminalreporter):
        terminalreporter.write_sep('-', 'pyrept HTML report: %s' % self.html_path)
        terminalreporter.write_sep('-', 'pyrept JSON report: %s' % self.json_path)
