.PHONY: install db-upgrade db-downgrade run fmt

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
