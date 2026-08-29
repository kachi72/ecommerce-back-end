set dotenv-load := true
set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command"]

alias d := dev
alias t := test
alias qa := quality
alias clean := cleanup-cache
alias shell := python-shell

default:
    @just --list

install:
    uv sync --frozen --group dev

lock:
    uv lock

dev:
    uv run uvicorn ekumidayomi.main:app --reload

run: dev

lint:
    uv run ruff check src migrations

lint-fix:
    uv run ruff check --fix .

format:
    uv run ruff format src migrations

format-check:
    uv run ruff format --check src migrations

typecheck:
    uv run mypy

test-unit +args="":
    uv run pytest -m "not integration" src/ekumidayomi/tests {{args}}

test-integration +args="":
    uv run pytest -m integration src/ekumidayomi/tests {{args}}

test +args="":
    uv run pytest src/ekumidayomi/tests --cov=ekumidayomi --cov-report=term-missing --cov-report=html {{args}}

coverage +args="":
    uv run pytest src/ekumidayomi/tests --cov=ekumidayomi --cov-report=term-missing {{args}}

check: lint format-check typecheck test

[windows]
quality +args="":
    $rawArgs = "{{args}}"; $cleanupAfter = $rawArgs -match '(^|\s)--cleanup-after(\s|$)'; $testArgs = (($rawArgs -replace '(^|\s)--cleanup-after(?=\s|$)', ' ') -replace '\s+', ' ').Trim(); just lint; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }; just format-check; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }; just typecheck; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }; if ($testArgs -eq "") { just test } else { just test $testArgs }; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }; if ($cleanupAfter) { just cleanup-cache; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } }

[unix]
quality +args="":
    raw_args='{{args}}'; cleanup_after=false; case " $raw_args " in *" --cleanup-after "*) cleanup_after=true ;; esac; test_args=$(printf '%s' "$raw_args" | sed -E 's/(^|[[:space:]])--cleanup-after([[:space:]]|$)/ /g; s/[[:space:]]+/ /g; s/^ //; s/ $//'); just lint && just format-check && just typecheck && if [ -z "$test_args" ]; then just test; else just test $test_args; fi; status=$?; if [ "$status" -ne 0 ]; then exit "$status"; fi; if [ "$cleanup_after" = true ]; then just cleanup-cache; fi

[windows]
cleanup-cache:
    $cacheDirs = @(".mypy_cache", ".pytest_cache", ".ruff_cache", ".uv-cache"); foreach ($dir in $cacheDirs) { if (Test-Path -LiteralPath $dir) { Remove-Item -LiteralPath $dir -Recurse -Force; Write-Host "Removed $dir" } }; Get-ChildItem -Path . -Directory -Recurse -Force -Filter "__pycache__" | Where-Object { $_.FullName -notmatch '\\.venv\\' } | ForEach-Object { Remove-Item -LiteralPath $_.FullName -Recurse -Force; Write-Host "Removed $($_.FullName)" }

[unix]
cleanup-cache:
    rm -rf .mypy_cache .pytest_cache .ruff_cache .uv-cache
    find . \( -path './.venv' -o -path './.git' \) -prune -o -type d -name '__pycache__' -prune -print -exec rm -rf {} +

python-shell:
    uv run python -m asyncio

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

migration-integrity: migration-heads migrate migration-check

docs:
    uv run sphinx-build -b html docs docs/_build/html

docs-check:
    uv run sphinx-build -W --keep-going -b html docs docs/_build/html
    uv run sphinx-build -W --keep-going -b linkcheck docs docs/_build/linkcheck

ci: lint format-check typecheck test migration-integrity docs-check

containers-build:
    docker compose build app

containers-up:
    docker compose up --build --wait --wait-timeout 120 -d

containers-up-deps:
    docker compose up --wait --wait-timeout 120 -d postgres postgres-test redis

containers-down:
    docker compose down

containers-status:
    docker compose ps

containers-logs service="app":
    docker compose logs --follow {{service}}

container-migrate:
    docker compose run --rm -e RUN_MIGRATIONS_ON_STARTUP=false app alembic upgrade head

container-smoke:
    docker compose up --build --wait --wait-timeout 120 -d postgres redis app
    docker compose exec -T app python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health/live', timeout=3)"
    docker compose exec -T app python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health/ready', timeout=3)"
