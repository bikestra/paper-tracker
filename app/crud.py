"""CRUD operations for Paper Tracker."""

from __future__ import annotations

import datetime as dt
from typing import Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from . import models, schemas
from .arxiv import normalize_author_name


# Default user ID for single-user mode (local development)
DEFAULT_USER_ID = 1


# --- User CRUD ---


def get_or_create_user_by_email(db: Session, email: str) -> models.User:
    """Get or create a user by email."""
    stmt = select(models.User).where(models.User.email == email)
    user = db.scalar(stmt)
    if user:
        return user

    # Create new user
    user = models.User(email=email)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_user_by_id(db: Session, user_id: int) -> models.User | None:
    """Get a user by ID."""
    return db.get(models.User, user_id)


# --- Category CRUD ---


def get_categories(
    db: Session, user_id: int = DEFAULT_USER_ID
) -> Sequence[models.Category]:
    """Get all categories for a user."""
    stmt = (
        select(models.Category)
        .where(models.Category.user_id == user_id)
        .order_by(models.Category.name)
    )
    return db.scalars(stmt).all()


def get_category(
    db: Session, category_id: int, user_id: int = DEFAULT_USER_ID
) -> models.Category | None:
    """Get a category by ID."""
    stmt = select(models.Category).where(
        models.Category.id == category_id, models.Category.user_id == user_id
    )
    return db.scalar(stmt)


def create_category(
    db: Session, data: schemas.CategoryCreate, user_id: int = DEFAULT_USER_ID
) -> models.Category:
    """Create a new category."""
    category = models.Category(user_id=user_id, name=data.name)
    db.add(category)
    db.commit()
    db.refresh(category)
    return category


def update_category(
    db: Session,
    category_id: int,
    data: schemas.CategoryUpdate,
    user_id: int = DEFAULT_USER_ID,
) -> models.Category | None:
    """Update a category."""
    category = get_category(db, category_id, user_id)
    if not category:
        return None
    category.name = data.name
    db.commit()
    db.refresh(category)
    return category


def delete_category(
    db: Session, category_id: int, user_id: int = DEFAULT_USER_ID
) -> bool:
    """Delete a category. Returns True if deleted."""
    category = get_category(db, category_id, user_id)
    if not category:
        return False
    db.delete(category)
    db.commit()
    return True


# --- Author CRUD ---


def get_authors(db: Session, user_id: int = DEFAULT_USER_ID) -> list[dict]:
    """Get all authors with paper counts."""
    stmt = (
        select(
            models.Author,
            func.count(models.PaperAuthor.paper_id).label("paper_count"),
        )
        .outerjoin(models.PaperAuthor)
        .where(models.Author.user_id == user_id)
        .group_by(models.Author.id)
        .order_by(models.Author.name)
    )
    results = db.execute(stmt).all()
    return [
        {
            "id": author.id,
            "user_id": author.user_id,
            "name": author.name,
            "orcid": author.orcid,
            "arxiv_id": author.arxiv_id,
            "created_at": author.created_at,
            "paper_count": count,
        }
        for author, count in results
    ]


def get_author(
    db: Session, author_id: int, user_id: int = DEFAULT_USER_ID
) -> models.Author | None:
    """Get an author by ID."""
    stmt = select(models.Author).where(
        models.Author.id == author_id, models.Author.user_id == user_id
    )
    return db.scalar(stmt)


def get_or_create_author(
    db: Session,
    name: str,
    user_id: int = DEFAULT_USER_ID,
    orcid: str | None = None,
    arxiv_id: str | None = None,
) -> models.Author:
    """Get or create an author.

    Matching priority:
    1. By orcid if provided
    2. By arxiv_id if provided
    3. By normalized name
    """
    # Try to find by orcid first
    if orcid:
        stmt = select(models.Author).where(
            models.Author.user_id == user_id, models.Author.orcid == orcid
        )
        author = db.scalar(stmt)
        if author:
            return author

    # Try to find by arxiv_id
    if arxiv_id:
        stmt = select(models.Author).where(
            models.Author.user_id == user_id, models.Author.arxiv_id == arxiv_id
        )
        author = db.scalar(stmt)
        if author:
            return author

    # Generate arxiv_id from name if not provided
    if not arxiv_id:
        arxiv_id = normalize_author_name(name)

    # Try to find by generated arxiv_id
    stmt = select(models.Author).where(
        models.Author.user_id == user_id, models.Author.arxiv_id == arxiv_id
    )
    author = db.scalar(stmt)
    if author:
        return author

    # Create new author
    author = models.Author(
        user_id=user_id,
        name=name,
        orcid=orcid,
        arxiv_id=arxiv_id,
    )
    db.add(author)
    db.flush()  # Get the ID without committing
    return author


