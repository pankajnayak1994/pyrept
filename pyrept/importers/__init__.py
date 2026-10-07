"""
Convert reports produced by other tools into pyrept HTML/JSON reports.
"""
from .allure import load_allure_results
from .cucumber import load_cucumber_json
from .junit import load_junit_xml
from .nunit import load_nunit_xml, load_xunit_xml
from .playwright import load_playwright_json
from .pyrept_json import load_pyrept_json
from .pytest_json import load_pytest_json
from .robot import load_robot_xml
from .tap import load_tap
from .trx import load_trx

IMPORTERS = {
    'allure': load_allure_results,
    'cucumber': load_cucumber_json,
    'junit': load_junit_xml,
    'nunit': load_nunit_xml,
    'playwright': load_playwright_json,
    'pyrept': load_pyrept_json,
    'pytest-json': load_pytest_json,
    'robot': load_robot_xml,
    'tap': load_tap,
    'trx': load_trx,
    'xunit': load_xunit_xml,
}

# Shown in the report's "Framework" field and the default title.
DISPLAY_NAMES = {
    'allure': 'Allure', 'cucumber': 'Cucumber', 'junit': 'JUnit', 'nunit': 'NUnit', 'playwright': 'Playwright',
    'pyrept': 'pyrept', 'pytest-json': 'pytest', 'robot': 'Robot Framework', 'tap': 'TAP', 'trx': '.NET (TRX)',
    'xunit': 'xUnit.net',
}

__all__ = ['DISPLAY_NAMES', 'IMPORTERS', 'load_allure_results', 'load_cucumber_json', 'load_junit_xml',
           'load_nunit_xml', 'load_playwright_json', 'load_pyrept_json', 'load_pytest_json', 'load_robot_xml',
           'load_tap', 'load_trx', 'load_xunit_xml']
