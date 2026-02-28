# All commands run inside the UV virtual environment

.PHONY: dev test lint type-check format eval ci clean

dev:          ## Start the bot in development mode (long polling)
	PYTHONPATH=src uv run python -m life_os.telegram.bot --mode polling

test:         ## Run unit + integration tests with coverage
	uv run pytest tests/unit tests/integration -v

test-all:     ## Run all tests including e2e (slower)
	uv run pytest -v

lint:         ## Ruff linting
	uv run ruff check src/ tests/

format:       ## Black formatting (auto-fixes)
	uv run black src/ tests/

type-check:   ## mypy strict type checking
	uv run mypy src/

eval:         ## Run extraction + e2e evals
	PYTHONPATH=src uv run python -m life_os.evals.run_evals

ci:           ## Full CI pipeline (runs in GitHub Actions / Cloud Build)
	$(MAKE) format lint type-check test eval

clean:        ## Remove caches
	find . -type d -name __pycache__ | xargs rm -rf
	find . -name '*.pyc' -delete
