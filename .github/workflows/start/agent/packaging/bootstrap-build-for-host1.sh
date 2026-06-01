#!/usr/bin/env bash
# host1(RHVH 4.5.3 / el8.6) 설치용 RPM 을 RHEL 9 VM 에서 빌드한다.
#   - 실행 위치: RHEL 9 게스트 VM (RHEL9 ISO repo 구성된 상태). rpmbuild 가 여기 있음.
#   - 산출물: el8.6 host1 에서 'rpm -ivh' 로 바로 설치되는 noarch rpm.
#       * python 3.6 호환 (host1 기본 python3=3.6.8 사용, 추가 패키지 0)
#       * unit -> /etc/systemd/system  (RHVH /usr 읽기전용 회피)
#       * app  -> /var/opt/osv-agent   (RHVH 쓰기영역)
#   - 결과: ~/osv-agent-build/artifacts/osv-agent-0.1.0-1.noarch.rpm
set -euo pipefail

VER=0.1.0
ROOT="${HOME}/osv-agent-build"
SRC="${ROOT}/agent"
PKG="${ROOT}/packaging"
ART="${ROOT}/artifacts"

echo "[*] 작업 디렉터리: ${ROOT}"
rm -rf "${ROOT}"
mkdir -p "${SRC}/src/agent" "${PKG}" "${ART}"

# ── 1) Python 에이전트 소스 (python 3.6 호환: dataclasses/future 미사용) ──
cat > "${SRC}/src/agent/__init__.py" <<'EOF'
"""OSV 취약점 수집 에이전트 (T1)."""

__version__ = "0.1.0"
EOF

cat > "${SRC}/src/agent/config.py" <<'EOF'
"""환경변수 기반 설정 (systemd EnvironmentFile = /etc/osv-agent.env).

python 3.6 호환을 위해 dataclasses 를 쓰지 않는다.
"""
import os


class Config(object):
    def __init__(self, t2_api_url, t2_api_key, osv_api_timeout,
                 collector_interval, log_level):
        self.t2_api_url = t2_api_url
        self.t2_api_key = t2_api_key
        self.osv_api_timeout = osv_api_timeout
        self.collector_interval = collector_interval
        self.log_level = log_level

    @classmethod
    def from_env(cls):
        return cls(
            t2_api_url=os.environ.get("T2_API_URL", "http://t2-api:8000"),
            t2_api_key=os.environ.get("T2_API_KEY", ""),
            osv_api_timeout=int(os.environ.get("OSV_API_TIMEOUT", "30")),
            collector_interval=int(os.environ.get("COLLECTOR_INTERVAL", "3600")),
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
        )

    def __repr__(self):
        return ("Config(t2_api_url=%r, osv_api_timeout=%r, "
                "collector_interval=%r, log_level=%r)" % (
                    self.t2_api_url, self.osv_api_timeout,
                    self.collector_interval, self.log_level))
EOF

cat > "${SRC}/src/agent/__main__.py" <<'EOF'
"""에이전트 진입점. 실행: python3 -m agent  (python 3.6 호환)"""
import logging
import sys
import time

from .config import Config


def setup_logging(level):
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    return logging.getLogger("osv-agent")


def collect_once(cfg, log):
    log.info("OSV 수집 시작 (timeout=%ss)", cfg.osv_api_timeout)
    # TODO: OSV API 호출 → T2 (cfg.t2_api_url) 로 결과 전송
    log.info("OSV 수집 완료, T2 보고 대상=%s", cfg.t2_api_url)
    return 0


def main():
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
    sys.exit(main())
EOF

# ── 2) systemd unit (시스템 python3 + /var/opt + /etc 위치) ──
cat > "${PKG}/osv-agent.service" <<'EOF'
[Unit]
Description=OSV Vulnerability Collector Agent (T1)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=osvagent
Group=osvagent
Environment=PYTHONPATH=/var/opt/osv-agent/src
EnvironmentFile=/etc/osv-agent.env
ExecStart=/usr/bin/python3 -m agent
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
NoNewPrivileges=true

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

