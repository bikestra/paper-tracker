from __future__ import annotations

import datetime as dt
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from .models import DiscoverySourceType, PaperSource, PaperStatus, TextbookStatus


# --- Category schemas ---


class CategoryBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


class CategoryCreate(CategoryBase):
    pass


class CategoryUpdate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


class Category(CategoryBase):
    id: int
    user_id: int
    created_at: dt.datetime

    model_config = ConfigDict(from_attributes=True)


# --- Author schemas ---


class AuthorBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    orcid: Optional[str] = None
    arxiv_id: Optional[str] = None


class AuthorCreate(AuthorBase):
    pass


class Author(AuthorBase):
    id: int
    user_id: int
    created_at: dt.datetime
    paper_count: int = 0  # Computed field for listing

    model_config = ConfigDict(from_attributes=True)


class AuthorBrief(BaseModel):
    """Brief author info for paper listings."""

    id: int
    name: str

    model_config = ConfigDict(from_attributes=True)


# --- Paper schemas ---


class PaperBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    abstract: Optional[str] = None
    url: Optional[str] = None
    pdf_url: Optional[str] = None
    venue_year: Optional[str] = Field(None, max_length=100)
    status: PaperStatus = PaperStatus.PLANNED
    category_id: Optional[int] = None
    notes: Optional[str] = None


class PaperCreate(PaperBase):
    """Schema for creating a paper."""

    source: PaperSource = PaperSource.MANUAL
    authors: list[str] = Field(default_factory=list)  # Author names

    # arXiv fields (populated from fetch)
    arxiv_id: Optional[str] = None
    arxiv_version: Optional[str] = None
    arxiv_primary_category: Optional[str] = None
    arxiv_published_at: Optional[dt.datetime] = None
    arxiv_updated_at: Optional[dt.datetime] = None
    doi: Optional[str] = None
    journal_ref: Optional[str] = None
    citation_key: Optional[str] = None


class PaperUpdate(BaseModel):
    """Schema for updating a paper. All fields optional."""

    title: Optional[str] = Field(None, min_length=1, max_length=500)
    abstract: Optional[str] = None
    url: Optional[str] = None
    pdf_url: Optional[str] = None
    venue_year: Optional[str] = Field(None, max_length=100)
    status: Optional[PaperStatus] = None
    category_id: Optional[int] = None
    notes: Optional[str] = None
    authors: Optional[list[str]] = None  # If provided, replaces authors

    # arXiv fields
    arxiv_id: Optional[str] = None
    arxiv_version: Optional[str] = None
    arxiv_primary_category: Optional[str] = None
    arxiv_published_at: Optional[dt.datetime] = None
    arxiv_updated_at: Optional[dt.datetime] = None
    doi: Optional[str] = None
    journal_ref: Optional[str] = None
    citation_key: Optional[str] = None


class Paper(PaperBase):
    """Full paper response schema."""

    id: int
    user_id: int
    source: PaperSource
    order_index: int
    arxiv_id: Optional[str] = None
    arxiv_version: Optional[str] = None
    arxiv_primary_category: Optional[str] = None
    arxiv_published_at: Optional[dt.datetime] = None
    arxiv_updated_at: Optional[dt.datetime] = None
    doi: Optional[str] = None
    journal_ref: Optional[str] = None
    citation_key: Optional[str] = None
    created_at: dt.datetime
    updated_at: Optional[dt.datetime] = None
    read_at: Optional[dt.datetime] = None
    authors: list[AuthorBrief] = Field(default_factory=list)
    category: Optional[Category] = None

    model_config = ConfigDict(from_attributes=True)


class PaperBrief(BaseModel):
    """Brief paper info for listings."""

    id: int
    title: str
    status: PaperStatus
    source: PaperSource
    url: Optional[str] = None
    arxiv_id: Optional[str] = None
    venue_year: Optional[str] = None
    order_index: int
    authors: list[AuthorBrief] = Field(default_factory=list)
    category: Optional[Category] = None

    model_config = ConfigDict(from_attributes=True)


