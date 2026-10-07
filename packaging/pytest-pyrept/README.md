# pytest-pyrept

This package installs [pyrept](https://pypi.org/project/pyrept/), which provides the pytest plugin, and nothing else.

```bash
pip install pytest-pyrept    # same as: pip install pyrept
pytest --pyrept              # writes report.html and report.json
```

pyrept writes one self-contained HTML report, a JSON report and optional JUnit XML for pytest, unittest, nose2, behave and Playwright/Selenium tests. It also compares each run with the previous one, adds GitHub job summaries and quality gates, and converts JUnit XML, TRX, NUnit, Robot Framework, TAP, Allure, Cucumber and Playwright reports.

Documentation: https://github.com/pankajnayak1994/pyrept
