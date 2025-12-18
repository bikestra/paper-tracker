from __future__ import annotations

import datetime as dt
from enum import Enum

from sqlalchemy import Column, DateTime, Enum as SqlEnum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class PaperStatus(str, Enum):
    PLANNED = "PLANNED"
    READING = "READING"
    READ = "READ"


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


class Category(Base):
    __tablename__ = "categories"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_category_user_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
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

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    authors: Mapped[str | None] = mapped_column(Text, nullable=True)
    venue_year: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[PaperStatus] = mapped_column(
        SqlEnum(PaperStatus), default=PaperStatus.PLANNED, nullable=False
    )
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id"), nullable=True, index=True
    )
    order_index: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    read_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship("User", back_populates="papers")
    category: Mapped[Category | None] = relationship("Category", back_populates="papers")
