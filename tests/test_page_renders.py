"""Tests for full-page GET routes.

Every full-page route is tested to ensure the template renders without errors.
A 500 status means the template has a variable mismatch or other rendering bug.
"""

from __future__ import annotations


class TestHomePages:
    """Tests for home page with different status filters."""

    def test_home_planned(self, client):
        response = client.get("/?status=PLANNED")
        assert response.status_code == 200

    def test_home_reading(self, client):
        response = client.get("/?status=READING")
        assert response.status_code == 200

    def test_home_read(self, client):
        response = client.get("/?status=READ")
        assert response.status_code == 200

    def test_home_default(self, client):
        response = client.get("/")
        assert response.status_code == 200

    def test_home_with_sort(self, client):
        response = client.get("/?status=PLANNED&sort_by=likes")
        assert response.status_code == 200


class TestPaperPages:
    """Tests for paper form pages."""

    def test_add_paper_page(self, client):
        response = client.get("/add")
        assert response.status_code == 200

    def test_edit_paper_page(self, client, sample_paper):
        response = client.get(f"/papers/{sample_paper}/edit")
        assert response.status_code == 200

    def test_edit_paper_not_found(self, client):
        response = client.get("/papers/99999/edit")
        assert response.status_code == 404


class TestAuthorPages:
    """Tests for author pages."""

    def test_authors_page(self, client):
        response = client.get("/authors")
        assert response.status_code == 200

    def test_author_detail_page(self, client, sample_paper):
        # sample_paper creates an author "Alice"
        from app import crud

        session = client._Session()
        try:
            authors = crud.get_authors(session, user_id=1)
            if authors:
                response = client.get(f"/authors/{authors[0]['id']}")
                assert response.status_code == 200
        finally:
            session.close()


class TestCategoryPages:
    """Tests for category pages."""

    def test_categories_page(self, client):
        response = client.get("/categories")
        assert response.status_code == 200


class TestTextbookPages:
    """Tests for textbook pages."""

    def test_textbooks_planned(self, client):
        response = client.get("/textbooks?status=PLANNED")
        assert response.status_code == 200

    def test_textbooks_reading(self, client):
        response = client.get("/textbooks?status=READING")
        assert response.status_code == 200

    def test_textbooks_read(self, client):
        response = client.get("/textbooks?status=READ")
        assert response.status_code == 200

    def test_add_textbook_page(self, client):
        response = client.get("/textbooks/add")
        assert response.status_code == 200

    def test_edit_textbook_page(self, client, sample_textbook):
        response = client.get(f"/textbooks/{sample_textbook}/edit")
        assert response.status_code == 200

    def test_edit_textbook_not_found(self, client):
        response = client.get("/textbooks/99999/edit")
        assert response.status_code == 404


class TestEffortPages:
    """Tests for effort log pages."""

    def test_efforts_page(self, client):
        response = client.get("/efforts")
        assert response.status_code == 200


class TestInsightsPages:
    """Tests for monthly insights pages."""

    def test_insights_page_empty(self, client):
        response = client.get("/insights")
        assert response.status_code == 200

    def test_insights_page_with_effort(self, client, sample_paper):
        from app import crud

        session = client._Session()
        try:
            crud.create_effort_log(session, points=3, paper_id=sample_paper, user_id=1)
        finally:
            session.close()

        response = client.get("/insights")
        assert response.status_code == 200
        assert b"Not generated yet" in response.content

    def test_insights_month_page_no_summary(self, client, sample_paper):
        from app import crud

        session = client._Session()
        try:
            log = crud.create_effort_log(
                session, points=3, paper_id=sample_paper, user_id=1
            )
            year, month = log.created_at.year, log.created_at.month
        finally:
            session.close()

        response = client.get(f"/insights/{year}/{month}")
        assert response.status_code == 200
        assert b"No summary yet" in response.content

    def test_insights_month_page_with_summary(self, client, sample_paper):
        from app import crud

        session = client._Session()
        try:
            log = crud.create_effort_log(
                session, points=3, paper_id=sample_paper, user_id=1
            )
            year, month = log.created_at.year, log.created_at.month
            crud.upsert_monthly_summary(
                session, year, month, "This month was about testing.", user_id=1
            )
        finally:
            session.close()

        response = client.get(f"/insights/{year}/{month}")
        assert response.status_code == 200
        assert b"This month was about testing." in response.content

    def test_insights_month_page_invalid_month(self, client):
        response = client.get("/insights/2026/13")
        assert response.status_code == 404


class TestWorkoutPages:
    """Tests for workout pages."""

    def test_workouts_page(self, client):
        response = client.get("/workouts")
        assert response.status_code == 200

    def test_workout_detail_page(self, client, sample_workout_with_set):
        workout_id, _ = sample_workout_with_set
        response = client.get(f"/workouts/{workout_id}")
        assert response.status_code == 200

    def test_workout_detail_not_found(self, client):
        response = client.get("/workouts/99999")
        assert response.status_code == 404


class TestLoginPage:
    """Tests for login page."""

    def test_login_page(self, client):
        response = client.get("/login")
        assert response.status_code == 200


class TestStatsPage:
    """Tests for stats page with charts."""

    def test_stats_page(self, client):
        response = client.get("/stats")
        assert response.status_code == 200
        assert b"Statistics" in response.content


class TestPendingPage:
    """Tests for pending arxiv links page."""

    def test_pending_page(self, client):
        response = client.get("/pending")
        assert response.status_code == 200
        assert b"Pending ArXiv Links" in response.content


class TestHealthCheck:
    """Tests for health check endpoint."""

    def test_health_check(self, client):
        response = client.get("/health")
        assert response.status_code == 200
