# CI, gates and notifications

## GitHub Action

The **pyrept** action ([GitHub Marketplace](https://github.com/marketplace?type=actions&query=pyrept)) adds the result to the job summary and keeps one comment on the pull request up to date.

```yaml
permissions:
  contents: read
  pull-requests: write   # for the PR comment

steps:
  - uses: actions/checkout@v4
  - uses: actions/setup-python@v5
    with:
      python-version: '3.13'
  - run: pip install pyrept && pytest --pyrept-json=reports/report.json --pyrept-html=reports/report.html
    continue-on-error: true            # let the action decide whether the job fails
  - uses: pankajnayak1994/pyrept@v1
    with:
      report: reports/report.json
      fail-on-failure: true
  - uses: actions/upload-artifact@v4
    if: always()
    with:
      name: test-report
      path: reports/
```

Any language works through `convert-from`:

```yaml
  - run: mvn test
    continue-on-error: true
  - uses: pankajnayak1994/pyrept@v1
    with:
      convert-from: junit
      convert-inputs: target/surefire-reports/*.xml
      report: reports/report.json
      fail-on-failure: true
```

| Input | Default | Meaning |
|---|---|---|
| `report` | `report.json` | The pyrept JSON report to summarise. |
| `convert-from`, `convert-inputs` | | Convert another tool's report first (any `pyrept convert` format). |
| `html`, `junit`, `baseline`, `title` | | Options for `convert-from`. |
| `job-summary` | `true` | Add the summary to the job summary. |
| `pr-comment` | `true` | Comment on the pull request and update that comment on every run. |
| `fail-on-failure` | `false` | Fail when a test failed. |
| `ignore-known-failures` | `false` | Only fail on new failures (needs a baseline). |
| `fail-under` | | Fail when the pass rate is below this percentage. |
| `report-url` | | Link to the published HTML report. |
| `notify` | `false` | Send the notifications configured below. |
| `version` | latest | pyrept version to install. |

Outputs: `total`, `passed`, `failed`, `errors`, `skipped`, `pass-rate` and `new-failures`.

`@v1` always points to the newest 1.x release; pin an exact release such as `@v1.3.3` if you prefer.

Without the action, `pytest --pyrept-github-summary` (or `pyrept summary report.json --github-summary`) writes the same job summary.

## Quality gates

| Gate | pytest | unittest | nose2 | convert / summary |
|---|---|---|---|---|
| Fail below a pass rate | `--pyrept-fail-under=95` | `--pyrept-fail-under 95` | `--pyrept-fail-under=95` | `--fail-under 95` |
| Only fail on new failures | `--pyrept-ignore-known-failures` | same | same | `--fail-on-failure --ignore-known-failures` |

`ignore-known-failures` lets a job with known-broken tests stay green until a test breaks that passed in the baseline. Combine it with a pass-rate floor so known failures cannot pile up:

```bash
pytest --pyrept-baseline=reports/report.json --pyrept-json=reports/report.json \
       --pyrept-ignore-known-failures --pyrept-fail-under=90
```

With pytest, pyrept never turns a run green when another plugin failed it too (for example pytest-cov's `--cov-fail-under`), and never hides collection errors. With nose2, do not combine `ignore-known-failures` with other plugins that fail the run, such as the coverage plugin's `fail-under`. When no tests were executed at all, `fail-under` is not checked. behave decides its own exit status, so gates are not available there; use `pyrept summary report.json --fail-under 95` after behave instead.

## Notifications

Set environment variables in CI; nothing else changes. Webhook URLs are secrets, so they are never logged.

| Variable | Meaning |
|---|---|
| `PYREPT_SLACK_WEBHOOK_URL` | Slack incoming webhook. |
| `PYREPT_TEAMS_WEBHOOK_URL` | Teams workflow webhook ("When a Teams webhook request is received"). |
| `PYREPT_WEBHOOK_URL` | Any endpoint; receives the summary as JSON. |
| `PYREPT_NOTIFY_ON` | `always` (default), `failure` or `new-failures`. |
| `PYREPT_REPORT_URL` | Link to the published report, added to every message and summary. |

Every integration sends them after writing its report. A message that cannot be delivered is logged as a warning and never fails the run.

## GitLab CI and Jenkins

```yaml
# .gitlab-ci.yml
test:
  script:
    - pytest --pyrept-html=reports/report.html --pyrept-junit=reports/junit.xml
  artifacts:
    when: always
    paths: [reports/]
    reports:
      junit: reports/junit.xml
```

```groovy
// Jenkinsfile
sh 'pytest --pyrept-html=reports/report.html --pyrept-junit=reports/junit.xml'
junit 'reports/junit.xml'
archiveArtifacts artifacts: 'reports/**', allowEmptyArchive: true
```