def get_papers_by_author(
    db: Session,
    author_id: int,
    user_id: int = DEFAULT_USER_ID,
    status: models.PaperStatus | None = None,
) -> Sequence[models.Paper]:
    """Get all papers by an author."""
    stmt = (
        select(models.Paper)
        .join(models.PaperAuthor)
        .where(
            models.Paper.user_id == user_id,
            models.PaperAuthor.author_id == author_id,
        )
        .options(
            joinedload(models.Paper.authors),
            joinedload(models.Paper.category),
        )
        .order_by(models.Paper.order_index)
    )
    if status:
        stmt = stmt.where(models.Paper.status == status)
    return db.scalars(stmt).unique().all()


# --- Paper CRUD ---


def get_papers(
    db: Session,
    user_id: int = DEFAULT_USER_ID,
    status: models.PaperStatus | None = None,
    category_id: int | None = None,
    sort_by: str = "manual",
) -> Sequence[models.Paper]:
    """Get papers with optional filtering and sorting.

    Args:
        sort_by: One of "manual" (order_index), "likes", "added" (created_at), "read" (read_at)
    """
    stmt = (
        select(models.Paper)
        .where(models.Paper.user_id == user_id)
        .options(
            joinedload(models.Paper.authors),
            joinedload(models.Paper.category),
        )
    )

    # Apply sorting
    if sort_by == "likes":
        stmt = stmt.order_by(models.Paper.likes.desc(), models.Paper.created_at.desc())
    elif sort_by == "added":
        stmt = stmt.order_by(models.Paper.created_at.desc())
    elif sort_by == "read":
        # Papers with read_at first (most recent), then unread papers by created_at
        stmt = stmt.order_by(
            models.Paper.read_at.desc().nulls_last(),
            models.Paper.created_at.desc(),
        )
    else:  # "manual" or default
        stmt = stmt.order_by(models.Paper.order_index)

    if status:
        stmt = stmt.where(models.Paper.status == status)
    if category_id is not None:
        stmt = stmt.where(models.Paper.category_id == category_id)

    return db.scalars(stmt).unique().all()


def get_paper(
    db: Session, paper_id: int, user_id: int = DEFAULT_USER_ID
) -> models.Paper | None:
    """Get a paper by ID with authors and category loaded."""
    stmt = (
        select(models.Paper)
        .where(models.Paper.id == paper_id, models.Paper.user_id == user_id)
        .options(
            joinedload(models.Paper.authors),
            joinedload(models.Paper.category),
        )
    )
    return db.scalar(stmt)


def create_paper(
    db: Session, data: schemas.PaperCreate, user_id: int = DEFAULT_USER_ID
) -> models.Paper:
    """Create a new paper with authors."""
    # Get min order_index across ALL papers with this status (ignoring category)
    # This ensures new papers always appear at the top when viewing all papers
    stmt = select(func.min(models.Paper.order_index)).where(
        models.Paper.user_id == user_id,
        models.Paper.status == data.status,
    )
    min_order = db.scalar(stmt)
    new_order = (min_order - 10) if min_order is not None else 0

    paper = models.Paper(
        user_id=user_id,
        title=data.title,
        abstract=data.abstract,
        url=data.url,
        pdf_url=data.pdf_url,
        source=data.source,
        status=data.status,
        category_id=data.category_id,
        order_index=new_order,
        notes=data.notes,
        arxiv_id=data.arxiv_id,
        arxiv_version=data.arxiv_version,
        arxiv_primary_category=data.arxiv_primary_category,
        arxiv_published_at=data.arxiv_published_at,
        arxiv_updated_at=data.arxiv_updated_at,
        doi=data.doi,
        journal_ref=data.journal_ref,
        citation_key=data.citation_key,
        venue_year=data.venue_year,
    )
    db.add(paper)
    db.flush()

    # Add authors
    for position, author_name in enumerate(data.authors):
        author = get_or_create_author(db, author_name, user_id)
        paper_author = models.PaperAuthor(
            paper_id=paper.id,
            author_id=author.id,
            position=position,
        )
        db.add(paper_author)

    db.commit()
    db.refresh(paper)

    # Reload with relationships
    return get_paper(db, paper.id, user_id)  # type: ignore


