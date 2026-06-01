#!/usr/bin/env bash
# 오프라인 자체 완결형 RPM 빌드 (인터넷 0% / ISO repo 만 있으면 됨)
#   - venv/pip 미사용. 시스템 python3 로 직접 구동 (현재 스텁은 stdlib 만 사용).
#   - 실행 위치: RHV 클러스터 위의 RHEL 9 / Rocky 9 "게스트 VM" (RHVH 호스트 아님).
#   - 사전: RHEL9 ISO 를 /mnt/iso 에 마운트하고 iso repo 등록 (BaseOS/AppStream).
#   - 결과: ~/osv-agent-build/artifacts/osv-agent-0.1.0-1.*.noarch.rpm
set -euo pipefail

VER=0.1.0
ROOT="${HOME}/osv-agent-build"
SRC="${ROOT}/agent"
PKG="${ROOT}/packaging"
ART="${ROOT}/artifacts"

# 0) el9 확인 (RHVH/el8 에서 잘못 실행 방지)
if ! grep -q 'platform:el9' /etc/os-release 2>/dev/null; then
  echo "[!] 이 호스트는 el9 가 아닙니다. RHEL9/Rocky9 게스트 VM 에서 실행하세요."
  grep -E 'PRETTY_NAME|PLATFORM_ID' /etc/os-release || true
  exit 1
fi

echo "[*] 작업 디렉터리: ${ROOT}"
rm -rf "${ROOT}"
mkdir -p "${SRC}/src/agent" "${PKG}" "${ART}"

# ── 1) Python 에이전트 소스 (stdlib 전용) ─────────────────
cat > "${SRC}/src/agent/__init__.py" <<'EOF'
"""OSV 취약점 수집 에이전트 (T1)."""

__version__ = "0.1.0"
EOF

