"""FastAPI application for Paper Tracker."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Annotated, Optional

from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from . import crud, models, schemas
from .arxiv import ArxivError, fetch_arxiv_metadata, parse_arxiv_input
from .auth import (
    NotAuthenticatedException,
    SESSION_COOKIE,
    _create_session_token,
    get_current_user,
    verify_password,
)
from .db import Base, engine, get_db

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Paper Tracker")


@app.middleware("http")
async def timing_middleware(request: Request, call_next):
    """Log request timing."""
    start = time.perf_counter()
    response = await call_next(request)
    elapsed = time.perf_counter() - start
    logger.info(f"{request.method} {request.url.path} took {elapsed:.3f}s")
    return response


# Templates
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.bind = engine


# --- Exception handler for auth redirect ---


@app.exception_handler(NotAuthenticatedException)
async def not_authenticated_handler(request: Request, exc: NotAuthenticatedException):
    """Redirect to login page when not authenticated."""
    return RedirectResponse(url="/login", status_code=303)


@app.exception_handler(SQLAlchemyError)
async def database_error_handler(request: Request, exc: SQLAlchemyError):
    """Handle database errors with user-friendly messages."""
    logger.error(f"Database error: {exc}")

    # Extract a user-friendly message
    error_msg = str(exc.orig) if hasattr(exc, "orig") else str(exc)

    # Check for common errors and provide better messages
    if "no such column" in error_msg:
        error_msg = "Database schema mismatch. Please run migrations: make db-upgrade"
    elif "no such table" in error_msg:
        error_msg = "Database tables missing. Please run migrations: make db-upgrade"
    elif "UNIQUE constraint failed" in error_msg:
        error_msg = "This item already exists."
    elif "FOREIGN KEY constraint failed" in error_msg:
        error_msg = "Cannot delete: this item is referenced by other records."

    # For HTMX requests, return plain text error
    if request.headers.get("HX-Request"):
        return HTMLResponse(content=error_msg, status_code=500)

    # For API requests (JSON), return JSON error
    if request.headers.get("Accept", "").startswith("application/json"):
        return JSONResponse(content={"detail": error_msg}, status_code=500)

    # For regular page loads, render with error
    return templates.TemplateResponse(
        "base.html",
        {"request": request, "error": error_msg},
        status_code=500,
    )


@app.exception_handler(Exception)
async def general_error_handler(request: Request, exc: Exception):
    """Catch-all handler for unexpected errors."""
    logger.error(f"Unexpected error: {type(exc).__name__}: {exc}")

    error_msg = f"An unexpected error occurred: {type(exc).__name__}"

    # For HTMX requests, return plain text error
    if request.headers.get("HX-Request"):
        return HTMLResponse(content=error_msg, status_code=500)

    # For API requests (JSON), return JSON error
    if request.headers.get("Accept", "").startswith("application/json"):
        return JSONResponse(content={"detail": error_msg}, status_code=500)

    # For regular page loads, render with error
    return templates.TemplateResponse(
        "base.html",
        {"request": request, "error": error_msg},
        status_code=500,
    )


# --- Health check ---


@app.get("/health", tags=["health"], response_model=schemas.Healthcheck)
def health_check(db: Session = Depends(get_db)) -> schemas.Healthcheck:
    db.execute(text("SELECT 1"))
    return schemas.Healthcheck(message="Paper Tracker API is running")


# --- Login/Logout ---


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, error: str = ""):
    """Login page."""
    from .auth import APP_PASSWORD, SESSION_SECRET
    import os

    config_warning = None
    if not APP_PASSWORD:
        config_warning = "APP_PASSWORD environment variable is not set. Authentication is disabled."
    elif not os.getenv("SESSION_SECRET"):
        config_warning = "SESSION_SECRET environment variable is not set. Sessions won't persist across server restarts."

    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": error, "config_warning": config_warning},
    )


@app.post("/login")
def login(
    request: Request,
    password: Annotated[str, Form()],
):
    """Handle login form submission."""
    if verify_password(password):
        response = RedirectResponse(url="/", status_code=303)
        response.set_cookie(
            key=SESSION_COOKIE,
            value=_create_session_token(),
            httponly=True,
            samesite="lax",
            secure=True,  # Only send over HTTPS
            max_age=60 * 60 * 24 * 30,  # 30 days
        )
        return response

    # Invalid password - show error
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": "Invalid password"},
        status_code=401,
    )


@app.post("/logout")
def logout():
    """Log out by clearing session cookie."""
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(key=SESSION_COOKIE)
    return response


# --- HTML Pages ---


@app.get("/", response_class=HTMLResponse)
def home(
    request: Request,
    status: models.PaperStatus = Query(models.PaperStatus.PLANNED),
    category_id: Optional[int] = Query(None),
    sort_by: str = Query("manual"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Main page with paper list."""
    user_id = current_user.id

    # Validate sort_by
    valid_sorts = ("manual", "likes", "added", "read")
    if sort_by not in valid_sorts:
        sort_by = "manual"

    papers = crud.get_papers(
        db, user_id=user_id, status=status, category_id=category_id, sort_by=sort_by
    )

    categories = crud.get_categories(db, user_id=user_id)

    # Get paper counts per status
    all_papers = crud.get_papers(db, user_id=user_id)

    counts = {
        "PLANNED": sum(1 for p in all_papers if p.status == models.PaperStatus.PLANNED),
        "READING": sum(1 for p in all_papers if p.status == models.PaperStatus.READING),
        "READ": sum(1 for p in all_papers if p.status == models.PaperStatus.READ),
    }

    # Get effort totals for all papers
    effort_totals = crud.get_all_papers_effort_totals(db, user_id=user_id)

    # Get source counts for all papers
    source_counts = crud.get_all_papers_source_counts(db, user_id=user_id)

    # Reordering only allowed in manual sort mode
    sortable = sort_by == "manual"

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "papers": papers,
            "categories": categories,
            "current_status": status.value,
            "category_id": category_id,
            "counts": counts,
            "active_page": "home",
            "user_email": current_user.email,
            "sort_by": sort_by,
            "sortable": sortable,
            "effort_totals": effort_totals,
            "source_counts": source_counts,
        },
    )


