import os

import pytest

pytest_plugins = ['pytester']

# pyrept reads these from the environment. A developer's shell, or GitHub Actions
# itself ($GITHUB_STEP_SUMMARY), must not make the test suite post to Slack or
# write to the job summary.
_PYREPT_ENV = ('GITHUB_STEP_SUMMARY', 'PYREPT_SLACK_WEBHOOK_URL', 'PYREPT_TEAMS_WEBHOOK_URL', 'PYREPT_WEBHOOK_URL',
               'PYREPT_NOTIFY_ON', 'PYREPT_REPORT_URL', 'PYREPT_LOGO', 'PYREPT_ACCENT_COLOR')


@pytest.fixture(autouse=True)
def _isolated_pyrept_env(monkeypatch):
    for name in _PYREPT_ENV:
        monkeypatch.delenv(name, raising=False)
    assert not any(os.environ.get(name) for name in _PYREPT_ENV)
