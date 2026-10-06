# Changelog

## Unreleased (1.1.0)

### Added
- pytest plugin: `pytest --pyrept`, `--pyrept-html`, `--pyrept-json` and `pyrept` / `pyrept_html` / `pyrept_json` ini options. Registered via the `pytest11` entry point and off unless enabled.
- Shared, framework-agnostic report module (`pyrept.report`) used by both plugins.
- CI runs tests on every pull request across Python 3.8 to 3.13; the publish workflow runs tests before tagging a release.

### Fixed
- nose2: `html-report-path` / `json-report-path` (and the documented `path` key) in `nose2.cfg` were ignored; command-line flags now override the config file, which overrides the defaults.
- Search index crashed with `AttributeError` when a docstring word matched a test name.
- Report directories are created automatically; files are written as UTF-8.
- Replaced deprecated `datetime.utcnow()`.

### Changed
- Development status raised from Alpha to Beta; added Python 3.13 and `Framework :: Pytest` classifiers and project URLs.
