coverage:
	coverage run -m pytest
	coverage combine
	coverage report

uninstall:
	pip uninstall pyrept -y

changelog:
	pip3 install git-changelog
	git-changelog -t keepachnagelog . -o docs/changelog.rst -s basic
