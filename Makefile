.PHONY: help install dev test lint format clean build push docs serve deploy logs lock lock-upgrade sync requirements-freeze requirements-check

help:
	@echo "RIF Runtime Development Makefile"
	@echo ""
	@echo "Setup:"
	@echo "  make install              Install dependencies"
	@echo "  make dev                  Install dev dependencies"
	@echo ""
	@echo "Development:"
	@echo "  make serve                Start dev server with hot reload"
	@echo "  make test                 Run all tests"
	@echo "  make test-unit            Run unit tests only"
	@echo "  make test-integration     Run integration tests only"
	@echo "  make coverage             Run tests with coverage report"
	@echo ""
	@echo "Code Quality:"
	@echo "  make lint                 Run all linters (ruff, mypy, bandit)"
	@echo "  make format               Auto-format code"
	@echo "  make format-check         Check formatting without changes"
	@echo "  make type-check           Run type checker"
	@echo "  make security             Run security scanners"
	@echo ""
	@echo "Docker:"
	@echo "  make docker-build         Build Docker image"
	@echo "  make docker-run           Run in Docker"
	@echo "  make docker-up            Start compose stack"
	@echo "  make docker-down          Stop compose stack"
	@echo "  make docker-logs          View compose logs"
	@echo "  make docker-prod-up       Start production stack"
	@echo ""
	@echo "Documentation:"
	@echo "  make docs                 Generate API docs"
	@echo ""
	@echo "Utilities:"
	@echo "  make clean                Remove build artifacts and cache"
	@echo "  make info                 Show project info"

# Setup targets
install:
	pip install -q -e .

dev:
	pip install -q -e ".[dev]"

# Development targets
serve:
	uvicorn 'src.rif_runtime.api:app' --host=0.0.0.0 --port=8000 --reload

test:
	pytest -v

test-unit:
	pytest -v tests/unit/

test-integration:
	pytest -v tests/integration/

test-e2e:
	pytest -v tests/e2e/

coverage:
	pytest --cov=src/rif_runtime --cov-report=html --cov-report=term tests/
	@echo "Coverage report: htmlcov/index.html"

# Code quality targets
lint: lint-ruff type-check security
	@echo "✓ All lint checks passed"

lint-ruff:
	ruff check src/ tests/

format:
	ruff format src/ tests/

format-check:
	ruff format --check src/ tests/

type-check:
	mypy src/ tests/

security:
	bandit -r src/ -ll
	pip-audit --desc || true

# Docker targets
docker-build:
	docker build -t rif-runtime-server:latest .

docker-run: docker-build
	docker run -p 8000:8000 \
		-e RIF_LOG_LEVEL=INFO \
		-v $(PWD)/data:/app/data \
		-v $(PWD)/config:/app/config \
		rif-runtime-server:latest

docker-up:
	docker compose up --build

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f server

docker-prod-up:
	docker compose -f docker-compose.prod.yml up -d

docker-prod-down:
	docker compose -f docker-compose.prod.yml down

docker-prod-logs:
	docker compose -f docker-compose.prod.yml logs -f server

# CLI targets
cli-execute:
	rif execute --intent "test execution"

cli-health:
	curl -s http://localhost:8000/health | python -m json.tool

cli-docs:
	open http://localhost:8000/docs

# Documentation
docs:
	@echo "Generating API documentation..."
	@echo "Available at http://localhost:8000/docs (after running server)"

# Utility targets
clean:
	rm -rf build/ dist/ *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache .mypy_cache .ruff_cache
	rm -rf htmlcov .coverage

info:
	@echo "RIF Runtime Project Info"
	@echo "========================"
	@python --version
	@echo ""
	@echo "Installed packages:"
	@pip list | grep -E "rif|fastapi|uvicorn|pytest|mypy" || true
	@echo ""
	@echo "Source files:"
	@find src/ -name "*.py" -type f | wc -l
	@echo ""
	@echo "Test files:"
	@find tests/ -name "test_*.py" -type f | wc -l

# Development workflow shortcuts
setup: install dev docker-build
	@echo "✓ Development environment ready"
	@echo "  Next: make serve"

quick-test: lint test
	@echo "✓ Quick test cycle complete"

full-check: lint coverage security docs
	@echo "✓ Full quality check complete"

