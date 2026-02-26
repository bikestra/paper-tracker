"""Tests for HTMX partial routes.

Every route that renders a Jinja2 partial template is tested here.
A 500 status means the template failed to render (e.g. variable name mismatch).
"""

from __future__ import annotations


# --- Workout Set Partials ---


class TestWorkoutSetPartials:
    """Tests for workout set HTMX partials."""

    def test_complete_set_renders(self, client, sample_workout_with_set):
        """The exact bug that motivated these tests: POST /workouts/sets/{id}/complete
        must pass the correct template variable to partials/workout_set.html."""
        workout_id, set_id = sample_workout_with_set
        response = client.post(
            f"/workouts/sets/{set_id}/complete",
            data={"actual_weight": 225.0, "actual_reps": 5},
        )
        assert response.status_code == 200

    def test_edit_set_renders(self, client, sample_workout_with_set):
        workout_id, set_id = sample_workout_with_set
        response = client.post(
            f"/workouts/sets/{set_id}/edit",
            data={"target_weight": 230.0, "target_reps": 5},
        )
        assert response.status_code == 200


# --- Paper Partials ---


class TestPaperPartials:
    """Tests for paper-related HTMX partials."""

    def test_start_reading_renders(self, client, sample_paper):
        response = client.post(f"/papers/{sample_paper}/start-reading")
        assert response.status_code == 200

    def test_delete_paper_renders(self, client, sample_paper):
        response = client.post(f"/papers/{sample_paper}/delete")
        assert response.status_code == 200

    def test_like_paper_renders(self, client, sample_paper):
        response = client.post(f"/papers/{sample_paper}/like")
        assert response.status_code == 200

    def test_effort_paper_renders(self, client, sample_paper):
        response = client.post(
            f"/papers/{sample_paper}/effort",
            data={"points": 1, "note": ""},
        )
        assert response.status_code == 200

    def test_papers_list_partial_renders(self, client):
        response = client.get("/partials/papers?status=PLANNED")
        assert response.status_code == 200


# --- Paper Source Partials ---


class TestPaperSourcePartials:
    """Tests for discovery source HTMX partials."""

    def test_get_sources_renders(self, client, sample_paper):
        response = client.get(f"/partials/paper-sources/{sample_paper}")
        assert response.status_code == 200

    def test_add_source_renders(self, client, sample_paper):
        response = client.post(
            f"/papers/{sample_paper}/sources",
            data={"source_type": "TEXT", "source_text": "From a friend"},
        )
        assert response.status_code == 200

    def test_delete_source_renders(self, client, sample_paper):
        # First add a source
        client.post(
            f"/papers/{sample_paper}/sources",
            data={"source_type": "TEXT", "source_text": "From a friend"},
        )
        # Get the source ID via CRUD
        from app import crud

        session = client._Session()
        try:
            sources = crud.get_discovery_sources(session, sample_paper, user_id=1)
            assert sources, "Source should have been created"
            source_id = sources[0].id
        finally:
            session.close()

        response = client.request(
            "DELETE",
            f"/papers/{sample_paper}/sources/{source_id}",
        )
        assert response.status_code == 200


# --- Category Partials ---


class TestCategoryPartials:
    """Tests for category HTMX partials."""

    def test_create_category_renders(self, client):
        response = client.post("/categories", data={"name": "Deep Learning"})
        assert response.status_code == 200

    def test_delete_category_renders(self, client, sample_category):
        response = client.request("DELETE", f"/categories/{sample_category}")
        assert response.status_code == 200

    def test_inline_category_dropdown_renders(self, client):
        response = client.post(
            "/partials/category-dropdown",
            data={"name": "NLP", "context": "paper"},
        )
        assert response.status_code == 200

    def test_categories_list_partial_renders(self, client):
        response = client.get("/partials/categories")
        assert response.status_code == 200


# --- Textbook Partials ---


class TestTextbookPartials:
    """Tests for textbook HTMX partials."""

    def test_delete_textbook_renders(self, client, sample_textbook):
        response = client.post(f"/textbooks/{sample_textbook}/delete")
        assert response.status_code == 200

    def test_like_textbook_renders(self, client, sample_textbook):
        response = client.post(f"/textbooks/{sample_textbook}/like")
        assert response.status_code == 200

    def test_effort_textbook_renders(self, client, sample_textbook):
        response = client.post(
            f"/textbooks/{sample_textbook}/effort",
            data={"points": 1, "note": ""},
        )
        assert response.status_code == 200

    def test_textbooks_list_partial_renders(self, client):
        response = client.get("/partials/textbooks?status=PLANNED")
        assert response.status_code == 200


# --- Exercise Result Partials ---


class TestExerciseResultPartials:
    """Tests for exercise result HTMX partials."""

    def test_save_rir_renders(self, client, sample_workout_with_set):
        workout_id, set_id = sample_workout_with_set
        # Complete the set first so there's a top set to reference
        client.post(f"/workouts/sets/{set_id}/complete", data={"actual_weight": 225.0, "actual_reps": 5})
        response = client.post(
            f"/workouts/{workout_id}/exercises/SQUAT/rir",
            data={"rir": 2},
        )
        assert response.status_code == 200
