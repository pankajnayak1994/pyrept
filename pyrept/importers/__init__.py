"""
Convert reports produced by other tools into pyrept HTML/JSON reports.
"""
from .cucumber import load_cucumber_json
from .playwright import load_playwright_json

IMPORTERS = {
    'cucumber': load_cucumber_json,
    'playwright': load_playwright_json,
}

__all__ = ['IMPORTERS', 'load_cucumber_json', 'load_playwright_json']
