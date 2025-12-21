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

**Single-user scope**: All queries filter by `user_id=1` (seeded by migration). Auth to be added later.

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
