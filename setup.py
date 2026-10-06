from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name='pyrept',
    packages=find_packages(exclude=['tests', 'tests.*']),
    use_scm_version=True,
    setup_requires=['setuptools_scm'],
    description='Searchable HTML and JSON test reports for pytest and nose2.',
    long_description=long_description,
    long_description_content_type="text/markdown",
    author='Pankaj Kumar Nayak',
    author_email='nayakpankaj2015@gmail.com',
    license='MIT',
    install_requires=['jinja2', 'nose2'],
    package_data={
        'pyrept': ['templates/report.html']
    },
    url='https://github.com/pankajnayak1994/pyrept',
    download_url='https://github.com/pankajnayak1994/pyrept',
    project_urls={
        'Source': 'https://github.com/pankajnayak1994/pyrept',
        'Issues': 'https://github.com/pankajnayak1994/pyrept/issues',
        'Changelog': 'https://github.com/pankajnayak1994/pyrept/blob/master/CHANGELOG.md',
    },
    python_requires='>=3.8',
    entry_points={
        'pytest11': ['pyrept = pyrept.pytest_plugin'],
    },
    keywords=['nose2', 'pytest', 'testing', 'reporting', 'html-report', 'json-report'],
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'Topic :: Software Development :: Testing',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.12',
        'Programming Language :: Python :: 3.13',
        'Framework :: Pytest',
    ]
)
