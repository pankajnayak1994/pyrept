"""
Hooks other pytest plugins and ``conftest.py`` files can implement to add to
the pyrept report::

    # conftest.py
    import os
    from pyrept import make_attachment

    def pytest_pyrept_environment(config):
        return {'Build': os.environ.get('BUILD_ID', 'local'), 'Browser': 'Chromium 128'}

    def pytest_pyrept_attachments(item, report):
        if report.when == 'call' and report.failed:
            return [make_attachment('server.log', 'text/plain', text=read_server_log())]

    def pytest_pyrept_context(config, context):
        context['test_report_title'] += ' (nightly)'
"""


def pytest_pyrept_environment(config):
    """Return a dict of extra rows for the report's Environment panel."""


def pytest_pyrept_attachments(item, report):
    """
    Return a list of attachments (see :func:`pyrept.make_attachment`) for one
    phase (``report.when``: setup, call or teardown) of a test.

    Runs where the test runs, also inside pytest-xdist workers, so attachments
    must be plain data (strings, numbers, lists and dicts).
    """


def pytest_pyrept_context(config, context):
    """Change the report context in place just before the reports are written."""
