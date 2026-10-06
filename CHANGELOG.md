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

### Report redesign
- New self-contained template (no jQuery/Materialize/CDN), so it works offline and as a CI artifact.
- Summary cards, pass-rate chart, total time, slowest tests and environment panel.
- Problems listed first; search across names/descriptions/errors; status and "Problems" filters with counts; expand/collapse all.
- Durations, locations, tags, flaky/retry info, copyable tracebacks, embedded screenshots with zoom, and dark mode.
- All output is HTML-escaped (tracebacks containing `<...>` no longer break the page).

### Fixed
- nose2: `html-report-path` / `json-report-path` (and the documented `path` key) in `nose2.cfg` were ignored; the command line now overrides the config file, which overrides the defaults.
- Search index crashed with `AttributeError` when a docstring word matched a test name.
- Report directories are created automatically; files are written as UTF-8.
- Replaced deprecated `datetime.utcnow()`.

### Changed
- Pass rate now excludes skipped tests (passed / executed).
- JSON adds `environment`, `duration` and `slowest_tests`; the summary always includes `error` and `skipped`.
- Development status raised from Alpha to Beta; added Python 3.13 and `Framework :: Pytest` classifiers and project URLs.
- CI runs on every pull request across Python 3.8 to 3.13; the publish workflow runs tests before tagging.
