set dotenv-load := true

default:
    @just --list

install:
    uv sync --frozen --group dev

lock:
    uv lock

run:
    uv run uvicorn ekumidayomi.main:app --reload

lint:
    uv run ruff check src

format:
    uv run ruff format src

format-check:
    uv run ruff format --check src

typecheck:
    uv run mypy

test-unit:
    uv run pytest -m "not integration"

test-integration:
    uv run pytest -m integration

test:
    uv run pytest --cov=ekumidayomi --cov-report=term-missing

check: lint format-check typecheck test
