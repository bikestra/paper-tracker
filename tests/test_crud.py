"""Tests for CRUD operations."""

from __future__ import annotations

import pytest

from app import crud, models, schemas


class TestCategoryCRUD:
    """Tests for category CRUD operations."""

    def test_create_category(self, db_session):
        data = schemas.CategoryCreate(name="Machine Learning")
        category = crud.create_category(db_session, data)

        assert category.id is not None
        assert category.name == "Machine Learning"
        assert category.user_id == 1

    def test_get_categories(self, db_session):
        crud.create_category(db_session, schemas.CategoryCreate(name="ML"))
        crud.create_category(db_session, schemas.CategoryCreate(name="NLP"))

        categories = crud.get_categories(db_session)
        assert len(categories) == 2
        # Should be sorted by name
        assert categories[0].name == "ML"
        assert categories[1].name == "NLP"

    def test_update_category(self, db_session):
        category = crud.create_category(db_session, schemas.CategoryCreate(name="Old"))
        updated = crud.update_category(
            db_session, category.id, schemas.CategoryUpdate(name="New")
        )

        assert updated is not None
        assert updated.name == "New"

    def test_delete_category(self, db_session):
        category = crud.create_category(db_session, schemas.CategoryCreate(name="Test"))
        result = crud.delete_category(db_session, category.id)

        assert result is True
        assert crud.get_category(db_session, category.id) is None


class TestAuthorCRUD:
    """Tests for author CRUD operations."""

    def test_get_or_create_author_new(self, db_session):
        author = crud.get_or_create_author(db_session, "John Smith")
        db_session.commit()

        assert author.id is not None
        assert author.name == "John Smith"
        assert author.arxiv_id == "john_smith"

    def test_get_or_create_author_existing_by_arxiv_id(self, db_session):
        author1 = crud.get_or_create_author(db_session, "John Smith")
        db_session.commit()

        # Same normalized name should return same author
        author2 = crud.get_or_create_author(db_session, "John  Smith")  # Extra space
        db_session.commit()

        assert author1.id == author2.id

    def test_get_or_create_author_with_orcid(self, db_session):
        orcid = "0000-0002-1234-5678"
        author1 = crud.get_or_create_author(db_session, "John Smith", orcid=orcid)
        db_session.commit()

        # Different name but same ORCID should return same author
        author2 = crud.get_or_create_author(db_session, "J. Smith", orcid=orcid)
        db_session.commit()

        assert author1.id == author2.id

    def test_get_authors_with_paper_count(self, db_session):
        # Create an author with papers
        paper_data = schemas.PaperCreate(
            title="Test Paper",
            authors=["John Smith", "Jane Doe"],
        )
        crud.create_paper(db_session, paper_data)

        authors = crud.get_authors(db_session)
        assert len(authors) == 2

        # Both should have 1 paper
        for author in authors:
            assert author["paper_count"] == 1


