# Contributing to pyrept

Thanks for helping! Bug reports, new converters, framework integrations and docs fixes are all welcome.

## Set up

```bash
git clone https://github.com/pankajnayak1994/pyrept && cd pyrept
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt -e .
pytest
```

The suite covers every integration (pytest, unittest, nose2, behave, pytest-bdd), every converter and the GitHub Action script. CI runs it on Python 3.8 to 3.14 and the 3.15 pre-releases, so avoid syntax and standard-library features newer than Python 3.8.

## Where things live

| Path | What |
|---|---|
| `pyrept/report.py` | `ReportCollector`, the report context and writing the files |
| `pyrept/pytest_plugin.py`, `unittest_runner.py`, `html_report.py` (nose2), `behave_formatter.py` | Framework integrations |
| `pyrept/importers/` | One module per `pyrept convert --from` format |
| `pyrept/compare.py`, `history.py`, `summary.py`, `notify.py` | Baseline comparison, history, Markdown and gates, notifications |
| `pyrept/templates/` | `report.html`, `history.html` and the shared `_theme.css` |
| `action.yml`, `action/pyrept-action.sh` | The GitHub Action |
| `docs/` | The documentation site (MkDocs) and `docs/demo/make_demo.py` |

## Adding a converter

1. Add `pyrept/importers/<format>.py` with `load_<format>(path, collector=None)` that calls `collector.add(...)` per test and raises `ValueError` for files of another format.
2. Register it in `pyrept/importers/__init__.py` (`IMPORTERS` and `DISPLAY_NAMES`).
3. Add a fixture produced by the real tool under `tests/fixtures/` (remove machine names and paths) and tests in `tests/test_importers_formats.py`.
4. Document it in the README table and `docs/converters.md`.

## Changing the HTML report

- Escape everything that comes from test results (`|e`): names, messages and attachments can contain HTML.
- The report must keep working offline: no CDN, fonts or external scripts.
- Check light and dark mode and a narrow window, and refresh the screenshots with `python docs/demo/make_demo.py site/demo --screenshots` (needs Playwright and Chrome).

## Pull requests

- Add or update tests, keep `flake8 pyrept tests` clean and update `CHANGELOG.md` under "Unreleased".
- Start the PR title with `[MAJOR]`, `[MINOR]` or `[PATCH]`: the publish workflow reads it to pick the next version when the PR is merged.

## Releases

Merging to `master` tags the version from the PR title and publishes to PyPI. The `pytest-pyrept` alias package in `packaging/pytest-pyrept` is published by hand when pyrept's minimum version there changes:

```bash
python -m build packaging/pytest-pyrept && twine upload packaging/pytest-pyrept/dist/*
```
