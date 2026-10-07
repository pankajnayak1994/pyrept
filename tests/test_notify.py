import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from pyrept.notify import send_notifications, slack_payload, summary_text, teams_payload, webhook_payload
from pyrept.report import build_context, new_summary_stats, record_outcome


def _context(outcomes, baseline=None):
    stats, results = new_summary_stats(), []
    for name, outcome in outcomes:
        record_outcome(stats, results, name, outcome, traceback='boom' if outcome == 'failed' else None)
    return build_context(stats, results, title='Nightly', baseline=baseline)


class _Recorder(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802 - http.server API
        body = self.rfile.read(int(self.headers['Content-Length']))
        self.server.received.append((self.path, self.headers['Content-Type'], json.loads(body.decode('utf-8'))))
        self.send_response(self.server.status)
        self.end_headers()

    def log_message(self, *args):
        pass


class NotificationDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.server = HTTPServer(('127.0.0.1', 0), _Recorder)
        self.server.received = []
        self.server.status = 200
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = 'http://127.0.0.1:%d' % self.server.server_port

    def test_posts_to_every_configured_target(self):
        env = {'PYREPT_SLACK_WEBHOOK_URL': self.base + '/slack', 'PYREPT_TEAMS_WEBHOOK_URL': self.base + '/teams',
               'PYREPT_WEBHOOK_URL': self.base + '/hook', 'PYREPT_REPORT_URL': 'https://ci.example/report.html'}
        delivered = send_notifications(_context([('a', 'passed'), ('b', 'failed')]), environ=env)
        self.assertEqual(delivered, {'slack': True, 'teams': True, 'webhook': True})
        received = {path: (ctype, body) for path, ctype, body in self.server.received}
        self.assertEqual(received['/slack'][0], 'application/json')
        self.assertIn('❌ Nightly: 1 failed of 2 tests (pass rate 50.0%)', received['/slack'][1]['text'])
        self.assertIn('<https://ci.example/report.html|Open the report>', received['/slack'][1]['text'])
        card = received['/teams'][1]['attachments'][0]['content']
        self.assertEqual(card['actions'][0]['url'], 'https://ci.example/report.html')
        self.assertEqual(received['/hook'][1]['failures'], ['b'])
        self.assertEqual(received['/hook'][1]['status'], 'failed')

    def test_notify_on_modes(self):
        env = {'PYREPT_WEBHOOK_URL': self.base + '/hook', 'PYREPT_NOTIFY_ON': 'failure'}
        self.assertEqual(send_notifications(_context([('a', 'passed')]), environ=env), {})
        self.assertEqual(send_notifications(_context([('a', 'failed')]), environ=env), {'webhook': True})

        env['PYREPT_NOTIFY_ON'] = 'new-failures'
        baseline = {'test_results': [{'name': 'a', 'result': 'failed'}], 'test_summary': {}}
        self.assertEqual(send_notifications(_context([('a', 'failed')], baseline=baseline), environ=env), {})
        self.assertEqual(send_notifications(_context([('b', 'failed')], baseline=baseline), environ=env),
                         {'webhook': True})

        env['PYREPT_NOTIFY_ON'] = 'sometimes'
        with self.assertLogs('pyrept.notify', 'WARNING'):
            self.assertEqual(send_notifications(_context([('a', 'passed')]), environ=env), {'webhook': True})

    def test_http_errors_never_raise_and_never_log_the_secret_url(self):
        self.server.status = 500
        secret = self.base + '/services/T000/B000/SECRET-TOKEN'
        with self.assertLogs('pyrept.notify', 'WARNING') as logs:
            delivered = send_notifications(_context([('a', 'passed')]), environ={'PYREPT_SLACK_WEBHOOK_URL': secret})
        self.assertEqual(delivered, {'slack': False})
        self.assertIn('HTTP 500', logs.output[0])
        self.assertNotIn('SECRET-TOKEN', '\n'.join(logs.output))

    def test_unreachable_host_and_bad_scheme(self):
        self.server.server_close()
        env = {'PYREPT_WEBHOOK_URL': self.base + '/gone', 'PYREPT_SLACK_WEBHOOK_URL': 'file:///etc/passwd'}
        with self.assertLogs('pyrept.notify', 'WARNING') as logs:
            delivered = send_notifications(_context([('a', 'passed')]), environ=env, timeout=2)
        self.assertEqual(delivered, {'slack': False, 'webhook': False})
        self.assertNotIn('/etc/passwd', '\n'.join(logs.output))

    def test_nothing_configured(self):
        self.assertEqual(send_notifications(_context([('a', 'passed')]), environ={}), {})
        self.assertEqual(send_notifications(_context([('a', 'passed')]), environ={'PYREPT_WEBHOOK_URL': '  '}), {})


class PayloadTests(unittest.TestCase):
    def test_summary_text_variants(self):
        self.assertEqual(summary_text(_context([])), '⚠️ Nightly: no tests were run')
        self.assertEqual(summary_text(_context([('a', 'passed'), ('s', 'skipped')])),
                         '✅ Nightly: all 1 test passed (pass rate 100.0%)')
        baseline = {'test_results': [{'name': 'a', 'result': 'passed'}], 'test_summary': {'percentage': 100.0}}
        text = summary_text(_context([('a', 'failed'), ('b', 'error')], baseline=baseline))
        self.assertEqual(text, '❌ Nightly: 1 failed, 1 error of 2 tests (pass rate 0%, -100.00 pts) '
                               '· 2 new failures, 0 fixed')  # b is new and errors: also a new failure

    def test_payloads_without_report_url(self):
        ctx = _context([('a', 'passed')])
        self.assertNotIn('Open the report', slack_payload(ctx)['text'])
        self.assertNotIn('actions', teams_payload(ctx)['attachments'][0]['content'])
        hook = webhook_payload(ctx)
        self.assertIsNone(hook['report_url'])
        self.assertIsNone(hook['comparison'])
        json.dumps(hook)
