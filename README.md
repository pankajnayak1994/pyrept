# pyrept: HTML & JSON Test Reports for pytest and nose2

[![codecov](https://codecov.io/gh/pankajnayak1994/pyrept/graph/badge.svg?token=M0KTUAOO4V)](https://codecov.io/gh/pankajnayak1994/pyrept)
[![Tests](https://github.com/pankajnayak1994/pyrept/actions/workflows/codecov.yml/badge.svg)](https://github.com/pankajnayak1994/pyrept/actions/workflows/codecov.yml)
[![PyPI](https://img.shields.io/pypi/v/pyrept)](https://pypi.org/project/pyrept/)
![PyPI - Downloads](https://img.shields.io/pypi/dm/pyrept)
![PyPI - Python Version](https://img.shields.io/pypi/pyversions/pyrept)
![GitHub contributors](https://img.shields.io/github/contributors/pankajnayak1994/pyrept)
![PyPI - License](https://img.shields.io/pypi/l/pyrept)


### Introduction
A plugin for **pytest** and **nose2** that generates detailed, searchable, and user-friendly HTML and JSON reports of your test results.

Key Features:

- Rich Test Descriptions: Automatically captures docstrings from tests as descriptions, making the reports more informative and readable.
- Failure Tracebacks: Includes complete traceback details for any failed tests, enabling quick identification and resolution of issues.
- Searchable and Filterable Reports: Allows users to search and filter results by status (e.g., passed, failed, skipped, or error), making it easy to navigate through large test suites.
- Customizable Outputs: Supports customization options to fit specific reporting needs.
- JSON Integration: Provides JSON reports for easy integration with other tools or automated workflows.
- This plugin is ideal for enhancing test visibility and making debugging more efficient.

![Report Screenshot](https://raw.githubusercontent.com/pankajnayak1994/pyrept/master/docs/images/report.png)

### Installation
```
pip install pyrept
```

## Using with pytest
The plugin registers itself automatically and stays off until you ask for a report:
```
pytest --pyrept                                   # writes report.html and report.json
pytest --pyrept-html=reports/report.html --pyrept-json=reports/report.json
```

To always generate reports, add this to `pytest.ini` (or `[tool.pytest.ini_options]` in `pyproject.toml`):
```
[pytest]
pyrept = true
pyrept_html = reports/report.html
pyrept_json = reports/report.json
```
Test docstrings become descriptions, failures and setup errors include the full traceback, and `xfail` tests are reported as skipped.

## Using with nose2

### Configuration
To get `nose2` to recognize the plugin add an entry into the `plugin` key of the `unittest` section of your `nose2.cfg` file. Configurations for the plugin should be placed into an `html-report` section of the configuration file. Below is a working example:
```
[unittest]
plugins = pyrept.html_report

[html-report]
always-on = True
```

#### Additional Settings
Report paths default to `report.html` and `report.json`. Override them in `nose2.cfg`:
```
[unittest]
plugins = pyrept.html_report

[html-report]
always-on = True
html-report-path = test_results/report.html
json-report-path = test_results/report.json
```
or on the command line (takes precedence over the config file):
```
nose2 --html-report --html-report-path=test_results/report.html --json-report-path=test_results/report.json
```

### Usage
Command line flag:
```
nose2 --html-report
```

If you have `always-on=True` inside your `nose2.cfg`:
```
nose2
```

### JSON report
`report.json` contains the summary (`total`, `passed`, `failed`, `error`, `skipped`, `percentage`) and one entry per test with `name`, `description`, `result`, `traceback` and `metadata`, so you can feed results into dashboards or CI checks.
