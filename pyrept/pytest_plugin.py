"""
pytest plugin that generates the same HTML and JSON reports as the nose2 plugin.

The plugin is registered automatically through the ``pytest11`` entry point but
stays inactive until you opt in, either on the command line::

    pytest --pyrept
    pytest --pyrept-html=reports/report.html --pyrept-json=reports/report.json
    pytest --pyrept --pyrept-junit=junit.xml --pyrept-baseline=report.json
    pytest --pyrept --pyrept-github-summary --pyrept-fail-under=95

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
from .summary import evaluate_gates, parse_fail_under
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
_MAX_CONSOLE_MESSAGES = 200
# Files pytest-playwright keeps for failing tests (--tracing / --video retain-on-failure).
_PLAYWRIGHT_ARTIFACTS = (('trace', 'application/zip', 'Playwright trace (open at https://trace.playwright.dev)'),
                         ('video', 'video/webm', 'Video'))


def pytest_addhooks(pluginmanager):
    from . import hooks
    pluginmanager.add_hookspecs(hooks)


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
    group.addoption('--pyrept-markdown', action='store', default=None, metavar='PATH',
                    help='Also write a Markdown summary to PATH (implies --pyrept).')
    group.addoption('--pyrept-github-summary', action='store_true', default=False,
                    help='Append the Markdown summary to the GitHub Actions job summary (implies --pyrept).')
    group.addoption('--pyrept-fail-under', action='store', default=None, metavar='PERCENT',
                    help='Fail the run when the pass rate is below PERCENT (implies --pyrept).')
    group.addoption('--pyrept-ignore-known-failures', action='store_true', default=False,
                    help='Exit successfully when every failing test was already failing in the '
                         '--pyrept-baseline report (implies --pyrept).')
    group.addoption('--pyrept-title', action='store', default=None, help='Report title.')
    group.addoption('--pyrept-no-screenshots', action='store_true', default=False,
                    help='Do not capture Playwright/Selenium screenshots, browser console output or '
                         'trace/video links for failing tests.')
    parser.addini('pyrept', type='bool', default=False, help='Always generate pyrept reports.')
    parser.addini('pyrept_html', default='', help='Path of the pyrept HTML report.')
    parser.addini('pyrept_json', default='', help='Path of the pyrept JSON report.')
    parser.addini('pyrept_junit', default='', help='Path of an extra JUnit XML report.')
    parser.addini('pyrept_baseline', default='', help='Earlier pyrept JSON report to compare with.')
    parser.addini('pyrept_markdown', default='', help='Path of an extra Markdown summary.')
    parser.addini('pyrept_github_summary', type='bool', default=False,
                  help='Append the Markdown summary to the GitHub Actions job summary.')
    parser.addini('pyrept_fail_under', default='', help='Fail the run when the pass rate is below this percentage.')
    parser.addini('pyrept_ignore_known_failures', type='bool', default=False,
                  help='Exit successfully when every failing test was already failing in the baseline.')


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
    markdown_opt = config.getoption('pyrept_markdown')
    github_summary = config.getoption('pyrept_github_summary')
    fail_under_opt = config.getoption('pyrept_fail_under')
    ignore_known = config.getoption('pyrept_ignore_known_failures')
    enabled = (config.getoption('pyrept') or html_opt or json_opt or junit_opt or baseline_opt or markdown_opt
               or github_summary or fail_under_opt is not None or ignore_known or config.getini('pyrept'))
    if not enabled:
        return
    try:
        fail_under = parse_fail_under(fail_under_opt if fail_under_opt is not None
                                      else config.getini('pyrept_fail_under'))
    except ValueError as exc:
        raise pytest.UsageError('pyrept: %s' % exc)
    # Reports are built where the test runs (also inside xdist workers, whose
    # reports are sent to the controller with these extra attributes).
    config.pluginmanager.register(
        PyreptAnnotator(screenshots=not config.getoption('pyrept_no_screenshots')), _ANNOTATOR_NAME)
    # Do not write reports from xdist worker processes; the controller collects all results.
    if hasattr(config, 'workerinput'):
        return
    reporter = PyreptReporter(
        config=config,
        html_path=_resolve(config, html_opt, 'pyrept_html', DEFAULT_HTML_REPORT_PATH),
        json_path=_resolve(config, json_opt, 'pyrept_json', DEFAULT_JSON_REPORT_PATH),
        title=config.getoption('pyrept_title') or 'Test Report',
        junit_path=_resolve(config, junit_opt, 'pyrept_junit', None),
        baseline_path=_resolve(config, baseline_opt, 'pyrept_baseline', None),
        markdown_path=_resolve(config, markdown_opt, 'pyrept_markdown', None),
        github_summary=github_summary or config.getini('pyrept_github_summary'),
        fail_under=fail_under,
        ignore_known_failures=ignore_known or config.getini('pyrept_ignore_known_failures'),
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
        parts.append('(%s)' % ', '.join('%s=%s' % item for item in context.kwargs.items()))
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


def _bdd_description(bdd):
    """Feature, scenario and steps of a pytest-bdd scenario, each step with its status."""
    lines = ['Feature: %s' % bdd['feature'], 'Scenario: %s' % bdd['scenario']]
    for index, (keyword, name) in enumerate(bdd['steps']):
        status = bdd['status'].get(index, 'skipped')
        lines.append('  %s %s  [%s]' % (keyword, name, status))
    return '\n'.join(lines)


def _bdd_step_index(bdd, step):
    key = (str(getattr(step, 'keyword', '')).strip(), str(getattr(step, 'name', '')))
    for index, known in enumerate(bdd['steps']):
        if known == key and index not in bdd['status']:
            return index
    return None


def _playwright_artifacts(output_path):
    found = []
    try:
        names = sorted(os.listdir(output_path))
    except OSError:
        return found
    for prefix, content_type, label in _PLAYWRIGHT_ARTIFACTS:
        for name in names:
            if name.startswith(prefix):
                found.append({'name': label if name in ('trace.zip', 'video.webm') else '%s (%s)' % (label, name),
                              'content_type': content_type, 'path': os.path.join(output_path, name)})
    return found


class PyreptAnnotator:
    """Adds description, markers, failure screenshots and other evidence to each test report."""

    def __init__(self, screenshots=True):
        self.screenshots = screenshots

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_call(self, item):
        # Browser console output and uncaught page errors while the test body runs.
        page = (getattr(item, 'funcargs', None) or {}).get('page') if self.screenshots else None
        if page is None or not hasattr(page, 'on') or not hasattr(page, 'remove_listener'):
            yield
            return
        messages = item._pyrept_console = []

        def on_console(message):
            if len(messages) < _MAX_CONSOLE_MESSAGES:
                messages.append('[%s] %s' % (getattr(message, 'type', 'log'), getattr(message, 'text', message)))

        def on_page_error(error):
            if len(messages) < _MAX_CONSOLE_MESSAGES:
                messages.append('[pageerror] %s' % error)

        try:
            page.on('console', on_console)
            page.on('pageerror', on_page_error)
        except Exception:
            yield
            return
        try:
            yield
        finally:
            for event, handler in (('console', on_console), ('pageerror', on_page_error)):
                try:
                    page.remove_listener(event, handler)
                except Exception:  # page already closed
                    pass

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_makereport(self, item, call):
        outcome = yield
        report = outcome.get_result()
        bdd = getattr(item, '_pyrept_bdd', None)
        report.pyrept_description = _bdd_description(bdd) if bdd else _description(item)
        report.pyrept_attachments = []
        report.pyrept_markers = sorted({m.name for m in item.iter_markers() if m.name not in _IGNORED_MARKERS})
        if report.failed and report.when in ('setup', 'call'):
            item._pyrept_failed = True
        if self.screenshots and report.when == 'call':
            output_path = (getattr(item, 'funcargs', None) or {}).get('output_path')
            if isinstance(output_path, str):
                item._pyrept_output_path = output_path  # pytest-playwright's per-test artifact folder
            if report.failed:
                shot = _capture_screenshot(item)
                if shot:
                    report.pyrept_attachments.append(shot)
                console = getattr(item, '_pyrept_console', None)
                if console:
                    report.pyrept_attachments.append(make_attachment('Browser console', 'text/plain',
                                                                     text='\n'.join(console)))
        if self.screenshots and report.when == 'teardown' and getattr(item, '_pyrept_failed', False):
            # pytest-playwright saves traces and videos while the test's fixtures are torn down.
            output_path = getattr(item, '_pyrept_output_path', None)
            report.pyrept_artifacts = _playwright_artifacts(output_path) if output_path else []
        for extra in item.config.hook.pytest_pyrept_attachments(item=item, report=report):
            report.pyrept_attachments.extend(a for a in extra or [] if isinstance(a, dict))

    # pytest-bdd: scenario, steps and the failing step (optional: only called when pytest-bdd is installed)
    @pytest.hookimpl(optionalhook=True)
    def pytest_bdd_before_scenario(self, request, feature, scenario):
        request.node._pyrept_bdd = {
            'feature': getattr(feature, 'name', '') or '',
            'scenario': getattr(scenario, 'name', '') or '',
            'steps': [(str(getattr(step, 'keyword', '')).strip(), str(getattr(step, 'name', '')))
                      for step in getattr(scenario, 'steps', None) or []],
            'status': {},
        }

    @pytest.hookimpl(optionalhook=True)
    def pytest_bdd_after_step(self, request, step):
        bdd = getattr(request.node, '_pyrept_bdd', None)
        index = _bdd_step_index(bdd, step) if bdd else None
        if index is not None:
            bdd['status'][index] = 'passed'

    @pytest.hookimpl(optionalhook=True)
    def pytest_bdd_step_error(self, request, step):
        bdd = getattr(request.node, '_pyrept_bdd', None)
        index = _bdd_step_index(bdd, step) if bdd else None
        if index is not None:
            bdd['status'][index] = 'failed'


_GATE_OPTION_NAMES = {'fail_under': '--pyrept-fail-under', 'ignore_known_failures': '--pyrept-ignore-known-failures',
                      'baseline': '--pyrept-baseline'}


class PyreptReporter:
    def __init__(self, html_path, json_path, title='Test Report', junit_path=None, baseline_path=None,
                 markdown_path=None, github_summary=False, fail_under=None, ignore_known_failures=False,
                 config=None):
        self.config = config
        self.html_path = html_path
        self.json_path = json_path
        self.junit_path = junit_path
        self.baseline_path = baseline_path
        self.markdown_path = markdown_path
        self.github_summary = github_summary
        self.fail_under = fail_under
        self.ignore_known_failures = ignore_known_failures
        self.comparison = None
        self.gate_messages = []
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

    def _attach_artifacts(self, report):
        """Link pytest-playwright traces/videos (saved at teardown) to the test's entry."""
        artifacts = getattr(report, 'pyrept_artifacts', None)
        if not artifacts:
            return
        # The test's own entry, or its failing subtest's ("<nodeid> [msg] (k=v)").
        target = next((r for r in reversed(self.test_results)
                       if r['name'] == report.nodeid or r['name'].startswith(report.nodeid + ' ')), None)
        if target is None:
            return
        base = os.path.dirname(self.html_path)
        for artifact in artifacts:
            path = artifact['path']
            try:
                link = os.path.relpath(path, base)  # relative, so it works when the folder is uploaded as one
            except ValueError:  # pragma: no cover - another drive on Windows
                link = path
            target['metadata'].setdefault('attachments', []).append(
                make_attachment(artifact.get('name') or os.path.basename(path), artifact.get('content_type'),
                                path=link.replace(os.sep, '/'), embed=False))

    def pytest_runtest_logreport(self, report):
        if report.when == 'teardown':
            self._attach_artifacts(report)
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
        environment = {'Framework': 'pytest %s' % pytest.__version__, 'Python': platform.python_version(),
                       'Platform': platform.platform()}
        hook = self.config.hook
        for extra in hook.pytest_pyrept_environment(config=self.config):
            if isinstance(extra, dict):
                environment.update({str(k): v for k, v in extra.items()})
        context = build_context(self.summary_stats, self.test_results, title=self.title, environment=environment,
                                duration=time.time() - self._start,
                                baseline=load_baseline(self.baseline_path))
        hook.pytest_pyrept_context(config=self.config, context=context)
        self.comparison = context['comparison']
        write_reports(context, html_path=self.html_path, json_path=self.json_path, junit_path=self.junit_path,
                      markdown_path=self.markdown_path, github_summary=self.github_summary)
        if self.fail_under is not None or self.ignore_known_failures:
            self._apply_gates(session, context)

    def _apply_gates(self, session, context):
        gate = evaluate_gates(context, fail_under=self.fail_under, ignore_known_failures=self.ignore_known_failures,
                              option_names=_GATE_OPTION_NAMES)
        self.gate_messages = gate.messages
        status = int(session.exitstatus)
        if status == 0 and gate.below_threshold:
            session.exitstatus = pytest.ExitCode.TESTS_FAILED
        elif status == 1 and gate.successful(False):
            # Only when every failure pytest counted is a known one in the report:
            # other plugins (pytest-cov's --cov-fail-under, ...) also fail runs this way.
            stats = context['test_summary']
            if getattr(session, 'testsfailed', 0) <= stats['failed'] + stats['error']:
                session.exitstatus = pytest.ExitCode.OK
            else:
                self.gate_messages.append('another plugin also failed the run, so the exit status is unchanged')

    def pytest_terminal_summary(self, terminalreporter):
        terminalreporter.write_sep('-', 'pyrept HTML report: %s' % self.html_path)
        terminalreporter.write_sep('-', 'pyrept JSON report: %s' % self.json_path)
        if self.junit_path:
            terminalreporter.write_sep('-', 'pyrept JUnit report: %s' % self.junit_path)
        if self.markdown_path:
            terminalreporter.write_sep('-', 'pyrept Markdown summary: %s' % self.markdown_path)
        if self.comparison:
            terminalreporter.write_sep('-', 'pyrept: %s' % summary_line(self.comparison))
        for message in self.gate_messages:
            terminalreporter.write_sep('-', 'pyrept: %s' % message)
