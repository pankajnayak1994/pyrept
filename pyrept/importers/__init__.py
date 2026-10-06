"""
Convert reports produced by other tools into pyrept HTML/JSON reports.
"""
from .cucumber import load_cucumber_json
from .junit import load_junit_xml
from .playwright import load_playwright_json

IMPORTERS = {
    'cucumber': load_cucumber_json,
    'junit': load_junit_xml,
    'playwright': load_playwright_json,
}

__all__ = ['IMPORTERS', 'load_cucumber_json', 'load_junit_xml', 'load_playwright_json']
