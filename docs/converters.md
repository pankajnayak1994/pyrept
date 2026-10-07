# Converting reports

`pyrept convert` turns the reports of other tools into the same HTML and JSON report. Your project does not need to be written in Python: you only need Python on the machine that runs the conversion.

```bash
pyrept convert --from FORMAT INPUT... [--html report.html] [--json report.json] [--junit junit.xml]
```

| Format | Produced by | Example |
|---|---|---|
| `junit` | Maven Surefire, Gradle, Jest (jest-junit), Cypress, Go (gotestsum), pytest `--junitxml` and most runners | `pyrept convert --from junit target/surefire-reports/*.xml` |
| `trx` | .NET `dotnet test --logger trx` | `pyrept convert --from trx TestResults/*.trx` |
| `nunit` | NUnit 3 and NUnit 2 XML | `pyrept convert --from nunit TestResult.xml` |
| `xunit` | xUnit.net v2 XML | `pyrept convert --from xunit results.xml` |
| `robot` | Robot Framework `output.xml` (3.x to 7.x) | `pyrept convert --from robot output.xml` |
| `tap` | TAP 12 to 14: node `--test-reporter=tap`, prove, bats, pg_prove | `pyrept convert --from tap results.tap` |
| `allure` | any `allure-results` directory (Java, JS, Python, .NET) | `pyrept convert --from allure allure-results` |
| `cucumber` | Cucumber JSON (cucumber-jvm, cucumber-js, Ruby, godog, behave) | `pyrept convert --from cucumber cucumber.json` |
| `playwright` | Playwright Test `--reporter=json` | `pyrept convert --from playwright results.json` |
| `pytest-json` | pytest-json-report | `pyrept convert --from pytest-json .report.json` |
| `pyrept` | pyrept JSON reports (merge shards) | `pyrept convert --from pyrept shard-*/report.json` |

Several inputs are merged into one report, which also combines the results of parallel CI jobs.

## Options

| Option | Meaning |
|---|---|
| `--html PATH`, `--json PATH` | Output paths (default `report.html`, `report.json`). |
| `--junit PATH` | Also write JUnit XML, for example to show Robot Framework or TAP results in your CI's test tab. |
| `--baseline PATH` | Compare with an earlier pyrept JSON report. |
| `--markdown PATH`, `--github-summary` | Write a Markdown summary, or append it to the GitHub job summary. |
| `--fail-on-failure` | Exit with status 1 when a test failed. |
| `--ignore-known-failures` | With `--fail-on-failure`: only fail on tests that did not fail in the baseline. |
| `--fail-under PERCENT` | Exit with status 1 when the pass rate is lower. |
| `--title TEXT` | Report title. |

Exit status `2` means an input file is missing or is not a valid report of the chosen format.

## What is imported

- **Outcomes** map to passed, failed, error or skipped. Crashes, timeouts and broken tests are errors; ignored, inconclusive and TODO tests are skipped.
- **Retries** become `retries` and `flaky` (Surefire reruns, Playwright retries, Allure history).
- **Output and attachments**: captured stdout and stderr, screenshots (embedded), traces and videos (linked), TRX result files and NUnit attachments.
- **Tags** from JUnit properties, NUnit categories, xUnit.net traits, Robot Framework tags and Allure labels.