def update_paper(
    db: Session,
    paper_id: int,
    data: schemas.PaperUpdate,
    user_id: int = DEFAULT_USER_ID,
) -> models.Paper | None:
    """Update a paper."""
    paper = get_paper(db, paper_id, user_id)
    if not paper:
        return None

    # Track if status changed (for read_at timestamp)
    old_status = paper.status

    # Update fields that are set
    update_data = data.model_dump(exclude_unset=True, exclude={"authors"})
    for field, value in update_data.items():
        setattr(paper, field, value)

    # Set read_at if transitioning to READ
    if data.status == models.PaperStatus.READ and old_status != models.PaperStatus.READ:
        paper.read_at = dt.datetime.now(dt.timezone.utc)
    elif data.status and data.status != models.PaperStatus.READ:
        paper.read_at = None

    # Update authors if provided
    if data.authors is not None:
        # Remove existing author links
        for link in paper.author_links:
            db.delete(link)
        db.flush()

        # Add new authors
        for position, author_name in enumerate(data.authors):
            author = get_or_create_author(db, author_name, user_id)
            paper_author = models.PaperAuthor(
                paper_id=paper.id,
                author_id=author.id,
                position=position,
            )
            db.add(paper_author)

    db.commit()
    return get_paper(db, paper_id, user_id)


def delete_paper(db: Session, paper_id: int, user_id: int = DEFAULT_USER_ID) -> bool:
    """Delete a paper. Returns True if deleted."""
    paper = get_paper(db, paper_id, user_id)
    if not paper:
        return False
    db.delete(paper)
    db.commit()
    return True


def like_paper(
    db: Session, paper_id: int, user_id: int = DEFAULT_USER_ID
) -> int | None:
    """Increment likes for a paper. Returns new like count or None if not found."""
    paper = get_paper(db, paper_id, user_id)
    if not paper:
        return None
    paper.likes += 1
    db.commit()
    return paper.likes


def reorder_papers(
    db: Session,
    status: models.PaperStatus,
    paper_ids: list[int],
    user_id: int = DEFAULT_USER_ID,
    category_id: int | None = None,
) -> bool:
    """Reorder papers by setting order_index sequentially.

    Args:
        db: Database session
        status: Paper status to filter by
        paper_ids: List of paper IDs in desired order
        user_id: User ID
        category_id: Optional category ID to filter by

    Returns:
        True if successful
    """
    # Verify all papers exist and belong to user with correct status
    stmt = select(models.Paper).where(
        models.Paper.id.in_(paper_ids),
        models.Paper.user_id == user_id,
        models.Paper.status == status,
    )
    if category_id is not None:
        stmt = stmt.where(models.Paper.category_id == category_id)

    papers = {p.id: p for p in db.scalars(stmt).all()}

    if len(papers) != len(paper_ids):
        return False  # Some papers not found or don't match criteria

    # Update order_index
    for idx, paper_id in enumerate(paper_ids):
        papers[paper_id].order_index = (idx + 1) * 10

    db.commit()
    return True


def refresh_paper_from_arxiv(
    db: Session,
    paper_id: int,
    user_id: int = DEFAULT_USER_ID,
) -> models.Paper | None:
    """Refresh paper metadata from arXiv.

    Preserves user notes and category assignment.
    """
    from .arxiv import ArxivFetchError, fetch_arxiv_metadata

    paper = get_paper(db, paper_id, user_id)
    if not paper or not paper.arxiv_id:
        return None

    try:
        metadata = fetch_arxiv_metadata(paper.arxiv_id)
    except ArxivFetchError:
        return None

    # Update metadata (preserving notes, category, status)
    paper.title = metadata.title
    paper.abstract = metadata.abstract
    paper.url = metadata.url
    paper.pdf_url = metadata.pdf_url
    paper.arxiv_version = metadata.arxiv_version
    paper.arxiv_primary_category = metadata.primary_category
    paper.arxiv_published_at = metadata.published_at
    paper.arxiv_updated_at = metadata.updated_at
    paper.doi = metadata.doi
    paper.journal_ref = metadata.journal_ref

    # Update authors
    for link in paper.author_links:
        db.delete(link)
    db.flush()

    for position, author_info in enumerate(metadata.authors):
        author = get_or_create_author(
            db, author_info.name, user_id, arxiv_id=author_info.arxiv_id
        )
        paper_author = models.PaperAuthor(
            paper_id=paper.id,
            author_id=author.id,
            position=position,
        )
        db.add(paper_author)

    db.commit()
    return get_paper(db, paper_id, user_id)


