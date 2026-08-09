"""Tests for API routes."""

from __future__ import annotations


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


class TestInsightsGenerate:
    """Tests for POST /insights/{year}/{month}/generate."""

    def _log_effort(self, client, sample_paper):
        from app import crud

        session = client._Session()
        try:
            log = crud.create_effort_log(
                session, points=3, paper_id=sample_paper, user_id=1
            )
            return log.created_at.year, log.created_at.month
        finally:
            session.close()

    def test_generate_success(self, client, sample_paper):
        from unittest.mock import AsyncMock, patch
        from app import crud

        year, month = self._log_effort(client, sample_paper)

        with patch(
            "app.gpt.generate_monthly_summary",
            new=AsyncMock(return_value="A mocked monthly summary."),
        ):
            response = client.post(
                f"/insights/{year}/{month}/generate", follow_redirects=False
            )

        assert response.status_code == 303
        assert response.headers["location"] == f"/insights/{year}/{month}"

        session = client._Session()
        try:
            summary = crud.get_monthly_summary(session, year, month, user_id=1)
            assert summary is not None
            assert summary.summary == "A mocked monthly summary."
        finally:
            session.close()

    def test_generate_gpt_error(self, client, sample_paper):
        from unittest.mock import AsyncMock, patch
        from app.gpt import GPTError

        year, month = self._log_effort(client, sample_paper)

        with patch(
            "app.gpt.generate_monthly_summary",
            new=AsyncMock(side_effect=GPTError("boom")),
        ):
            response = client.post(f"/insights/{year}/{month}/generate")

        assert response.status_code == 500
        assert "boom" in response.text

    def test_regenerate_overwrites_in_place(self, client, sample_paper):
        from unittest.mock import AsyncMock, patch
        from app import crud

        year, month = self._log_effort(client, sample_paper)

        with patch(
            "app.gpt.generate_monthly_summary",
            new=AsyncMock(return_value="First version."),
        ):
            client.post(f"/insights/{year}/{month}/generate", follow_redirects=False)

        with patch(
            "app.gpt.generate_monthly_summary",
            new=AsyncMock(return_value="Second version."),
        ):
            client.post(f"/insights/{year}/{month}/generate", follow_redirects=False)

        session = client._Session()
        try:
            from app import models

            count = (
                session.query(models.MonthlySummary)
                .filter_by(user_id=1, year=year, month=month)
                .count()
            )
            assert count == 1
            summary = crud.get_monthly_summary(session, year, month, user_id=1)
            assert summary.summary == "Second version."
        finally:
            session.close()