@app.get("/add", response_class=HTMLResponse)
def add_paper_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Add paper form page."""
    categories = crud.get_categories(db, user_id=current_user.id)
    return templates.TemplateResponse(
        "add_paper.html",
        {
            "request": request,
            "categories": categories,
            "paper": None,
            "active_page": "home",
        },
    )


@app.get("/papers/{paper_id}/edit", response_class=HTMLResponse)
def edit_paper_page(
    request: Request,
    paper_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Edit paper form page."""
    paper = crud.get_paper(db, paper_id, user_id=current_user.id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    categories = crud.get_categories(db, user_id=current_user.id)

    # Convert paper to dict-like for template
    paper_data = {
        "id": paper.id,
        "title": paper.title,
        "abstract": paper.abstract,
        "url": paper.url,
        "pdf_url": paper.pdf_url,
        "source": paper.source.value,
        "status": paper.status.value,
        "category_id": paper.category_id,
        "notes": paper.notes,
        "venue_year": paper.venue_year,
        "arxiv_id": paper.arxiv_id,
        "arxiv_version": paper.arxiv_version,
        "arxiv_primary_category": paper.arxiv_primary_category,
        "arxiv_published_at": paper.arxiv_published_at.isoformat()
        if paper.arxiv_published_at
        else "",
        "arxiv_updated_at": paper.arxiv_updated_at.isoformat()
        if paper.arxiv_updated_at
        else "",
        "doi": paper.doi,
        "journal_ref": paper.journal_ref,
        "authors": [a.name for a in paper.authors],
    }

    return templates.TemplateResponse(
        "edit_paper.html",
        {
            "request": request,
            "paper": paper_data,
            "categories": categories,
            "active_page": "home",
        },
    )


@app.get("/authors", response_class=HTMLResponse)
def authors_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Authors list page."""
    authors = crud.get_authors(db, user_id=current_user.id)
    return templates.TemplateResponse(
        "authors.html",
        {
            "request": request,
            "authors": authors,
            "active_page": "authors",
        },
    )


@app.get("/authors/{author_id}", response_class=HTMLResponse)
def author_detail_page(
    request: Request,
    author_id: int,
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Author detail page with papers."""
    author = crud.get_author(db, author_id, user_id=current_user.id)
    if not author:
        raise HTTPException(status_code=404, detail="Author not found")

    status_enum = None
    if status:
        try:
            status_enum = models.PaperStatus(status)
        except ValueError:
            pass

    papers = crud.get_papers_by_author(
        db, author_id, user_id=current_user.id, status=status_enum
    )

    return templates.TemplateResponse(
        "author_detail.html",
        {
            "request": request,
            "author": author,
            "papers": papers,
            "status_filter": status,
            "active_page": "authors",
        },
    )


@app.get("/categories", response_class=HTMLResponse)
def categories_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Categories management page."""
    categories = crud.get_categories(db, user_id=current_user.id)
    return templates.TemplateResponse(
        "categories.html",
        {
            "request": request,
            "categories": categories,
            "active_page": "categories",
        },
    )


# --- HTMX Partials ---


@app.get("/partials/papers", response_class=HTMLResponse)
def papers_partial(
    request: Request,
    status: models.PaperStatus = Query(models.PaperStatus.PLANNED),
    category_id: Optional[int] = Query(None),
    sort_by: str = Query("manual"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Paper list partial for HTMX."""
    valid_sorts = ("manual", "likes", "added", "read")
    if sort_by not in valid_sorts:
        sort_by = "manual"

    papers = crud.get_papers(
        db,
        user_id=current_user.id,
        status=status,
        category_id=category_id,
        sort_by=sort_by,
    )
    sortable = sort_by == "manual"

    # Get effort totals and source counts for all papers
    effort_totals = crud.get_all_papers_effort_totals(db, user_id=current_user.id)
    source_counts = crud.get_all_papers_source_counts(db, user_id=current_user.id)

    return templates.TemplateResponse(
        "partials/paper_list.html",
        {
            "request": request,
            "papers": papers,
            "current_status": status.value,
            "category_id": category_id,
            "sortable": sortable,
            "effort_totals": effort_totals,
            "source_counts": source_counts,
        },
    )


@app.get("/partials/categories", response_class=HTMLResponse)
def categories_partial(
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Categories list partial for HTMX."""
    categories = crud.get_categories(db, user_id=current_user.id)
    return templates.TemplateResponse(
        "partials/category_list.html",
        {"request": request, "categories": categories},
    )


# --- Paper Actions ---


@app.post("/papers/fetch-arxiv", response_class=HTMLResponse)
def fetch_arxiv(
    request: Request,
    url_or_id: Annotated[str, Form()],
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Fetch arXiv metadata and return populated form."""
    categories = crud.get_categories(db, user_id=current_user.id)

    try:
        arxiv_id, version = parse_arxiv_input(url_or_id)
        metadata = fetch_arxiv_metadata(arxiv_id)

        paper_data = {
            "title": metadata.title,
            "abstract": metadata.abstract,
            "url": metadata.url,
            "pdf_url": metadata.pdf_url,
            "source": "ARXIV",
            "arxiv_id": metadata.arxiv_id,
            "arxiv_version": metadata.arxiv_version,
            "arxiv_primary_category": metadata.primary_category,
            "arxiv_published_at": metadata.published_at.isoformat()
            if metadata.published_at
            else "",
            "arxiv_updated_at": metadata.updated_at.isoformat()
            if metadata.updated_at
            else "",
            "doi": metadata.doi or "",
            "journal_ref": metadata.journal_ref or "",
            "authors": [a.name for a in metadata.authors],
            "status": "PLANNED",
            "category_id": None,
            "notes": "",
            "venue_year": "",
        }

        return templates.TemplateResponse(
            "partials/paper_form.html",
            {"request": request, "paper": paper_data, "categories": categories},
        )

    except ArxivError as e:
        return templates.TemplateResponse(
            "partials/paper_form.html",
            {
                "request": request,
                "paper": None,
                "categories": categories,
                "error": str(e),
            },
        )


@app.post("/papers", response_class=HTMLResponse)
def create_paper(
    request: Request,
    title: Annotated[str, Form()],
    status: Annotated[str, Form()] = "PLANNED",
    category_id: Annotated[Optional[str], Form()] = None,
    authors: Annotated[str, Form()] = "",
    abstract: Annotated[str, Form()] = "",
    url: Annotated[str, Form()] = "",
    pdf_url: Annotated[str, Form()] = "",
    notes: Annotated[str, Form()] = "",
    venue_year: Annotated[str, Form()] = "",
    source: Annotated[str, Form()] = "MANUAL",
    arxiv_id: Annotated[str, Form()] = "",
    arxiv_version: Annotated[str, Form()] = "",
    arxiv_primary_category: Annotated[str, Form()] = "",
    arxiv_published_at: Annotated[str, Form()] = "",
    arxiv_updated_at: Annotated[str, Form()] = "",
    doi: Annotated[str, Form()] = "",
    journal_ref: Annotated[str, Form()] = "",
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Create a new paper."""
    from datetime import datetime

    is_htmx = request.headers.get("HX-Request") == "true"

    try:
        # Validate title
        if not title or not title.strip():
            error_msg = "Title is required"
            if is_htmx:
                return HTMLResponse(
                    content=f'<div class="mb-4 p-4 bg-red-50 border border-red-200 rounded-lg text-red-700">{error_msg}</div>',
                    status_code=400,
                )
            raise HTTPException(status_code=400, detail=error_msg)

        # Parse authors
        author_list = [a.strip() for a in authors.split(",") if a.strip()]

        # Parse category_id
        cat_id = int(category_id) if category_id and category_id.strip() else None

        # Parse datetime fields
        def parse_dt(s: str) -> datetime | None:
            if not s:
                return None
            try:
                return datetime.fromisoformat(s.replace("Z", "+00:00"))
            except ValueError:
                return None

        data = schemas.PaperCreate(
            title=title.strip(),
            abstract=abstract or None,
            url=url or None,
            pdf_url=pdf_url or None,
            status=models.PaperStatus(status),
            category_id=cat_id,
            notes=notes or None,
            venue_year=venue_year or None,
            source=models.PaperSource(source) if source else models.PaperSource.MANUAL,
            authors=author_list,
            arxiv_id=arxiv_id or None,
            arxiv_version=arxiv_version or None,
            arxiv_primary_category=arxiv_primary_category or None,
            arxiv_published_at=parse_dt(arxiv_published_at),
            arxiv_updated_at=parse_dt(arxiv_updated_at),
            doi=doi or None,
            journal_ref=journal_ref or None,
        )

        crud.create_paper(db, data, user_id=current_user.id)

        # For HTMX requests, use HX-Redirect header
        if is_htmx:
            response = HTMLResponse(content="")
            response.headers["HX-Redirect"] = f"/?status={status}"
            return response

        return RedirectResponse(url=f"/?status={status}", status_code=303)

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error creating paper: {error_msg}")

        if is_htmx:
            return HTMLResponse(
                content=f'<div class="mb-4 p-4 bg-red-50 border border-red-200 rounded-lg text-red-700">Error: {error_msg}</div>',
                status_code=500,
            )
        raise


@app.post("/papers/reorder")
def reorder_papers(
    data: schemas.ReorderRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Reorder papers."""
    success = crud.reorder_papers(
        db,
        status=data.status,
        paper_ids=data.paper_ids,
        user_id=current_user.id,
        category_id=data.category_id,
    )
    if not success:
        raise HTTPException(status_code=400, detail="Invalid paper IDs")
    return {"status": "ok"}


@app.post("/papers/{paper_id}/like", response_class=HTMLResponse)
def like_paper(
    request: Request,
    paper_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Increment likes for a paper. Returns updated like count."""
    likes = crud.like_paper(db, paper_id, user_id=current_user.id)
    if likes is None:
        raise HTTPException(status_code=404, detail="Paper not found")
    return f'<span class="likes-count">{likes}</span>'


@app.post("/papers/{paper_id}/effort", response_class=HTMLResponse)
def log_paper_effort(
    request: Request,
    paper_id: int,
    points: Annotated[int, Form()] = 1,
    note: Annotated[str, Form()] = "",
    mark_as_read: Annotated[str | None, Form()] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Log effort points for a paper."""
    effort_log = crud.create_effort_log(
        db,
        points=points,
        note=note.strip() or None,
        paper_id=paper_id,
        user_id=current_user.id,
    )
    if effort_log is None:
        raise HTTPException(status_code=404, detail="Paper not found")

    # Mark paper as read if requested
    if mark_as_read:
        crud.update_paper(
            db,
            paper_id=paper_id,
            data=schemas.PaperUpdate(status=models.PaperStatus.READ),
            user_id=current_user.id,
        )
        # Tell HTMX to refresh the page since the paper moved to a different status
        total = crud.get_paper_effort_total(db, paper_id, user_id=current_user.id)
        return Response(
            content=f'<span class="effort-total">{total}</span>',
            headers={"HX-Refresh": "true"},
        )

    # Return updated effort total
    total = crud.get_paper_effort_total(db, paper_id, user_id=current_user.id)
    return f'<span class="effort-total">{total}</span>'


@app.post("/textbooks/{textbook_id}/effort", response_class=HTMLResponse)
def log_textbook_effort(
    request: Request,
    textbook_id: int,
    points: Annotated[int, Form()] = 1,
    note: Annotated[str, Form()] = "",
    mark_as_read: Annotated[str | None, Form()] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Log effort points for a textbook."""
    effort_log = crud.create_effort_log(
        db,
        points=points,
        note=note.strip() or None,
        textbook_id=textbook_id,
        user_id=current_user.id,
    )
    if effort_log is None:
        raise HTTPException(status_code=404, detail="Textbook not found")

    # Mark textbook as read if requested
    if mark_as_read:
        crud.update_textbook(
            db,
            textbook_id=textbook_id,
            data=schemas.TextbookUpdate(status=models.TextbookStatus.READ),
            user_id=current_user.id,
        )
        # Tell HTMX to refresh the page since the textbook moved to a different status
        total = crud.get_textbook_effort_total(db, textbook_id, user_id=current_user.id)
        return Response(
            content=f'<span class="effort-total">{total}</span>',
            headers={"HX-Refresh": "true"},
        )

    # Return updated effort total
    total = crud.get_textbook_effort_total(db, textbook_id, user_id=current_user.id)
    return f'<span class="effort-total">{total}</span>'


@app.get("/efforts", response_class=HTMLResponse)
def efforts_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Page showing all effort logs chronologically."""
    effort_logs = crud.get_effort_logs(db, user_id=current_user.id)
    return templates.TemplateResponse(
        "efforts.html",
        {
            "request": request,
            "effort_logs": effort_logs,
            "active_page": "efforts",
        },
    )


# --- Discovery Source Routes ---


@app.get("/partials/paper-sources/{paper_id}", response_class=HTMLResponse)
def get_paper_sources(
    request: Request,
    paper_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Get discovery sources for a paper."""
    sources = crud.get_discovery_sources(db, paper_id, user_id=current_user.id)
    return templates.TemplateResponse(
        "partials/paper_sources.html",
        {
            "request": request,
            "sources": sources,
            "paper_id": paper_id,
        },
    )


@app.post("/papers/{paper_id}/sources", response_class=HTMLResponse)
def add_paper_source(
    request: Request,
    paper_id: int,
    source_type: Annotated[str, Form()],
    source_arxiv_id: Annotated[str, Form()] = "",
    source_text: Annotated[str, Form()] = "",
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Add a discovery source to a paper."""
    source_type_enum = models.DiscoverySourceType(source_type)

    crud.add_discovery_source(
        db,
        paper_id=paper_id,
        source_type=source_type_enum,
        source_arxiv_id=source_arxiv_id.strip() or None,
        source_text=source_text.strip() or None,
        user_id=current_user.id,
    )

    sources = crud.get_discovery_sources(db, paper_id, user_id=current_user.id)
    return templates.TemplateResponse(
        "partials/paper_sources.html",
        {
            "request": request,
            "sources": sources,
            "paper_id": paper_id,
        },
    )


@app.delete("/papers/{paper_id}/sources/{source_id}", response_class=HTMLResponse)
def delete_paper_source(
    request: Request,
    paper_id: int,
    source_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Delete a discovery source from a paper."""
    crud.delete_discovery_source(db, source_id, user_id=current_user.id)

    sources = crud.get_discovery_sources(db, paper_id, user_id=current_user.id)
    return templates.TemplateResponse(
        "partials/paper_sources.html",
        {
            "request": request,
            "sources": sources,
            "paper_id": paper_id,
        },
    )


@app.post("/papers/{paper_id}", response_class=HTMLResponse)
def update_paper(
    request: Request,
    paper_id: int,
    title: Annotated[str, Form()],
    status: Annotated[str, Form()] = "PLANNED",
    category_id: Annotated[Optional[str], Form()] = None,
    authors: Annotated[str, Form()] = "",
    abstract: Annotated[str, Form()] = "",
    url: Annotated[str, Form()] = "",
    pdf_url: Annotated[str, Form()] = "",
    notes: Annotated[str, Form()] = "",
    venue_year: Annotated[str, Form()] = "",
    source: Annotated[str, Form()] = "MANUAL",
    arxiv_id: Annotated[str, Form()] = "",
    arxiv_version: Annotated[str, Form()] = "",
    arxiv_primary_category: Annotated[str, Form()] = "",
    arxiv_published_at: Annotated[str, Form()] = "",
    arxiv_updated_at: Annotated[str, Form()] = "",
    doi: Annotated[str, Form()] = "",
    journal_ref: Annotated[str, Form()] = "",
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Update a paper."""
    from datetime import datetime

    is_htmx = request.headers.get("HX-Request") == "true"
    t0 = time.perf_counter()

    try:
        # Validate title
        if not title or not title.strip():
            error_msg = "Title is required"
            if is_htmx:
                return HTMLResponse(
                    content=f'<div class="mb-4 p-4 bg-red-50 border border-red-200 rounded-lg text-red-700">{error_msg}</div>',
                    status_code=400,
                )
            raise HTTPException(status_code=400, detail=error_msg)

        # Parse authors
        author_list = [a.strip() for a in authors.split(",") if a.strip()]

        # Parse category_id
        cat_id = int(category_id) if category_id and category_id.strip() else None

        # Parse datetime fields
        def parse_dt(s: str) -> datetime | None:
            if not s:
                return None
            try:
                return datetime.fromisoformat(s.replace("Z", "+00:00"))
            except ValueError:
                return None

        data = schemas.PaperUpdate(
            title=title.strip(),
            abstract=abstract or None,
            url=url or None,
            pdf_url=pdf_url or None,
            status=models.PaperStatus(status),
            category_id=cat_id,
            notes=notes or None,
            venue_year=venue_year or None,
            authors=author_list,
            arxiv_id=arxiv_id or None,
            arxiv_version=arxiv_version or None,
            arxiv_primary_category=arxiv_primary_category or None,
            arxiv_published_at=parse_dt(arxiv_published_at),
            arxiv_updated_at=parse_dt(arxiv_updated_at),
            doi=doi or None,
            journal_ref=journal_ref or None,
        )

        paper = crud.update_paper(db, paper_id, data, user_id=current_user.id)
        t1 = time.perf_counter()
        logger.info(f"  update_paper: {t1-t0:.3f}s")

        if not paper:
            error_msg = "Paper not found"
            if is_htmx:
                return HTMLResponse(
                    content=f'<div class="mb-4 p-4 bg-red-50 border border-red-200 rounded-lg text-red-700">{error_msg}</div>',
                    status_code=404,
                )
            raise HTTPException(status_code=404, detail=error_msg)

        # For HTMX requests, use HX-Redirect header
        if is_htmx:
            response = HTMLResponse(content="")
            response.headers["HX-Redirect"] = f"/?status={status}"
            return response

        return RedirectResponse(url=f"/?status={status}", status_code=303)

    except HTTPException:
        raise
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error updating paper: {error_msg}")

        if is_htmx:
            return HTMLResponse(
                content=f'<div class="mb-4 p-4 bg-red-50 border border-red-200 rounded-lg text-red-700">Error: {error_msg}</div>',
                status_code=500,
            )
        raise


@app.post("/papers/{paper_id}/delete", response_class=HTMLResponse)
def delete_paper(
    request: Request,
    paper_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Delete a paper."""
    paper = crud.get_paper(db, paper_id, user_id=current_user.id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    status = paper.status
    category_id = paper.category_id
    crud.delete_paper(db, paper_id, user_id=current_user.id)

    # Return updated paper list
    papers = crud.get_papers(
        db, user_id=current_user.id, status=status, category_id=category_id
    )
    effort_totals = crud.get_all_papers_effort_totals(db, user_id=current_user.id)
    source_counts = crud.get_all_papers_source_counts(db, user_id=current_user.id)
    return templates.TemplateResponse(
        "partials/paper_list.html",
        {
            "request": request,
            "papers": papers,
            "current_status": status.value,
            "category_id": category_id,
            "effort_totals": effort_totals,
            "source_counts": source_counts,
        },
    )


@app.post("/papers/{paper_id}/refresh-arxiv", response_class=HTMLResponse)
def refresh_arxiv(
    request: Request,
    paper_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Refresh paper metadata from arXiv."""
    categories = crud.get_categories(db, user_id=current_user.id)

    paper = crud.refresh_paper_from_arxiv(db, paper_id, user_id=current_user.id)
    if not paper:
        return templates.TemplateResponse(
            "partials/paper_form.html",
            {
                "request": request,
                "paper": None,
                "categories": categories,
                "error": "Failed to refresh from arXiv",
            },
        )

    paper_data = {
        "id": paper.id,
        "title": paper.title,
        "abstract": paper.abstract,
        "url": paper.url,
        "pdf_url": paper.pdf_url,
        "source": paper.source.value,
        "status": paper.status.value,
        "category_id": paper.category_id,
        "notes": paper.notes,
        "venue_year": paper.venue_year,
        "arxiv_id": paper.arxiv_id,
        "arxiv_version": paper.arxiv_version,
        "arxiv_primary_category": paper.arxiv_primary_category,
        "arxiv_published_at": paper.arxiv_published_at.isoformat()
        if paper.arxiv_published_at
        else "",
        "arxiv_updated_at": paper.arxiv_updated_at.isoformat()
        if paper.arxiv_updated_at
        else "",
        "doi": paper.doi,
        "journal_ref": paper.journal_ref,
        "authors": [a.name for a in paper.authors],
    }

    return templates.TemplateResponse(
        "partials/paper_form.html",
        {"request": request, "paper": paper_data, "categories": categories},
    )


# --- Category Actions ---


@app.post("/categories", response_class=HTMLResponse)
def create_category(
    request: Request,
    name: Annotated[str, Form()],
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Create a category."""
    crud.create_category(db, schemas.CategoryCreate(name=name), user_id=current_user.id)
    categories = crud.get_categories(db, user_id=current_user.id)
    return templates.TemplateResponse(
        "partials/category_list.html",
        {"request": request, "categories": categories},
    )


@app.post("/partials/category-dropdown", response_class=HTMLResponse)
def create_category_inline(
    request: Request,
    name: Annotated[str, Form()],
    context: Annotated[str, Form()] = "paper",
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Create a category and return updated dropdown (for inline creation in forms)."""
    new_category = crud.create_category(
        db, schemas.CategoryCreate(name=name), user_id=current_user.id
    )
    categories = crud.get_categories(db, user_id=current_user.id)
    return templates.TemplateResponse(
        "partials/category_dropdown.html",
        {
            "request": request,
            "categories": categories,
            "selected_id": new_category.id,
            "context": context,
        },
    )


@app.put("/categories/{category_id}")
def update_category(
    category_id: int,
    data: schemas.CategoryUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Update a category."""
    category = crud.update_category(db, category_id, data, user_id=current_user.id)
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    return {"status": "ok"}


@app.delete("/categories/{category_id}", response_class=HTMLResponse)
def delete_category(
    request: Request,
    category_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Delete a category."""
    crud.delete_category(db, category_id, user_id=current_user.id)
    categories = crud.get_categories(db, user_id=current_user.id)
    return templates.TemplateResponse(
        "partials/category_list.html",
        {"request": request, "categories": categories},
    )


# --- Textbook Routes ---


@app.get("/textbooks", response_class=HTMLResponse)
def textbooks_page(
    request: Request,
    status: models.TextbookStatus = Query(models.TextbookStatus.PLANNED),
    category_id: Optional[int] = Query(None),
    sort_by: str = Query("manual"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Textbooks list page."""
    user_id = current_user.id

    valid_sorts = ("manual", "likes", "added", "read")
    if sort_by not in valid_sorts:
        sort_by = "manual"

    textbooks = crud.get_textbooks(
        db, user_id=user_id, status=status, category_id=category_id, sort_by=sort_by
    )

    categories = crud.get_categories(db, user_id=user_id)

    # Get textbook counts per status
    all_textbooks = crud.get_textbooks(db, user_id=user_id)
    counts = {
        "PLANNED": sum(
            1 for t in all_textbooks if t.status == models.TextbookStatus.PLANNED
        ),
        "READING": sum(
            1 for t in all_textbooks if t.status == models.TextbookStatus.READING
        ),
        "READ": sum(1 for t in all_textbooks if t.status == models.TextbookStatus.READ),
    }

    # Get effort totals for all textbooks
    effort_totals = crud.get_all_textbooks_effort_totals(db, user_id=user_id)

    sortable = sort_by == "manual"

    return templates.TemplateResponse(
        "textbooks.html",
        {
            "request": request,
            "textbooks": textbooks,
            "categories": categories,
            "current_status": status.value,
            "category_id": category_id,
            "counts": counts,
            "active_page": "textbooks",
            "sort_by": sort_by,
            "sortable": sortable,
            "effort_totals": effort_totals,
        },
    )


@app.get("/textbooks/add", response_class=HTMLResponse)
def add_textbook_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Add textbook form page."""
    categories = crud.get_categories(db, user_id=current_user.id)
    return templates.TemplateResponse(
        "add_textbook.html",
        {
            "request": request,
            "categories": categories,
            "textbook": None,
            "active_page": "textbooks",
        },
    )


@app.post("/textbooks/fetch-isbn", response_class=HTMLResponse)
def fetch_isbn(
    request: Request,
    isbn: Annotated[str, Form()],
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Fetch book metadata from Open Library by ISBN."""
    from .openlibrary import OpenLibraryError, fetch_book_by_isbn

    categories = crud.get_categories(db, user_id=current_user.id)

    try:
        metadata = fetch_book_by_isbn(isbn)

        textbook_data = {
            "title": metadata.title,
            "authors": metadata.authors or "",
            "publisher": metadata.publisher or "",
            "year": metadata.year,
            "isbn": metadata.isbn or "",
            "edition": "",
            "url": metadata.url or "",
            "status": "PLANNED",
            "category_id": None,
            "notes": "",
        }

        return templates.TemplateResponse(
            "partials/textbook_form.html",
            {"request": request, "textbook": textbook_data, "categories": categories},
        )

    except OpenLibraryError as e:
        return templates.TemplateResponse(
            "partials/textbook_form.html",
            {
                "request": request,
                "textbook": None,
                "categories": categories,
                "error": str(e),
            },
        )


@app.post("/textbooks")
def create_textbook(
    request: Request,
    title: Annotated[str, Form()],
    authors: Annotated[str, Form()] = "",
    publisher: Annotated[str, Form()] = "",
    year: Annotated[str, Form()] = "",
    isbn: Annotated[str, Form()] = "",
    edition: Annotated[str, Form()] = "",
    url: Annotated[str, Form()] = "",
    status: Annotated[str, Form()] = "PLANNED",
    category_id: Annotated[Optional[str], Form()] = None,
    notes: Annotated[str, Form()] = "",
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Create a new textbook."""
    cat_id = int(category_id) if category_id and category_id.strip() else None
    year_int = int(year) if year and year.strip() else None

    data = schemas.TextbookCreate(
        title=title,
        authors=authors or None,
        publisher=publisher or None,
        year=year_int,
        isbn=isbn or None,
        edition=edition or None,
        url=url or None,
        status=models.TextbookStatus(status),
        category_id=cat_id,
        notes=notes or None,
    )

    crud.create_textbook(db, data, user_id=current_user.id)
    return RedirectResponse(url=f"/textbooks?status={status}", status_code=303)


@app.get("/textbooks/{textbook_id}/edit", response_class=HTMLResponse)
def edit_textbook_page(
    request: Request,
    textbook_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Edit textbook form page."""
    textbook = crud.get_textbook(db, textbook_id, user_id=current_user.id)
    if not textbook:
        raise HTTPException(status_code=404, detail="Textbook not found")

    categories = crud.get_categories(db, user_id=current_user.id)

    textbook_data = {
        "id": textbook.id,
        "title": textbook.title,
        "authors": textbook.authors,
        "publisher": textbook.publisher,
        "year": textbook.year,
        "isbn": textbook.isbn,
        "edition": textbook.edition,
        "url": textbook.url,
        "status": textbook.status.value,
        "category_id": textbook.category_id,
        "notes": textbook.notes,
    }

    return templates.TemplateResponse(
        "edit_textbook.html",
        {
            "request": request,
            "textbook": textbook_data,
            "categories": categories,
            "active_page": "textbooks",
        },
    )


@app.post("/textbooks/{textbook_id}")
def update_textbook(
    request: Request,
    textbook_id: int,
    title: Annotated[str, Form()],
    authors: Annotated[str, Form()] = "",
    publisher: Annotated[str, Form()] = "",
    year: Annotated[str, Form()] = "",
    isbn: Annotated[str, Form()] = "",
    edition: Annotated[str, Form()] = "",
    url: Annotated[str, Form()] = "",
    status: Annotated[str, Form()] = "PLANNED",
    category_id: Annotated[Optional[str], Form()] = None,
    notes: Annotated[str, Form()] = "",
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Update a textbook."""
    cat_id = int(category_id) if category_id and category_id.strip() else None
    year_int = int(year) if year and year.strip() else None

    data = schemas.TextbookUpdate(
        title=title,
        authors=authors or None,
        publisher=publisher or None,
        year=year_int,
        isbn=isbn or None,
        edition=edition or None,
        url=url or None,
        status=models.TextbookStatus(status),
        category_id=cat_id,
        notes=notes or None,
    )

    textbook = crud.update_textbook(db, textbook_id, data, user_id=current_user.id)
    if not textbook:
        raise HTTPException(status_code=404, detail="Textbook not found")

    return RedirectResponse(url=f"/textbooks?status={status}", status_code=303)


@app.post("/textbooks/{textbook_id}/delete", response_class=HTMLResponse)
def delete_textbook(
    request: Request,
    textbook_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Delete a textbook."""
    textbook = crud.get_textbook(db, textbook_id, user_id=current_user.id)
    if not textbook:
        raise HTTPException(status_code=404, detail="Textbook not found")

    status = textbook.status
    category_id = textbook.category_id
    crud.delete_textbook(db, textbook_id, user_id=current_user.id)

    # Return updated textbook list
    textbooks = crud.get_textbooks(
        db, user_id=current_user.id, status=status, category_id=category_id
    )
    effort_totals = crud.get_all_textbooks_effort_totals(db, user_id=current_user.id)
    return templates.TemplateResponse(
        "partials/textbook_list.html",
        {
            "request": request,
            "textbooks": textbooks,
            "current_status": status.value,
            "category_id": category_id,
            "sortable": True,
            "effort_totals": effort_totals,
        },
    )


@app.post("/textbooks/{textbook_id}/like", response_class=HTMLResponse)
def like_textbook(
    request: Request,
    textbook_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Increment likes for a textbook."""
    likes = crud.like_textbook(db, textbook_id, user_id=current_user.id)
    if likes is None:
        raise HTTPException(status_code=404, detail="Textbook not found")
    return f'<span class="likes-count">{likes}</span>'


@app.post("/textbooks/reorder")
def reorder_textbooks(
    data: schemas.TextbookReorderRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Reorder textbooks."""
    success = crud.reorder_textbooks(
        db,
        status=data.status,
        textbook_ids=data.textbook_ids,
        user_id=current_user.id,
        category_id=data.category_id,
    )
    if not success:
        raise HTTPException(status_code=400, detail="Invalid textbook IDs")
    return {"status": "ok"}


@app.get("/partials/textbooks", response_class=HTMLResponse)
def textbooks_partial(
    request: Request,
    status: models.TextbookStatus = Query(models.TextbookStatus.PLANNED),
    category_id: Optional[int] = Query(None),
    sort_by: str = Query("manual"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Textbook list partial for HTMX."""
    valid_sorts = ("manual", "likes", "added", "read")
    if sort_by not in valid_sorts:
        sort_by = "manual"

    textbooks = crud.get_textbooks(
        db,
        user_id=current_user.id,
        status=status,
        category_id=category_id,
        sort_by=sort_by,
    )
    sortable = sort_by == "manual"

    # Get effort totals for all textbooks
    effort_totals = crud.get_all_textbooks_effort_totals(db, user_id=current_user.id)

    return templates.TemplateResponse(
        "partials/textbook_list.html",
        {
            "request": request,
            "textbooks": textbooks,
            "current_status": status.value,
            "category_id": category_id,
            "sortable": sortable,
            "effort_totals": effort_totals,
        },
    )
