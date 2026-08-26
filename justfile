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

migrate:
    uv run alembic upgrade head

migration message:
    uv run alembic revision --autogenerate -m "{{message}}"

migration-heads:
    uv run alembic heads

migration-current:
    uv run alembic current

migration-downgrade revision="base":
    uv run alembic downgrade "{{revision}}"

migration-check:
    uv run alembic check
