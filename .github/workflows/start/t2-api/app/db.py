"""DB 설정 — PostgreSQL (SQLAlchemy)."""
from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# 예: postgresql+psycopg2://osv:osv@127.0.0.1:5432/osvdb
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg2://osv:osv@127.0.0.1:5432/osvdb",
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, future=True)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
