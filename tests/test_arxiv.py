"""Tests for arXiv parsing and fetching."""

from __future__ import annotations

import pytest

from app.arxiv import (
    ArxivParseError,
    normalize_author_name,
    parse_arxiv_input,
)


class TestNormalizeAuthorName:
    """Tests for author name normalization."""

    def test_simple_name(self):
        assert normalize_author_name("John Smith") == "john_smith"

    def test_name_with_accents(self):
        assert normalize_author_name("José García") == "jose_garcia"

    def test_name_with_hyphen(self):
        assert normalize_author_name("Mary-Jane Watson") == "mary-jane_watson"

    def test_name_with_punctuation(self):
        assert normalize_author_name("John O'Brien") == "john_obrien"

    def test_name_with_extra_spaces(self):
        assert normalize_author_name("  John   Smith  ") == "john_smith"

    def test_asian_name(self):
        # Romanized Asian names should work fine
        assert normalize_author_name("Yann LeCun") == "yann_lecun"


class TestParseArxivInput:
    """Tests for parsing arXiv URLs and IDs."""

    # New format IDs
    def test_new_format_id_no_version(self):
        arxiv_id, version = parse_arxiv_input("2301.01234")
        assert arxiv_id == "2301.01234"
        assert version is None

    def test_new_format_id_with_version(self):
        arxiv_id, version = parse_arxiv_input("2301.01234v2")
        assert arxiv_id == "2301.01234"
        assert version == "v2"

    def test_new_format_5digit(self):
        arxiv_id, version = parse_arxiv_input("2301.12345")
        assert arxiv_id == "2301.12345"
        assert version is None

    # Old format IDs
    def test_old_format_id(self):
        arxiv_id, version = parse_arxiv_input("cs/9901001")
        assert arxiv_id == "cs/9901001"
        assert version is None

    def test_old_format_id_with_version(self):
        arxiv_id, version = parse_arxiv_input("hep-th/9901001v3")
        assert arxiv_id == "hep-th/9901001"
        assert version == "v3"

    # URL parsing - abs URLs
    def test_abs_url_new_format(self):
        arxiv_id, version = parse_arxiv_input("https://arxiv.org/abs/2301.01234")
        assert arxiv_id == "2301.01234"
        assert version is None

    def test_abs_url_with_version(self):
        arxiv_id, version = parse_arxiv_input("https://arxiv.org/abs/2301.01234v2")
        assert arxiv_id == "2301.01234"
        assert version == "v2"

    def test_abs_url_old_format(self):
        arxiv_id, version = parse_arxiv_input("https://arxiv.org/abs/cs/9901001")
        assert arxiv_id == "cs/9901001"
        assert version is None

    # URL parsing - PDF URLs
    def test_pdf_url(self):
        arxiv_id, version = parse_arxiv_input("https://arxiv.org/pdf/2301.01234.pdf")
        assert arxiv_id == "2301.01234"
        assert version is None

    def test_pdf_url_no_extension(self):
        arxiv_id, version = parse_arxiv_input("https://arxiv.org/pdf/2301.01234")
        assert arxiv_id == "2301.01234"
        assert version is None

    # ar5iv URLs
    def test_ar5iv_abs_url(self):
        arxiv_id, version = parse_arxiv_input("https://ar5iv.org/abs/2301.01234")
        assert arxiv_id == "2301.01234"
        assert version is None

    def test_ar5iv_html_url(self):
        arxiv_id, version = parse_arxiv_input("https://ar5iv.org/html/2301.01234")
        assert arxiv_id == "2301.01234"
        assert version is None

    # Edge cases
    def test_whitespace_handling(self):
        arxiv_id, version = parse_arxiv_input("  2301.01234  ")
        assert arxiv_id == "2301.01234"
        assert version is None

    def test_invalid_id_raises(self):
        with pytest.raises(ArxivParseError):
            parse_arxiv_input("invalid")

    def test_empty_string_raises(self):
        with pytest.raises(ArxivParseError):
            parse_arxiv_input("")

    def test_random_url_raises(self):
        with pytest.raises(ArxivParseError):
            parse_arxiv_input("https://example.com/paper")


# Note: fetch_arxiv_metadata tests would require mocking the arxiv API
# or running as integration tests. We keep them minimal here.
class TestFetchArxivMetadata:
    """Integration tests for arXiv fetching (require network)."""

    @pytest.mark.slow
    def test_fetch_real_paper(self):
        """Test fetching a real paper (skip in CI)."""
        # This test requires network access and is slow
        # Run with: pytest -m slow
        from app.arxiv import fetch_arxiv_metadata

        metadata = fetch_arxiv_metadata("1706.03762")  # Attention is All You Need
        assert "attention" in metadata.title.lower()
        assert len(metadata.authors) > 0
        assert metadata.arxiv_id == "1706.03762"
