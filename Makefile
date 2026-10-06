BUMP_TYPE ?= PATCH

coverage:
	coverage run -m pytest
	coverage combine
	coverage report

uninstall:
	pip uninstall py-html-json-reporter -y

changelog:
	pip3 install git-changelog
	git-changelog -t keepachnagelog . -o docs/changelog.rst -s basic

version-bump:
	git pull origin master
	python version_bump.py $(BUMP_TYPE)