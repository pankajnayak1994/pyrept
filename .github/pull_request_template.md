<!--
PR title must start with the version bump. The publish workflow reads it on merge:
  [MAJOR] breaking change   ·   [MINOR] new feature   ·   [PATCH] bug fix / docs / CI
No prefix defaults to [PATCH].
Example: [MINOR] Add pytest-xdist support
-->

## Summary
<!-- What changes and why, in a few sentences. Link the issue: "Fixes #123". -->


## Type of change
- [ ] Bug fix
- [ ] New feature or integration
- [ ] Breaking change (report format, CLI options, public API or Python version support)
- [ ] Docs only
- [ ] CI, packaging or tooling

## Areas affected
- [ ] pytest plugin
- [ ] unittest runner
- [ ] nose2 plugin
- [ ] behave formatter
- [ ] `pyrept convert` (converters in `pyrept/importers/`)
- [ ] `pyrept summary` / `pyrept history`, quality gates or notifications
- [ ] GitHub Action (`action.yml`)
- [ ] HTML templates (report, history)
- [ ] JSON report format
- [ ] Python API (`ReportCollector`, `make_attachment`) or pytest hooks
- [ ] Docs site

## How was this tested?
<!-- Commands run, Python versions used, and screenshots of the HTML report if the template changed. -->


## Checklist
- [ ] Tests added or updated; `pytest` passes locally
- [ ] `flake8 pyrept tests` is clean
- [ ] Coverage stays at the same level (`coverage run -m pytest && coverage combine && coverage report`)
- [ ] Any user-supplied text the template renders is escaped
- [ ] README updated if usage, options or output changed
- [ ] CHANGELOG.md updated under "Unreleased"
- [ ] PR title starts with `[MAJOR]`, `[MINOR]` or `[PATCH]`
