"""OpenReview metadata parsing and fetching utilities."""

from __future__ import annotations

import re
import time
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


def _fetch_from_semantic_scholar(openreview_id: str) -> OpenReviewMetadata:
    """Fetch metadata from Semantic Scholar as fallback."""
    api_url = f"https://api.semanticscholar.org/graph/v1/paper/OPENREVIEW:{openreview_id}"
    params = {"fields": "title,abstract,authors,venue,year"}
    headers = {"User-Agent": "PaperTracker/1.0 (Academic paper tracking tool)"}

    with httpx.Client(timeout=30.0, headers=headers) as client:
        for attempt in range(3):
            response = client.get(api_url, params=params)

            if response.status_code == 429:
                if attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                raise OpenReviewFetchError(
                    "Semantic Scholar rate limit exceeded. Please try again later."
                )
            break

        if response.status_code == 404:
            raise OpenReviewFetchError(
                f"Paper not found in Semantic Scholar: {openreview_id}"
            )

        response.raise_for_status()
        data = response.json()

        title = data.get("title", "Untitled")
        abstract = data.get("abstract", "") or ""
        authors = [a.get("name", "") for a in data.get("authors", [])]
        venue = data.get("venue")
        year = data.get("year")

        if venue and year:
            venue = f"{venue} {year}"
        elif year:
            venue = str(year)

        return OpenReviewMetadata(
            openreview_id=openreview_id,
            title=title.replace("\n", " ").strip(),
            abstract=abstract.strip(),
            authors=authors,
            url=f"https://openreview.net/forum?id={openreview_id}",
            pdf_url=f"https://openreview.net/pdf?id={openreview_id}",
            venue=venue,
        )


def _fetch_from_openreview_api(openreview_id: str) -> OpenReviewMetadata:
    """Fetch metadata directly from OpenReview API."""
    api_url = f"https://api2.openreview.net/notes?id={openreview_id}"

    with httpx.Client(timeout=30.0) as client:
        response = client.get(api_url)

        if response.status_code == 404:
            raise OpenReviewFetchError(f"Paper not found: {openreview_id}")
        if response.status_code == 403:
            raise OpenReviewFetchError("OpenReview API requires verification")

        response.raise_for_status()
        data = response.json()

        notes = data.get("notes", [])
        if not notes:
            raise OpenReviewFetchError(f"Paper not found: {openreview_id}")

        note = notes[0]
        content = note.get("content", {})

        def get_value(field):
            """Extract value from OpenReview content field."""
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


def fetch_openreview_metadata(openreview_id: str) -> OpenReviewMetadata:
    """Fetch metadata for an OpenReview paper.

    Tries OpenReview API first, falls back to Semantic Scholar if blocked.

    Args:
        openreview_id: OpenReview paper ID

    Returns:
        OpenReviewMetadata with paper details

    Raises:
        OpenReviewFetchError: If paper not found or network error
    """
    try:
        return _fetch_from_openreview_api(openreview_id)
    except OpenReviewFetchError as e:
        if "requires verification" in str(e):
            try:
                return _fetch_from_semantic_scholar(openreview_id)
            except Exception as ss_error:
                raise OpenReviewFetchError(
                    f"OpenReview API blocked and Semantic Scholar fallback failed: {ss_error}"
                )
        raise
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 403:
            try:
                return _fetch_from_semantic_scholar(openreview_id)
            except Exception as ss_error:
                raise OpenReviewFetchError(
                    f"OpenReview API blocked and Semantic Scholar fallback failed: {ss_error}"
                )
        raise OpenReviewFetchError(f"HTTP error fetching OpenReview metadata: {e}")
    except httpx.RequestError as e:
        raise OpenReviewFetchError(f"Network error fetching OpenReview metadata: {e}")
    except Exception as e:
        if isinstance(e, OpenReviewFetchError):
            raise
        raise OpenReviewFetchError(f"Failed to fetch OpenReview metadata: {e}")
