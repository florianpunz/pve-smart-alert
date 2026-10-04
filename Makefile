# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Entry points for development. See CONTRIBUTING.md.
#
#   make check        everything CI runs
#   make dev-install  create the virtual environment and install the dev tools
#   make test         the test suite
#   make build        wheel and sdist in dist/
#
# The targets that need the development tools create the virtual environment on
# their own, so a fresh clone needs nothing but `make check`.

PYTHON ?= python3
VENV   ?= .venv
BIN    := $(VENV)/bin
STAMP  := $(VENV)/.dev-installed

RUFF  := $(BIN)/python -m ruff
MYPY  := $(BIN)/python -m mypy
PYTEST := $(BIN)/python -m pytest
BUILD := $(BIN)/python -m build

.DEFAULT_GOAL := help
.PHONY: help dev-install check lint format typecheck hygiene test build clean distclean

help:
	@echo "make check        lint, format check, type check, repository checks, tests"
	@echo "make dev-install  create $(VENV) and install the development tools"
	@echo "make lint         ruff check and ruff format --check"
	@echo "make format       apply ruff format"
	@echo "make typecheck    mypy in strict mode"
	@echo "make hygiene      repository rules (no AI attribution, SPDX identifiers)"
	@echo "make test         pytest"
	@echo "make build        wheel and sdist in dist/"
	@echo "make clean        remove caches and build output"
	@echo "make distclean    remove $(VENV) as well"

# Reinstalls whenever pyproject.toml changes, because that is where the
# development dependencies live.
$(STAMP): pyproject.toml
	$(PYTHON) -m venv $(VENV)
	$(BIN)/python -m pip install --quiet --upgrade pip
	$(BIN)/python -m pip install --quiet --editable ".[dev]"
	@touch $(STAMP)

dev-install: $(STAMP)

check: lint typecheck hygiene test

lint: $(STAMP)
	$(RUFF) check .
	$(RUFF) format --check .

format: $(STAMP)
	$(RUFF) format .
	$(RUFF) check --fix .

typecheck: $(STAMP)
	$(MYPY)

# Uses the standard library only, so it runs before anything is installed.
hygiene:
	$(PYTHON) scripts/check_hygiene.py
	@if command -v perl >/dev/null 2>&1; then \
		perl -c libexec/notify-bridge; \
	else \
		echo "perl is not installed, the notify bridge is not syntax-checked"; \
	fi

test: $(STAMP)
	$(PYTEST)

build: $(STAMP)
	$(BUILD)

clean:
	rm -rf .mypy_cache .pytest_cache .ruff_cache build dist
	find . -path ./$(VENV) -prune -o -type d -name __pycache__ -print0 | xargs -0 -r rm -rf

distclean: clean
	rm -rf $(VENV)