# ── 4) RPM spec (el8 설치 호환: AutoReq no, xz 페이로드, dist 중립) ──
cat > "${PKG}/osv-agent.spec" <<'EOF'
%global appdir   /var/opt/osv-agent
%global appuser  osvagent
%global unitdir  /etc/systemd/system
%define dist %{nil}
%global _binary_payload w7.xzdio

Name:           osv-agent
Version:        0.1.0
Release:        1
Summary:        OSV Vulnerability Collector Agent (T1)

License:        Proprietary
URL:            https://example.local/osv-agent
Source0:        %{name}-%{version}.tar.gz
Source1:        osv-agent.service
Source2:        osv-agent.env

BuildArch:      noarch
AutoReq:        no
Requires:       python3
Requires(post): systemd
Requires(preun): systemd
Requires(postun): systemd

%description
T1 OSV 취약점 수집 에이전트. 시스템 python3 로 구동(3.6 호환).
el8/el9 공통 설치 가능. 설치 시 네트워크 불필요.

%prep
%autosetup -n %{name}-%{version}

%build

%install
install -d -m 0755 %{buildroot}%{appdir}/src
cp -a src/agent %{buildroot}%{appdir}/src/
install -D -m 0644 %{SOURCE1} %{buildroot}%{unitdir}/%{name}.service
install -D -m 0640 %{SOURCE2} %{buildroot}%{_sysconfdir}/osv-agent.env

%pre
getent group %{appuser} >/dev/null || groupadd -r %{appuser}
getent passwd %{appuser} >/dev/null || \
    useradd -r -g %{appuser} -d %{appdir} -s /sbin/nologin -c "OSV Agent" %{appuser}
exit 0

%post
systemctl daemon-reload >/dev/null 2>&1 || :
systemctl enable %{name}.service >/dev/null 2>&1 || :

%preun
if [ $1 -eq 0 ]; then
    systemctl --no-reload disable %{name}.service >/dev/null 2>&1 || :
    systemctl stop %{name}.service >/dev/null 2>&1 || :
fi

%postun
systemctl daemon-reload >/dev/null 2>&1 || :

%files
%dir %{appdir}
%dir %{appdir}/src
%{appdir}/src/agent
%{unitdir}/%{name}.service
%config(noreplace) %{_sysconfdir}/osv-agent.env

%changelog
* Thu May 29 2026 lab_ai3 <lab_ai3@icomsoft.co.kr> - 0.1.0-1
- el8/el9 공통 noarch. python3.6 호환, unit=/etc/systemd/system, app=/var/opt
EOF

# ── 5) 빌드 도구 (RHEL9 ISO repo 에서) ───────────────────
echo "[*] 빌드 도구 설치 (sudo, RHEL9 ISO repo)"
sudo dnf install -y rpm-build rpmdevtools

# ── 6) 빌드 ──────────────────────────────────────────────
rpmdev-setuptree
TOPDIR="$(rpm --eval %_topdir)"
tar czf "${TOPDIR}/SOURCES/osv-agent-${VER}.tar.gz" -C "${SRC}" \
    --transform "s,^,osv-agent-${VER}/," src
cp -f "${PKG}/osv-agent.service" "${PKG}/osv-agent.env" "${TOPDIR}/SOURCES/"
rpmbuild -ba "${PKG}/osv-agent.spec"

# ── 7) 산출물 회수 ───────────────────────────────────────
RPM_PATH="$(find "${TOPDIR}/RPMS" -name "osv-agent-${VER}-1.noarch.rpm" | head -n1)"
cp -f "${RPM_PATH}" "${ART}/"
echo
echo "[+] 빌드 완료: ${ART}/$(basename "${RPM_PATH}")"
echo
echo "[+] 다음: 이 .rpm 을 host1(RHVH)로 복사 후 설치"
echo "    scp ${ART}/$(basename "${RPM_PATH}") root@<host1>:/root/"
echo "    # host1 에서:"
echo "    sudo rpm -ivh /root/$(basename "${RPM_PATH}")"
echo "    sudo systemctl start osv-agent"
echo "    systemctl status osv-agent && journalctl -u osv-agent -n 20 --no-pager"
