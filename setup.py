from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name='pyrept',
    packages=find_packages(),
    use_scm_version=True,
    setup_requires=['setuptools_scm'],
    description='This library generates both HTML and JSON reports for your Nose unit tests, providing a clear and structured overview of test results.',
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
    keywords=['nose2', 'testing', 'reporting', 'pytest'],
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Developers',
        'Topic :: Software Development :: Testing',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.12',
    ]
)
