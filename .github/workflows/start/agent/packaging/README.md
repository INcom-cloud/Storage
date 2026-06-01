# osv-agent RPM 패키징

`.spec` + `rpmbuild` 로 **네이티브 RPM** 을 만든다. 설치는 `dnf install`, 제거는 `dnf remove`.

## 구성 파일
- `osv-agent.spec` — 패키지 정의 (계정 생성/venv/systemd 스크립틀릿 포함)
- `osv-agent.service` — systemd unit (→ `/usr/lib/systemd/system/`)
- `osv-agent.env` — 기본 환경설정 (→ `/etc/`, `%config(noreplace)`)

## 빌드 (Rocky 9 빌드 호스트)

```bash
# 0) 빌드 도구
sudo dnf install -y rpm-build rpmdevtools python3

# 1) 빌드 트리 준비
rpmdev-setuptree                 # ~/rpmbuild/{SPECS,SOURCES,...} 생성

# 2) 소스 tar 생성 (agent/ 의 pyproject.toml + src/ 를 묶음)
#    start/ 기준 경로에서 실행
ver=0.1.0
tar czf ~/rpmbuild/SOURCES/osv-agent-${ver}.tar.gz \
    --transform "s,^agent,osv-agent-${ver}," \
    agent/pyproject.toml agent/src

# 3) 보조 소스 복사
cp agent/packaging/osv-agent.service ~/rpmbuild/SOURCES/
cp agent/packaging/osv-agent.env     ~/rpmbuild/SOURCES/

# 4) 빌드
rpmbuild -ba agent/packaging/osv-agent.spec

# 산출물: ~/rpmbuild/RPMS/noarch/osv-agent-0.1.0-1.*.noarch.rpm
```

> tar 의 `--transform` 으로 아카이브 내부 최상위 폴더명을 `osv-agent-0.1.0/` 로 맞춘다
> (spec 의 `%autosetup -n osv-agent-0.1.0` 와 일치해야 함).

## 설치 / 제거

```bash
sudo dnf install ./osv-agent-0.1.0-1.*.noarch.rpm   # 설치 (+venv 자동 생성, 서비스 enable)
systemctl start osv-agent                            # 기동
journalctl -u osv-agent -f                           # 디버그 로그
sudo dnf remove osv-agent                            # 제거 (venv 정리)
```

## 동작 메모
- `%post` 가 `/opt/osv-agent/venv` 를 만들고 `pip install` 로 앱을 설치한다.
  **T1 은 인터넷 직결 노드**라 pip 가 정상 동작한다.
- **에어갭(폐쇄망) 빌드/설치**라면: 의존 wheel 들을 미리 받아 패키지에 동봉하고
  `%post` 에서 `pip install --no-index --find-links <wheelhouse>` 로 바꾼다.
  (필요 시 spec 에 `Source3: wheelhouse.tar.gz` 추가)
- 의존성을 100% RPM 으로만 관리하려면 `httpx` 등을 EPEL/사내 repo 의 `python3-*`
  RPM 으로 `Requires` 에 명시하고 `%post` 의 pip 설치를 제거하는 방법도 있다.
