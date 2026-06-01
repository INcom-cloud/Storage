"""OSV T2 운영 API — FastAPI + PostgreSQL.

PoC(stdlib http.server+sqlite)의 엔드포인트/상태머신을 운영 스택으로 승격.
탐지(T1) → 보고(pending_approval) → 승인 → 조치 → done 폐루프.
"""
from __future__ import annotations

import json
import subprocess
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import Base, engine, get_db
from .models import Task

# 단순 부트스트랩(운영은 alembic 권장)
Base.metadata.create_all(engine)

app = FastAPI(title="OSV T2 API", version="1.0.0")


# ---------------- 스키마 ----------------
class Report(BaseModel):
    source: str = "unknown"
    host: Optional[str] = None
    vulns: List[Dict[str, Any]] = []


class TaskOut(BaseModel):
    id: int
    ts: str
    source: str
    payload: Dict[str, Any]
    status: str
    remediation: Optional[Dict[str, Any]] = None
    updated_ts: str


def _to_out(t: Task) -> TaskOut:
    return TaskOut(
        id=t.id,
        ts=t.ts.isoformat(),
        source=t.source,
        payload=json.loads(t.payload),
        status=t.status,
        remediation=json.loads(t.remediation) if t.remediation else None,
        updated_ts=t.updated_ts.isoformat(),
    )


def _remediate(payload: Dict[str, Any]) -> Dict[str, Any]:
    """승인 시 조치. 운영: AWX 잡 템플릿 호출(아래 TODO). 현재는 계획+재확인 기록."""
    vulns = payload.get("vulns", []) if isinstance(payload, dict) else []
    planned = ["dnf update %s" % v.get("package", "?") for v in vulns]
    try:
        kernel = subprocess.check_output(["uname", "-r"]).decode().strip()
    except Exception:
        kernel = "unknown"
    # TODO: AWX REST 로 잡 실행 — POST {AWX}/api/v2/job_templates/{id}/launch/
    #       extra_vars 로 대상/패키지 전달, 결과 폴링 후 status 갱신.
    return {
        "mode": "plan",
        "planned": planned,
        "running_kernel": kernel,
        "result": "queued-for-awx",
        "note": "production: trigger AWX job template on approval",
    }


# ---------------- 엔드포인트 ----------------
@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/reports", status_code=201)
def create_report(report: Report, db: Session = Depends(get_db)) -> Dict[str, Any]:
    t = Task(source=report.source, payload=report.model_dump_json(), status="pending_approval")
    db.add(t)
    db.commit()
    db.refresh(t)
    return {"id": t.id, "status": t.status}


@app.get("/tasks", response_model=List[TaskOut])
def list_tasks(db: Session = Depends(get_db)) -> List[TaskOut]:
    rows = db.execute(select(Task).order_by(Task.id)).scalars().all()
    return [_to_out(t) for t in rows]


@app.get("/tasks/{task_id}", response_model=TaskOut)
def get_task(task_id: int, db: Session = Depends(get_db)) -> TaskOut:
    t = db.get(Task, task_id)
    if not t:
        raise HTTPException(status_code=404, detail="not found")
    return _to_out(t)


@app.post("/tasks/{task_id}/approve", response_model=TaskOut)
def approve(task_id: int, db: Session = Depends(get_db)) -> TaskOut:
    t = db.get(Task, task_id)
    if not t:
        raise HTTPException(status_code=404, detail="not found")
    if t.status not in ("pending_approval",):
        raise HTTPException(status_code=409, detail="not pending_approval")
    t.remediation = json.dumps(_remediate(json.loads(t.payload)))
    t.status = "done"
    db.commit()
    db.refresh(t)
    return _to_out(t)


@app.post("/tasks/{task_id}/reject", response_model=TaskOut)
def reject(task_id: int, db: Session = Depends(get_db)) -> TaskOut:
    t = db.get(Task, task_id)
    if not t:
        raise HTTPException(status_code=404, detail="not found")
    t.status = "rejected"
    db.commit()
    db.refresh(t)
    return _to_out(t)
