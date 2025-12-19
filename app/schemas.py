from __future__ import annotations

import datetime as dt
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from .models import PaperStatus


class CategoryBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


class Category(CategoryBase):
    id: int
    user_id: int
    created_at: dt.datetime

    model_config = ConfigDict(from_attributes=True)


class PaperBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    url: Optional[HttpUrl] = None
    authors: list[str] = Field(default_factory=list)
    venue_year: Optional[str] = Field(None, max_length=100)
    status: PaperStatus = PaperStatus.PLANNED
    category_id: Optional[int] = None
    notes: Optional[str] = None


class Paper(PaperBase):
    id: int
    user_id: int
    order_index: int
    created_at: dt.datetime
    updated_at: Optional[dt.datetime] = None
    read_at: Optional[dt.datetime] = None

    model_config = ConfigDict(from_attributes=True)


class Author(BaseModel):
    id: int
    user_id: int
    name: str
    orcid: Optional[str] = None
    created_at: dt.datetime

    model_config = ConfigDict(from_attributes=True)


class User(BaseModel):
    id: int
    email: Optional[str] = None
    created_at: dt.datetime

    model_config = ConfigDict(from_attributes=True)


class Healthcheck(BaseModel):
    message: str