cat > "${SRC}/src/agent/config.py" <<'EOF'
"""환경변수 기반 설정 (systemd EnvironmentFile = /etc/osv-agent.env)."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    t2_api_url: str
    t2_api_key: str
    osv_api_timeout: int
    collector_interval: int
    log_level: str

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            t2_api_url=os.environ.get("T2_API_URL", "http://t2-api:8000"),
            t2_api_key=os.environ.get("T2_API_KEY", ""),
            osv_api_timeout=int(os.environ.get("OSV_API_TIMEOUT", "30")),
            collector_interval=int(os.environ.get("COLLECTOR_INTERVAL", "3600")),
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
        )
EOF

cat > "${SRC}/src/agent/__main__.py" <<'EOF'
"""에이전트 진입점. 실행: python3 -m agent"""
from __future__ import annotations

import logging
import sys
import time

from .config import Config


def setup_logging(level: str) -> logging.Logger:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    return logging.getLogger("osv-agent")


def collect_once(cfg: Config, log: logging.Logger) -> int:
    log.info("OSV 수집 시작 (timeout=%ss)", cfg.osv_api_timeout)
    # TODO: OSV API 호출 → T2 (cfg.t2_api_url) 로 결과 전송
    log.info("OSV 수집 완료, T2 보고 대상=%s", cfg.t2_api_url)
    return 0


def main() -> int:
    cfg = Config.from_env()
    log = setup_logging(cfg.log_level)
    log.info("osv-agent 기동 (interval=%ss)", cfg.collector_interval)
    try:
        while True:
            collect_once(cfg, log)
            time.sleep(cfg.collector_interval)
    except KeyboardInterrupt:
        log.info("종료 신호 수신, 정상 종료")
        return 0
    except Exception:
        log.exception("수집 중 오류 발생")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
EOF

# ── 2) systemd unit (시스템 python3 + PYTHONPATH) ─────────
cat > "${PKG}/osv-agent.service" <<'EOF'
[Unit]
Description=OSV Vulnerability Collector Agent (T1)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=osvagent
Group=osvagent
Environment=PYTHONPATH=/opt/osv-agent/src
EnvironmentFile=/etc/osv-agent.env
ExecStart=/usr/bin/python3 -m agent
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true

[Install]
WantedBy=multi-user.target
EOF

# ── 3) 기본 환경설정 ─────────────────────────────────────
cat > "${PKG}/osv-agent.env" <<'EOF'
T2_API_URL=http://t2-api:8000
T2_API_KEY=your-secret-key
OSV_API_TIMEOUT=30
COLLECTOR_INTERVAL=3600
LOG_LEVEL=INFO
EOF

# ── 4) RPM spec (venv/pip 없음 → 오프라인 설치 가능) ──────
cat > "${PKG}/osv-agent.spec" <<'EOF'
%global appdir   /opt/osv-agent
%global appuser  osvagent

Name:           osv-agent
Version:        0.1.0
Release:        1%{?dist}
Summary:        OSV Vulnerability Collector Agent (T1) - offline

License:        Proprietary
URL:            https://example.local/osv-agent
Source0:        %{name}-%{version}.tar.gz
Source1:        osv-agent.service
Source2:        osv-agent.env

BuildArch:      noarch

Requires:       python3 >= 3.9
%{?systemd_requires}

%description
T1 OSV 취약점 수집 에이전트(오프라인 빌드). 시스템 python3 로 구동되며
설치 시 네트워크가 필요 없다(스텁은 표준 라이브러리만 사용).

%prep
%autosetup -n %{name}-%{version}

%build

%install
install -d -m 0755 %{buildroot}%{appdir}/src
cp -a src/agent %{buildroot}%{appdir}/src/
install -D -m 0644 %{SOURCE1} %{buildroot}%{_unitdir}/%{name}.service
install -D -m 0640 %{SOURCE2} %{buildroot}%{_sysconfdir}/osv-agent.env

%pre
getent group %{appuser} >/dev/null || groupadd -r %{appuser}
getent passwd %{appuser} >/dev/null || \
    useradd -r -g %{appuser} -d %{appdir} -s /sbin/nologin -c "OSV Agent" %{appuser}
exit 0

%post
%systemd_post %{name}.service

%preun
%systemd_preun %{name}.service

%postun
%systemd_postun_with_restart %{name}.service

%files
%dir %{appdir}
%dir %{appdir}/src
%{appdir}/src/agent
%{_unitdir}/%{name}.service
%config(noreplace) %{_sysconfdir}/osv-agent.env

%changelog
* Thu May 29 2026 lab_ai3 <lab_ai3@icomsoft.co.kr> - 0.1.0-1
- 오프라인 빌드: venv/pip 제거, 시스템 python3 구동
EOF

# ── 5) 빌드 도구 (ISO repo 에서, 인터넷 불필요) ───────────
echo "[*] 빌드 도구 설치 (sudo, ISO repo 사용)"
sudo dnf install -y rpm-build rpmdevtools python3 systemd-rpm-macros

# ── 6) 빌드 ──────────────────────────────────────────────
rpmdev-setuptree
TOPDIR="$(rpm --eval %_topdir)"
tar czf "${TOPDIR}/SOURCES/osv-agent-${VER}.tar.gz" -C "${SRC}" \
    --transform "s,^,osv-agent-${VER}/," src
cp -f "${PKG}/osv-agent.service" "${PKG}/osv-agent.env" "${TOPDIR}/SOURCES/"
rpmbuild -ba "${PKG}/osv-agent.spec"

# ── 7) 산출물 회수 ───────────────────────────────────────
RPM_PATH="$(find "${TOPDIR}/RPMS" -name "osv-agent-${VER}-*.noarch.rpm" | head -n1)"
cp -f "${RPM_PATH}" "${ART}/"
echo
echo "[+] 완료: ${ART}/$(basename "${RPM_PATH}")"
echo "[+] 오프라인 설치/검증:"
echo "    sudo dnf install -y ${ART}/$(basename "${RPM_PATH}")"
echo "    sudo systemctl start osv-agent"
echo "    systemctl status osv-agent && journalctl -u osv-agent -n 20 --no-pager"
