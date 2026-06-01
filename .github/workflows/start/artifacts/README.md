# artifacts — 빌드 산출물 보관 위치

빌드된 RPM(및 기타 배포 산출물)을 **여기에 둔다**. ansible 의 `t1_agent` 역할이
이 경로에서 RPM 을 찾아 노드로 전송 후 `dnf install` 한다.

## 흐름
```
rpmbuild (Rocky 9 빌드 호스트)
  → ~/rpmbuild/RPMS/noarch/osv-agent-0.1.0-1.el9.noarch.rpm
  → 복사 → start/artifacts/osv-agent-0.1.0-1.el9.noarch.rpm   ← (이 디렉터리)
  → ansible-playbook site.yml --limit t1   (자동 전송·설치)
```

## 경로를 바꾸려면
`ansible/roles/t1_agent/defaults/main.yml` 의 `osv_agent_rpm_local` 기본값을 쓰거나,
실행 시 덮어쓴다:
```bash
ansible-playbook site.yml --limit t1 \
  -e "osv_agent_rpm_local=/abs/path/osv-agent-0.1.0-1.el9.noarch.rpm"
```

> 주의: `.rpm` 바이너리는 보통 git 에 커밋하지 않는다(용량/재현성).
> 이 디렉터리는 `.gitkeep` 으로 경로만 유지하고, RPM 자체는 빌드 산출물로 둔다.