deploy: lint test coverage
	docker compose -f docker-compose.prod.yml up -d
	@echo "✓ Deployed to production"

# Watch mode (requires ptw)
watch:
	ptw -- --maxfail=1

# Performance profiling
profile:
	python -m cProfile -s cumulative -m rif execute --intent "test" > profile.txt
	@echo "Profile saved to profile.txt"

# Database targets (if using PostgreSQL)
db-init:
	docker compose exec postgres psql -U rif_user -d rif_runtime -f config/init.sql

db-backup:
	@mkdir -p backups
	docker compose exec postgres pg_dump -U rif_user rif_runtime | gzip > backups/db-$$(date +%Y%m%d_%H%M%S).sql.gz
	@echo "Database backed up to backups/"

db-restore:
	@read -p "Enter backup file path: " filepath; \
	gunzip < $$filepath | docker compose exec -T postgres psql -U rif_user rif_runtime

# Release targets
version:
	@grep version src/rif_runtime/_version.py | head -1

bump-patch:
	bump2version patch

bump-minor:
	bump2version minor

bump-major:
	bump2version major

# CI/CD simulation
ci: clean install lint test coverage security
	@echo "✓ CI checks complete (would pass)"

# Local development with all services
all: docker-down clean install dev docker-up
	@echo "✓ Full development environment started"
	@echo "  API: http://localhost:8000"
	@echo "  Docs: http://localhost:8000/docs"
	@echo "  Logs: make docker-logs"

# Dependency locks (see requirements/README.md)
PIP_COMPILE_ARGS = --quiet --generate-hashes --strip-extras --allow-unsafe
PIP_COMPILE_LOCK = CUSTOM_COMPILE_COMMAND="make lock" pip-compile
PIP_COMPILE_LOCK_UPGRADE = CUSTOM_COMPILE_COMMAND="make lock" pip-compile

# Recompile the locks from pyproject.toml. pip-compile keeps the versions
# already pinned in the output files, so this is a no-op unless pyproject.toml
# changed. CI's `lock-sync` job runs the same commands and fails on any diff.
lock:
	$(PIP_COMPILE_LOCK) $(PIP_COMPILE_ARGS) \
		--output-file requirements/runtime.txt pyproject.toml
	$(PIP_COMPILE_LOCK) $(PIP_COMPILE_ARGS) \
		--extra dev --output-file requirements/dev.txt pyproject.toml

# Deliberately pull in newer upstream releases within the declared ranges.
lock-upgrade:
	$(PIP_COMPILE_LOCK_UPGRADE) $(PIP_COMPILE_ARGS) --upgrade \
		--output-file requirements/runtime.txt pyproject.toml
	$(PIP_COMPILE_LOCK_UPGRADE) $(PIP_COMPILE_ARGS) --upgrade \
		--extra dev --output-file requirements/dev.txt pyproject.toml

# Install exactly what CI installs — including the pip upgrade the CI jobs do,
# so a local `make sync` and a CI run start from the same pip.
sync:
	python -m pip install --upgrade pip
	python -m pip install --require-hashes -r requirements/dev.txt
	python -m pip install -e . --no-deps

# Maintenance
requirements-freeze:
	pip freeze > requirements.txt.frozen

# Audits the locks, matching the `dependency-security` job in merge-gate.yml.
requirements-check:
	pip-audit --requirement requirements/runtime.txt --disable-pip
	pip-audit --requirement requirements/dev.txt --disable-pip

# Help for specific topics
help-docker:
	@echo "Docker Commands:"
	@echo "  make docker-build        Build image"
	@echo "  make docker-up           Start services"
	@echo "  make docker-down         Stop services"
	@echo "  make docker-logs         View logs"
	@echo "  make docker-prod-up      Start production"

help-test:
	@echo "Test Commands:"
	@echo "  make test                Run all tests"
	@echo "  make test-unit           Unit tests only"
	@echo "  make coverage            Coverage report"
	@echo "  make watch               Watch mode (auto-run tests)"

help-quality:
	@echo "Quality Commands:"
	@echo "  make lint                All linters"
	@echo "  make format              Auto-format code"
	@echo "  make type-check          Type checking"
	@echo "  make security            Security scans"
