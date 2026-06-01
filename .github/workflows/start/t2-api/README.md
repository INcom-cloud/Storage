# T2 운영 API (FastAPI + PostgreSQL) — 단일 노드

PoC(stdlib http.server + sqlite)를 운영 스택으로 승격한 버전. **DB+API를 한 노드에** 통합 배포.

> ⚠️ **배포 대상 = RHEL 9 / Rocky 9 노드** (host1/RHVH el8.6 불가:
> FastAPI는 python 3.8+, PostgreSQL은 패키지 설치 필요).

```
t2-api/
├── app/
│   ├── main.py     # FastAPI 엔드포인트 (health, reports, tasks, approve, reject)
│   ├── db.py       # SQLAlchemy 엔진/세션 (DATABASE_URL)
│   └── models.py   # Task ORM (상태머신: pending_approval→done/rejected)
└── requirements.txt
```

## 배포 (Ansible, 단일 노드)
`ansible/roles/t2_api` 역할이 한 노드에 전부 깐다: PostgreSQL 설치·initdb·DB/계정 생성,
venv+pip, 앱 배포, systemd(uvicorn), 헬스체크.

```bash
cd ansible
# inventory.ini 의 [t2] 에 대상 노드 지정 후:
ansible-playbook site.yml --limit t2 --check --diff -vvv   # dry-run
ansible-playbook site.yml --limit t2 -vvv                  # 실제 배포
```

- **online**(기본): pip 가 PyPI 에서 의존성 설치 (노드에 인터넷 필요)
- **offline**: `-e t2_pip_mode=offline` + `t2_wheelhouse` 에 wheel 미리 배치
- 비밀값(`pg_password`)은 `ansible-vault` 로 암호화 권장

## 수동 실행(개발/검증)
```bash
python3 -m venv venv && . venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL=postgresql+psycopg2://osv:osv@127.0.0.1:5432/osvdb
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## 엔드포인트 (PoC와 동일 계약)
- `GET  /health`
- `POST /reports`            — T1 보고 → task(pending_approval) 생성
- `GET  /tasks`, `GET /tasks/{id}`
- `POST /tasks/{id}/approve` — 승인 → 조치(현재 plan, 운영은 AWX 잡 호출) → done
- `POST /tasks/{id}/reject`  — 거부

## 운영 TODO
- `_remediate()` 에서 **AWX 잡 템플릿 호출**(REST `/api/v2/job_templates/{id}/launch/`) 구현
- DB 스키마는 `create_all` → **alembic** 마이그레이션으로
- Tier3 메일 보고(성공/취소/수정권장) 연동
