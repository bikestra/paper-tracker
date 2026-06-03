"""FastAPI application for Paper Tracker."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Annotated, Optional

from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
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

# Mount static files
app.mount(
    "/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static"
)


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

# Add Pacific timezone filter for dates
from zoneinfo import ZoneInfo
import datetime as dt

PACIFIC_TZ = ZoneInfo("America/Los_Angeles")


def to_pacific(value: dt.datetime | None) -> dt.datetime | None:
    """Convert UTC datetime to Pacific time."""
    if value is None:
        return None
    if value.tzinfo is None:
        # Assume UTC if no timezone
        value = value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(PACIFIC_TZ)


templates.env.filters["pacific"] = to_pacific


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
        config_warning = (
            "APP_PASSWORD environment variable is not set. Authentication is disabled."
        )
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

    # Reordering only allowed in manual sort mode, not for READ (sorted by read_at)
    sortable = sort_by == "manual" and status != models.PaperStatus.READ

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
    # Reordering not allowed for READ (sorted by read_at)
    sortable = sort_by == "manual" and status != models.PaperStatus.READ

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

        existing_paper = crud.get_paper_by_arxiv_id(
            db, metadata.arxiv_id, user_id=current_user.id
        )
        if existing_paper:
            return templates.TemplateResponse(
                "partials/duplicate_paper.html",
                {
                    "request": request,
                    "paper": existing_paper,
                },
            )

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
        crud.create_pending_arxiv_link(
            db, url_or_id=url_or_id, error_message=str(e), user_id=current_user.id
        )
        pending_count = len(crud.get_pending_arxiv_links(db, user_id=current_user.id))
        return templates.TemplateResponse(
            "partials/paper_form.html",
            {
                "request": request,
                "paper": None,
                "categories": categories,
                "error": str(e),
                "pending_saved": True,
                "pending_count": pending_count,
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


@app.post("/papers/{paper_id}/move-to-top", response_class=HTMLResponse)
def move_paper_to_top(
    request: Request,
    paper_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Move a paper to the top of its status list."""
    paper = crud.get_paper(db, paper_id, user_id=current_user.id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    from sqlalchemy import func, select

    stmt = select(func.min(models.Paper.order_index)).where(
        models.Paper.user_id == current_user.id,
        models.Paper.status == paper.status,
    )
    min_order = db.scalar(stmt)
    paper.order_index = (min_order - 10) if min_order is not None else 0
    db.commit()

    return HTMLResponse(
        content="",
        headers={"HX-Redirect": f"/?status={paper.status.value}"},
    )


@app.post("/papers/{paper_id}/start-reading", response_class=HTMLResponse)
def start_reading_paper(
    request: Request,
    paper_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Move a paper from PLANNED to READING status."""
    paper = crud.get_paper(db, paper_id, user_id=current_user.id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    # Update status to READING
    crud.update_paper(
        db,
        paper_id,
        schemas.PaperUpdate(status=models.PaperStatus.READING),
        user_id=current_user.id,
    )

    # Return updated paper list for PLANNED status
    papers = crud.get_papers(
        db, user_id=current_user.id, status=models.PaperStatus.PLANNED
    )
    effort_totals = crud.get_all_papers_effort_totals(db, current_user.id)
    source_counts = crud.get_all_papers_source_counts(db, current_user.id)
    return templates.TemplateResponse(
        request,
        "partials/paper_list.html",
        {
            "papers": papers,
            "effort_totals": effort_totals,
            "source_counts": source_counts,
            "sortable": True,
        },
    )


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


# --- Stats Routes ---


@app.get("/stats", response_class=HTMLResponse)
def stats_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Page showing statistics charts."""
    import calendar
    from datetime import date

    today = date.today()
    current_year = today.year
    current_month = today.month
    last_year = current_year - 1

    if current_month == 1:
        last_month = 12
        last_month_year = current_year - 1
    else:
        last_month = current_month - 1
        last_month_year = current_year

    papers_added_this_year = crud.get_papers_added_by_month(
        db, current_year, user_id=current_user.id
    )
    papers_added_last_year = crud.get_papers_added_by_month(
        db, last_year, user_id=current_user.id
    )
    papers_read_this_year = crud.get_papers_read_by_month(
        db, current_year, user_id=current_user.id
    )
    papers_read_last_year = crud.get_papers_read_by_month(
        db, last_year, user_id=current_user.id
    )
    effort_this_year = crud.get_effort_by_month(
        db, current_year, user_id=current_user.id
    )
    effort_last_year = crud.get_effort_by_month(db, last_year, user_id=current_user.id)

    days_in_current_month = calendar.monthrange(current_year, current_month)[1]
    days_in_last_month = calendar.monthrange(last_month_year, last_month)[1]

    papers_added_this_month = crud.get_papers_added_by_day(
        db, current_year, current_month, user_id=current_user.id
    )
    papers_added_last_month = crud.get_papers_added_by_day(
        db, last_month_year, last_month, user_id=current_user.id
    )
    papers_read_this_month = crud.get_papers_read_by_day(
        db, current_year, current_month, user_id=current_user.id
    )
    papers_read_last_month = crud.get_papers_read_by_day(
        db, last_month_year, last_month, user_id=current_user.id
    )
    effort_this_month = crud.get_effort_by_day(
        db, current_year, current_month, user_id=current_user.id
    )
    effort_last_month = crud.get_effort_by_day(
        db, last_month_year, last_month, user_id=current_user.id
    )

    month_names = [calendar.month_abbr[i] for i in range(1, 13)]
    current_month_name = calendar.month_name[current_month]
    last_month_name = calendar.month_name[last_month]

    return templates.TemplateResponse(
        "stats.html",
        {
            "request": request,
            "active_page": "stats",
            "current_year": current_year,
            "last_year": last_year,
            "current_month": current_month,
            "current_month_name": current_month_name,
            "last_month": last_month,
            "last_month_name": last_month_name,
            "last_month_year": last_month_year,
            "month_names": month_names,
            "days_in_current_month": days_in_current_month,
            "days_in_last_month": days_in_last_month,
            "papers_added_this_year": papers_added_this_year,
            "papers_added_last_year": papers_added_last_year,
            "papers_read_this_year": papers_read_this_year,
            "papers_read_last_year": papers_read_last_year,
            "effort_this_year": effort_this_year,
            "effort_last_year": effort_last_year,
            "papers_added_this_month": papers_added_this_month,
            "papers_added_last_month": papers_added_last_month,
            "papers_read_this_month": papers_read_this_month,
            "papers_read_last_month": papers_read_last_month,
            "effort_this_month": effort_this_month,
            "effort_last_month": effort_last_month,
        },
    )


# --- Pending ArXiv Links Routes ---


@app.get("/pending", response_class=HTMLResponse)
def pending_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Page showing pending arxiv links that failed to fetch."""
    pending_links = crud.get_pending_arxiv_links(db, user_id=current_user.id)
    return templates.TemplateResponse(
        "pending.html",
        {
            "request": request,
            "pending_links": pending_links,
            "active_page": "pending",
        },
    )


@app.post("/pending/{link_id}/retry", response_class=HTMLResponse)
def retry_pending_link(
    request: Request,
    link_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Retry fetching a pending arxiv link."""
    from sqlalchemy import select

    stmt = select(models.PendingArxivLink).where(
        models.PendingArxivLink.id == link_id,
        models.PendingArxivLink.user_id == current_user.id,
    )
    link = db.scalar(stmt)
    if not link:
        raise HTTPException(status_code=404, detail="Pending link not found")

    categories = crud.get_categories(db, user_id=current_user.id)

    try:
        arxiv_id, version = parse_arxiv_input(link.url_or_id)
        metadata = fetch_arxiv_metadata(arxiv_id)

        crud.delete_pending_arxiv_link(db, link_id, user_id=current_user.id)

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
            "partials/pending_success.html",
            {
                "request": request,
                "paper": paper_data,
                "categories": categories,
                "link_id": link_id,
            },
        )

    except ArxivError as e:
        crud.update_pending_link_retry(
            db, link_id, error_message=str(e), user_id=current_user.id
        )
        link = db.scalar(stmt)
        return templates.TemplateResponse(
            "partials/pending_row.html",
            {
                "request": request,
                "link": link,
                "retry_failed": True,
            },
        )


@app.delete("/pending/{link_id}", response_class=HTMLResponse)
def delete_pending_link(
    link_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Delete a pending arxiv link."""
    deleted = crud.delete_pending_arxiv_link(db, link_id, user_id=current_user.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Pending link not found")
    return ""


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

    # Reordering not allowed for READ (sorted by read_at)
    sortable = sort_by == "manual" and status != models.TextbookStatus.READ

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
    # Reordering not allowed for READ (sorted by read_at)
    sortable = sort_by == "manual" and status != models.TextbookStatus.READ

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


# --- Workout Routes ---


@app.get("/workouts", response_class=HTMLResponse)
def workouts_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Main workouts page."""
    user_id = current_user.id
    active_workout = crud.get_active_workout(db, user_id=user_id)
    recent_workouts = crud.get_workouts(
        db, user_id=user_id, limit=10, status=models.WorkoutStatus.COMPLETED
    )
    exercises = crud.get_exercises(db, user_id=user_id)
    next_workout_type = crud.get_next_workout_type(db, user_id=user_id)

    # Get exercise history for charts (last 20 workouts per exercise)
    exercise_history = {}
    for ex_type in models.ExerciseType:
        history = crud.get_exercise_history(db, ex_type, user_id=user_id, limit=20)
        # Reverse to get chronological order (oldest first)
        exercise_history[ex_type.value] = list(reversed(history))

    return templates.TemplateResponse(
        "workouts.html",
        {
            "request": request,
            "active_workout": active_workout,
            "recent_workouts": recent_workouts,
            "exercises": exercises,
            "next_workout_type": next_workout_type,
            "exercise_history": exercise_history,
            "active_page": "workouts",
        },
    )


@app.post("/workouts/start", response_class=HTMLResponse)
def start_workout(
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Start a new workout (auto-selects A or B based on last workout)."""
    # Abandon any stale PLANNING/IN_PROGRESS workouts so they don't block the UI
    active = crud.get_active_workout(db, user_id=current_user.id)
    if active:
        crud.abandon_workout(db, active.id, user_id=current_user.id)

    workout_type = crud.get_next_workout_type(db, user_id=current_user.id)
    workout = crud.create_workout(
        db, workout_type=workout_type, user_id=current_user.id
    )
    return RedirectResponse(url=f"/workouts/{workout.id}/plan", status_code=303)


@app.get("/workouts/{workout_id}/plan", response_class=HTMLResponse)
def workout_plan_page(
    request: Request,
    workout_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Workout planning page - enter context and generate plan."""
    from .gpt import get_exercises_for_workout, SYSTEM_PROMPT, build_workout_plan_prompt

    workout = crud.get_workout(db, workout_id, user_id=current_user.id)
    if not workout:
        raise HTTPException(status_code=404, detail="Workout not found")

    exercise_types = get_exercises_for_workout(workout.workout_type)

    # Get recent history for each exercise (last 10 records)
    exercise_history = {}
    for ex_type in exercise_types:
        exercise_history[ex_type] = crud.get_exercise_history(
            db, ex_type, user_id=current_user.id, limit=10
        )

    # Build the full prompt to show the user
    user_prompt = build_workout_plan_prompt(
        workout.workout_type, exercise_history, workout.context
    )

    return templates.TemplateResponse(
        "workout_plan.html",
        {
            "request": request,
            "workout": workout,
            "exercise_types": exercise_types,
            "exercise_history": exercise_history,
            "system_prompt": SYSTEM_PROMPT,
            "user_prompt": user_prompt,
            "active_page": "workouts",
        },
    )


@app.post("/workouts/{workout_id}/generate", response_class=HTMLResponse)
async def generate_workout_plan(
    request: Request,
    workout_id: int,
    context: Annotated[str, Form()] = "",
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Generate workout plan using GPT."""
    from .gpt import (
        generate_workout_plan as gpt_generate_plan,
        get_exercises_for_workout,
        GPTError,
    )

    workout = crud.get_workout(db, workout_id, user_id=current_user.id)
    if not workout:
        raise HTTPException(status_code=404, detail="Workout not found")

    # Update context
    workout.context = context if context else None
    db.commit()

    # Get exercise history
    exercise_types = get_exercises_for_workout(workout.workout_type)
    exercise_history = {}
    for ex_type in exercise_types:
        exercise_history[ex_type] = crud.get_exercise_history(
            db, ex_type, user_id=current_user.id, limit=5
        )

    try:
        gpt_response, plan = await gpt_generate_plan(
            workout.workout_type,
            exercise_history,
            context if context else None,
        )

        # Save the conversation
        crud.save_gpt_conversation(
            db,
            user_message=f"Generate workout plan for {workout.workout_type.value}"
            + (f"\nContext: {context}" if context else ""),
            gpt_response=gpt_response,
            workout_id=workout_id,
            user_id=current_user.id,
        )

        if plan:
            # Create workout sets from the plan
            all_sets = []
            for ex_plan in plan.exercises:
                logger.info(
                    f"Creating sets for {ex_plan.exercise}: {len(ex_plan.sets)} sets"
                )
                for i, set_data in enumerate(ex_plan.sets):
                    all_sets.append(
                        schemas.WorkoutSetCreate(
                            exercise_type=ex_plan.exercise,
                            set_type=set_data.type,
                            set_number=i + 1,
                            target_weight=set_data.weight,
                            target_reps=set_data.reps,
                        )
                    )
            logger.info(f"Adding {len(all_sets)} total sets to workout {workout_id}")
            crud.add_workout_sets(db, workout_id, all_sets, user_id=current_user.id)

            # Start the workout
            crud.start_workout(db, workout_id, user_id=current_user.id)

            return RedirectResponse(url=f"/workouts/{workout_id}", status_code=303)
        else:
            # Parsing failed - show error with GPT response
            return templates.TemplateResponse(
                "workout_plan.html",
                {
                    "request": request,
                    "workout": workout,
                    "exercise_types": exercise_types,
                    "exercise_history": exercise_history,
                    "active_page": "workouts",
                    "error": "Failed to parse workout plan from GPT response. Please try again.",
                    "gpt_response": gpt_response,
                },
            )

    except GPTError as e:
        return templates.TemplateResponse(
            "workout_plan.html",
            {
                "request": request,
                "workout": workout,
                "exercise_types": exercise_types,
                "exercise_history": exercise_history,
                "active_page": "workouts",
                "error": str(e),
            },
            status_code=500,
        )


@app.get("/api/workouts/{workout_id}/stream-plan")
async def stream_workout_plan(
    workout_id: int,
    message: str = "",
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Stream workout plan generation via SSE."""
    import json as json_module
    from .gpt import (
        stream_openai,
        SYSTEM_PROMPT,
        build_workout_plan_prompt,
        get_exercises_for_workout,
        format_exercise_history,
        GPTError,
    )

    workout = crud.get_workout(db, workout_id, user_id=current_user.id)
    if not workout:
        raise HTTPException(status_code=404, detail="Workout not found")

    # Get exercise history (last 10 records)
    exercise_types = get_exercises_for_workout(workout.workout_type)
    exercise_history = {}
    for ex_type in exercise_types:
        exercise_history[ex_type] = crud.get_exercise_history(
            db, ex_type, user_id=current_user.id, limit=10
        )

    # Get previous conversations for this workout
    conversations = crud.get_recent_conversations(
        db, workout_id=workout_id, user_id=current_user.id, limit=20
    )

    # Build messages
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    # Add conversation history
    for conv in reversed(conversations):
        messages.append({"role": "user", "content": conv.user_message})
        messages.append({"role": "assistant", "content": conv.gpt_response})

    # Determine user message
    if message:
        user_message = message
    else:
        # Initial plan generation
        user_message = build_workout_plan_prompt(
            workout.workout_type,
            exercise_history,
            workout.context,
        )

    messages.append({"role": "user", "content": user_message})

    async def generate():
        full_response = ""
        try:
            async for chunk in stream_openai(messages):
                full_response += chunk
                # Send chunk as SSE
                yield f"data: {json_module.dumps({'type': 'chunk', 'content': chunk})}\n\n"

            # Save conversation to DB
            crud.save_gpt_conversation(
                db,
                user_message=user_message,
                gpt_response=full_response,
                workout_id=workout_id,
                user_id=current_user.id,
            )

            # Send completion with full response
            yield f"data: {json_module.dumps({'type': 'done', 'content': full_response})}\n\n"
        except GPTError as e:
            yield f"data: {json_module.dumps({'type': 'error', 'content': str(e)})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/workouts/{workout_id}/accept-plan")
async def accept_workout_plan(
    request: Request,
    workout_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Accept the workout plan and create sets from the last GPT response."""
    from .gpt import parse_workout_plan, GPTError

    workout = crud.get_workout(db, workout_id, user_id=current_user.id)
    if not workout:
        raise HTTPException(status_code=404, detail="Workout not found")

    # Get the most recent GPT response for this workout
    conversations = crud.get_recent_conversations(
        db, workout_id=workout_id, user_id=current_user.id, limit=1
    )
    if not conversations:
        return JSONResponse({"error": "No workout plan generated yet"}, status_code=400)

    last_response = conversations[0].gpt_response
    plan = parse_workout_plan(last_response)

    if not plan or not plan.exercises:
        return JSONResponse(
            {
                "error": "Could not parse workout plan from response. Ask GPT to regenerate the plan."
            },
            status_code=400,
        )

    # Create workout sets from the plan
    all_sets = []
    for ex_plan in plan.exercises:
        logger.info(f"Creating sets for {ex_plan.exercise}: {len(ex_plan.sets)} sets")
        for i, set_data in enumerate(ex_plan.sets):
            all_sets.append(
                schemas.WorkoutSetCreate(
                    exercise_type=ex_plan.exercise,
                    set_type=set_data.type,
                    set_number=i + 1,
                    target_weight=set_data.weight,
                    target_reps=set_data.reps,
                )
            )

    logger.info(f"Adding {len(all_sets)} total sets to workout {workout_id}")
    crud.add_workout_sets(db, workout_id, all_sets, user_id=current_user.id)

    # Start the workout
    crud.start_workout(db, workout_id, user_id=current_user.id)

    return JSONResponse({"success": True, "redirect": f"/workouts/{workout_id}"})


@app.get("/api/workouts/{workout_id}/parse-plan")
async def parse_current_plan(
    workout_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Parse and return the current workout plan from the last GPT response."""
    from .gpt import parse_workout_plan

    workout = crud.get_workout(db, workout_id, user_id=current_user.id)
    if not workout:
        raise HTTPException(status_code=404, detail="Workout not found")

    # Get the most recent GPT response for this workout
    conversations = crud.get_recent_conversations(
        db, workout_id=workout_id, user_id=current_user.id, limit=1
    )
    if not conversations:
        return JSONResponse({"plan": None})

    last_response = conversations[0].gpt_response
    plan = parse_workout_plan(last_response)

    if not plan:
        return JSONResponse({"plan": None})

    # Convert to JSON-serializable format
    plan_data = {
        "exercises": [
            {
                "exercise": ex.exercise.value.replace("_", " ").title(),
                "notes": ex.notes,
                "sets": [
                    {
                        "type": s.type.value,
                        "weight": s.weight,
                        "reps": s.reps,
                    }
                    for s in ex.sets
                ],
            }
            for ex in plan.exercises
        ]
    }

    return JSONResponse({"plan": plan_data})


@app.get("/api/workouts/{workout_id}/stream-chat")
async def stream_coach_chat(
    workout_id: int,
    message: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Stream chat response from coach via SSE."""
    import json as json_module
    from .gpt import (
        stream_openai,
        SYSTEM_PROMPT,
        format_exercise_history,
        get_exercises_for_workout,
        GPTError,
    )

    workout = crud.get_workout(db, workout_id, user_id=current_user.id)
    if not workout:
        raise HTTPException(status_code=404, detail="Workout not found")

    # Get exercise history for context
    exercise_types = get_exercises_for_workout(workout.workout_type)
    exercise_history = {}
    for ex_type in exercise_types:
        exercise_history[ex_type] = crud.get_exercise_history(
            db, ex_type, user_id=current_user.id, limit=5
        )

    # Build context
    workout_name = (
        "Workout A"
        if workout.workout_type == models.WorkoutType.WORKOUT_A
        else "Workout B"
    )
    context = f"The user is currently doing {workout_name}."
    context += "\n\nRecent exercise history:"
    for ex_type, history in exercise_history.items():
        ex_name = ex_type.value.replace("_", " ").title()
        context += f"\n\n{ex_name}:\n{format_exercise_history(history)}"

    # Get recent conversations
    conversations = crud.get_recent_conversations(
        db, workout_id=workout_id, user_id=current_user.id, limit=10
    )

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.append({"role": "user", "content": f"[Context: {context}]"})
    messages.append(
        {
            "role": "assistant",
            "content": "Got it, I understand the context. How can I help?",
        }
    )

    # Add conversation history
    for conv in reversed(conversations):
        messages.append({"role": "user", "content": conv.user_message})
        messages.append({"role": "assistant", "content": conv.gpt_response})

    messages.append({"role": "user", "content": message})

    async def generate():
        full_response = ""
        try:
            async for chunk in stream_openai(messages, max_tokens=1000):
                full_response += chunk
                yield f"data: {json_module.dumps({'type': 'chunk', 'content': chunk})}\n\n"

            # Save conversation
            crud.save_gpt_conversation(
                db,
                user_message=message,
                gpt_response=full_response,
                workout_id=workout_id,
                user_id=current_user.id,
            )

            yield f"data: {json_module.dumps({'type': 'done', 'content': full_response})}\n\n"
        except GPTError as e:
            yield f"data: {json_module.dumps({'type': 'error', 'content': str(e)})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/workouts/{workout_id}", response_class=HTMLResponse)
def workout_detail(
    request: Request,
    workout_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Active workout view."""
    workout = crud.get_workout(db, workout_id, user_id=current_user.id)
    if not workout:
        raise HTTPException(status_code=404, detail="Workout not found")

    # Group sets by exercise
    sets_by_exercise: dict[models.ExerciseType, list[models.WorkoutSet]] = {}
    for ws in workout.workout_sets:
        if ws.exercise_type not in sets_by_exercise:
            sets_by_exercise[ws.exercise_type] = []
        sets_by_exercise[ws.exercise_type].append(ws)

    # Sort sets by set_number within each exercise
    for ex_type in sets_by_exercise:
        sets_by_exercise[ex_type].sort(key=lambda s: s.set_number)

    # Get exercise results (RIR) already submitted
    exercise_results = {r.exercise_type: r for r in workout.exercise_results}

    # Get GPT conversations for this workout
    conversations = crud.get_recent_conversations(
        db, user_id=current_user.id, workout_id=workout_id, limit=20
    )

    return templates.TemplateResponse(
        "workout_active.html",
        {
            "request": request,
            "workout": workout,
            "sets_by_exercise": sets_by_exercise,
            "exercise_results": exercise_results,
            "conversations": conversations,
            "active_page": "workouts",
        },
    )


@app.post("/workouts/sets/{set_id}/complete", response_class=HTMLResponse)
def complete_set_route(
    request: Request,
    set_id: int,
    actual_weight: Annotated[float | None, Form()] = None,
    actual_reps: Annotated[int | None, Form()] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Mark a set as completed."""
    ws = crud.complete_set(
        db, set_id, actual_weight, actual_reps, user_id=current_user.id
    )
    if not ws:
        raise HTTPException(status_code=404, detail="Set not found")

    return templates.TemplateResponse(
        "partials/workout_set.html",
        {"request": request, "s": ws},
    )


@app.post("/workouts/sets/{set_id}/edit", response_class=HTMLResponse)
def edit_set_route(
    request: Request,
    set_id: int,
    target_weight: Annotated[float | None, Form()] = None,
    target_reps: Annotated[int | None, Form()] = None,
    notes: Annotated[str | None, Form()] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Edit set target values."""
    ws = crud.update_set(
        db, set_id, target_weight, target_reps, notes, user_id=current_user.id
    )
    if not ws:
        raise HTTPException(status_code=404, detail="Set not found")

    return templates.TemplateResponse(
        "partials/workout_set.html",
        {"request": request, "s": ws},
    )


@app.post(
    "/workouts/{workout_id}/exercises/{exercise_type}/rir", response_class=HTMLResponse
)
def save_exercise_rir(
    request: Request,
    workout_id: int,
    exercise_type: str,
    rir: Annotated[int, Form()],
    notes: Annotated[str | None, Form()] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Save RIR for an exercise."""
    ex_type = models.ExerciseType(exercise_type)

    # Get the top set for this exercise to save its weight/reps
    workout = crud.get_workout(db, workout_id, user_id=current_user.id)
    if not workout:
        raise HTTPException(status_code=404, detail="Workout not found")

    # Find the top set
    top_set = None
    for ws in workout.workout_sets:
        if ws.exercise_type == ex_type and ws.set_type == models.SetType.TOP_SET:
            top_set = ws
            break

    top_weight = top_set.actual_weight or top_set.target_weight if top_set else None
    top_reps = top_set.actual_reps or top_set.target_reps if top_set else None

    result = crud.save_exercise_result(
        db,
        workout_id=workout_id,
        exercise_type=ex_type,
        top_set_weight=top_weight,
        top_set_reps=top_reps,
        rir=rir,
        notes=notes,
        user_id=current_user.id,
    )

    if not result:
        raise HTTPException(status_code=404, detail="Could not save result")

    return templates.TemplateResponse(
        "partials/rir_input.html",
        {"request": request, "exercise_type": ex_type, "result": result, "saved": True},
    )


@app.post("/workouts/{workout_id}/complete")
def complete_workout_route(
    workout_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Complete the workout."""
    workout = crud.complete_workout(db, workout_id, user_id=current_user.id)
    if not workout:
        raise HTTPException(status_code=404, detail="Workout not found")

    return RedirectResponse(url="/workouts", status_code=303)


@app.post("/workouts/{workout_id}/abandon")
def abandon_workout_route(
    workout_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Abandon the workout."""
    workout = crud.abandon_workout(db, workout_id, user_id=current_user.id)
    if not workout:
        raise HTTPException(status_code=404, detail="Workout not found")

    return RedirectResponse(url="/workouts", status_code=303)


@app.post("/api/workouts/{workout_id}/chat", response_class=JSONResponse)
async def chat_with_coach(
    workout_id: int,
    data: schemas.GPTMessageRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Chat with GPT coach during workout."""
    from .gpt import chat_with_coach as gpt_chat, get_exercises_for_workout, GPTError

    workout = crud.get_workout(db, workout_id, user_id=current_user.id)
    if not workout:
        raise HTTPException(status_code=404, detail="Workout not found")

    # Get exercise history for context
    exercise_types = get_exercises_for_workout(workout.workout_type)
    exercise_history = {}
    for ex_type in exercise_types:
        exercise_history[ex_type] = crud.get_exercise_history(
            db, ex_type, user_id=current_user.id, limit=5
        )

    # Get recent conversation history for this workout
    recent_convos = crud.get_recent_conversations(
        db, user_id=current_user.id, workout_id=workout_id, limit=5
    )
    conversation_history = []
    for conv in reversed(list(recent_convos)):
        conversation_history.append({"role": "user", "content": conv.user_message})
        conversation_history.append({"role": "assistant", "content": conv.gpt_response})

    try:
        response = await gpt_chat(
            data.message,
            workout_type=workout.workout_type,
            exercise_history=exercise_history,
            conversation_history=conversation_history,
        )

        # Save conversation
        crud.save_gpt_conversation(
            db,
            user_message=data.message,
            gpt_response=response,
            workout_id=workout_id,
            user_id=current_user.id,
        )

        return {"response": response}

    except GPTError as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)
