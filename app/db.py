import logging
import os
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

logger = logging.getLogger(__name__)

# Check if running in Cloud Run (K_SERVICE is set by Cloud Run)
IS_CLOUD_RUN = os.getenv("K_SERVICE") is not None

DATABASE_URL = os.getenv("DATABASE_URL", "")

if not DATABASE_URL:
    if IS_CLOUD_RUN:
        # In production, DATABASE_URL must be set
        raise RuntimeError(
            "DATABASE_URL environment variable is not set! "
            "The app cannot start without a database connection. "
            "Set DATABASE_URL in Cloud Run environment variables."
        )
    else:
        # Local development - use SQLite
        DATABASE_URL = "sqlite:///./paper_tracker.db"
        logger.info("Using local SQLite database (DATABASE_URL not set)")

# Handle different database backends
connect_args = {}

# Handle Turso/libsql URLs - sqlalchemy-libsql uses sqlite+libsql:// scheme
if DATABASE_URL.startswith("libsql://"):
    import sqlalchemy_libsql  # noqa: F401 - registers dialect

    # Parse the URL to extract authToken
    parsed = urlparse(DATABASE_URL)
    query_params = parse_qs(parsed.query)

    # Extract authToken and pass it as connect_arg (libsql_experimental expects this)
    if "authToken" in query_params:
        connect_args["auth_token"] = query_params["authToken"][0]
        # Remove authToken from query string (it's passed via connect_args)
        del query_params["authToken"]

    # Ensure secure=true for HTTPS (required for Turso)
    query_params["secure"] = ["true"]

    # Rebuild the URL without authToken but with secure=true
    new_query = urlencode({k: v[0] for k, v in query_params.items()})
    new_parsed = parsed._replace(scheme="sqlite+libsql", query=new_query)
    DATABASE_URL = urlunparse(new_parsed)

    connect_args["check_same_thread"] = False

elif DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
