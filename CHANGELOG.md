# Changelog

## Unreleased

### Changed
- Releases are fully automated: each merged pull request also moves the `v1` tag for the GitHub Action, creates the GitHub release and publishes the `pytest-pyrept` alias package. `[SKIP]` titles or the `skip-release` label merge without a release.
- The GitHub Action is tested on every pull request (`.github/workflows/test-action.yml`), and Dependabot keeps the workflows' actions up to date.
- Examples use `pankajnayak1994/pyrept@v1` instead of `@master`.

## 1.3.0

### Added
- **GitHub job summaries and Markdown summaries** from every integration: `--pyrept-markdown` / `--pyrept-github-summary` (pytest, unittest), `markdown-report-path` / `github-summary` (nose2), `pyrept_markdown` / `pyrept_github_summary` (behave), `--markdown` / `--github-summary` (convert). Output stays far below GitHub's 1 MiB limit.
- **`pyrept summary report.json`**: print or publish the Markdown summary of any pyrept report and apply quality gates to it.
- **GitHub Action** (`uses: pankajnayak1994/pyrept@...`): job summary, an always-up-to-date pull request comment, quality gates, outputs, and `convert-from` for reports from any language.
- **Quality gates**: `fail-under` (minimum pass rate) and `ignore-known-failures` (fail only on tests that did not fail in the baseline) for pytest, unittest, nose2, `pyrept convert` and `pyrept summary`. With pytest, failures from other plugins (such as `--cov-fail-under`) and collection errors are never hidden.
- **Common failure causes**: failures sharing an error message are grouped in the HTML report, the Markdown summary and the JSON report (`failure_groups`).
- **`pyrept history`**: pass-rate trends, outcomes and durations per run, flaky tests (failing in separate stretches, or passing after a retry), failure streaks, most failing and slowest tests across many JSON reports.
- **Converters**: .NET TRX (including data-driven rows and result files), NUnit 3 and 2, xUnit.net v2, Robot Framework 3.x to 7.x, TAP 12 to 14 (plans, SKIP/TODO, YAML diagnostics, bail out), Allure results (retries folded), pytest-json-report, and pyrept JSON (merge shards).
- **Notifications** to Slack, Microsoft Teams and any webhook, configured with `PYREPT_*_WEBHOOK_URL` and `PYREPT_NOTIFY_ON`; webhook URLs are never logged and delivery failures never fail the run. `PYREPT_REPORT_URL` links the published report.
- **pytest**: pytest-bdd scenarios show the feature, scenario and each step's status; failing Playwright tests get the browser console output and links to pytest-playwright traces and videos; new hooks `pytest_pyrept_environment`, `pytest_pyrept_attachments` and `pytest_pyrept_context`.
- **Logo and branding**: reports and history pages show the pyrept logo in the header and as the tab icon; `PYREPT_LOGO` replaces it (`none` removes it) and `PYREPT_ACCENT_COLOR` sets the accent colour. Applied to the HTML only.
- Developer credit (Pankaj Kumar Nayak) in report and history footers, Markdown summaries, `pyrept --version`, the README and the docs site.
- Documentation site with a live demo report (`mkdocs.yml`, `.github/workflows/docs.yml`), `CONTRIBUTING.md`, issue templates and the `pytest-pyrept` alias package (`packaging/pytest-pyrept`).

### Changed
- **New HTML report design**: run verdict header with pass-rate ring, outcome bar and clickable counts; a test map with one square per test; test names split into path and name; per-test duration bars; sort by status, name or duration; `j`/`k` keyboard navigation; filters kept in the URL (`#failed`, `#skipped`, ...); print-friendly output.
- **nose2 is now an optional extra** (`pip install "pyrept[nose2]"`); `jinja2` is the only required dependency.
- Templates are loaded through a Jinja2 environment: custom templates can `{% include '_theme.css' %}` and use the `split_test_name` filter.
- JUnit XML `message` attributes no longer contain ANSI colour codes.
- Packaging: `setup.py` and `setup.cfg` removed; setuptools 64 or newer builds the package.

### Fixed
- Makefile `uninstall` target used the package's old name.

## 1.1.0 and 1.2.0