# --- Effort Log CRUD ---


def create_effort_log(
    db: Session,
    points: int,
    note: str | None = None,
    paper_id: int | None = None,
    textbook_id: int | None = None,
    user_id: int = DEFAULT_USER_ID,
) -> models.EffortLog | None:
    """Create a new effort log entry for a paper or textbook."""
    # Must specify either paper_id or textbook_id
    if paper_id is None and textbook_id is None:
        return None

    # Verify the item exists and belongs to user
    if paper_id is not None:
        paper = get_paper(db, paper_id, user_id)
        if not paper:
            return None
    if textbook_id is not None:
        textbook = get_textbook(db, textbook_id, user_id)
        if not textbook:
            return None

    effort_log = models.EffortLog(
        user_id=user_id,
        paper_id=paper_id,
        textbook_id=textbook_id,
        points=points,
        note=note,
    )
    db.add(effort_log)
    db.commit()
    db.refresh(effort_log)
    return effort_log


def get_effort_logs(
    db: Session,
    user_id: int = DEFAULT_USER_ID,
    paper_id: int | None = None,
    textbook_id: int | None = None,
    limit: int | None = None,
) -> Sequence[models.EffortLog]:
    """Get effort logs, optionally filtered, ordered by most recent first."""
    stmt = (
        select(models.EffortLog)
        .where(models.EffortLog.user_id == user_id)
        .options(
            joinedload(models.EffortLog.paper),
            joinedload(models.EffortLog.textbook),
        )
        .order_by(models.EffortLog.created_at.desc())
    )

    if paper_id is not None:
        stmt = stmt.where(models.EffortLog.paper_id == paper_id)
    if textbook_id is not None:
        stmt = stmt.where(models.EffortLog.textbook_id == textbook_id)

    if limit is not None:
        stmt = stmt.limit(limit)

    return db.scalars(stmt).unique().all()


def get_paper_effort_total(
    db: Session,
    paper_id: int,
    user_id: int = DEFAULT_USER_ID,
) -> int:
    """Get total effort points for a paper."""
    stmt = select(func.sum(models.EffortLog.points)).where(
        models.EffortLog.user_id == user_id,
        models.EffortLog.paper_id == paper_id,
    )
    result = db.scalar(stmt)
    return result or 0


def get_textbook_effort_total(
    db: Session,
    textbook_id: int,
    user_id: int = DEFAULT_USER_ID,
) -> int:
    """Get total effort points for a textbook."""
    stmt = select(func.sum(models.EffortLog.points)).where(
        models.EffortLog.user_id == user_id,
        models.EffortLog.textbook_id == textbook_id,
    )
    result = db.scalar(stmt)
    return result or 0


def get_all_papers_effort_totals(
    db: Session,
    user_id: int = DEFAULT_USER_ID,
) -> dict[int, int]:
    """Get total effort points for all papers as a dict {paper_id: total_points}."""
    stmt = (
        select(models.EffortLog.paper_id, func.sum(models.EffortLog.points))
        .where(
            models.EffortLog.user_id == user_id,
            models.EffortLog.paper_id.isnot(None),
        )
        .group_by(models.EffortLog.paper_id)
    )
    results = db.execute(stmt).all()
    return {paper_id: total for paper_id, total in results}


