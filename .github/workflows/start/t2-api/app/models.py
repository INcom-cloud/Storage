"""ORM 모델 — 취약점 작업(Task)."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import Column, DateTime, Integer, String, Text

from .db import Base


class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True)
    ts = Column(DateTime, default=dt.datetime.utcnow, nullable=False)
    source = Column(String(128), nullable=False, default="unknown")
    payload = Column(Text, nullable=False)            # 원본 보고 JSON
    status = Column(String(32), nullable=False, default="pending_approval")
    remediation = Column(Text, nullable=True)         # 조치 결과 JSON
    updated_ts = Column(DateTime, default=dt.datetime.utcnow,
                        onupdate=dt.datetime.utcnow, nullable=False)
