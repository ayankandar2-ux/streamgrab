.PHONY: install test lint build clean publish

install:
	python -m pip install -e ".[dev,crypto]"

test:
	python -m pytest -q

lint:
	ruff check streamgrab tests

build:
	python -m build

clean:
	rm -rf build dist *.egg-info .pytest_cache .ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

publish:
	./scripts/publish.sh
