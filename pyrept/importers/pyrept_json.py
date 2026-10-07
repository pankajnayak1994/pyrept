"""
Merge pyrept JSON reports, e.g. from sharded CI jobs or pytest-xdist runs on
several machines::

    pyrept convert --from pyrept shard-*/report.json --html report.html --json report.json
"""
import json

from ..report import VALID_OUTCOMES, ReportCollector


def load_pyrept_json(path, collector=None, title='Test Report'):
    with open(path, encoding='utf-8-sig') as fh:
        report = json.load(fh)
    if not isinstance(report, dict) or not isinstance(report.get('test_results'), list):
        raise ValueError('%s is not a pyrept JSON report (expected an object with "test_results")' % path)
    collector = collector or ReportCollector(title=report.get('test_report_title') or title)
    for key, value in (report.get('environment') or {}).items():
        collector.environment.setdefault(str(key), value)
    for result in report['test_results']:
        if not isinstance(result, dict) or result.get('result') not in VALID_OUTCOMES or 'name' not in result:
            continue  # hand-edited or truncated entries are skipped, not fatal
        metadata = result.get('metadata') if isinstance(result.get('metadata'), dict) else {}
        collector.add(name=result['name'], outcome=result['result'], description=result.get('description'),
                      traceback=result.get('traceback'), metadata=dict(metadata))
    return collector
