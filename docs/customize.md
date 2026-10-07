# Customising

## Your logo and colour

Reports show the pyrept logo in the header and as the browser tab icon. Use your own, or none:

```bash
export PYREPT_LOGO=branding/logo.svg       # image file (embedded, up to 1 MB) or https:// URL
export PYREPT_LOGO=none                    # no logo
export PYREPT_ACCENT_COLOR="#0f766e"       # hex colour
```

Branding applies to every HTML report and history page and is never stored in the JSON report.

## pytest hooks

Add environment rows, attachments or anything else from `conftest.py` or your own plugin:

```python
# conftest.py
import os
from pyrept import make_attachment

def pytest_pyrept_environment(config):
    return {'Build': os.environ.get('BUILD_ID', 'local'), 'Browser': 'Chromium 128'}

def pytest_pyrept_attachments(item, report):
    if report.when == 'call' and report.failed:
        return [make_attachment('server.log', 'text/plain', text=open('server.log').read())]

def pytest_pyrept_context(config, context):
    context['test_report_title'] += ' (nightly)'
```

`pytest_pyrept_attachments` runs where the test runs, also in pytest-xdist workers, so return plain data.

## Python API

Build reports from your own runner or tooling:

```python
from pyrept import ReportCollector, make_attachment

report = ReportCollector(title='Smoke tests', environment={'Build': '1.4.2'})
report.add('login works', 'passed', metadata={'duration': 0.42, 'tags': ['smoke']})
report.add('checkout', 'failed', traceback='Timeout after 30s',
           attachments=[make_attachment('screenshot', path='shot.png')])
report.write('reports/report.html', 'reports/report.json',
             junit_path='reports/junit.xml', baseline_path='reports/previous.json',
             markdown_path='reports/summary.md')
```

## Custom HTML template

nose2's `template` setting and `ReportCollector.write(template_path=...)` take your own Jinja2 template. It can include pyrept's design system with `{% include '_theme.css' %}` and use the `split_test_name` filter. The JSON report shows every value the template receives.
