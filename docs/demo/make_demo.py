"""
Build the demo reports used by the README screenshots and the docs site.

    python docs/demo/make_demo.py site/demo                  # report.html, history.html, ...
    python docs/demo/make_demo.py site/demo --screenshots    # also docs/images/*.png (needs Playwright + Chrome)

The data is invented: a small web shop's test suite over several nightly runs.
"""
import argparse
import json
import os
import random
import sys
import zlib

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from pyrept import ReportCollector, make_attachment  # noqa: E402
from pyrept.history import build_history, load_runs, write_history  # noqa: E402

ENVIRONMENT = {'Python': '3.13.2', 'Platform': 'Linux-6.8-x86_64', 'Framework': 'pytest 9.0 + Playwright',
               'Branch': 'main', 'Build': '#1842'}

PAY_TB = '''page = <Page url='https://shop.test/checkout'>

    def test_pay_with_card(page):
        """Pays with a saved Visa card and expects the confirmation page."""
        page.goto("/checkout")
        page.get_by_role("button", name="Pay now").click()
>       expect(page).to_have_title("Order confirmed")
E       AssertionError: Page title expected to be 'Order confirmed'
E       Actual value: 'Payment failed'

tests/test_checkout.py:42: AssertionError'''

COUPON_TB = '''    def test_apply_coupon(cart):
        cart.add("SKU-1001", qty=2)
        cart.apply_coupon("AUTUMN15")
>       assert cart.total() == 85.0
E       assert 90.0 == 85.0
E        +  where 90.0 = <Cart items=2>.total()

tests/test_checkout.py:71: AssertionError'''

REDIS_TB = '''    @pytest.fixture
    def cache():
>       return redis.Redis.from_url(os.environ["CACHE_URL"]).ping()
E       redis.exceptions.ConnectionError: Error 111 connecting to cache:6379. Connection refused.

tests/conftest.py:18: ConnectionError'''

# name: (outcome now, duration, tags, description, traceback)
TESTS = [
    ('tests/test_checkout.py::test_pay_with_card', 'failed', 3.42, ['smoke', 'payments'],
     'Pays with a saved Visa card.\nExpects the confirmation page.', PAY_TB),
    ('tests/test_checkout.py::test_apply_coupon', 'failed', 0.33, ['payments'], 'AUTUMN15 takes 15% off.', COUPON_TB),
    ('tests/test_api.py::test_rate_limit', 'error', 0.01, [], None, REDIS_TB),
    ('tests/test_api.py::test_session_cache', 'error', 0.02, [], None, REDIS_TB),
    ('tests/test_auth.py::test_login_redirect', 'passed', 0.41, ['smoke'], 'Unauthenticated users go to /login.', None),
    ('tests/test_auth.py::test_password_reset', 'passed', 0.49, [], 'Reset email arrives with a valid link.', None),
    ('tests/test_auth.py::test_logout', 'passed', 0.11, [], None, None),
    ('tests/test_catalog.py::test_search[shoes]', 'passed', 1.38, ['search'], None, None),
    ('tests/test_catalog.py::test_search[hats]', 'passed', 0.61, ['search'], None, None),
    ('tests/test_catalog.py::test_filters', 'passed', 0.70, [], 'Price and size filters combine.', None),
    ('tests/test_cart.py::test_add_item', 'passed', 0.22, ['smoke'], None, None),
    ('tests/test_cart.py::test_remove_item', 'passed', 0.20, [], None, None),
    ('tests/test_cart.py::test_quantity_limits', 'passed', 0.18, [], None, None),
    ('tests/test_wishlist.py::test_share_link', 'passed', 0.27, [], 'A shared wishlist opens without login.', None),
    ('tests/test_search.py::test_autocomplete', 'skipped', 0.0, [], None, 'Skipped: search service down'),
] + [('tests/test_products.py::test_product_page[sku-%d]' % i, 'passed', round(0.05 + (i % 7) * 0.03, 3), [],
      None, None) for i in range(1001, 1037)]


def _png(width, height, rgb):
    """A tiny solid-colour PNG, so the demo needs no image files."""
    raw = b''.join(b'\x00' + bytes(rgb) * width for _ in range(height))

    def chunk(kind, data):
        return (len(data).to_bytes(4, 'big') + kind + data
                + zlib.crc32(kind + data).to_bytes(4, 'big'))
    header = width.to_bytes(4, 'big') + height.to_bytes(4, 'big') + b'\x08\x02\x00\x00\x00'
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header) + chunk(b'IDAT', zlib.compress(raw))
            + chunk(b'IEND', b''))


