"""FastAPI application for Paper Tracker."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Annotated, Optional

from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
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


# --- Health check ---


@app.get("/health", tags=["health"], response_model=schemas.Healthcheck)
def health_check(db: Session = Depends(get_db)) -> schemas.Healthcheck:
    db.execute(text("SELECT 1"))
    return schemas.Healthcheck(message="Paper Tracker API is running")


# --- Login/Logout ---


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, error: str = ""):
    """Login page."""
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": error},
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
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Main page with paper list."""
    user_id = current_user.id
    t0 = time.perf_counter()

    papers = crud.get_papers(db, user_id=user_id, status=status, category_id=category_id)
    t1 = time.perf_counter()
    logger.info(f"  get_papers(status={status.value}): {t1-t0:.3f}s")

    categories = crud.get_categories(db, user_id=user_id)
    t2 = time.perf_counter()
    logger.info(f"  get_categories: {t2-t1:.3f}s")

    # Get paper counts per status
    all_papers = crud.get_papers(db, user_id=user_id)
    t3 = time.perf_counter()
    logger.info(f"  get_papers(all): {t3-t2:.3f}s")

    counts = {
        "PLANNED": sum(1 for p in all_papers if p.status == models.PaperStatus.PLANNED),
        "READING": sum(1 for p in all_papers if p.status == models.PaperStatus.READING),
        "READ": sum(1 for p in all_papers if p.status == models.PaperStatus.READ),
    }

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

    papers = crud.get_papers_by_author(db, author_id, user_id=current_user.id, status=status_enum)

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
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Paper list partial for HTMX."""
    papers = crud.get_papers(db, user_id=current_user.id, status=status, category_id=category_id)
    return templates.TemplateResponse(
        "partials/paper_list.html",
        {
            "request": request,
            "papers": papers,
            "current_status": status.value,
            "category_id": category_id,
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


@app.post("/papers")
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
        title=title,
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
    return RedirectResponse(url=f"/?status={status}", status_code=303)


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


@app.post("/papers/{paper_id}")
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

    t0 = time.perf_counter()

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
        title=title,
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
        raise HTTPException(status_code=404, detail="Paper not found")

    return RedirectResponse(url=f"/?status={status}", status_code=303)


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
    papers = crud.get_papers(db, user_id=current_user.id, status=status, category_id=category_id)
    return templates.TemplateResponse(
        "partials/paper_list.html",
        {
            "request": request,
            "papers": papers,
            "current_status": status.value,
            "category_id": category_id,
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
