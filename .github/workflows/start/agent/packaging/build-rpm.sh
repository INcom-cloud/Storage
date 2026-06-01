#!/usr/bin/env bash
# osv-agent RPM 빌드 헬퍼 (Rocky/RHEL 9 에서 실행)
#   - rpmbuild 를 감싸는 빌더일 뿐, 산출물은 네이티브 .rpm 이다.
#   - 결과: start/artifacts/osv-agent-<ver>-1.*.noarch.rpm
#
# 사용:
#   chmod +x build-rpm.sh
#   ./build-rpm.sh                # 빌드 도구가 이미 있으면 그대로
#   INSTALL_DEPS=1 ./build-rpm.sh # 빌드 도구까지 자동 설치(sudo 필요)
set -euo pipefail

VER="${VER:-0.1.0}"

# 경로 자동 탐지: 이 스크립트는 start/agent/packaging/ 에 있다.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG_DIR="${SCRIPT_DIR}"                         # .../agent/packaging
AGENT_DIR="$(cd "${PKG_DIR}/.." && pwd)"        # .../agent
START_DIR="$(cd "${AGENT_DIR}/.." && pwd)"      # .../start
ARTIFACTS_DIR="${START_DIR}/artifacts"

echo "[*] START_DIR    = ${START_DIR}"
echo "[*] 버전(VER)    = ${VER}"

# 1) (선택) 빌드 도구 설치
if [[ "${INSTALL_DEPS:-0}" == "1" ]]; then
  echo "[*] 빌드 도구 설치 (sudo)"
  sudo dnf install -y rpm-build rpmdevtools python3 systemd-rpm-macros
fi

for bin in rpmbuild rpmdev-setuptree tar python3; do
  command -v "$bin" >/dev/null 2>&1 || {
    echo "[!] '$bin' 없음. INSTALL_DEPS=1 ./build-rpm.sh 로 재실행하거나"
    echo "    sudo dnf install -y rpm-build rpmdevtools python3 systemd-rpm-macros"
    exit 1
  }
done

# 2) 빌드 트리 준비
rpmdev-setuptree
TOPDIR="$(rpm --eval %_topdir)"
echo "[*] rpmbuild topdir = ${TOPDIR}"

# 3) 소스 tar 생성 (아카이브 최상위 폴더명을 spec 의 %autosetup -n 과 일치)
tar czf "${TOPDIR}/SOURCES/osv-agent-${VER}.tar.gz" \
    -C "${AGENT_DIR}" \
    --transform "s,^,osv-agent-${VER}/," \
    pyproject.toml src
echo "[*] 소스 tar 생성: SOURCES/osv-agent-${VER}.tar.gz"

# 4) 보조 소스 복사
cp -f "${PKG_DIR}/osv-agent.service" "${TOPDIR}/SOURCES/"
cp -f "${PKG_DIR}/osv-agent.env"     "${TOPDIR}/SOURCES/"

# 5) 빌드 (버전은 spec 의 Version: 필드를 따른다)
rpmbuild -ba "${PKG_DIR}/osv-agent.spec"

# 6) 산출물 회수
mkdir -p "${ARTIFACTS_DIR}"
RPM_PATH="$(find "${TOPDIR}/RPMS" -name "osv-agent-${VER}-*.noarch.rpm" | head -n1)"
if [[ -z "${RPM_PATH}" ]]; then
  echo "[!] RPM 산출물을 찾지 못함. 위 rpmbuild 출력을 확인하세요."
  exit 1
fi
cp -f "${RPM_PATH}" "${ARTIFACTS_DIR}/"
echo
echo "[+] 완료: ${ARTIFACTS_DIR}/$(basename "${RPM_PATH}")"
echo "[+] 설치 테스트:"
echo "    sudo dnf install -y ${ARTIFACTS_DIR}/$(basename "${RPM_PATH}")"
echo "    rpm -ql osv-agent && systemctl status osv-agent"
