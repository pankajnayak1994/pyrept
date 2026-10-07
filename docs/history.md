# Comparison and history

## Compare with the previous run

Pass an earlier `report.json` as the baseline. It may be the very file the run is about to overwrite: pyrept reads it first.

```bash
pytest --pyrept --pyrept-baseline=report.json
pyrept convert --from junit results/*.xml --baseline report.json
```

The report then opens with a comparison panel, and every changed test is marked:

| Label | Meaning |
|---|---|
| New failure | Fails now, passed or did not exist before. Look at these first. |
| Fixed | Failed before, passes now. |
| Still failing | Failed in both runs. |
| New / Removed | Not in the baseline / no longer in this run. |
| Slower | At least 1.5× and 0.5 s slower than in the baseline. |

`report.html#new-failures` opens the report with only the new failures shown. A missing baseline (the first CI run) is not an error.

### Keeping the baseline in GitHub Actions

```yaml
- uses: actions/cache/restore@v4
  with:
    path: reports/report.json
    key: pyrept-${{ github.ref_name }}-${{ github.run_id }}
    restore-keys: pyrept-${{ github.ref_name }}-
- run: pytest --pyrept-json=reports/report.json --pyrept-baseline=reports/report.json
- uses: actions/cache/save@v4
  if: always()
  with:
    path: reports/report.json
    key: pyrept-${{ github.ref_name }}-${{ github.run_id }}
```

## History across many runs

`pyrept history` reads the JSON reports of many runs and writes a page with:

- **Pass rate over time**, outcomes per run and run durations.
- **Flaky tests**: tests that fail in two or more separate stretches with passing runs in between, or that passed only after a retry. A test that broke once and was fixed is a regression, not flakiness, and is not listed.
- **Failing now**: how many runs in a row each test has been failing, and since when.
- **Most failing** and **slowest** tests, with a run-by-run outcome strip for each.

```bash
pyrept history history/ --html reports/history.html --json reports/history.json --limit 30
```

Keep one report per run, for example in a cached directory:

```yaml
- uses: actions/cache/restore@v4
  with:
    path: history
    key: pyrept-history-${{ github.run_id }}
    restore-keys: pyrept-history-
- run: |
    pytest --pyrept-json=reports/report.json || true
    mkdir -p history && cp reports/report.json "history/run-${{ github.run_number }}.json"
    ls -t history/*.json | tail -n +31 | xargs -r rm   # keep the newest 30
    pyrept history history --html reports/history.html
- uses: actions/cache/save@v4
  if: always()
  with:
    path: history
    key: pyrept-history-${{ github.run_id }}
```

Files that are not pyrept reports are skipped with a message, and runs are ordered by their timestamp, not by file name.
