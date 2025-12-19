from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from . import models
from .db import Base, engine, get_db
from .schemas import Healthcheck

app = FastAPI(title="Paper Tracker")


@app.on_event("startup")
def on_startup() -> None:
    # Ensure models are known to Alembic; tables should be created via migrations.
    Base.metadata.bind = engine


@app.get("/", tags=["health"], response_model=Healthcheck)
def read_root(db: Session = Depends(get_db)) -> Healthcheck:
    db.execute(text("SELECT 1"))
    return Healthcheck(message="Paper Tracker API is running")
