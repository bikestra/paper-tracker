"""FastAPI application for Paper Tracker."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.orm import Session

from . import crud, models, schemas
from .arxiv import ArxivError, fetch_arxiv_metadata, parse_arxiv_input
from .db import Base, engine, get_db

app = FastAPI(title="Paper Tracker")

# Templates
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.bind = engine


# --- Health check ---


@app.get("/health", tags=["health"], response_model=schemas.Healthcheck)
def health_check(db: Session = Depends(get_db)) -> schemas.Healthcheck:
    db.execute(text("SELECT 1"))
    return schemas.Healthcheck(message="Paper Tracker API is running")


# --- HTML Pages ---


@app.get("/", response_class=HTMLResponse)
def home(
    request: Request,
    status: models.PaperStatus = Query(models.PaperStatus.PLANNED),
    category_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """Main page with paper list."""
    papers = crud.get_papers(db, status=status, category_id=category_id)
    categories = crud.get_categories(db)

    # Get paper counts per status
    all_papers = crud.get_papers(db)
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
        },
    )


@app.get("/add", response_class=HTMLResponse)
def add_paper_page(request: Request, db: Session = Depends(get_db)):
    """Add paper form page."""
    categories = crud.get_categories(db)
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
):
    """Edit paper form page."""
    paper = crud.get_paper(db, paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    categories = crud.get_categories(db)

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
def authors_page(request: Request, db: Session = Depends(get_db)):
    """Authors list page."""
    authors = crud.get_authors(db)
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
):
    """Author detail page with papers."""
    author = crud.get_author(db, author_id)
    if not author:
        raise HTTPException(status_code=404, detail="Author not found")

    status_enum = None
    if status:
        try:
            status_enum = models.PaperStatus(status)
        except ValueError:
            pass

    papers = crud.get_papers_by_author(db, author_id, status=status_enum)

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
def categories_page(request: Request, db: Session = Depends(get_db)):
    """Categories management page."""
    categories = crud.get_categories(db)
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
):
    """Paper list partial for HTMX."""
    papers = crud.get_papers(db, status=status, category_id=category_id)
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
def categories_partial(request: Request, db: Session = Depends(get_db)):
    """Categories list partial for HTMX."""
    categories = crud.get_categories(db)
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
):
    """Fetch arXiv metadata and return populated form."""
    categories = crud.get_categories(db)

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

    crud.create_paper(db, data)
    return RedirectResponse(url=f"/?status={status}", status_code=303)


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
):
    """Update a paper."""
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

    paper = crud.update_paper(db, paper_id, data)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    return RedirectResponse(url=f"/?status={status}", status_code=303)


@app.post("/papers/{paper_id}/delete", response_class=HTMLResponse)
def delete_paper(
    request: Request,
    paper_id: int,
    db: Session = Depends(get_db),
):
    """Delete a paper."""
    paper = crud.get_paper(db, paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    status = paper.status
    category_id = paper.category_id
    crud.delete_paper(db, paper_id)

    # Return updated paper list
    papers = crud.get_papers(db, status=status, category_id=category_id)
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
):
    """Refresh paper metadata from arXiv."""
    categories = crud.get_categories(db)

    paper = crud.refresh_paper_from_arxiv(db, paper_id)
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


@app.post("/papers/reorder")
def reorder_papers(
    data: schemas.ReorderRequest,
    db: Session = Depends(get_db),
):
    """Reorder papers."""
    success = crud.reorder_papers(
        db,
        status=data.status,
        paper_ids=data.paper_ids,
        category_id=data.category_id,
    )
    if not success:
        raise HTTPException(status_code=400, detail="Invalid paper IDs")
    return {"status": "ok"}


# --- Category Actions ---


@app.post("/categories", response_class=HTMLResponse)
def create_category(
    request: Request,
    name: Annotated[str, Form()],
    db: Session = Depends(get_db),
):
    """Create a category."""
    crud.create_category(db, schemas.CategoryCreate(name=name))
    categories = crud.get_categories(db)
    return templates.TemplateResponse(
        "partials/category_list.html",
        {"request": request, "categories": categories},
    )


@app.put("/categories/{category_id}")
def update_category(
    category_id: int,
    data: schemas.CategoryUpdate,
    db: Session = Depends(get_db),
):
    """Update a category."""
    category = crud.update_category(db, category_id, data)
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    return {"status": "ok"}


@app.delete("/categories/{category_id}", response_class=HTMLResponse)
def delete_category(
    request: Request,
    category_id: int,
    db: Session = Depends(get_db),
):
    """Delete a category."""
    crud.delete_category(db, category_id)
    categories = crud.get_categories(db)
    return templates.TemplateResponse(
        "partials/category_list.html",
        {"request": request, "categories": categories},
    )
