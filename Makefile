.PHONY: install db-upgrade db-downgrade run fmt test test-all lint check

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
	pytest tests/ -v -m "not slow"

test-all:
	pytest tests/ -v

lint:
	ruff check app alembic tests

check: lint test
