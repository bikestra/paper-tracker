"""arXiv metadata parsing and fetching utilities."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime

import arxiv


class ArxivError(Exception):
    """Base exception for arXiv-related errors."""

    pass


class ArxivParseError(ArxivError):
    """Error parsing arXiv URL or ID."""

    pass


class ArxivFetchError(ArxivError):
    """Error fetching metadata from arXiv API."""

    pass


@dataclass
class AuthorInfo:
    """Author information from arXiv."""

    name: str
    arxiv_id: str | None = None  # normalized name slug


@dataclass
class ArxivMetadata:
    """Metadata fetched from arXiv."""

    arxiv_id: str
    arxiv_version: str | None
    title: str
    abstract: str
    authors: list[AuthorInfo]
    url: str
    pdf_url: str
    published_at: datetime
    updated_at: datetime
    primary_category: str
    doi: str | None
    journal_ref: str | None


# Regex patterns for arXiv IDs
# New format: YYMM.NNNNN (with optional version)
NEW_ID_PATTERN = re.compile(r"^(\d{4}\.\d{4,5})(v\d+)?$")
# Old format: archive/YYMMNNN or archive.subject/YYMMNNN
OLD_ID_PATTERN = re.compile(r"^([a-z-]+(?:\.[a-z-]+)?/\d{7})(v\d+)?$", re.IGNORECASE)

# URL patterns
ARXIV_URL_PATTERNS = [
    # https://arxiv.org/abs/2301.01234 or https://arxiv.org/abs/2301.01234v2
    re.compile(r"arxiv\.org/abs/([a-z-]*/?[\d.]+v?\d*)"),
    # https://arxiv.org/pdf/2301.01234.pdf
    re.compile(r"arxiv\.org/pdf/([a-z-]*/?[\d.]+v?\d*)(?:\.pdf)?"),
    # https://ar5iv.org/abs/2301.01234
    re.compile(r"ar5iv\.org/(?:abs|html)/([a-z-]*/?[\d.]+v?\d*)"),
]


def normalize_author_name(name: str) -> str:
    """Normalize author name to a slug for arxiv_id field.

    - Lowercase
    - Remove accents/diacritics
    - Remove punctuation except hyphens
    - Replace spaces with underscores
    """
    # Normalize unicode to decomposed form and remove accents
    normalized = unicodedata.normalize("NFD", name)
    ascii_name = "".join(c for c in normalized if unicodedata.category(c) != "Mn")

    # Lowercase
    ascii_name = ascii_name.lower()

    # Remove punctuation except hyphens, replace spaces with underscores
    slug = re.sub(r"[^\w\s-]", "", ascii_name)
    slug = re.sub(r"\s+", "_", slug.strip())

    return slug


def parse_arxiv_input(url_or_id: str) -> tuple[str, str | None]:
    """Parse an arXiv URL or ID into (arxiv_id, version).

    Args:
        url_or_id: An arXiv URL or ID string

    Returns:
        Tuple of (arxiv_id without version, version string or None)

    Raises:
        ArxivParseError: If input cannot be parsed as valid arXiv identifier
    """
    url_or_id = url_or_id.strip()

    # Try URL patterns first
    for pattern in ARXIV_URL_PATTERNS:
        match = pattern.search(url_or_id)
        if match:
            extracted = match.group(1)
            # Remove .pdf suffix if present
            extracted = extracted.rstrip(".pdf")
            return _parse_id_with_version(extracted)

    # Try direct ID parsing
    return _parse_id_with_version(url_or_id)


def _parse_id_with_version(id_str: str) -> tuple[str, str | None]:
    """Parse ID string that may contain version suffix."""
    id_str = id_str.strip()

    # Try new format
    match = NEW_ID_PATTERN.match(id_str)
    if match:
        base_id = match.group(1)
        version = match.group(2)  # e.g., "v2" or None
        return base_id, version

    # Try old format
    match = OLD_ID_PATTERN.match(id_str)
    if match:
        base_id = match.group(1)
        version = match.group(2)
        return base_id, version

    raise ArxivParseError(f"Invalid arXiv identifier: {id_str}")


def fetch_arxiv_metadata(arxiv_id: str) -> ArxivMetadata:
    """Fetch metadata for an arXiv paper.

    Args:
        arxiv_id: arXiv ID (without version suffix)

    Returns:
        ArxivMetadata with paper details

    Raises:
        ArxivFetchError: If paper not found or network error
    """
    client = arxiv.Client()

    try:
        search = arxiv.Search(id_list=[arxiv_id])
        results = list(client.results(search))

        if not results:
            raise ArxivFetchError(f"Paper not found: {arxiv_id}")

        paper = results[0]

        # Extract version from entry_id URL
        version = None
        if paper.entry_id:
            version_match = re.search(r"v(\d+)$", paper.entry_id)
            if version_match:
                version = f"v{version_match.group(1)}"

        # Process authors
        authors = []
        for author in paper.authors:
            name = author.name
            slug = normalize_author_name(name)
            authors.append(AuthorInfo(name=name, arxiv_id=slug))

        return ArxivMetadata(
            arxiv_id=arxiv_id,
            arxiv_version=version,
            title=paper.title.replace("\n", " ").strip(),
            abstract=paper.summary.strip(),
            authors=authors,
            url=paper.entry_id,
            pdf_url=paper.pdf_url,
            published_at=paper.published,
            updated_at=paper.updated,
            primary_category=paper.primary_category,
            doi=paper.doi,
            journal_ref=paper.journal_ref,
        )

    except arxiv.UnexpectedEmptyPageError:
        raise ArxivFetchError(f"Paper not found: {arxiv_id}")
    except Exception as e:
        if isinstance(e, ArxivFetchError):
            raise
        raise ArxivFetchError(f"Failed to fetch arXiv metadata: {e}")