def _run(outcome_for, title='Checkout suite', seed=0):
    rng = random.Random(seed)
    collector = ReportCollector(title=title, environment=ENVIRONMENT)
    for name, outcome, duration, tags, description, traceback in TESTS:
        outcome = outcome_for(name, outcome)
        if outcome is None:
            continue
        attachments = []
        if name.endswith('test_pay_with_card') and outcome == 'failed':
            shot = _png(360, 200, (243, 228, 228))
            attachments.append(make_attachment('Screenshot on failure', 'image/png', data=shot))
            attachments.append(make_attachment('Captured log call', 'text/plain',
                                               text='WARNING  payments: gateway answered 402 (card declined)'))
        jitter = duration * rng.uniform(-0.08, 0.08)
        collector.add(name, outcome, description=description,
                      traceback=traceback if outcome in ('failed', 'error', 'skipped') else None,
                      metadata={'duration': round(max(duration + jitter, 0), 3), 'tags': tags,
                                'location': '%s:%d' % (name.split('::')[0], 10 + len(name) % 60)},
                      attachments=attachments or None)
    return collector


def build(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    history_dir = os.path.join(out_dir, 'history')
    os.makedirs(history_dir, exist_ok=True)

    flaky = 'tests/test_catalog.py::test_filters'
    nights = []
    for night in range(12):
        def outcome_for(name, outcome, night=night):
            if name == flaky:
                return 'failed' if night in (2, 5, 10) else 'passed'
            if name.endswith('test_pay_with_card'):
                return 'failed' if night >= 9 else 'passed'
            if name.endswith('test_apply_coupon'):
                return 'failed' if night == 11 else 'passed'
            if 'test_api.py' in name:
                return 'error' if night in (6, 11) else 'passed'
            if name.endswith('test_share_link') and night < 8:
                return None  # added later
            if name.endswith('test_password_reset') and night in (3, 4):
                return 'failed'
            return outcome if outcome != 'failed' else 'passed'
        nights.append(outcome_for)

    for night, outcome_for in enumerate(nights):
        path = os.path.join(history_dir, 'run-%02d.json' % (night + 1))
        _run(outcome_for, seed=night).write(os.path.join(out_dir, '.tmp.html'), path)
        with open(path, encoding='utf-8') as fh:
            data = json.load(fh)
        data['timestamp'] = '2026/09/%02d 02:00:%02d UTC' % (night + 20 if night < 11 else 30, night)
        if night == 11:
            data['timestamp'] = '2026/10/01 02:00:11 UTC'
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(data, fh)
    os.remove(os.path.join(out_dir, '.tmp.html'))

    baseline = os.path.join(history_dir, 'run-11.json')
    _run(nights[-1], seed=11).write(os.path.join(out_dir, 'report.html'), os.path.join(out_dir, 'report.json'),
                                    junit_path=os.path.join(out_dir, 'junit.xml'),
                                    markdown_path=os.path.join(out_dir, 'summary.md'), baseline_path=baseline)
    runs, _ = load_runs(sorted(os.path.join(history_dir, f) for f in os.listdir(history_dir)))
    write_history(build_history(runs, title='Checkout suite: last 12 nights'),
                  html_path=os.path.join(out_dir, 'history.html'), json_path=os.path.join(out_dir, 'history.json'))
    return out_dir


def screenshots(out_dir, image_dir):
    from playwright.sync_api import sync_playwright

    os.makedirs(image_dir, exist_ok=True)
    report = 'file://' + os.path.abspath(os.path.join(out_dir, 'report.html'))
    history = 'file://' + os.path.abspath(os.path.join(out_dir, 'history.html'))
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception:
            browser = p.chromium.launch(channel='chrome')
        for scheme in ('light', 'dark'):
            page = browser.new_page(viewport={'width': 1280, 'height': 900}, device_scale_factor=2, color_scheme=scheme)
            page.goto(report)
            suffix = '' if scheme == 'light' else '-dark'
            page.screenshot(path=os.path.join(image_dir, 'report%s.png' % suffix), full_page=False)
            if scheme == 'light':
                page.evaluate("document.querySelectorAll('.compare details')"
                              ".forEach(d => d.open = /New failures|Fixed|Slower/.test(d.textContent))")
                page.evaluate("document.querySelectorAll('details.test').forEach(d => d.open = false)")
                page.wait_for_timeout(400)  # let the open/close transitions finish
                box = page.evaluate("""() => {
                    const r = document.querySelector('.compare').getBoundingClientRect();
                    return {y: r.top + window.scrollY, h: r.height};
                }""")
                page.screenshot(path=os.path.join(image_dir, 'comparison.png'), full_page=True,
                                clip={'x': 0, 'y': box['y'] - 16, 'width': 1280, 'height': box['h'] + 32})
            page.goto(history)
            page.screenshot(path=os.path.join(image_dir, 'history%s.png' % suffix), full_page=False)
            page.close()
        browser.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument('out_dir')
    parser.add_argument('--screenshots', action='store_true', help='Also write docs/images/*.png.')
    args = parser.parse_args()
    build(args.out_dir)
    if args.screenshots:
        screenshots(args.out_dir, os.path.join(os.path.dirname(__file__), '..', 'images'))
    print('demo written to %s' % os.path.abspath(args.out_dir))


if __name__ == '__main__':
    main()
