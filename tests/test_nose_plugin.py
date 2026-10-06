import sys
import unittest
from nose2 import events, result
from nose2.session import Session

from pyrept.html_report import HTMLReporter


def _test_func():
    """
    A dummy test function.
    Bug 1234
    """
    pass


def _test_func_fail():
    """
    Test case that fails.
    """
    assert 1 == 2


for func in [_test_func, _test_func_fail]:
    setattr(func, '_testMethodDoc', func.__doc__)
setattr(_test_func, 'id', lambda: _test_func.__name__)
setattr(_test_func_fail, 'id', lambda: _test_func_fail.__name__)


def create_plugin_instance():
    return HTMLReporter(session=Session())


class NosePluginTests(unittest.TestCase):
    def test_outcome_processing_successful_test(self):
        test_function = _test_func
        ev = events.TestOutcomeEvent(test_function, None, result.PASS)

        reporter = create_plugin_instance()
        reporter.testOutcome(ev)

        self.assertEqual(len(reporter.test_results), 1, 'Actual contents: %s' % reporter.test_results)
        test_result = reporter.test_results[0]
        self.assertEqual(test_result['result'], result.PASS)
        self.assertEqual(test_result['name'], test_function.__name__)
        self.assertEqual(test_result['description'], test_function.__doc__)
        self.assertIsNone(test_result['traceback'])

    def test_outcome_with_failed_test(self):
        test_function = _test_func_fail
        try:
            test_function()
        except:
            exc_info = sys.exc_info()
        ev = events.TestOutcomeEvent(test_function, None, result.FAIL, exc_info=exc_info)

        reporter = create_plugin_instance()
        reporter.testOutcome(ev)

        self.assertEqual(len(reporter.test_results), 1, 'Actual contents: %s' % reporter.test_results)
        test_result = reporter.test_results[0]
        self.assertEqual(test_result['result'], result.FAIL)
        self.assertEqual(test_result['name'], test_function.__name__)
        self.assertEqual(test_result['description'], test_function.__doc__)
        self.assertIsNotNone(test_result['traceback'])
        self.assertIn('assert 1 == 2', test_result['traceback'])

    def test_summary_stats_new_test(self):
        ev = events.TestOutcomeEvent(_test_func, None, result.PASS)
        reporter = create_plugin_instance()
        reporter.testOutcome(ev)

        self.assertIn('passed', reporter.summary_stats)
        self.assertEqual(reporter.summary_stats['passed'], 1)

    def test_summary_stats_increment(self):
        ev = events.TestOutcomeEvent(_test_func, None, result.PASS)
        reporter = create_plugin_instance()
        reporter.summary_stats['passed'] = 10
        reporter.testOutcome(ev)

        self.assertIn('passed', reporter.summary_stats)
        self.assertEqual(reporter.summary_stats['passed'], 11)

    def test_summary_stats_total(self):
        ev = events.TestOutcomeEvent(_test_func, None, result.PASS)
        reporter = create_plugin_instance()
        for i in range(0, 20):
            reporter.testOutcome(ev)

        self.assertIn('passed', reporter.summary_stats)
        self.assertEqual(reporter.summary_stats['total'], 20)

    def test_outcome_with_error_test_result(self):
        test_function = _test_func_fail
        try:
            test_function()
        except:
            exc_info = sys.exc_info()
        ev = events.TestOutcomeEvent(test_function, None, result.ERROR, exc_info=exc_info)

        reporter = create_plugin_instance()
        reporter.testOutcome(ev)

        self.assertEqual(len(reporter.test_results), 1, 'Actual contents: %s' % reporter.test_results)
        test_result = reporter.test_results[0]
        self.assertEqual(test_result['result'], result.ERROR)
        self.assertEqual(test_result['name'], test_function.__name__)
        self.assertEqual(test_result['description'], test_function.__doc__)
        self.assertIsNotNone(test_result['traceback'])
        self.assertIn('assert 1 == 2', test_result['traceback'])


class FetchFilePathTests(unittest.TestCase):
    def test_defaults_are_none_so_config_can_apply(self):
        from pyrept.html_report import fetch_file_path
        self.assertEqual(fetch_file_path([]), {'html-report-path': None, 'json-report-path': None})

    def test_cli_paths(self):
        from pyrept.html_report import fetch_file_path
        paths = fetch_file_path(['--html-report-path=out/r.html', '--json-report-path=out/r.json'])
        self.assertEqual(paths, {'html-report-path': 'out/r.html', 'json-report-path': 'out/r.json'})

    def test_invalid_extension(self):
        from pyrept.html_report import fetch_file_path
        with self.assertRaises(ValueError):
            fetch_file_path(['--html-report-path=out/r.txt'])


class ConfigPathTests(unittest.TestCase):
    def _reporter_with_cfg(self, body):
        import os
        import tempfile
        tmp = tempfile.mkdtemp()
        cfg = os.path.join(tmp, 'nose2.cfg')
        with open(cfg, 'w') as fh:
            fh.write(body.format(tmp=tmp))
        session = Session()
        session.loadConfigFiles(cfg)
        return tmp, HTMLReporter(session=session)

    def test_config_file_paths_are_used(self):
        import os
        tmp, reporter = self._reporter_with_cfg(
            '[html-report]\nhtml-report-path = {tmp}/x.html\njson-report-path = {tmp}/x.json\n')
        self.assertEqual(reporter._config['html_report_path'], os.path.realpath(os.path.join(tmp, 'x.html')))
        self.assertEqual(reporter._config['json_report_path'], os.path.realpath(os.path.join(tmp, 'x.json')))

    def test_legacy_path_key(self):
        import os
        tmp, reporter = self._reporter_with_cfg('[html-report]\npath = {tmp}/legacy.html\n')
        self.assertEqual(reporter._config['html_report_path'], os.path.realpath(os.path.join(tmp, 'legacy.html')))
