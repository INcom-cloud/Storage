#!/usr/bin/env bash
# 자체 완결형 RPM 빌드 부트스트랩 (Rocky/RHEL 9 에서 실행)
#   - 파일 전송/리포 클론 없이, 이 스크립트 하나로 소스를 재생성하고 RPM 을 빌드한다.
#   - SSH 로 접속한 빌드 호스트(일반 Rocky 9 게스트)에 붙여넣어 실행.
#   - 결과: ~/osv-agent-build/artifacts/osv-agent-0.1.0-1.*.noarch.rpm
#
# 주의: oVirt Node/RHVH(잠긴 어플라이언스) 말고 일반 Rocky 9 에서 실행할 것.
set -euo pipefail

VER=0.1.0
ROOT="${HOME}/osv-agent-build"
SRC="${ROOT}/agent"
PKG="${ROOT}/packaging"
ART="${ROOT}/artifacts"

echo "[*] 작업 디렉터리: ${ROOT}"
rm -rf "${ROOT}"
mkdir -p "${SRC}/src/agent" "${PKG}" "${ART}"

# ── 1) Python 에이전트 소스 ───────────────────────────────
cat > "${SRC}/pyproject.toml" <<'EOF'
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "osv-agent"
version = "0.1.0"
description = "T1 Public 노드 OSV 취약점 수집 에이전트"
requires-python = ">=3.9"
dependencies = [
    "httpx>=0.27",
]

[project.scripts]
osv-agent = "agent.__main__:main"

[tool.setuptools.packages.find]
where = ["src"]
EOF

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
"""에이전트 진입점. 실행: python -m agent"""
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
    # TODO: httpx 로 OSV API 호출 → T2 (cfg.t2_api_url) 로 결과 전송
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

# ── 2) systemd unit ──────────────────────────────────────
cat > "${PKG}/osv-agent.service" <<'EOF'
[Unit]
Description=OSV Vulnerability Collector Agent (T1)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=osvagent
Group=osvagent
EnvironmentFile=/etc/osv-agent.env
ExecStart=/opt/osv-agent/venv/bin/python -m agent
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/opt/osv-agent

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

# ── 4) RPM spec ──────────────────────────────────────────
cat > "${PKG}/osv-agent.spec" <<'EOF'
%global appdir   /opt/osv-agent
%global venvdir  %{appdir}/venv
%global appuser  osvagent

Name:           osv-agent
Version:        0.1.0
Release:        1%{?dist}
Summary:        OSV Vulnerability Collector Agent (T1)

License:        Proprietary
URL:            https://example.local/osv-agent
Source0:        %{name}-%{version}.tar.gz
Source1:        osv-agent.service
Source2:        osv-agent.env

BuildArch:      noarch

Requires:       python3 >= 3.9
Requires:       python3-pip
%{?systemd_requires}

%description
T1 Public 노드 OSV 취약점 수집 에이전트. 전용 venv 에 설치되고 systemd 로 구동.

%prep
%autosetup -n %{name}-%{version}

%build

%install
install -d -m 0750 %{buildroot}%{appdir}/src
cp -a pyproject.toml src %{buildroot}%{appdir}/src/
install -d -m 0750 %{buildroot}%{venvdir}
install -D -m 0644 %{SOURCE1} %{buildroot}%{_unitdir}/%{name}.service
install -D -m 0640 %{SOURCE2} %{buildroot}%{_sysconfdir}/osv-agent.env

%pre
getent group %{appuser} >/dev/null || groupadd -r %{appuser}
getent passwd %{appuser} >/dev/null || \
    useradd -r -g %{appuser} -d %{appdir} -s /sbin/nologin -c "OSV Agent" %{appuser}
exit 0

%post
if [ ! -x %{venvdir}/bin/python ]; then
    python3 -m venv %{venvdir}
fi
%{venvdir}/bin/pip install --upgrade pip >/dev/null 2>&1 || :
%{venvdir}/bin/pip install --upgrade %{appdir}/src
chown -R %{appuser}:%{appuser} %{appdir}
%systemd_post %{name}.service

%preun
%systemd_preun %{name}.service

%postun
%systemd_postun_with_restart %{name}.service
if [ $1 -eq 0 ]; then
    rm -rf %{venvdir}
fi

%files
%dir %{appdir}
%dir %{appdir}/src
%{appdir}/src/pyproject.toml
%{appdir}/src/src
%dir %{venvdir}
%{_unitdir}/%{name}.service
%config(noreplace) %{_sysconfdir}/osv-agent.env

%changelog
* Thu May 29 2026 lab_ai3 <lab_ai3@icomsoft.co.kr> - 0.1.0-1
- 초기 패키지
EOF

# ── 5) 빌드 도구 ─────────────────────────────────────────
echo "[*] 빌드 도구 설치 (sudo)"
sudo dnf install -y rpm-build rpmdevtools python3 systemd-rpm-macros

# ── 6) 빌드 ──────────────────────────────────────────────
rpmdev-setuptree
TOPDIR="$(rpm --eval %_topdir)"
tar czf "${TOPDIR}/SOURCES/osv-agent-${VER}.tar.gz" -C "${SRC}" \
    --transform "s,^,osv-agent-${VER}/," pyproject.toml src
cp -f "${PKG}/osv-agent.service" "${PKG}/osv-agent.env" "${TOPDIR}/SOURCES/"
rpmbuild -ba "${PKG}/osv-agent.spec"

# ── 7) 산출물 회수 ───────────────────────────────────────
RPM_PATH="$(find "${TOPDIR}/RPMS" -name "osv-agent-${VER}-*.noarch.rpm" | head -n1)"
cp -f "${RPM_PATH}" "${ART}/"
echo
echo "[+] 완료: ${ART}/$(basename "${RPM_PATH}")"
echo "[+] 설치 테스트:"
echo "    sudo dnf install -y ${ART}/$(basename "${RPM_PATH}")"
echo "    rpm -ql osv-agent && systemctl status osv-agent && journalctl -u osv-agent -n 20"
