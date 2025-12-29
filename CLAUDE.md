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

**Database:** Cloud SQL (PostgreSQL 15)
- Instance: `paper-tracker-db`
- Connection: `project-f6dcbf1a-1498-4bd2-a78:us-central1:paper-tracker-db`

**IAM Requirements:**
The Cloud Run service account needs `roles/cloudsql.client` to connect to Cloud SQL:
```bash
PROJECT_NUMBER=$(gcloud projects describe project-f6dcbf1a-1498-4bd2-a78 --format='value(projectNumber)')
gcloud projects add-iam-policy-binding project-f6dcbf1a-1498-4bd2-a78 \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/cloudsql.client"
```

**Environment Variables (Cloud Run) - REQUIRED:**
- `CLOUD_SQL_CONNECTION` - Cloud SQL instance connection name
- `DB_USER` - Database user (default: postgres)
- `DB_PASS` - Database password
- `DB_NAME` - Database name (default: postgres)
- `APP_PASSWORD` - Login password
- `SESSION_SECRET` - Cookie signing key (must be stable for sessions to persist)

**Cloud SQL Commands:**
```bash
# List instances
gcloud sql instances list

# Set user password
gcloud sql users set-password postgres --instance=paper-tracker-db --password="<new-password>"

# Connect via Cloud SQL Proxy (for local development)
cloud-sql-proxy project-f6dcbf1a-1498-4bd2-a78:us-central1:paper-tracker-db

# Run migrations against Cloud SQL (with proxy running on port 5432)
DATABASE_URL="postgresql+pg8000://postgres:<password>@127.0.0.1:5432/postgres" alembic upgrade head
```

**Deploy Script (PREFERRED):**
```bash
# Use deploy.sh for deployments - it includes all required env vars
# This file is gitignored and contains secrets (DATABASE_URL, APP_PASSWORD, SESSION_SECRET)
./deploy.sh
```

The `deploy.sh` script:
- Ensures Cloud SQL Client IAM role is granted to the Cloud Run service account
- Builds the Docker image for linux/amd64
- Pushes to Artifact Registry
- Deploys to Cloud Run with Cloud SQL connection and all required environment variables
- **IMPORTANT:** Edit this file to fill in your secrets before first use

**Manual Deploy Commands (if needed):**
```bash
# IMPORTANT: Always source ~/.zshrc first to get gcloud in PATH
source ~/.zshrc

# Ensure IAM permissions (required for Cloud SQL access)
PROJECT_NUMBER=$(gcloud projects describe project-f6dcbf1a-1498-4bd2-a78 --format='value(projectNumber)')
gcloud projects add-iam-policy-binding project-f6dcbf1a-1498-4bd2-a78 \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/cloudsql.client"

# Build for linux/amd64 (required for Cloud Run)
docker build --platform linux/amd64 -t us-central1-docker.pkg.dev/project-f6dcbf1a-1498-4bd2-a78/paper-tracker/paper-tracker:latest .

# Push to Artifact Registry
docker push us-central1-docker.pkg.dev/project-f6dcbf1a-1498-4bd2-a78/paper-tracker/paper-tracker:latest

# Deploy to Cloud Run WITH Cloud SQL and env vars
gcloud run deploy paper-tracker \
  --image=us-central1-docker.pkg.dev/project-f6dcbf1a-1498-4bd2-a78/paper-tracker/paper-tracker:latest \
  --region=us-central1 \
  --allow-unauthenticated \
  --add-cloudsql-instances=project-f6dcbf1a-1498-4bd2-a78:us-central1:paper-tracker-db \
  --set-env-vars="CLOUD_SQL_CONNECTION=project-f6dcbf1a-1498-4bd2-a78:us-central1:paper-tracker-db,DB_USER=postgres,DB_PASS=<pass>,DB_NAME=postgres,APP_PASSWORD=<pass>,SESSION_SECRET=<secret>"

# Verify env vars after deploy
gcloud run services describe paper-tracker --region=us-central1 \
  --format="yaml(spec.template.spec.containers[0].env)"
```

**Troubleshooting:**
- If deployment fails with "Cloud SQL Client role" error: Run the IAM binding command above
- If papers don't show: Check CLOUD_SQL_CONNECTION and DB_* vars are set in Cloud Run env vars
- If login doesn't persist: Check SESSION_SECRET is set and stable
- View logs: `gcloud run services logs read paper-tracker --region=us-central1 --limit=50`
