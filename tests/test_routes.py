"""Tests for API routes."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app import models


@pytest.fixture
def client():
    """Create test client with in-memory database."""
    # Use StaticPool for SQLite in-memory to allow cross-thread access
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    # Create default user upfront
    session = Session()
    session.add(models.User(id=1, email=None))
    session.commit()
    session.close()

    def override_get_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()
    engine.dispose()


class TestHomePage:
    """Tests for home page."""

    def test_home_page_loads(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert "Paper Tracker" in response.text

    def test_home_page_with_status_filter(self, client):
        response = client.get("/?status=READING")
        assert response.status_code == 200
        assert "Reading" in response.text


class TestAddPaper:
    """Tests for add paper functionality."""

    def test_add_paper_page_loads(self, client):
        response = client.get("/add")
        assert response.status_code == 200
        assert "Add Paper" in response.text

    def test_create_paper(self, client):
        response = client.post(
            "/papers",
            data={"title": "Test Paper", "status": "PLANNED", "authors": "John Doe"},
            follow_redirects=False,
        )
        assert response.status_code == 303  # Redirect

        # Verify paper was created
        response = client.get("/?status=PLANNED")
        assert "Test Paper" in response.text


class TestAuthors:
    """Tests for authors functionality."""

    def test_authors_page_loads(self, client):
        response = client.get("/authors")
        assert response.status_code == 200
        assert "Authors" in response.text


class TestCategories:
    """Tests for categories functionality."""

    def test_categories_page_loads(self, client):
        response = client.get("/categories")
        assert response.status_code == 200
        assert "Categories" in response.text

    def test_create_category(self, client):
        response = client.post(
            "/categories",
            data={"name": "Machine Learning"},
        )
        assert response.status_code == 200
        assert "Machine Learning" in response.text


class TestReorder:
    """Tests for reorder functionality."""

    def test_reorder_endpoint_exists(self, client):
        # Just test that the endpoint exists and validates properly
        response = client.post(
            "/papers/reorder",
            json={"status": "PLANNED", "category_id": None, "paper_ids": []},
        )
        # Should fail validation (empty paper_ids)
        assert response.status_code == 422

    def test_reorder_with_invalid_ids(self, client):
        response = client.post(
            "/papers/reorder",
            json={"status": "PLANNED", "category_id": None, "paper_ids": [999, 998]},
        )
        # Should fail because papers don't exist (400) or validation (422)
        assert response.status_code in [400, 422]


class TestHealthCheck:
    """Tests for health check endpoint."""

    def test_health_check(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert "running" in response.json()["message"].lower()