# --- arXiv schemas ---


class ArxivFetchRequest(BaseModel):
    """Request to fetch arXiv metadata."""

    url_or_id: str = Field(..., min_length=1)


class ArxivFetchResponse(BaseModel):
    """Response from arXiv metadata fetch."""

    arxiv_id: str
    arxiv_version: Optional[str] = None
    title: str
    abstract: str
    authors: list[str]  # Author names
    url: str
    pdf_url: str
    published_at: dt.datetime
    updated_at: dt.datetime
    primary_category: str
    doi: Optional[str] = None
    journal_ref: Optional[str] = None


# --- Reorder schemas ---


class ReorderRequest(BaseModel):
    """Request to reorder papers."""

    status: PaperStatus
    category_id: Optional[int] = None
    paper_ids: list[int] = Field(..., min_length=1)


# --- User schemas ---


class User(BaseModel):
    id: int
    email: Optional[str] = None
    created_at: dt.datetime

    model_config = ConfigDict(from_attributes=True)


# --- Effort Log schemas ---


class EffortLogCreate(BaseModel):
    """Create a new effort log entry."""

    paper_id: int
    points: int = Field(default=1, ge=1)
    note: Optional[str] = None


class EffortLog(BaseModel):
    """Effort log response schema."""

    id: int
    user_id: int
    paper_id: int
    points: int
    note: Optional[str] = None
    created_at: dt.datetime

    model_config = ConfigDict(from_attributes=True)


class EffortLogWithPaper(EffortLog):
    """Effort log with paper details for display."""

    paper_title: str
    paper_status: PaperStatus


# --- Discovery Source schemas ---


class DiscoverySourceCreate(BaseModel):
    """Create a new discovery source."""

    source_type: DiscoverySourceType
    source_arxiv_id: Optional[str] = None  # For PAPER type
    source_text: Optional[str] = None  # For TEXT type


class DiscoverySource(BaseModel):
    """Discovery source response schema."""

    id: int
    paper_id: int
    source_type: DiscoverySourceType
    source_arxiv_id: Optional[str] = None
    source_paper_id: Optional[int] = None
    source_text: Optional[str] = None
    created_at: dt.datetime

    model_config = ConfigDict(from_attributes=True)


# --- Textbook schemas ---


class TextbookBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    authors: Optional[str] = Field(None, max_length=500)
    publisher: Optional[str] = Field(None, max_length=200)
    year: Optional[int] = None
    isbn: Optional[str] = Field(None, max_length=20)
    edition: Optional[str] = Field(None, max_length=50)
    url: Optional[str] = None
    status: TextbookStatus = TextbookStatus.PLANNED
    category_id: Optional[int] = None
    notes: Optional[str] = None


class TextbookCreate(TextbookBase):
    """Schema for creating a textbook."""

    pass


class TextbookUpdate(BaseModel):
    """Schema for updating a textbook. All fields optional."""

    title: Optional[str] = Field(None, min_length=1, max_length=500)
    authors: Optional[str] = Field(None, max_length=500)
    publisher: Optional[str] = Field(None, max_length=200)
    year: Optional[int] = None
    isbn: Optional[str] = Field(None, max_length=20)
    edition: Optional[str] = Field(None, max_length=50)
    url: Optional[str] = None
    status: Optional[TextbookStatus] = None
    category_id: Optional[int] = None
    notes: Optional[str] = None


class Textbook(TextbookBase):
    """Full textbook response schema."""

    id: int
    user_id: int
    order_index: int
    likes: int = 0
    created_at: dt.datetime
    updated_at: Optional[dt.datetime] = None
    read_at: Optional[dt.datetime] = None
    category: Optional[Category] = None

    model_config = ConfigDict(from_attributes=True)


class TextbookReorderRequest(BaseModel):
    """Request to reorder textbooks."""

    status: TextbookStatus
    category_id: Optional[int] = None
    textbook_ids: list[int] = Field(..., min_length=1)


# --- Misc ---


class Healthcheck(BaseModel):
    message: str