def get_all_textbooks_effort_totals(
    db: Session,
    user_id: int = DEFAULT_USER_ID,
) -> dict[int, int]:
    """Get total effort points for all textbooks as a dict {textbook_id: total_points}."""
    stmt = (
        select(models.EffortLog.textbook_id, func.sum(models.EffortLog.points))
        .where(
            models.EffortLog.user_id == user_id,
            models.EffortLog.textbook_id.isnot(None),
        )
        .group_by(models.EffortLog.textbook_id)
    )
    results = db.execute(stmt).all()
    return {textbook_id: total for textbook_id, total in results}


# --- Discovery Source CRUD ---


def add_discovery_source(
    db: Session,
    paper_id: int,
    source_type: models.DiscoverySourceType,
    source_arxiv_id: str | None = None,
    source_text: str | None = None,
    user_id: int = DEFAULT_USER_ID,
) -> models.DiscoverySource | None:
    """Add a discovery source to a paper."""
    # Verify paper exists and belongs to user
    paper = get_paper(db, paper_id, user_id)
    if not paper:
        return None

    # If source is a paper, try to find it in our system
    source_paper_id = None
    if source_type == models.DiscoverySourceType.PAPER and source_arxiv_id:
        # Look for paper with this arxiv_id in our system
        stmt = select(models.Paper).where(
            models.Paper.user_id == user_id,
            models.Paper.arxiv_id == source_arxiv_id,
        )
        source_paper = db.scalar(stmt)
        if source_paper:
            source_paper_id = source_paper.id

    discovery_source = models.DiscoverySource(
        paper_id=paper_id,
        source_type=source_type,
        source_arxiv_id=source_arxiv_id,
        source_paper_id=source_paper_id,
        source_text=source_text,
    )
    db.add(discovery_source)
    db.commit()
    db.refresh(discovery_source)
    return discovery_source


def get_discovery_sources(
    db: Session,
    paper_id: int,
    user_id: int = DEFAULT_USER_ID,
) -> Sequence[models.DiscoverySource]:
    """Get all discovery sources for a paper."""
    # Verify paper belongs to user
    paper = get_paper(db, paper_id, user_id)
    if not paper:
        return []

    stmt = (
        select(models.DiscoverySource)
        .where(models.DiscoverySource.paper_id == paper_id)
        .order_by(models.DiscoverySource.created_at.desc())
    )
    return db.scalars(stmt).all()


def delete_discovery_source(
    db: Session,
    source_id: int,
    user_id: int = DEFAULT_USER_ID,
) -> bool:
    """Delete a discovery source."""
    stmt = (
        select(models.DiscoverySource)
        .join(models.Paper)
        .where(
            models.DiscoverySource.id == source_id,
            models.Paper.user_id == user_id,
        )
    )
    source = db.scalar(stmt)
    if not source:
        return False

    db.delete(source)
    db.commit()
    return True


def get_discovery_source_count(
    db: Session,
    paper_id: int,
) -> int:
    """Get count of discovery sources for a paper."""
    stmt = select(func.count(models.DiscoverySource.id)).where(
        models.DiscoverySource.paper_id == paper_id
    )
    return db.scalar(stmt) or 0


def get_all_papers_source_counts(
    db: Session,
    user_id: int = DEFAULT_USER_ID,
) -> dict[int, int]:
    """Get source counts for all papers as a dict {paper_id: count}."""
    stmt = (
        select(models.DiscoverySource.paper_id, func.count(models.DiscoverySource.id))
        .join(
            models.Paper,
            models.DiscoverySource.paper_id == models.Paper.id,
        )
        .where(models.Paper.user_id == user_id)
        .group_by(models.DiscoverySource.paper_id)
    )
    results = db.execute(stmt).all()
    return {paper_id: count for paper_id, count in results}


# --- Textbook CRUD ---


def get_textbooks(
    db: Session,
    user_id: int = DEFAULT_USER_ID,
    status: models.TextbookStatus | None = None,
    category_id: int | None = None,
    sort_by: str = "manual",
) -> Sequence[models.Textbook]:
    """Get textbooks with optional filtering and sorting."""
    stmt = (
        select(models.Textbook)
        .where(models.Textbook.user_id == user_id)
        .options(joinedload(models.Textbook.category))
    )

    # Apply sorting
    if sort_by == "likes":
        stmt = stmt.order_by(
            models.Textbook.likes.desc(), models.Textbook.created_at.desc()
        )
    elif sort_by == "added":
        stmt = stmt.order_by(models.Textbook.created_at.desc())
    elif sort_by == "read":
        stmt = stmt.order_by(
            models.Textbook.read_at.desc().nulls_last(),
            models.Textbook.created_at.desc(),
        )
    else:  # "manual" or default
        stmt = stmt.order_by(models.Textbook.order_index)

    if status:
        stmt = stmt.where(models.Textbook.status == status)
    if category_id is not None:
        stmt = stmt.where(models.Textbook.category_id == category_id)

    return db.scalars(stmt).unique().all()


