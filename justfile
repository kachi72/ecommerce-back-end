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

format:
    uv run ruff format src migrations

format-check:
    uv run ruff format --check src migrations

typecheck:
    uv run mypy

test-unit:
    uv run pytest -m "not integration"

test-integration:
    uv run pytest -m integration

test +args="":
    uv run pytest --cov=ekumidayomi --cov-report=term-missing {{args}}

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
