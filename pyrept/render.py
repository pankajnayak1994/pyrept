"""
    Functions to generate the HTML output
"""


def load_template(template_file_path):
    """
    Load a Jinja2 template and return it

    Args:
        template_file_path (str): path to the Jinja2 template file

    Returns:
        Template: contains jinja2 template
    """
    from jinja2 import Template  # imported lazily so report building works without jinja2

    with open(template_file_path, encoding='utf-8') as fh:
        return Template(fh.read())


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
