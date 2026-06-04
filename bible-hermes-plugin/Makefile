.PHONY: lint fmt check fix test

# Run ruff linter (check only — no mutations)
lint:
	uv run ruff check bible_hermes_plugin/

# Run basedpyright type-checker
typecheck:
	uv run basedpyright bible_hermes_plugin/

# Run both (CI gate)
check: lint typecheck

# Apply all safe auto-fixes (ruff format + ruff check --fix)
fix:
	uv run ruff format bible_hermes_plugin/
	uv run ruff check --fix bible_hermes_plugin/

# Format only (no lint fixes)
fmt:
	uv run ruff format bible_hermes_plugin/

# Run test suite with coverage
test:
	uv run pytest --cov=bible_hermes_plugin --cov-report=term-missing
