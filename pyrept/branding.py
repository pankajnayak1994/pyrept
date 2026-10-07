"""
Report branding: your logo and accent colour in the HTML reports.

    PYREPT_LOGO          image file (embedded, up to 1 MB) or http(s) URL
    PYREPT_ACCENT_COLOR  CSS hex colour such as #0f766e

Branding is applied when the HTML is rendered and never stored in the JSON report.
"""
import base64
import logging
import mimetypes
import os
import re

logger = logging.getLogger(__name__)

LOGO_ENV = 'PYREPT_LOGO'
ACCENT_ENV = 'PYREPT_ACCENT_COLOR'
MAX_LOGO_BYTES = 1024 * 1024
_HEX_COLOR = re.compile(r'^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$')


def logo_source(value):
    """An ``<img src>`` for a logo path or URL, or ``None`` (with a warning) when it cannot be used."""
    value = (value or '').strip()
    if not value:
        return None
    if value.lower().startswith(('https://', 'http://')):
        return value
    path = os.path.expanduser(value)
    content_type = mimetypes.guess_type(path)[0] or ''
    if not content_type.startswith('image/'):
        logger.warning('pyrept: %s=%s is not an image file or URL; logo skipped', LOGO_ENV, value)
        return None
    try:
        if os.path.getsize(path) > MAX_LOGO_BYTES:
            logger.warning('pyrept: logo %s is larger than 1 MB; logo skipped', value)
            return None
        with open(path, 'rb') as fh:
            return 'data:%s;base64,%s' % (content_type, base64.b64encode(fh.read()).decode('ascii'))
    except OSError as exc:
        logger.warning('pyrept: cannot read logo %s: %s', value, exc)
        return None


def accent_color(value):
    value = (value or '').strip()
    if not value:
        return None
    if not _HEX_COLOR.match(value):
        logger.warning('pyrept: %s must be a hex colour such as #0f766e, got %r; ignored', ACCENT_ENV, value)
        return None
    return value


def branding_from_env(environ=None):
    environ = os.environ if environ is None else environ
    return {'logo': logo_source(environ.get(LOGO_ENV)), 'accent': accent_color(environ.get(ACCENT_ENV))}
