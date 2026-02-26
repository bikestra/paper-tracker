.PHONY: install db-upgrade db-downgrade run fmt test test-fast

install:
	pip install -r requirements.txt

db-upgrade:
	alembic upgrade head

db-downgrade:
	alembic downgrade -1

run:
	uvicorn app.main:app --reload

fmt:
	ruff format app alembic

test:
	pytest tests/ -v

test-fast:
	pytest tests/ -v -x --tb=short