def get_textbook(
    db: Session, textbook_id: int, user_id: int = DEFAULT_USER_ID
) -> models.Textbook | None:
    """Get a textbook by ID."""
    stmt = (
        select(models.Textbook)
        .where(models.Textbook.id == textbook_id, models.Textbook.user_id == user_id)
        .options(joinedload(models.Textbook.category))
    )
    return db.scalar(stmt)


def create_textbook(
    db: Session, data: schemas.TextbookCreate, user_id: int = DEFAULT_USER_ID
) -> models.Textbook:
    """Create a new textbook."""
    import datetime as dt

    # Get min order_index across ALL textbooks with this status (ignoring category)
    # This ensures new textbooks always appear at the top when viewing all textbooks
    stmt = select(func.min(models.Textbook.order_index)).where(
        models.Textbook.user_id == user_id,
        models.Textbook.status == data.status,
    )
    min_order = db.scalar(stmt)
    new_order = (min_order - 10) if min_order is not None else 0

    textbook = models.Textbook(
        user_id=user_id,
        title=data.title,
        authors=data.authors,
        publisher=data.publisher,
        year=data.year,
        isbn=data.isbn,
        edition=data.edition,
        url=data.url,
        status=data.status,
        category_id=data.category_id,
        order_index=new_order,
        notes=data.notes,
    )
    db.add(textbook)
    db.commit()
    db.refresh(textbook)
    return get_textbook(db, textbook.id, user_id)  # type: ignore


def update_textbook(
    db: Session,
    textbook_id: int,
    data: schemas.TextbookUpdate,
    user_id: int = DEFAULT_USER_ID,
) -> models.Textbook | None:
    """Update a textbook."""
    import datetime as dt

    textbook = get_textbook(db, textbook_id, user_id)
    if not textbook:
        return None

    old_status = textbook.status

    # Update fields that are set
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(textbook, field, value)

    # Set read_at if transitioning to READ
    if (
        data.status == models.TextbookStatus.READ
        and old_status != models.TextbookStatus.READ
    ):
        textbook.read_at = dt.datetime.now(dt.timezone.utc)
    elif data.status and data.status != models.TextbookStatus.READ:
        textbook.read_at = None

    db.commit()
    return get_textbook(db, textbook_id, user_id)


def delete_textbook(
    db: Session, textbook_id: int, user_id: int = DEFAULT_USER_ID
) -> bool:
    """Delete a textbook. Returns True if deleted."""
    textbook = get_textbook(db, textbook_id, user_id)
    if not textbook:
        return False
    db.delete(textbook)
    db.commit()
    return True


def like_textbook(
    db: Session, textbook_id: int, user_id: int = DEFAULT_USER_ID
) -> int | None:
    """Increment likes for a textbook. Returns new like count or None if not found."""
    textbook = get_textbook(db, textbook_id, user_id)
    if not textbook:
        return None
    textbook.likes += 1
    db.commit()
    return textbook.likes


def reorder_textbooks(
    db: Session,
    status: models.TextbookStatus,
    textbook_ids: list[int],
    user_id: int = DEFAULT_USER_ID,
    category_id: int | None = None,
) -> bool:
    """Reorder textbooks by setting order_index sequentially."""
    stmt = select(models.Textbook).where(
        models.Textbook.id.in_(textbook_ids),
        models.Textbook.user_id == user_id,
        models.Textbook.status == status,
    )
    if category_id is not None:
        stmt = stmt.where(models.Textbook.category_id == category_id)

    textbooks = {t.id: t for t in db.scalars(stmt).all()}

    if len(textbooks) != len(textbook_ids):
        return False

    for idx, textbook_id in enumerate(textbook_ids):
        textbooks[textbook_id].order_index = (idx + 1) * 10

    db.commit()
    return True
