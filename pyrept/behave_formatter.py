"""
Cucumber-style BDD support for behave (https://behave.readthedocs.io).

Each scenario (and each Scenario Outline example) becomes one test in the report;
its steps become the description and the first failing step's error becomes the
traceback.

Usage::

    behave -f pyrept.behave_formatter:PyreptFormatter -o /dev/null
    behave -f pyrept.behave_formatter:PyreptFormatter -D pyrept_html=reports/report.html \\
           -D pyrept_json=reports/report.json

or register it once in ``behave.ini``::

    [behave.formatters]
    pyrept = pyrept.behave_formatter:PyreptFormatter

    [behave.userdata]
    pyrept_html = reports/report.html
    pyrept_json = reports/report.json

and run ``behave -f pyrept -o /dev/null -f pretty``. behave pairs each ``-o`` with the
``-f`` before it, so keep ``-f pyrept -o /dev/null`` first or the console output is lost.

Screenshots and other files attached with ``context.attach(mime_type, data)`` are embedded.
"""
import os

from behave.formatter.base import Formatter

from .report import DEFAULT_HTML_REPORT_PATH, DEFAULT_JSON_REPORT_PATH, ReportCollector, make_attachment

_STATUS_MAP = {
    'passed': 'passed',
    'failed': 'failed',
    'error': 'error',
    'hook_error': 'error',
    'skipped': 'skipped',
    'untested': 'skipped',
    'undefined': 'error',
    'pending': 'skipped',
    'pending_warn': 'skipped',
}


def _status_name(status):
    # behave >= 1.2.6 uses a Status enum; older versions use plain strings.
    return getattr(status, 'name', status) or 'untested'


def map_status(status):
    return _STATUS_MAP.get(str(_status_name(status)).lower(), 'error')


def _step_line(step):
    status = _status_name(getattr(step, 'status', None))
    return '%s %s  [%s]' % (step.keyword.strip(), step.name, status)


class PyreptFormatter(Formatter):
    name = 'pyrept'
    description = 'pyrept HTML and JSON report'

    def __init__(self, stream_opener, config):
        super().__init__(stream_opener, config)
        userdata = getattr(config, 'userdata', {}) or {}
        self.html_path = os.path.realpath(userdata.get('pyrept_html', DEFAULT_HTML_REPORT_PATH))
        self.json_path = os.path.realpath(userdata.get('pyrept_json', DEFAULT_JSON_REPORT_PATH))
        import behave
        self.collector = ReportCollector(title=userdata.get('pyrept_title', 'BDD Test Report'),
                                         environment={'Framework': 'behave %s' % getattr(behave, '__version__', '')})
        self._feature = None
        self._scenarios = []
        self._attachments = {}  # id(scenario) -> attachments from context.attach()

    # behave calls these as it runs ------------------------------------------
    def feature(self, feature):
        self._flush()
        self._feature = feature

    def scenario(self, scenario):
        self._scenarios.append(scenario)

    def embedding(self, mime_type, data):
        """Called by behave for ``context.attach(mime_type, data)``."""
        if not self._scenarios:
            return  # attached outside a scenario (before_feature/before_all hooks)
        attachments = self._attachments.setdefault(id(self._scenarios[-1]), [])
        attachments.append(make_attachment(
            name='Attachment %d' % (len(attachments) + 1),
            content_type=mime_type,
            data=data.encode('utf-8') if isinstance(data, str) else data))

    def eof(self):
        self._flush()

    def close(self):
        self._flush()
        self.collector.write(html_path=self.html_path, json_path=self.json_path)
        super().close()

    # ------------------------------------------------------------------------
    def _flush(self):
        """Record the scenarios of the current feature once their status is final."""
        for scenario in self._scenarios:
            self._record(scenario)
        self._scenarios = []
        self._attachments = {}

    def _record(self, scenario):
        feature_name = self._feature.name if self._feature is not None else ''
        steps = list(getattr(scenario, 'all_steps', None) or scenario.steps)
        failing = next((s for s in steps if map_status(getattr(s, 'status', None)) in ('failed', 'error')), None)
        traceback = None
        if failing is not None:
            traceback = '%s\n\n%s' % (_step_line(failing), getattr(failing, 'error_message', '') or '')
        elif getattr(scenario, 'error_message', None):
            traceback = scenario.error_message  # hook errors

        tags = ['@' + str(t) for t in getattr(scenario, 'effective_tags', None) or scenario.tags]
        description = '\n'.join(([' '.join(tags)] if tags else []) + [_step_line(s) for s in steps])

        attachments = self._attachments.get(id(scenario), [])
        scenario_name = (scenario.name or '').strip() or 'Scenario'

        self.collector.add(
            name='%s :: %s' % (feature_name, scenario_name) if feature_name else scenario_name,
            outcome=map_status(scenario.status),
            description=description,
            traceback=traceback,
            metadata={
                'framework': 'behave',
                'location': str(getattr(scenario, 'location', '')),
                'duration': round(getattr(scenario, 'duration', 0) or 0, 4),
                'tags': tags,
            },
            attachments=attachments or None,
        )
