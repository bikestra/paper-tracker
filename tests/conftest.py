"""Pytest configuration and fixtures."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app import crud, models, schemas


@pytest.fixture
def db_session():
    """Create an in-memory SQLite database session for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    # Create default user
    user = models.User(id=1, email=None)
    session.add(user)
    session.commit()

    yield session

    session.close()
    engine.dispose()


@pytest.fixture
def client():
    """Create test client with in-memory database."""
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

    with TestClient(app) as c:
        # Stash Session factory so fixtures can create data
        c._Session = Session
        yield c

    app.dependency_overrides.clear()
    engine.dispose()


@pytest.fixture
def sample_paper(client):
    """Create a PLANNED paper and return its ID."""
    session = client._Session()
    try:
        paper = crud.create_paper(
            session,
            schemas.PaperCreate(title="Test Paper", status=models.PaperStatus.PLANNED, authors=["Alice"]),
            user_id=1,
        )
        return paper.id
    finally:
        session.close()


@pytest.fixture
def sample_category(client):
    """Create a category and return its ID."""
    session = client._Session()
    try:
        cat = crud.create_category(session, schemas.CategoryCreate(name="ML"), user_id=1)
        return cat.id
    finally:
        session.close()


@pytest.fixture
def sample_textbook(client):
    """Create a PLANNED textbook and return its ID."""
    session = client._Session()
    try:
        tb = crud.create_textbook(
            session,
            schemas.TextbookCreate(title="Test Textbook", status=models.TextbookStatus.PLANNED),
            user_id=1,
        )
        return tb.id
    finally:
        session.close()


@pytest.fixture
def sample_workout_with_set(client):
    """Create an IN_PROGRESS workout with one TOP_SET. Returns (workout_id, set_id)."""
    session = client._Session()
    try:
        workout = crud.create_workout(session, models.WorkoutType.WORKOUT_A, user_id=1)
        sets = crud.add_workout_sets(
            session,
            workout.id,
            [
                schemas.WorkoutSetCreate(
                    exercise_type=models.ExerciseType.SQUAT,
                    set_type=models.SetType.TOP_SET,
                    set_number=1,
                    target_weight=225.0,
                    target_reps=5,
                ),
            ],
            user_id=1,
        )
        crud.start_workout(session, workout.id, user_id=1)
        return workout.id, sets[0].id
    finally:
        session.close()
