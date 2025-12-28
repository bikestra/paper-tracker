from __future__ import annotations

import datetime as dt
from enum import Enum

from sqlalchemy import (
    Column,
    DateTime,
    Enum as SqlEnum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class PaperStatus(str, Enum):
    PLANNED = "PLANNED"
    READING = "READING"
    READ = "READ"


class PaperSource(str, Enum):
    ARXIV = "ARXIV"
    URL = "URL"
    MANUAL = "MANUAL"


class DiscoverySourceType(str, Enum):
    """Type of discovery source."""

    PAPER = "PAPER"  # Discovered from another paper
    TEXT = "TEXT"  # Free text description


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    categories: Mapped[list[Category]] = relationship(
        "Category", back_populates="user", cascade="all, delete-orphan"
    )
    papers: Mapped[list[Paper]] = relationship(
        "Paper", back_populates="user", cascade="all, delete-orphan"
    )
    authors: Mapped[list[Author]] = relationship(
        "Author", back_populates="user", cascade="all, delete-orphan"
    )
    effort_logs: Mapped[list[EffortLog]] = relationship(
        "EffortLog", back_populates="user", cascade="all, delete-orphan"
    )
    textbooks: Mapped[list[Textbook]] = relationship(
        "Textbook", back_populates="user", cascade="all, delete-orphan"
    )


class Category(Base):
    __tablename__ = "categories"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_category_user_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    user: Mapped[User] = relationship("User", back_populates="categories")
    papers: Mapped[list[Paper]] = relationship(
        "Paper", back_populates="category", cascade="all, delete-orphan"
    )


class Paper(Base):
    __tablename__ = "papers"
    __table_args__ = (
        UniqueConstraint("user_id", "arxiv_id", name="uq_paper_user_arxiv_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    abstract: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    pdf_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source: Mapped[PaperSource] = mapped_column(
        SqlEnum(PaperSource), default=PaperSource.MANUAL, nullable=False
    )
    status: Mapped[PaperStatus] = mapped_column(
        SqlEnum(PaperStatus), default=PaperStatus.PLANNED, nullable=False
    )
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id"), nullable=True, index=True
    )
    order_index: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    likes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # arXiv-specific fields
    arxiv_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    arxiv_version: Mapped[str | None] = mapped_column(String(10), nullable=True)
    arxiv_primary_category: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )
    arxiv_published_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    arxiv_updated_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Additional metadata
    doi: Mapped[str | None] = mapped_column(String(100), nullable=True)
    journal_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    citation_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    venue_year: Mapped[str | None] = mapped_column(String(100), nullable=True)

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    read_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped[User] = relationship("User", back_populates="papers")
    category: Mapped[Category | None] = relationship(
        "Category", back_populates="papers"
    )
    author_links: Mapped[list[PaperAuthor]] = relationship(
        "PaperAuthor", back_populates="paper", cascade="all, delete-orphan"
    )
    authors: Mapped[list[Author]] = relationship(
        "Author",
        secondary="paper_authors",
        back_populates="papers",
        order_by="PaperAuthor.position",
        overlaps="author_links,paper_links",
    )
    effort_logs: Mapped[list[EffortLog]] = relationship(
        "EffortLog", back_populates="paper", cascade="all, delete-orphan"
    )
    discovery_sources: Mapped[list[DiscoverySource]] = relationship(
        "DiscoverySource",
        back_populates="paper",
        cascade="all, delete-orphan",
        foreign_keys="DiscoverySource.paper_id",
    )


class Author(Base):
    __tablename__ = "authors"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_author_user_name"),
        UniqueConstraint("user_id", "arxiv_id", name="uq_author_user_arxiv_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    orcid: Mapped[str | None] = mapped_column(String(50), nullable=True)
    arxiv_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    user: Mapped[User] = relationship("User", back_populates="authors")
    paper_links: Mapped[list[PaperAuthor]] = relationship(
        "PaperAuthor", back_populates="author", cascade="all, delete-orphan"
    )
    papers: Mapped[list[Paper]] = relationship(
        "Paper",
        secondary="paper_authors",
        back_populates="authors",
        overlaps="author_links,paper_links",
    )


class PaperAuthor(Base):
    __tablename__ = "paper_authors"
    __table_args__ = (
        UniqueConstraint("paper_id", "author_id", name="uq_paper_author"),
        UniqueConstraint("paper_id", "position", name="uq_paper_author_position"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    paper_id: Mapped[int] = mapped_column(
        ForeignKey("papers.id"), nullable=False, index=True
    )
    author_id: Mapped[int] = mapped_column(
        ForeignKey("authors.id"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    paper: Mapped[Paper] = relationship(
        "Paper", back_populates="author_links", overlaps="authors,papers"
    )
    author: Mapped[Author] = relationship(
        "Author", back_populates="paper_links", overlaps="authors,papers"
    )


class EffortLog(Base):
    """Log of effort/time spent on a paper or textbook."""

    __tablename__ = "effort_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    paper_id: Mapped[int | None] = mapped_column(
        ForeignKey("papers.id"), nullable=True, index=True
    )
    textbook_id: Mapped[int | None] = mapped_column(
        ForeignKey("textbooks.id"), nullable=True, index=True
    )
    points: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    user: Mapped[User] = relationship("User", back_populates="effort_logs")
    paper: Mapped[Paper | None] = relationship("Paper", back_populates="effort_logs")
    textbook: Mapped[Textbook | None] = relationship(
        "Textbook", back_populates="effort_logs"
    )


class DiscoverySource(Base):
    """How a paper was discovered (from another paper or a text description)."""

    __tablename__ = "discovery_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    paper_id: Mapped[int] = mapped_column(
        ForeignKey("papers.id"), nullable=False, index=True
    )
    source_type: Mapped[DiscoverySourceType] = mapped_column(
        SqlEnum(DiscoverySourceType), nullable=False
    )
    # If source_type is PAPER, this is the arXiv ID of the source paper
    source_arxiv_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # If source_type is PAPER and the source paper is in our system
    source_paper_id: Mapped[int | None] = mapped_column(
        ForeignKey("papers.id"), nullable=True, index=True
    )
    # If source_type is TEXT, this is the description
    source_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    paper: Mapped[Paper] = relationship(
        "Paper", foreign_keys=[paper_id], back_populates="discovery_sources"
    )
    source_paper: Mapped[Paper | None] = relationship(
        "Paper", foreign_keys=[source_paper_id]
    )


class TextbookStatus(str, Enum):
    PLANNED = "PLANNED"
    READING = "READING"
    READ = "READ"


class Textbook(Base):
    """Textbook tracking model."""

    __tablename__ = "textbooks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    authors: Mapped[str | None] = mapped_column(String(500), nullable=True)
    publisher: Mapped[str | None] = mapped_column(String(200), nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    isbn: Mapped[str | None] = mapped_column(String(20), nullable=True)
    edition: Mapped[str | None] = mapped_column(String(50), nullable=True)
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[TextbookStatus] = mapped_column(
        SqlEnum(TextbookStatus), default=TextbookStatus.PLANNED, nullable=False
    )
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id"), nullable=True, index=True
    )
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    likes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    read_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped[User] = relationship("User", back_populates="textbooks")
    category: Mapped[Category | None] = relationship("Category")
    effort_logs: Mapped[list[EffortLog]] = relationship(
        "EffortLog", back_populates="textbook", cascade="all, delete-orphan"
    )
