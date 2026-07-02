"""OpenReview metadata parsing and fetching utilities."""

from __future__ import annotations

import re
from dataclasses import dataclass

import httpx


class OpenReviewError(Exception):
    """Base exception for OpenReview-related errors."""

    pass


class OpenReviewParseError(OpenReviewError):
    """Error parsing OpenReview URL or ID."""

    pass


class OpenReviewFetchError(OpenReviewError):
    """Error fetching metadata from OpenReview API."""

    pass


@dataclass
class OpenReviewMetadata:
    """Metadata fetched from OpenReview."""

    openreview_id: str
    title: str
    abstract: str
    authors: list[str]
    url: str
    pdf_url: str
    venue: str | None


OPENREVIEW_URL_PATTERNS = [
    re.compile(r"openreview\.net/forum\?id=([a-zA-Z0-9_-]+)"),
    re.compile(r"openreview\.net/pdf\?id=([a-zA-Z0-9_-]+)"),
]

OPENREVIEW_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")


def parse_openreview_input(url_or_id: str) -> str:
    """Parse an OpenReview URL or ID into the paper ID.

    Args:
        url_or_id: An OpenReview URL or ID string

    Returns:
        The OpenReview paper ID

    Raises:
        OpenReviewParseError: If input cannot be parsed as valid OpenReview identifier
    """
    url_or_id = url_or_id.strip()

    for pattern in OPENREVIEW_URL_PATTERNS:
        match = pattern.search(url_or_id)
        if match:
            return match.group(1)

    if OPENREVIEW_ID_PATTERN.match(url_or_id):
        return url_or_id

    raise OpenReviewParseError(f"Invalid OpenReview identifier: {url_or_id}")


def fetch_openreview_metadata(openreview_id: str) -> OpenReviewMetadata:
    """Fetch metadata for an OpenReview paper.

    Args:
        openreview_id: OpenReview paper ID

    Returns:
        OpenReviewMetadata with paper details

    Raises:
        OpenReviewFetchError: If paper not found or network error
    """
    api_url = f"https://api2.openreview.net/notes?id={openreview_id}"

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(api_url)

            if response.status_code == 404:
                raise OpenReviewFetchError(f"Paper not found: {openreview_id}")

            response.raise_for_status()
            data = response.json()

            notes = data.get("notes", [])
            if not notes:
                raise OpenReviewFetchError(f"Paper not found: {openreview_id}")

            note = notes[0]
            content = note.get("content", {})

            def get_value(field):
                """Extract value from OpenReview content field (handles dict or direct value)."""
                val = content.get(field)
                if val is None:
                    return None
                if isinstance(val, dict):
                    return val.get("value")
                return val

            title = get_value("title") or "Untitled"
            abstract = get_value("abstract") or ""
            authors = get_value("authors") or []
            venue = get_value("venue") or get_value("venueid")

            if isinstance(authors, str):
                authors = [authors]

            forum_id = note.get("forum", openreview_id)

            return OpenReviewMetadata(
                openreview_id=openreview_id,
                title=title.replace("\n", " ").strip(),
                abstract=abstract.strip(),
                authors=authors,
                url=f"https://openreview.net/forum?id={forum_id}",
                pdf_url=f"https://openreview.net/pdf?id={forum_id}",
                venue=venue,
            )

    except httpx.HTTPStatusError as e:
        raise OpenReviewFetchError(f"HTTP error fetching OpenReview metadata: {e}")
    except httpx.RequestError as e:
        raise OpenReviewFetchError(f"Network error fetching OpenReview metadata: {e}")
    except Exception as e:
        if isinstance(e, OpenReviewFetchError):
            raise
        raise OpenReviewFetchError(f"Failed to fetch OpenReview metadata: {e}")
