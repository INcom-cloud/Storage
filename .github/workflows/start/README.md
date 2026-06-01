# start / 설치·배포 (bare systemd)

`1-1.md` 의 계획을 **실행 가능한 코드**로 분리한 디렉터리.

```
start/
├── 1-1.md        # 사람이 읽는 계획 문서
├── ansible/      # 멱등 배포 (AWX/Ansible) — 정식 경로
├── agent/        # T1 Python 커스텀 에이전트 (패키지화 대상)
└── systemd/      # 수동 bare systemd 참고 unit
```

## 디버그 / error·fail 확인 (Rocky 9 설치 전 검증)

`ansible/` 디렉터리에서:

```bash
# 1) 문법 검사 (가장 빠른 1차 확인)
ansible-playbook site.yml --syntax-check

# 2) 정적 분석 (선택)
ansible-lint site.yml
yamllint .

# 3) dry-run — 실제 변경 없이 무엇이 바뀔지 + 실패 지점 확인
ansible-playbook site.yml --check --diff -vvv

# 4) 실제 실행 (상세 디버그 출력)
ansible-playbook site.yml -vvv
```

- 실패는 `assert` / `failed_when` 으로 **명시적 fail** 처리되어 콘솔에 원인이 출력됩니다.
- 실행 로그는 `ansible/ansible-run.log` 에도 보존됩니다 (`ansible.cfg` 의 `log_path`).
- 서비스 런타임 로그: `journalctl -u osv-agent -f`, `journalctl -u t2-api -f`.

## 다음 단계 (TODO)
- `t2_api` 의 FastAPI 앱 소스(`app.main:app`) 실제 구현
- `agent` 의 OSV API 호출 → T2 보고 로직 구현
- 비밀값(`t2_api_key`, `pg_password`) `ansible-vault` 로 암호화
- `molecule` + Podman 으로 Rocky 9 컨테이너 통합 테스트
