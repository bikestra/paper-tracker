"""Open Library API integration for fetching book metadata."""

from __future__ import annotations

import re
from dataclasses import dataclass

import httpx


class OpenLibraryError(Exception):
    """Error fetching from Open Library."""

    pass


@dataclass
class BookMetadata:
    """Book metadata from Open Library."""

    title: str
    authors: str | None
    publisher: str | None
    year: int | None
    isbn: str | None
    url: str | None


def normalize_isbn(isbn: str) -> str:
    """Remove hyphens and spaces from ISBN."""
    return re.sub(r"[-\s]", "", isbn.strip())


def fetch_book_by_isbn(isbn: str) -> BookMetadata:
    """Fetch book metadata from Open Library by ISBN.

    Args:
        isbn: ISBN-10 or ISBN-13 (with or without hyphens)

    Returns:
        BookMetadata with book details

    Raises:
        OpenLibraryError: If book not found or API error
    """
    isbn = normalize_isbn(isbn)

    if not isbn:
        raise OpenLibraryError("ISBN is required")

    # Validate ISBN format (10 or 13 digits)
    if not re.match(r"^\d{10}(\d{3})?$", isbn.replace("X", "0")):
        raise OpenLibraryError(f"Invalid ISBN format: {isbn}")

    try:
        # Use Open Library Books API
        url = f"https://openlibrary.org/api/books?bibkeys=ISBN:{isbn}&format=json&jscmd=data"
        response = httpx.get(url, timeout=10.0)
        response.raise_for_status()

        data = response.json()
        key = f"ISBN:{isbn}"

        if key not in data:
            raise OpenLibraryError(f"Book not found for ISBN: {isbn}")

        book = data[key]

        # Extract authors
        authors = None
        if "authors" in book:
            authors = ", ".join(a.get("name", "") for a in book["authors"])

        # Extract publisher
        publisher = None
        if "publishers" in book and book["publishers"]:
            publisher = book["publishers"][0].get("name")

        # Extract year
        year = None
        if "publish_date" in book:
            # Try to extract year from publish_date (various formats)
            match = re.search(r"\b(19|20)\d{2}\b", book["publish_date"])
            if match:
                year = int(match.group())

        # Get URL
        book_url = book.get("url")

        return BookMetadata(
            title=book.get("title", "Unknown Title"),
            authors=authors,
            publisher=publisher,
            year=year,
            isbn=isbn,
            url=book_url,
        )

    except httpx.HTTPError as e:
        raise OpenLibraryError(f"Failed to fetch book: {e}") from e
    except (KeyError, ValueError) as e:
        raise OpenLibraryError(f"Failed to parse response: {e}") from e
