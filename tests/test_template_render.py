import unittest
from jinja2 import Template

from pyrept.render import render_template


class TemplateRenderingTests(unittest.TestCase):
    def test_template_render(self):
        template = Template('<h1>This is {{ name }} html json report generation service created on {{ time_stamp }}.</h1>')
        context = {
            'name': 'py-html-json-report',
            'time_stamp': '2025-01-01'
        }
        rendered_template = render_template(template, context)
        self.assertEqual(rendered_template, '<h1>This is py-html-json-report html json report generation service created on 2025-01-01.</h1>')
