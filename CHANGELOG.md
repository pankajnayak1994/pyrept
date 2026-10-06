# Changelog

## Unreleased (1.1.0)

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
