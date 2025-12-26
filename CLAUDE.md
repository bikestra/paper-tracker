# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies (in activated venv)
python3 -m venv .venv
source .venv/bin/activate
make install

# Database migrations
make db-upgrade    # Apply all migrations
make db-downgrade  # Rollback one migration
alembic revision -m "description"  # Create new migration

# Run development server
make run
# or: uvicorn app.main:app --reload

# Format code
make fmt

# Run tests
pytest tests/ -v -m "not slow"
```

## Architecture

FastAPI web application for tracking academic paper reading lists, using SQLAlchemy ORM with SQLite (default) or any SQL database via `DATABASE_URL` env var. Server-rendered HTML with Jinja2 templates, HTMX for interactivity, and SortableJS for drag-and-drop.

**Single-user scope**: All queries filter by authenticated user. Password auth via `APP_PASSWORD` env var (if not set, auth is disabled for local dev).

### Core Models (`app/models.py`)

- `User` - owns all entities
- `Category` - groups papers, unique name per user
- `Paper` - main entity with status (PLANNED/READING/READ), arXiv metadata fields, ordering
- `Author` - can have ORCID and arxiv_id for disambiguation
- `PaperAuthor` - many-to-many join table preserving author order (position field)

### Key Files

- `app/main.py` - FastAPI routes (HTML pages, HTMX partials, API endpoints)
- `app/crud.py` - Database operations with `user_id` scoping
- `app/arxiv.py` - arXiv URL/ID parsing and metadata fetching via `arxiv` library
- `app/schemas.py` - Pydantic schemas for validation
- `app/templates/` - Jinja2 templates (base, pages, partials/)

### Key Patterns

- All models use `Mapped[]` type annotations with `mapped_column()`
- Timestamps use timezone-aware datetimes via `utcnow()` helper
- Pydantic schemas use `from_attributes=True` for ORM conversion
- Database session via FastAPI dependency injection (`get_db`)
- HTMX partials return HTML fragments for dynamic updates
- Paper reordering uses `order_index` field (increments of 10)

### arXiv Integration

- `parse_arxiv_input()` - handles URLs (abs, pdf, ar5iv) and IDs (new/old format with optional version)
- `fetch_arxiv_metadata()` - returns title, abstract, authors, categories, DOI, etc.
- Authors matched by: ORCID > arxiv_id (normalized name slug) > name

## GCP Deployment

**Project:** `project-f6dcbf1a-1498-4bd2-a78` (named "Paper Tracker")

**Cloud Run Service:**
- Service: `paper-tracker`
- Region: `us-central1`
- URL: https://paper-tracker-531032889576.us-central1.run.app

**Artifact Registry:**
- Repository: `us-central1-docker.pkg.dev/project-f6dcbf1a-1498-4bd2-a78/paper-tracker`
- Image: `paper-tracker:latest`

**Database:** Turso (libsql) - connection string in `DATABASE_URL` env var

**Environment Variables (Cloud Run) - REQUIRED:**
- `DATABASE_URL` - Turso connection string (app will fail to start without this in production)
- `APP_PASSWORD` - Login password
- `SESSION_SECRET` - Cookie signing key (must be stable for sessions to persist)

**Turso Database:**
```bash
# Get database URL
~/.turso/turso db show paper-tracker --url

# Create auth token
~/.turso/turso db tokens create paper-tracker

# Full DATABASE_URL format:
# libsql://<db-name>-<username>.aws-us-west-2.turso.io?authToken=<token>
```

**Deploy Commands:**
```bash
# IMPORTANT: Always source ~/.zshrc first to get gcloud in PATH
source ~/.zshrc

# Build for linux/amd64 (required for Cloud Run)
docker build --platform linux/amd64 -t us-central1-docker.pkg.dev/project-f6dcbf1a-1498-4bd2-a78/paper-tracker/paper-tracker:latest .

# Push to Artifact Registry
docker push us-central1-docker.pkg.dev/project-f6dcbf1a-1498-4bd2-a78/paper-tracker/paper-tracker:latest

# Deploy to Cloud Run (env vars persist from previous revision)
gcloud run deploy paper-tracker \
  --image=us-central1-docker.pkg.dev/project-f6dcbf1a-1498-4bd2-a78/paper-tracker/paper-tracker:latest \
  --region=us-central1 \
  --allow-unauthenticated

# IMPORTANT: Verify env vars after deploy
gcloud run services describe paper-tracker --region=us-central1 \
  --format="yaml(spec.template.spec.containers[0].env)"

# If DATABASE_URL is missing, set it (get values from Turso):
gcloud run services update paper-tracker --region=us-central1 \
  --set-env-vars="DATABASE_URL=libsql://paper-tracker-bikestra.aws-us-west-2.turso.io?authToken=<token>"
```

**Troubleshooting:**
- If papers don't show: Check DATABASE_URL is set in Cloud Run env vars
- If login doesn't persist: Check SESSION_SECRET is set and stable
- View logs: `gcloud run services logs read paper-tracker --region=us-central1 --limit=50`
