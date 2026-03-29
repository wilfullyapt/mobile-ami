.PHONY: dev test test-cov lint clean

UV := uv

dev:
	$(UV) venv .venv --python 3.12
	$(UV) pip install -e ".[dev]"
	@echo "Run: source .venv/bin/activate"

test:
	$(UV) run pytest tests/ -q

test-cov:
	$(UV) run pytest tests/ --cov=. --cov-report=term-missing -q

lint:
	$(UV) run ruff check .

clean:
	rm -rf .venv __pycache__ .pytest_cache dist *.egg-info _version.py
