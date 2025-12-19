# paper-tracker

Web app to track a paper reading list.

## Getting started

1. Create a virtual environment and install dependencies:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install --upgrade pip
   make install
   ```

2. Apply the initial database migration (creates tables and seeds a default user with `id=1`):

   ```bash
   alembic upgrade head
   ```

3. Run the development server:

   ```bash
   uvicorn app.main:app --reload
   ```

The API will be available at `http://127.0.0.1:8000/`.

To format the codebase consistently, run:

```bash
make fmt
```

## Project layout

- `app/`
  - `main.py`: FastAPI application entrypoint
  - `db.py`: Database engine/session configuration
  - `models.py`: SQLAlchemy ORM models
  - `schemas.py`: Pydantic schemas
- `alembic/`: Migration environment and versioned migrations
- `alembic/versions/0001_initial_setup.py`: Creates initial tables and seeds default user
- `Makefile`: Common commands for installing, migrating, and running the app
- `requirements.txt`: Python dependencies