class TestPaperCRUD:
    """Tests for paper CRUD operations."""

    def test_create_paper_basic(self, db_session):
        data = schemas.PaperCreate(title="Test Paper")
        paper = crud.create_paper(db_session, data)

        assert paper.id is not None
        assert paper.title == "Test Paper"
        assert paper.status == models.PaperStatus.PLANNED
        assert paper.source == models.PaperSource.MANUAL
        assert paper.order_index == 10

    def test_create_paper_with_authors(self, db_session):
        data = schemas.PaperCreate(
            title="Test Paper",
            authors=["Alice", "Bob", "Charlie"],
        )
        paper = crud.create_paper(db_session, data)

        assert len(paper.authors) == 3
        # Authors should be in order
        author_names = [a.name for a in paper.authors]
        assert author_names == ["Alice", "Bob", "Charlie"]

    def test_create_paper_with_arxiv_fields(self, db_session):
        data = schemas.PaperCreate(
            title="Attention Is All You Need",
            source=models.PaperSource.ARXIV,
            arxiv_id="1706.03762",
            arxiv_version="v5",
            arxiv_primary_category="cs.CL",
            authors=["Vaswani", "Shazeer"],
        )
        paper = crud.create_paper(db_session, data)

        assert paper.arxiv_id == "1706.03762"
        assert paper.arxiv_version == "v5"
        assert paper.source == models.PaperSource.ARXIV

    def test_get_papers_filter_by_status(self, db_session):
        crud.create_paper(
            db_session,
            schemas.PaperCreate(title="P1", status=models.PaperStatus.PLANNED),
        )
        crud.create_paper(
            db_session,
            schemas.PaperCreate(title="P2", status=models.PaperStatus.READING),
        )
        crud.create_paper(
            db_session,
            schemas.PaperCreate(title="P3", status=models.PaperStatus.PLANNED),
        )

        planned = crud.get_papers(db_session, status=models.PaperStatus.PLANNED)
        assert len(planned) == 2

        reading = crud.get_papers(db_session, status=models.PaperStatus.READING)
        assert len(reading) == 1

    def test_get_papers_filter_by_category(self, db_session):
        cat = crud.create_category(db_session, schemas.CategoryCreate(name="ML"))

        crud.create_paper(
            db_session, schemas.PaperCreate(title="P1", category_id=cat.id)
        )
        crud.create_paper(db_session, schemas.PaperCreate(title="P2"))

        papers = crud.get_papers(db_session, category_id=cat.id)
        assert len(papers) == 1
        assert papers[0].title == "P1"

    def test_update_paper(self, db_session):
        paper = crud.create_paper(db_session, schemas.PaperCreate(title="Old Title"))
        updated = crud.update_paper(
            db_session,
            paper.id,
            schemas.PaperUpdate(title="New Title", notes="Some notes"),
        )

        assert updated is not None
        assert updated.title == "New Title"
        assert updated.notes == "Some notes"

    def test_update_paper_status_to_read_sets_read_at(self, db_session):
        paper = crud.create_paper(db_session, schemas.PaperCreate(title="Test"))
        assert paper.read_at is None

        updated = crud.update_paper(
            db_session,
            paper.id,
            schemas.PaperUpdate(status=models.PaperStatus.READ),
        )

        assert updated is not None
        assert updated.read_at is not None

    def test_update_paper_authors(self, db_session):
        paper = crud.create_paper(
            db_session,
            schemas.PaperCreate(title="Test", authors=["Alice", "Bob"]),
        )
        assert len(paper.authors) == 2

        updated = crud.update_paper(
            db_session,
            paper.id,
            schemas.PaperUpdate(authors=["Charlie"]),
        )

        assert updated is not None
        assert len(updated.authors) == 1
        assert updated.authors[0].name == "Charlie"

    def test_delete_paper(self, db_session):
        paper = crud.create_paper(db_session, schemas.PaperCreate(title="Test"))
        result = crud.delete_paper(db_session, paper.id)

        assert result is True
        assert crud.get_paper(db_session, paper.id) is None


class TestReorderPapers:
    """Tests for paper reordering."""

    def test_reorder_papers(self, db_session):
        p1 = crud.create_paper(db_session, schemas.PaperCreate(title="P1"))
        p2 = crud.create_paper(db_session, schemas.PaperCreate(title="P2"))
        p3 = crud.create_paper(db_session, schemas.PaperCreate(title="P3"))

        # Reverse order
        result = crud.reorder_papers(
            db_session,
            status=models.PaperStatus.PLANNED,
            paper_ids=[p3.id, p2.id, p1.id],
        )

        assert result is True

        # Verify new order
        papers = crud.get_papers(db_session)
        assert [p.id for p in papers] == [p3.id, p2.id, p1.id]

    def test_reorder_papers_wrong_status_fails(self, db_session):
        p1 = crud.create_paper(
            db_session,
            schemas.PaperCreate(title="P1", status=models.PaperStatus.PLANNED),
        )
        p2 = crud.create_paper(
            db_session,
            schemas.PaperCreate(title="P2", status=models.PaperStatus.READING),
        )

        # Try to reorder with wrong status
        result = crud.reorder_papers(
            db_session,
            status=models.PaperStatus.PLANNED,
            paper_ids=[p1.id, p2.id],
        )

        assert result is False  # p2 has wrong status


class TestPapersByAuthor:
    """Tests for getting papers by author."""

    def test_get_papers_by_author(self, db_session):
        crud.create_paper(
            db_session,
            schemas.PaperCreate(title="P1", authors=["Alice", "Bob"]),
        )
        crud.create_paper(
            db_session,
            schemas.PaperCreate(title="P2", authors=["Bob", "Charlie"]),
        )
        crud.create_paper(
            db_session,
            schemas.PaperCreate(title="P3", authors=["Charlie"]),
        )

        # Get Bob's author record
        authors = crud.get_authors(db_session)
        bob = next(a for a in authors if a["name"] == "Bob")

        papers = crud.get_papers_by_author(db_session, bob["id"])
        assert len(papers) == 2
        titles = {p.title for p in papers}
        assert titles == {"P1", "P2"}