### Added
- **pytest** plugin: `pytest --pyrept`, `--pyrept-html`, `--pyrept-json`, `--pyrept-title`, and the `pyrept` / `pyrept_html` / `pyrept_json` ini options. Registered via the `pytest11` entry point and off unless enabled.
- **Playwright / Selenium** screenshots: failing tests that use a `page` (pytest-playwright) or `driver` / `selenium` / `browser` fixture get a full-page screenshot embedded in the report (`--pyrept-no-screenshots` to disable).
- **unittest** runner with no extra dependencies: `python -m pyrept.unittest_runner` and `PyreptTestRunner`; subtests, expected failures and unexpected successes are handled.
- **behave** (Cucumber BDD) formatter: `pyrept.behave_formatter:PyreptFormatter`.
- `pyrept convert` CLI for **Cucumber JSON** (any language) and **Playwright Test JSON** reports, with merge support and `--fail-on-failure`.
- Public `ReportCollector` / `make_attachment` API for custom integrations.
- Optional extras: `pyrept[behave]`, `pyrept[playwright]`.

- Python 3.14 support (classifier and CI); CI also runs the Python 3.15 pre-releases.
- pytest: works with **pytest-xdist** (descriptions, tags and screenshots now survive the trip from worker to controller), **pytest-rerunfailures** (`retries` / `flaky` instead of extra skipped entries) and **subtests** (pytest 9 built-in or `pytest-subtests`; each failing subtest gets its own name).
- pytest: collection errors (e.g. a test module that fails to import) and module-level skips are reported; skip and xfail reasons are shown; captured stdout/stderr/log is attached to failing tests.
- unittest runner: per-test durations (and the slowest-tests panel), skip reasons, `--pyrept-title`; Python 3.12+ `--durations` keeps working.
- nose2: per-test durations and skip reasons.
- Playwright converter: top-level errors (e.g. a spec that fails to load), stderr and binary stdout are imported.
- Non-image attachments with inline data (e.g. `text/plain` Cucumber embeddings) are offered as downloads instead of being dropped.

### Report redesign
- New self-contained template (no jQuery/Materialize/CDN), so it works offline and as a CI artifact.
- Summary cards, pass-rate chart, total time, slowest tests and environment panel.
- Problems listed first; search across names/descriptions/errors; status and "Problems" filters with counts; expand/collapse all.
- Durations, locations, tags, flaky/retry info, copyable tracebacks, embedded screenshots with zoom, and dark mode.
- All output is HTML-escaped (tracebacks containing `<...>` no longer break the page).

### Fixed
- nose2: subtests were recorded with an unknown `subtest` outcome (passing subtests inflated the totals and failing ones were not counted as failures); expected failures were counted as failed and unexpected successes as passed.
- behave: files attached with `context.attach()` never reached the report.
- HTML report: attachment data from imported reports was not escaped inside the `src` attribute, so a crafted Cucumber/Playwright JSON could inject HTML; `javascript:` links in attachment paths are no longer rendered.
- `pyrept convert` printed a Python traceback for invalid JSON or the wrong `--from` format; it now prints a short message and exits with status 2, and checks all inputs exist before writing anything.
- Cucumber converter: behave's `-f json` durations (seconds) were divided as if they were nanoseconds; unnamed scenarios showed as `None`; files with a UTF-8 BOM failed to load.
- pytest: `pyrept_html` / `pyrept_json` from the ini file were resolved against the current directory instead of the ini file's directory.
- unittest runner: `main()` could not be called twice in one process on Python < 3.11.
- Report building no longer fails on non-string test names, and `True`/`False` are not treated as durations.
- README: `behave -f pretty -f pyrept -o /dev/null` sent the console output to `/dev/null`; the documented order is now `-f pyrept -o /dev/null -f pretty`.
- nose2: `html-report-path` / `json-report-path` (and the documented `path` key) in `nose2.cfg` were ignored; the command line now overrides the config file, which overrides the defaults.
- Search index crashed with `AttributeError` when a docstring word matched a test name.
- Report directories are created automatically; files are written as UTF-8.
- Replaced deprecated `datetime.utcnow()`.

### Changed
- Pass rate now excludes skipped tests (passed / executed).
- JSON adds `environment`, `duration` and `slowest_tests`; the summary always includes `error` and `skipped`.
- Development status raised to Production/Stable; added Python 3.13, 3.14, `Python :: 3 :: Only` and `Framework :: Pytest` classifiers and project URLs.
- Packaging: added `pyproject.toml` build-system (setuptools + setuptools_scm) instead of the deprecated `setup_requires`; wheels are tagged `py3` only (was `py2.py3`); fixed the deprecated `description-file` key in `setup.cfg`; dropped the deprecated license classifier (the SPDX `license='MIT'` stays).
- Dev requirements: removed unused `python-coveralls` and `six`; added `behave`, `pytest-xdist` and `pytest-rerunfailures` so CI runs those integration tests.
- CI runs on every pull request across Python 3.8 to 3.14 (+3.15 pre-release; 3.8 on ubuntu-22.04 as the latest image no longer ships it); the publish workflow runs tests on 3.14 before tagging.
