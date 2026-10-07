# Frameworks

Every integration writes `report.html` and `report.json` (paths are configurable), and the same extra options: JUnit XML, a baseline to compare with, a Markdown summary and quality gates.

| You use | Run this |
|---|---|
| pytest | `pytest --pyrept` |
| pytest-bdd | `pytest --pyrept` (scenarios, steps and the failing step are recorded) |
| Playwright / Selenium (Python) | `pytest --pyrept` (failure screenshots, browser console, traces and videos) |
| unittest | `python -m pyrept.unittest_runner discover -s tests` |
| nose2 | `pip install "pyrept[nose2]"`, then `nose2 --html-report` |
| behave | `behave -f pyrept.behave_formatter:PyreptFormatter -o /dev/null` |

## pytest

```bash
pytest --pyrept                                       # report.html + report.json
pytest --pyrept-html=reports/report.html --pyrept-json=reports/report.json
pytest --pyrept --pyrept-junit=reports/junit.xml      # JUnit XML for your CI
pytest --pyrept --pyrept-baseline=reports/report.json # compare with the previous run
pytest --pyrept --pyrept-github-summary               # GitHub Actions job summary
```

Or configure it once:

```ini
# pytest.ini (or [tool.pytest.ini_options] in pyproject.toml)
[pytest]
pyrept = true
pyrept_html = reports/report.html
pyrept_json = reports/report.json
pyrept_junit = reports/junit.xml
pyrept_baseline = reports/report.json
pyrept_markdown = reports/summary.md
```

pytest-xdist, pytest-rerunfailures (retries and flaky flags), subtests, collection errors, setup and teardown errors, and captured stdout, stderr and logs are all handled.

### Playwright and Selenium

For a failing test that uses a pytest-playwright `page` fixture (or a Selenium `driver`, `selenium` or `browser` fixture), pyrept attaches:

- a full-page **screenshot**, taken while the browser is still open;
- the **browser console** output and uncaught page errors (Playwright);
- links to the **trace** and **video** that pytest-playwright keeps with `--tracing retain-on-failure` and `--video retain-on-failure`.

```bash
pip install "pyrept[playwright]" && playwright install chromium
pytest --pyrept --tracing retain-on-failure --video retain-on-failure
```

Links are relative to the HTML report, so upload the report and `test-results/` together. Turn all of this off with `--pyrept-no-screenshots`.

### pytest-bdd

Scenarios run with pytest-bdd show the feature, the scenario and each step with its status, so you see which step failed:

```text
Feature: Checkout
Scenario: Pay with card
  Given a cart with 2 items  [passed]
  When I pay with a declined card  [failed]
  Then I see the confirmation page  [skipped]
```

## unittest

```bash
python -m pyrept.unittest_runner discover -s tests --pyrept-html=reports/report.html
```

It accepts every `python -m unittest` argument, plus `--pyrept-json`, `--pyrept-junit`, `--pyrept-baseline`, `--pyrept-markdown`, `--pyrept-github-summary`, `--pyrept-fail-under` and `--pyrept-ignore-known-failures`.

## nose2

nose2 is an optional extra: `pip install "pyrept[nose2]"`.

```ini
# nose2.cfg
[unittest]
plugins = pyrept.html_report

[html-report]
always-on = True
html-report-path = reports/report.html
json-report-path = reports/report.json
markdown-report-path = reports/summary.md
```

## behave

```bash
pip install "pyrept[behave]"
behave -f pyrept.behave_formatter:PyreptFormatter -o /dev/null \
       -D pyrept_html=reports/report.html -D pyrept_markdown=reports/summary.md
```

!!! note
    behave pairs each `-o` with the `-f` before it. Put `-f pyrept -o /dev/null` first, then `-f pretty`, or the console output goes to `/dev/null`.
