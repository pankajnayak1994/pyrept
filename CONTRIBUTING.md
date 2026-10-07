# Contributing to pyrept

pyrept is developed and maintained by Pankaj Kumar Nayak ([@pankajnayak1994](https://github.com/pankajnayak1994)).

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

Releases are fully automated. When a pull request is merged into `master`, `.github/workflows/publish.yml`:

1. runs the tests, then picks the next version from the PR title (`[MAJOR]`, `[MINOR]`, `[PATCH]`; no prefix means patch) and pushes the tag, for example `v1.4.0`;
2. moves the major tag (`v1`) to it, so `uses: pankajnayak1994/pyrept@v1` always gets the newest 1.x action;
3. builds and uploads pyrept to PyPI (trusted publishing, no token);
4. creates the GitHub release with generated notes and the built files;
5. publishes the `pytest-pyrept` alias package with the same version.

Pull requests titled `[SKIP] ...` or labelled `skip-release` (Dependabot's weekly action updates) are merged without a release. The docs site and live demo redeploy on every push to `master` (`.github/workflows/docs.yml`), and `.github/workflows/test-action.yml` tests the GitHub Action itself on every pull request.

One-time setup that cannot be automated:

- **PyPI:** add a trusted publisher for the project `pytest-pyrept` (owner `pankajnayak1994`, repository `pyrept`, workflow `publish.yml`). Until then the alias step only warns.
- **GitHub Marketplace:** the repository may contain only one file named `action.yml` (the action at the root), so never name a workflow `action.yml`. To list the action, edit a release and tick "Publish this Action to the GitHub Marketplace". GitHub has no API for this, so the Marketplace page shows the version you last published there; `@v1` always gets the newest release regardless.
