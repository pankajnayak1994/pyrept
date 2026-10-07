"""
    Functions to generate the HTML output
"""
import os
import re

PACKAGE_TEMPLATES = os.path.join(os.path.dirname(__file__), 'templates')

# Separators between a test's "where" and its own name, most specific first:
# pytest ``a/b.py::Class::test``, BDD ``Feature :: Scenario``, Playwright ``file › describe › test``.
_SEPARATORS = (' :: ', '::', ' › ')
_DOTTED = re.compile(r'^([A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)+)\.([A-Za-z_]\w*)(.*)$', re.DOTALL)


def split_test_name(name):
    """
    Split a test name into ``(where, own name)`` for display; ``where`` keeps its trailing separator.

    ``tests/test_a.py::test_x[1]`` -> ``('tests/test_a.py::', 'test_x[1]')``
    ``pkg.mod.TestX.test_y (i=1)`` -> ``('pkg.mod.TestX.', 'test_y (i=1)')``
    """
    name = str(name)
    # Never split inside parameter ids ("test_x[a::b]"); a leading "[project] " is not one.
    start = name.index('] ') + 2 if name.startswith('[') and '] ' in name else 0
    bracket = name.find('[', start)
    head = name[:bracket] if bracket != -1 else name
    for separator in _SEPARATORS:
        index = head.rfind(separator)
        if index > 0:
            cut = index + len(separator)
            return name[:cut], name[cut:]
    match = _DOTTED.match(name)
    if match:
        return match.group(1) + '.', match.group(2) + match.group(3)
    return '', name


def _environment(template_dir):
    from jinja2 import ChoiceLoader, Environment, FileSystemLoader  # imported lazily: optional at import time

    loaders = [FileSystemLoader(template_dir)]
    if os.path.realpath(template_dir) != os.path.realpath(PACKAGE_TEMPLATES):
        loaders.append(FileSystemLoader(PACKAGE_TEMPLATES))  # custom templates can include the built-in parts
    env = Environment(loader=ChoiceLoader(loaders), autoescape=False)
    env.filters['split_test_name'] = split_test_name
    return env


def load_template(template_file_path):
    """
    Load a Jinja2 template and return it

    Args:
        template_file_path (str): path to the Jinja2 template file

    Returns:
        Template: contains jinja2 template
    """
    template_file_path = os.path.abspath(template_file_path)
    if not os.path.isfile(template_file_path):
        raise FileNotFoundError('template not found: %s' % template_file_path)
    env = _environment(os.path.dirname(template_file_path))
    return env.get_template(os.path.basename(template_file_path))


def render_template(template, context):
    """
    Generate an HTML test report.

    Args:
        template (Template): Jinja2 Template object containing the template to render
        context (dict): the context to pass to the template

    Returns:
        str: the contents of the rendered template
    """
    return template.render(context)
