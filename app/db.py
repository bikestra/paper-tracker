import logging
import os
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

logger = logging.getLogger(__name__)

# Check if running in Cloud Run (K_SERVICE is set by Cloud Run)
IS_CLOUD_RUN = os.getenv("K_SERVICE") is not None

DATABASE_URL = os.getenv("DATABASE_URL", "")
# Cloud SQL instance connection name (e.g., "project:region:instance")
CLOUD_SQL_CONNECTION = os.getenv("CLOUD_SQL_CONNECTION", "")

if not DATABASE_URL and not CLOUD_SQL_CONNECTION:
    if IS_CLOUD_RUN:
        # In production, DATABASE_URL or CLOUD_SQL_CONNECTION must be set
        raise RuntimeError(
            "DATABASE_URL or CLOUD_SQL_CONNECTION environment variable is not set! "
            "The app cannot start without a database connection. "
            "Set DATABASE_URL or CLOUD_SQL_CONNECTION in Cloud Run environment variables."
        )
    else:
        # Local development - use SQLite
        DATABASE_URL = "sqlite:///./paper_tracker.db"
        logger.info("Using local SQLite database (DATABASE_URL not set)")

# Handle different database backends
connect_args: dict = {}
creator = None

# Cloud SQL via Python Connector (recommended for Cloud Run)
if CLOUD_SQL_CONNECTION:
    from google.cloud.sql.connector import Connector

    connector = Connector()
    DB_USER = os.getenv("DB_USER", "postgres")
    DB_PASS = os.getenv("DB_PASS", "")
    DB_NAME = os.getenv("DB_NAME", "postgres")

    def get_conn():
        return connector.connect(
            CLOUD_SQL_CONNECTION,
            "pg8000",
            user=DB_USER,
            password=DB_PASS,
            db=DB_NAME,
        )

    creator = get_conn
    DATABASE_URL = "postgresql+pg8000://"
    logger.info(f"Using Cloud SQL connector: {CLOUD_SQL_CONNECTION}")

# Handle Turso/libsql URLs - sqlalchemy-libsql uses sqlite+libsql:// scheme
elif DATABASE_URL.startswith("libsql://"):
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

# Standard PostgreSQL connection string
elif DATABASE_URL.startswith("postgresql"):
    # No special handling needed for standard PostgreSQL URLs
    pass

elif DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

if creator:
    engine = create_engine(DATABASE_URL, creator=creator)
else:
    engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
